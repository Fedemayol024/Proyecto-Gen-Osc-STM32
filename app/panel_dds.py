"""Panel del módulo AD9833 (generador DDS externo) para la pestaña Generador.

Incluye:
- forma, frecuencia, fase y amplitud (en % del potenciómetro o en Vpp si está calibrado);
- modulaciones hechas por el firmware: barrido, FSK, PSK, ráfaga y AM;
- calibración de la amplitud (tabla de % → Vpp y tensión media medidos);
- medición del reloj real del módulo con el frecuencímetro de la placa.
"""
from __future__ import annotations

import re
import time
from dataclasses import asdict

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
                               QMessageBox, QSpinBox, QStackedWidget, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

import modelo as M
import widgets as W

COLOR = W.OK
F_MEDICION = 1e6          # frecuencia para medir el reloj (cuadrada, con compuerta de 1 s)
F_CAL = 1000.0            # seno para calibrar la amplitud
FS_CAL = 200e3            # muestreo de CH1 en la calibración automática: 200 puntos por período
N_CAL = 8192              # ~41 períodos
ESPERA_CAL_MS = 450       # que el módulo cambie y la salida se asiente antes de capturar


_PREFIJOS = {"": 1.0, "m": 1e-3, "u": 1e-6, "µ": 1e-6, "n": 1e-9, "k": 1e3}
_RE_TENSION = re.compile(r"^\s*([-+]?[\d.,]+)\s*([mµunk]?)\s*(v(pp)?)?\s*$", re.IGNORECASE)


def leer_tension(texto: str) -> float | None:
    """Lee una tensión escrita como la muestra un osciloscopio: «906,25mV», «625,00 mV»,
    «1,48 V», «1.48», «2,02». Sin unidad se toma en volts. None si no se entiende."""
    m = _RE_TENSION.match((texto or "").replace(" ", " "))
    if not m:
        return None
    num, pref = m.group(1), m.group(2)
    if "," in num and "." in num:              # 1.250,5 → miles con punto, decimal con coma
        num = num.replace(".", "").replace(",", ".")
    else:
        num = num.replace(",", ".")
    try:
        v = float(num)
    except ValueError:
        return None
    pref = pref if pref in ("µ", "") else pref.lower()
    return v * _PREFIJOS.get(pref, 1.0)


def _leer_num(texto: str) -> float | None:
    return leer_tension((texto or "").replace("%", ""))


def _fmt(v: float | None, dec: int = 3) -> str:
    return "" if v is None else f"{v:.{dec}f}".rstrip("0").rstrip(".").replace(".", ",")


def _grados(g: float) -> str:
    return f"{g:.1f}°".replace(".", ",")


def _fmt_v(v: float | None, cifras: int = 4) -> str:
    if v is None:
        return "—"
    if abs(v) < 1e-6:                  # ruido numérico: es cero
        v = 0.0
    return M.si(v, "V", cifras)


class DialogoCalDDS(QDialog):
    """Asistente paso a paso: la app pone la salida en cada amplitud (0, 25, 50, 75 y 100 %),
    vos medís y cargás Vpp y tensión media, «Continuar» pasa al siguiente. Al final, un
    resumen editable. Al cerrar, el AD9833 vuelve a como estaba."""

    def __init__(self, panel: "PanelDDS"):
        super().__init__(panel)
        self.panel = panel
        self.setWindowTitle("Calibrar la amplitud del AD9833")
        self.puntos_pct = list(M.DDS_PUNTOS_CAL)
        previos = {round(p[0], 3): p for p in panel.c.cal}
        # mediciones: % -> [vpp, vmed]; arranca con lo que ya había para esos puntos
        self.medidas = {pct: [previos.get(round(pct, 3), [pct, None, None])[1],
                              previos.get(round(pct, 3), [pct, None, None])[2]]
                        for pct in self.puntos_pct}
        self.otros = [p for k, p in previos.items() if k not in {round(x, 3) for x in self.puntos_pct}]
        self.paso = 0
        self._config_previa = M.ConfigDDS.desde_dict(asdict(panel.c))
        # medición automática con el CH1 de la placa
        self.auto = False
        self.osc_corria = False            # para volver a RUN al cerrar
        self.recortados: list[float] = []
        self._t_auto = QTimer(self)
        self._t_auto.setSingleShot(True)
        self._t_auto.timeout.connect(self._auto_capturar)
        self._t_vence = QTimer(self)
        self._t_vence.setSingleShot(True)
        self._t_vence.timeout.connect(self._auto_sin_datos)

        lay = QVBoxLayout(self)
        self.pila = QStackedWidget()
        lay.addWidget(self.pila, 1)

        # ---- página de medición
        pm = QWidget()
        lm = QVBoxLayout(pm)
        lm.setContentsMargins(0, 0, 0, 0)
        self.lbl_paso = QLabel()
        self.lbl_paso.setObjectName("titulo")
        lm.addWidget(self.lbl_paso)
        self.lbl_instr = W.etiqueta_tenue("")
        self.lbl_instr.setWordWrap(True)
        lm.addWidget(self.lbl_instr)
        self.e_vpp = QLineEdit()
        self.e_vmed = QLineEdit()
        for e, ph in ((self.e_vpp, "p. ej. 906,25 mV"), (self.e_vmed, "p. ej. 2,02 V (opcional)")):
            e.setPlaceholderText(ph)
            W.tam(e, "setFixedWidth", 180)
            e.textChanged.connect(self._validar)
            e.returnPressed.connect(self._continuar)
        lm.addWidget(W.fila("Vpp medido", self.e_vpp))
        lm.addWidget(W.fila("Tensión media", self.e_vmed,
                            ayuda="El centro de la onda: la media del osciloscopio en acople DC, "
                                  "o (Vmáx + Vmín) / 2. Si no la tenés, dejala vacía."))
        self.lbl_lectura = W.etiqueta_tenue("")
        lm.addWidget(self.lbl_lectura)
        self.lbl_progreso = W.etiqueta_tenue("")
        self.lbl_progreso.setWordWrap(True)
        lm.addWidget(self.lbl_progreso)
        lm.addStretch(1)
        auto = QHBoxLayout()
        self.btn_auto = W.boton("Medir automático con CH1", self._alternar_auto)
        self.btn_auto.setToolTip("Uniendo la salida PGA con A0 (CH1), la app mide sola cada punto "
                                 "con el osciloscopio de la placa.")
        auto.addWidget(self.btn_auto)
        auto.addStretch(1)
        lm.addLayout(auto)
        self.pila.addWidget(pm)

        # ---- página de resumen (editable)
        pr = QWidget()
        lr = QVBoxLayout(pr)
        lr.setContentsMargins(0, 0, 0, 0)
        t = QLabel("Resumen")
        t.setObjectName("titulo")
        lr.addWidget(t)
        lr.addWidget(W.etiqueta_tenue("Revisá los valores (se pueden corregir acá). Las filas sin "
                                      "Vpp no se guardan."))
        self.tabla = QTableWidget(0, 3)
        self.tabla.setHorizontalHeaderLabels(["Amplitud (%)", "Vpp medido", "Tensión media"])
        self.tabla.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.tabla.verticalHeader().setVisible(False)
        W.tam(self.tabla, "setMinimumSize", 440, 200)
        lr.addWidget(self.tabla, 1)
        fila = QHBoxLayout()
        fila.addWidget(W.boton("Agregar fila", lambda: self._agregar_fila(50.0, None, None)))
        fila.addWidget(W.boton("Quitar fila", self._quitar))
        fila.addStretch(1)
        lr.addLayout(fila)
        self.pila.addWidget(pr)

        # ---- botones
        b = QHBoxLayout()
        self.btn_ant = W.boton("◀ Anterior", self._anterior)
        self.btn_saltar = W.boton("Saltar este punto", self._saltar)
        self.btn_sig = W.boton("Continuar ▶", self._continuar, primario=True)
        self.btn_cancelar = W.boton("Cancelar", self.reject)
        b.addWidget(self.btn_ant)
        b.addWidget(self.btn_saltar)
        b.addStretch(1)
        b.addWidget(self.btn_cancelar)
        b.addWidget(self.btn_sig)
        lay.addLayout(b)
        W.tam(self, "setMinimumSize", 520, 380)
        self._ir(0)

    # ------------------------------------------------------------------ pasos
    def _ir(self, paso: int):
        self.paso = paso
        n = len(self.puntos_pct)
        if paso < n:
            pct = self.puntos_pct[paso]
            self.pila.setCurrentIndex(0)
            self.lbl_paso.setText(f"Paso {paso + 1} de {n} · amplitud {pct:.0f} %")
            self.lbl_instr.setText(
                f"El AD9833 ya está en seno de 1 kHz al {pct:.0f} % (potenciómetro "
                f"{M.dds_paso_amplitud(pct)}/255). Medí la salida PGA con el osciloscopio en "
                "acople DC y escribí lo que marca. Acepta «906,25mV», «625,00 mV», «1,48 V»…")
            vpp, vmed = self.medidas[pct]
            self.e_vpp.setText("" if vpp is None else _fmt_v(vpp, 5))
            self.e_vmed.setText("" if vmed is None else _fmt_v(vmed, 5))
            self.panel.poner_para_calibrar(pct)
            self.btn_sig.setText("Continuar ▶" if paso < n - 1 else "Ver resumen ▶")
            self.btn_saltar.setVisible(True)
            self.e_vpp.setFocus()
            self.e_vpp.selectAll()
            if self.auto:
                self.lbl_lectura.setText("Midiendo con CH1…")
                self._t_auto.start(ESPERA_CAL_MS)
        else:
            if self.auto:
                self._terminar_auto()
            self._armar_resumen()
            self.pila.setCurrentIndex(1)
            self.btn_sig.setText("Guardar")
            self.btn_saltar.setVisible(False)
        self.btn_ant.setEnabled(paso > 0 and not self.auto)
        self._progreso()
        self._validar()

    def _progreso(self):
        partes = []
        for pct in self.puntos_pct:
            vpp, _ = self.medidas[pct]
            partes.append(f"{pct:.0f} %: {_fmt_v(vpp)}" if vpp is not None else f"{pct:.0f} %: —")
        self.lbl_progreso.setText("Medido hasta ahora · " + " · ".join(partes))

    def _validar(self, *_):
        if self.pila.currentIndex() != 0:
            self.btn_sig.setEnabled(True)
            return
        if self.auto:
            return
        vpp = leer_tension(self.e_vpp.text())
        txt_med = self.e_vmed.text().strip()
        vmed = leer_tension(txt_med) if txt_med else None
        ok = vpp is not None and vpp >= 0 and (not txt_med or vmed is not None)
        self.btn_sig.setEnabled(ok)
        if not self.e_vpp.text().strip():
            self.lbl_lectura.setText("")
        elif vpp is None or (txt_med and vmed is None):
            self.lbl_lectura.setText(f"<span style='color:{W.ALERTA}'>No entiendo ese valor: probá "
                                     "con «906,25 mV» o «1,48 V».</span>")
        else:
            t = f"Se guarda: {_fmt_v(vpp)}pp"
            if vmed is not None:
                t += f" sobre {_fmt_v(vmed)}"
            self.lbl_lectura.setText(t)

    def _guardar_paso(self) -> bool:
        vpp = leer_tension(self.e_vpp.text())
        txt_med = self.e_vmed.text().strip()
        vmed = leer_tension(txt_med) if txt_med else None
        if vpp is None or (txt_med and vmed is None):
            return False
        self.medidas[self.puntos_pct[self.paso]] = [vpp, vmed]
        return True

    def _continuar(self):
        if self.pila.currentIndex() == 1:
            self.accept()
            return
        if not self.btn_sig.isEnabled() or not self._guardar_paso():
            return
        self._ir(self.paso + 1)

    def _saltar(self):
        self._ir(self.paso + 1)

    def _anterior(self):
        if self.pila.currentIndex() == 0:
            self._guardar_paso()            # si había algo válido, no se pierde
        self._ir(max(0, self.paso - 1))

    # ------------------------------------------------------------------ automático
    def _alternar_auto(self):
        if self.auto:
            self._terminar_auto()
            self.panel.tab.v.estado("Medición automática detenida.", W.TENUE)
            return
        v = self.panel.tab.v
        if not v.disp.esta_conectado:
            v.estado("Conectá la placa primero.", W.ALERTA)
            return
        ch1 = v.tab_osc.canales[1]
        r = QMessageBox.question(
            self, "Medir automático con CH1",
            "Uní la salida PGA del módulo con A0 (CH1 de la placa) y las masas.\n\n"
            f"CH1 está en «{ch1.entrada.currentText()}», punta {ch1.punta.currentText()}. "
            "Usá acople DC en la etapa de entrada (si la usás): si no, la tensión media no se puede "
            "medir. Con «Pin directo» la salida tiene que quedar entre 0 y 3,3 V (a 100 % el "
            "módulo llega a unos 3 V).\n\n"
            "Mientras mide, el osciloscopio queda en pausa. ¿Empezar?")
        if r != QMessageBox.Yes:
            return
        self.auto = True
        self.recortados = []
        self.osc_corria = self.osc_corria or v.tab_osc.corriendo
        v.tab_osc._set_run(False)
        v.cancelar_captura()
        self.btn_auto.setText("Detener medición automática")
        for w in (self.btn_ant, self.btn_saltar, self.btn_sig, self.e_vpp, self.e_vmed):
            w.setEnabled(False)
        self._ir(self.paso)

    def _auto_capturar(self):
        if not self.auto:
            return
        self.panel.tab.v.pedir_captura("dds", N_CAL, 0, FS_CAL)
        self._t_vence.start(2500)

    def _auto_sin_datos(self):
        if not self.auto:
            return
        self._terminar_auto()
        self.panel.tab.v.estado("No llegó la captura de CH1: se detuvo la medición automática.", W.ERROR)

    def al_captura(self, d: dict):
        """Captura de CH1 pedida por la medición automática."""
        if not self.auto or self.pila.currentIndex() != 0:
            return
        self._t_vence.stop()
        osc = self.panel.tab.v.tab_osc
        codigos = d["ch1"]
        v = osc.recta(1).volt(codigos) * osc.canales[1].factor
        f = M.dds_frecuencia_real(F_CAL, self.panel.c.mclk)
        vpp, vmed = M.medir_seno(v, d["fs"], f)
        pct = self.puntos_pct[self.paso]
        recortada = int(codigos.min()) <= 2 or int(codigos.max()) >= 4093
        if recortada:
            self.recortados.append(pct)
        self.medidas[pct] = [vpp, vmed]
        self.e_vpp.setText(_fmt_v(vpp, 5))
        self.e_vmed.setText(_fmt_v(vmed, 5))
        aviso = f" <span style='color:{W.ALERTA}'>⚠ se recortó en el ADC</span>" if recortada else ""
        self.lbl_lectura.setText(f"Medido con CH1: {_fmt_v(vpp)}pp sobre {_fmt_v(vmed)}{aviso}")
        self._progreso()
        QTimer.singleShot(250, lambda: self._ir(self.paso + 1) if self.auto else None)

    def _terminar_auto(self):
        self.auto = False
        self._t_auto.stop()
        self._t_vence.stop()
        self.btn_auto.setText("Medir automático con CH1")
        for w in (self.btn_saltar, self.e_vpp, self.e_vmed):
            w.setEnabled(True)
        self.btn_ant.setEnabled(self.paso > 0)
        self._validar()
        if self.pila.currentIndex() == 0 or self.paso >= len(self.puntos_pct):
            v = self.panel.tab.v
            vpp100 = self.medidas[self.puntos_pct[-1]][0]
            if self.recortados:
                v.estado("Medición automática lista, pero se recortó en "
                         + ", ".join(f"{p:.0f} %" for p in self.recortados)
                         + ": usá la entrada ±10 V de la placa y repetí.", W.ALERTA)
            elif vpp100 is not None and vpp100 < 0.01:
                v.estado("Medición automática lista, pero a 100 % casi no hay señal: ¿está unida "
                         "la salida PGA con A0?", W.ALERTA)
            else:
                v.estado("Medición automática lista: revisá el resumen y guardá.", W.OK)

    # ------------------------------------------------------------------ resumen
    def _armar_resumen(self):
        self.tabla.setRowCount(0)
        filas = [[pct, *self.medidas[pct]] for pct in self.puntos_pct] + [list(p) for p in self.otros]
        for pct, vpp, vmed in sorted(filas, key=lambda f: f[0]):
            self._agregar_fila(pct, vpp, vmed)

    def _agregar_fila(self, pct, vpp, vmed):
        r = self.tabla.rowCount()
        self.tabla.insertRow(r)
        textos = (_fmt(pct, 2), "" if vpp is None else _fmt_v(vpp, 5),
                  "" if vmed is None else _fmt_v(vmed, 5))
        for col, t in enumerate(textos):
            self.tabla.setItem(r, col, QTableWidgetItem(t))

    def _quitar(self):
        r = self.tabla.currentRow()
        if r >= 0:
            self.tabla.removeRow(r)

    def puntos(self) -> list:
        if self.pila.currentIndex() == 0:   # se guardó sin pasar por el resumen
            self._guardar_paso()
            self._armar_resumen()
        salida = []
        for r in range(self.tabla.rowCount()):
            celdas = [self.tabla.item(r, c).text() if self.tabla.item(r, c) else "" for c in range(3)]
            pct = _leer_num(celdas[0])
            vpp = leer_tension(celdas[1])
            vmed = leer_tension(celdas[2]) if celdas[2].strip() else None
            if pct is not None and vpp is not None:
                salida.append([pct, vpp, vmed])
        return M.limpiar_cal_dds(salida)

    def done(self, r):
        if self.auto:
            self._terminar_auto()
        self.panel._dlg_cal = None
        self.panel.aplicar_config(self._config_previa, conservar_cal=True)   # vuelve a como estaba
        osc = self.panel.tab.v.tab_osc
        if self.osc_corria and not osc.corriendo and self.panel.tab.v.disp.esta_conectado:
            osc._alternar_run()                                              # y el osciloscopio a RUN
        super().done(r)


class PanelDDS(QWidget):
    """Módulo AD9833 externo: seno, triangular o cuadrada de 0,1 Hz a 12,5 MHz, con
    fase, modulaciones y calibración."""

    def __init__(self, tab, datos: dict | None):
        super().__init__()
        self.tab = tab
        self.c = M.ConfigDDS.desde_dict(datos)
        self.frec_real = None
        self.fase_real = None
        self._midiendo: dict | None = None
        self._dlg_cal: DialogoCalDDS | None = None
        raiz = QVBoxLayout(self)
        raiz.setContentsMargins(0, 0, 0, 0)

        # ---------------------------------------------------------------- salida
        g, lay = W.grupo("Módulo AD9833  ·  salida PGA / VOUT del módulo")
        g.setStyleSheet(f"QGroupBox::title {{ color: {COLOR}; }}")
        raiz.addWidget(g)
        self.hab = W.boton("", self._cambio, chequeable=True)
        self.hab.setChecked(self.c.habilitado)
        W.tam(self.hab, "setMinimumHeight", 34)
        lay.addWidget(self.hab)

        fmax = self.c.mclk / 2
        self.forma = W.combo(M.DDS_FORMAS, self.c.forma)
        self.frec = W.EntradaSI("Hz", M.DDS_F_MIN, fmax, self.c.frecuencia, 8)
        self.periodo = W.EntradaSI("s", 1 / fmax, 1 / M.DDS_F_MIN, 1 / self.c.frecuencia, 6)
        self.fase = W.EntradaSI("°", 0, 360, self.c.fase, 5)
        self.amp = W.EntradaSI("%", 0, 100, self.c.amplitud, 4)
        self.vpp = W.EntradaSI("V", 0, 20, 0.0, 4)
        self.fase.setToolTip("Pasos de 0,088°. Con una sola salida no se nota (la fase es relativa "
                             "a algo): sirve en PSK y para la fase con que arranca cada ráfaga.")
        lay.addWidget(W.fila("Forma", self.forma,
                             ayuda="Cuadrada f/2: la cuadrada del AD9833 a la mitad de la frecuencia."))
        lay.addWidget(W.fila("Frecuencia", self.frec))
        lay.addWidget(W.fila("Período", self.periodo))
        # La fase solo se ve en PSK y en ráfagas: ahí aparece (ver _mostrar)
        self.fila_fase = W.fila("Fase", self.fase)
        lay.addWidget(self.fila_fase)
        # Amplitud: en % del potenciómetro mientras no hay calibración; después, en Vpp
        self.fila_amp = W.fila("Amplitud", self.amp,
                               ayuda="Posición del potenciómetro digital (MCP41010) que fija la "
                                     "ganancia de la salida amplificada (PGA). Calibrando, se "
                                     "elige directamente en Vpp.")
        lay.addWidget(self.fila_amp)
        self.fila_vpp = W.fila("Amplitud (Vpp en PGA)", self.vpp,
                               ayuda="Según la calibración, de 0 V al Vpp medido a 100 %. El "
                                     "potenciómetro tiene 256 pasos: queda en el más cercano.")
        lay.addWidget(self.fila_vpp)
        self.lbl_info = W.etiqueta_tenue("")
        self.lbl_info.setWordWrap(True)
        lay.addWidget(self.lbl_info)
        fila_bot = QHBoxLayout()
        fila_bot.addWidget(W.boton("Calibrar amplitud…", self.calibrar_amplitud))
        self.btn_reloj = W.boton("Medir reloj…", self.medir_reloj)
        self.btn_reloj.setToolTip("Mide el reloj real del módulo con el frecuencímetro (D32) y "
                                  "corrige la frecuencia de salida.")
        fila_bot.addWidget(self.btn_reloj)
        lay.addLayout(fila_bot)

        # ---------------------------------------------------------------- modulación
        g2, l2 = W.grupo("Modulación del AD9833")
        raiz.addWidget(g2)
        self.mod = W.combo(M.DDS_MODULACIONES, self.c.modulacion)
        l2.addWidget(W.fila("Tipo", self.mod))
        # barrido
        self.bar_escala = W.combo(["Logarítmico", "Lineal"], "Logarítmico" if self.c.bar_log else "Lineal")
        self.bar_f1 = W.EntradaSI("Hz", M.DDS_F_MIN, fmax, self.c.bar_f1, 6)
        self.bar_f2 = W.EntradaSI("Hz", M.DDS_F_MIN, fmax, self.c.bar_f2, 6)
        self.bar_t = W.EntradaSI("s", 0.05, 1000, self.c.bar_t, 4)
        # FSK / PSK
        self.fsk_f2 = W.EntradaSI("Hz", 0, fmax, self.c.fsk_f2, 7)
        self.fsk_tasa = W.EntradaSI("Bd", 0.1, M.DDS_TASA_MAX, self.c.fsk_tasa, 4)
        self.psk_fase2 = W.EntradaSI("°", 0, 360, self.c.psk_fase2, 5)
        self.psk_tasa = W.EntradaSI("Bd", 0.1, M.DDS_TASA_MAX, self.c.psk_tasa, 4)
        # ráfaga
        self.raf_ciclos = QSpinBox()
        self.raf_ciclos.setRange(1, 1_000_000)
        self.raf_ciclos.setValue(int(self.c.raf_ciclos))
        W.tam(self.raf_ciclos, "setFixedWidth", 110)
        self.raf_periodo = W.EntradaSI("s", 0.001, 100, self.c.raf_periodo, 4)
        # AM
        self.am_prof = W.EntradaSI("%", 0, 100, self.c.am_prof, 4)
        self.am_frec = W.EntradaSI("Hz", 0.01, M.DDS_AM_FMAX, self.c.am_frec, 4)

        self.filas_mod = {
            "Barrido": [W.fila("Escala", self.bar_escala), W.fila("Desde", self.bar_f1),
                        W.fila("Hasta", self.bar_f2), W.fila("Duración", self.bar_t)],
            "FSK": [W.fila("Frecuencia 2", self.fsk_f2),
                    W.fila("Tasa (símbolos/s)", self.fsk_tasa,
                           ayuda="Cada 1/tasa segundos cambia entre la frecuencia principal y la 2.")],
            "PSK": [W.fila("Fase 2", self.psk_fase2),
                    W.fila("Tasa (símbolos/s)", self.psk_tasa,
                           ayuda="Cada 1/tasa segundos cambia entre la fase principal y la 2.")],
            "Ráfaga": [W.fila("Ciclos por ráfaga", self.raf_ciclos),
                       W.fila("Período de repetición", self.raf_periodo)],
            "AM": [W.fila("Profundidad", self.am_prof), W.fila("Frecuencia moduladora", self.am_frec)],
        }
        for filas in self.filas_mod.values():
            for f in filas:
                l2.addWidget(f)
        self.lbl_mod = W.etiqueta_tenue("")
        self.lbl_mod.setWordWrap(True)
        l2.addWidget(self.lbl_mod)

        nota = W.etiqueta_tenue(
            "El seno sale bien hasta unos MHz (probado a 5 MHz). El osciloscopio del instrumento "
            "lo muestra hasta ~500 kHz; más arriba usá el frecuencímetro o un osciloscopio externo.")
        nota.setWordWrap(True)
        raiz.addWidget(nota)
        raiz.addStretch(1)

        # señales
        for cb in (self.forma, self.mod, self.bar_escala):
            cb.currentIndexChanged.connect(self._cambio)
        for e in (self.fase, self.amp, self.bar_f1, self.bar_f2, self.bar_t, self.fsk_f2,
                  self.fsk_tasa, self.psk_fase2, self.psk_tasa, self.raf_periodo, self.am_prof,
                  self.am_frec):
            e.cambiado.connect(self._cambio)
        self.raf_ciclos.valueChanged.connect(self._cambio)
        self.frec.cambiado.connect(lambda f: (self.periodo.set_valor(1 / f), self._cambio()))
        self.periodo.cambiado.connect(lambda t: (self.frec.set_valor(1 / t), self._cambio()))
        self.vpp.cambiado.connect(self._vpp_editado)

        self._t_medicion = QTimer(self)
        self._t_medicion.setSingleShot(True)
        self._t_medicion.timeout.connect(self._medicion_fallida)
        self._mostrar()

    # ------------------------------------------------------------------ estado
    def _leer(self):
        c = self.c
        c.habilitado = self.hab.isChecked()
        c.forma = self.forma.currentText()
        c.frecuencia = self.frec.valor()
        c.fase = self.fase.valor()
        c.amplitud = self.amp.valor()
        c.modulacion = self.mod.currentText()
        c.bar_log = self.bar_escala.currentText() == "Logarítmico"
        c.bar_f1, c.bar_f2, c.bar_t = self.bar_f1.valor(), self.bar_f2.valor(), self.bar_t.valor()
        c.fsk_f2, c.fsk_tasa = self.fsk_f2.valor(), self.fsk_tasa.valor()
        c.psk_fase2, c.psk_tasa = self.psk_fase2.valor(), self.psk_tasa.valor()
        c.raf_ciclos = float(self.raf_ciclos.value())
        c.raf_periodo = self.raf_periodo.valor()
        c.am_prof, c.am_frec = self.am_prof.valor(), self.am_frec.valor()

    def _cambio(self, *_):
        self._leer()
        self._mostrar()
        self.tab.programar_envio_dds()

    def _vpp_editado(self, vpp: float):
        pct = M.dds_porcentaje_para_vpp(M.dds_cal_selector(self.c.cal), vpp)
        if pct is None:
            return
        self.amp.set_valor(pct)
        self._cambio()

    def comandos(self) -> list[str]:
        return M.dds_comandos(self.c, self.tab.dds_extendido())

    # ------------------------------------------------------------------ vista
    def _mostrar(self):
        c = self.c
        self.hab.setText("●  AD9833 ACTIVADO" if self.hab.isChecked() else "○  AD9833 APAGADO")
        for nombre, filas in self.filas_mod.items():
            for f in filas:
                f.setVisible(c.modulacion == nombre)

        # fase: solo donde se nota
        self.fila_fase.setVisible(c.modulacion in ("PSK", "Ráfaga"))
        self.fila_fase.layout().itemAt(0).widget().setText(
            "Fase 1" if c.modulacion == "PSK" else "Fase de arranque")

        # amplitud: con calibración se elige en Vpp (0 % = 0 V); sin ella, en %
        sel = M.dds_cal_selector(c.cal)
        pct_q = M.dds_porcentaje_cuantizado(c.amplitud)
        vpp = M.dds_vpp(sel, pct_q)
        vmed = M.dds_vmedia(c.cal, pct_q)
        calibrada = vpp is not None
        self.fila_amp.setVisible(not calibrada)
        self.fila_vpp.setVisible(calibrada)
        self.vpp.blockSignals(True)
        if calibrada:
            self.vpp.set_rango(0.0, max(M.dds_vpp(sel, 100.0) or 0.0, 1e-3))
        self.vpp.set_valor(vpp or 0.0)
        self.vpp.blockSignals(False)

        disp = self.tab.v.disp
        avisos = []
        if disp.esta_conectado and not self.tab.dds_soportado():
            avisos.append("⚠ El firmware de la placa no maneja el AD9833: cargá el firmware nuevo.")
        elif disp.esta_conectado and not self.tab.dds_extendido():
            avisos.append("⚠ Este firmware solo maneja frecuencia, forma y amplitud: cargá el nuevo "
                          "para fase, modulación y corrección de reloj.")
        # La confirmación de la placa vale mientras coincida con lo pedido (si cambió
        # otra cosa, como la modulación, la frecuencia no se vuelve a mandar)
        esperada = M.dds_frecuencia_real(c.frecuencia, c.mclk)
        confirmada = self.frec_real is not None and abs(self.frec_real - esperada) < 0.01 + 1e-9 * esperada
        f = self.frec_real if confirmada else esperada
        quien = "confirmada por la placa" if confirmada else "que va a salir"
        lineas = [f"Frecuencia {quien}: {M.si(f, 'Hz', 9)} · potenciómetro "
                  f"{M.dds_paso_amplitud(c.amplitud)}/255 ({pct_q:.1f} %)".replace(".", ",")]
        if vpp is not None:
            t = f"≈ {M.si(vpp, 'V', 3)}pp"
            if vmed is not None:
                t += f" sobre {M.si(vmed, 'V', 3)} de continua (de {M.si(vmed - vpp / 2, 'V', 3)} a " \
                     f"{M.si(vmed + vpp / 2, 'V', 3)})"
                if vmed + vpp / 2 > 3.3 or vmed - vpp / 2 < 0:
                    avisos.append("⚠ Así no entra en los pines directos (0 a 3,3 V): usá la etapa de entrada.")
            lineas.append(f"Salida PGA {t} · calibrada con {len(c.cal)} punto(s), de 0 a "
                          f"{M.si(M.dds_vpp(sel, 100.0), 'V', 3)}pp")
        else:
            lineas.append("Amplitud sin calibrar (tocá «Calibrar amplitud…» para verla en volts)")
        ppm = (c.mclk / M.DDS_MCLK - 1) * 1e6
        lineas.append(f"Reloj del módulo: {M.si(c.mclk, 'Hz', 9)}"
                      + (" (nominal)" if abs(ppm) < 0.05 else f" ({ppm:+.1f} ppm, medido)"))
        texto = "<br>".join(lineas)
        if avisos:
            texto = "<br>".join(f"<span style='color:{W.ALERTA}'>{a}</span>" for a in avisos) + "<br>" + texto
        self.lbl_info.setText(texto)
        self.lbl_mod.setText(self._texto_modulacion())

    def _texto_modulacion(self) -> str:
        c = self.c
        m = c.modulacion
        if m == "Barrido":
            return (f"Barre de {M.si(c.bar_f1, 'Hz', 4)} a {M.si(c.bar_f2, 'Hz', 4)} en "
                    f"{M.si(c.bar_t, 's', 3)} y vuelve a empezar (cambia la frecuencia cada 0,5 ms, "
                    "sin saltos de fase).")
        if m == "FSK":
            return (f"Alterna {M.si(c.frecuencia, 'Hz', 6)} y {M.si(c.fsk_f2, 'Hz', 6)}, cada "
                    f"{M.si(1 / c.fsk_tasa, 's', 3)}. Hasta {int(M.DDS_TASA_MAX)} símbolos/s.")
        if m == "PSK":
            return (f"Alterna la fase entre {_grados(c.fase)} y {_grados(c.psk_fase2)}, cada "
                    f"{M.si(1 / c.psk_tasa, 's', 3)}. Hasta {int(M.DDS_TASA_MAX)} símbolos/s. "
                    "Para verlo, dispará el osciloscopio con la señal de datos o usá una base de "
                    "tiempo que muestre varios símbolos.")
        if m == "Ráfaga":
            dur = c.raf_ciclos / max(c.frecuencia, 1e-9)
            t = (f"{int(c.raf_ciclos)} ciclos ({M.si(dur, 's', 3)}) cada {M.si(c.raf_periodo, 's', 3)}; "
                 f"cada ráfaga arranca en {_grados(c.fase)} (la «fase de arranque»). Los tiempos tienen "
                 "~20 µs de incertidumbre.")
            if dur >= c.raf_periodo:
                t = f"<span style='color:{W.ALERTA}'>⚠ La ráfaga dura más que el período: sale continua.</span> " + t
            return t
        if m == "AM":
            return (f"Varía la amplitud ±{c.am_prof:.0f} % a {M.si(c.am_frec, 'Hz', 3)} moviendo el "
                    "potenciómetro (256 pasos, hasta 200 Hz). Es una AM tosca, para pruebas.")
        return "Sin modulación."

    # ------------------------------------------------------------------ calibración de amplitud
    def al_captura(self, d: dict):
        if self._dlg_cal is not None:
            self._dlg_cal.al_captura(d)

    def calibrar_amplitud(self):
        dlg = DialogoCalDDS(self)
        self._dlg_cal = dlg
        if dlg.exec() != QDialog.Accepted:
            return
        self.c.cal = dlg.puntos()
        self._mostrar()
        self.tab.v.guardar_config_pronto()
        n = len(self.c.cal)
        self.tab.v.estado(f"Calibración de amplitud guardada ({n} punto{'s' if n != 1 else ''}).", W.OK)

    def aplicar_config(self, c: "M.ConfigDDS", conservar_cal: bool = False):
        """Pone todos los controles según una configuración (y la manda)."""
        cal, mclk = self.c.cal, self.c.mclk
        controles = [self.hab, self.forma, self.frec, self.periodo, self.fase, self.amp, self.mod,
                     self.bar_escala, self.bar_f1, self.bar_f2, self.bar_t, self.fsk_f2,
                     self.fsk_tasa, self.psk_fase2, self.psk_tasa, self.raf_ciclos,
                     self.raf_periodo, self.am_prof, self.am_frec]
        for w in controles:
            w.blockSignals(True)
        try:
            self.hab.setChecked(c.habilitado)
            self.forma.setCurrentText(c.forma)
            self.frec.set_valor(c.frecuencia)
            self.periodo.set_valor(1 / c.frecuencia)
            self.fase.set_valor(c.fase)
            self.amp.set_valor(c.amplitud)
            self.mod.setCurrentText(c.modulacion)
            self.bar_escala.setCurrentText("Logarítmico" if c.bar_log else "Lineal")
            self.bar_f1.set_valor(c.bar_f1)
            self.bar_f2.set_valor(c.bar_f2)
            self.bar_t.set_valor(c.bar_t)
            self.fsk_f2.set_valor(c.fsk_f2)
            self.fsk_tasa.set_valor(c.fsk_tasa)
            self.psk_fase2.set_valor(c.psk_fase2)
            self.psk_tasa.set_valor(c.psk_tasa)
            self.raf_ciclos.setValue(int(c.raf_ciclos))
            self.raf_periodo.set_valor(c.raf_periodo)
            self.am_prof.set_valor(c.am_prof)
            self.am_frec.set_valor(c.am_frec)
        finally:
            for w in controles:
                w.blockSignals(False)
        self._leer()
        self.c.mclk = mclk
        if conservar_cal:
            self.c.cal = cal
        self._cambio()

    def poner_para_calibrar(self, pct: float):
        """Seno de 1 kHz encendido a la amplitud pedida, sin modulación, para medir."""
        self.hab.setChecked(True)
        self.forma.setCurrentText("Seno")
        self.mod.setCurrentText("Ninguna")
        self.frec.set_valor(1000.0)
        self.periodo.set_valor(1e-3)
        self.amp.set_valor(pct)
        self._cambio()
        self.tab.v.estado(f"AD9833: seno de 1 kHz al {pct:.0f} %. Medí la salida PGA.", W.TEXTO)

    # ------------------------------------------------------------------ medición del reloj
    def medir_reloj(self):
        v = self.tab.v
        if not v.disp.esta_conectado:
            v.estado("Conectá la placa primero.", W.ALERTA)
            return
        if not self.tab.dds_extendido():
            v.estado("Para medir el reloj hace falta el firmware nuevo del AD9833.", W.ALERTA)
            return
        r = QMessageBox.question(
            self, "Medir el reloj del AD9833",
            "Uní la salida VOUT del módulo con D32 (PA0, entrada del frecuencímetro) y la masa.\n\n"
            "Durante ~2 s el AD9833 va a sacar una cuadrada de 1 MHz; después vuelve a lo que "
            "tenías. La precisión es la del cristal de la Nucleo (unas decenas de ppm).\n\n"
            "¿Medir ahora?")
        if r != QMessageBox.Yes:
            return
        self._midiendo = {"f": F_MEDICION, "mclk": self.c.mclk, "t0": time.monotonic()}
        for cmd in (f"DDSCLK {self.c.mclk:.1f}", "DDSMOD NO", "DDSA 128",
                    f"DDS {F_MEDICION:.4f} 2 1", "FCNT 1000 0"):
            v.disp.enviar(cmd)
        self.btn_reloj.setEnabled(False)
        self.btn_reloj.setText("Midiendo…")
        self._t_medicion.start(4000)
        v.estado("Midiendo el reloj del AD9833 con el frecuencímetro…", W.TEXTO)

    def _terminar_medicion(self):
        self._midiendo = None
        self._t_medicion.stop()
        self.btn_reloj.setEnabled(True)
        self.btn_reloj.setText("Medir reloj…")
        self.tab.reenviar_dds()                         # vuelve a lo que estaba
        self.tab.v.tab_herr._reiniciar_f()              # y el frecuencímetro, si estaba midiendo

    def _medicion_fallida(self):
        if self._midiendo is None:
            return
        self._terminar_medicion()
        self.tab.v.estado("No llegó la medición del frecuencímetro: revisá que VOUT esté unido "
                          "a D32 y que el AD9833 esté alimentado.", W.ERROR)

    def al_linea(self, p: list[str]):
        if p[0] == "OK" and len(p) >= 3 and p[1] == "DDS":
            try:
                f = float(p[2])
            except ValueError:
                return
            if self._midiendo is None:
                self.frec_real = f
                self._mostrar()
        elif p[0] == "OK" and len(p) >= 3 and p[1] == "DDSF":
            try:
                self.fase_real = float(p[2])
            except ValueError:
                pass
        elif p[0] == "FREQ" and len(p) >= 2 and self._midiendo is not None:
            try:
                f_med = float(p[1])
            except ValueError:
                return
            m = self._midiendo
            nuevo = M.dds_mclk_corregido(m["mclk"], m["f"], f_med)
            if nuevo is None:
                self._terminar_medicion()
                self.tab.v.estado(f"La medición dio {M.si(f_med, 'Hz', 7)}, que no es la cuadrada de "
                                  "1 MHz del AD9833: revisá la conexión de VOUT a D32.", W.ERROR)
                return
            self.c.mclk = nuevo
            self._terminar_medicion()
            ppm = (nuevo / M.DDS_MCLK - 1) * 1e6
            self._mostrar()
            self.tab.v.guardar_config_pronto()
            self.tab.v.estado(f"Reloj del AD9833: {M.si(nuevo, 'Hz', 9)} ({ppm:+.1f} ppm). "
                              "Ya se corrige en todas las frecuencias.", W.OK)
