"""Panel del módulo AD9833 (generador DDS externo) para la pestaña Generador.

Incluye:
- forma, frecuencia, fase y amplitud (en % del potenciómetro o en Vpp si está calibrado);
- modulaciones hechas por el firmware: barrido, FSK, PSK, ráfaga y AM;
- calibración de la amplitud (tabla de % → Vpp y tensión media medidos);
- medición del reloj real del módulo con el frecuencímetro de la placa.
"""
from __future__ import annotations

import time

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QAbstractItemView, QDialog, QDialogButtonBox, QHBoxLayout,
                               QHeaderView, QMessageBox, QSpinBox, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

import modelo as M
import widgets as W

COLOR = W.OK
F_MEDICION = 1e6          # frecuencia para medir el reloj (cuadrada, con compuerta de 1 s)


def _leer_num(texto: str) -> float | None:
    t = (texto or "").strip().replace(",", ".").replace("V", "").replace("v", "").strip()
    if not t:
        return None
    try:
        return float(t)
    except ValueError:
        return None


def _fmt(v: float | None, dec: int = 3) -> str:
    return "" if v is None else f"{v:.{dec}f}".rstrip("0").rstrip(".").replace(".", ",")


class DialogoCalDDS(QDialog):
    """Tabla de puntos medidos: amplitud en % → Vpp y tensión media de la salida PGA."""

    def __init__(self, panel: "PanelDDS"):
        super().__init__(panel)
        self.panel = panel
        self.setWindowTitle("Calibrar la amplitud del AD9833")
        lay = QVBoxLayout(self)
        lay.addWidget(W.etiqueta_tenue(
            "Poné el AD9833 en seno a 1 kHz y medí la salida PGA con un osciloscopio en acople DC. "
            "Para cada amplitud anotá el Vpp y la tensión media (el centro de la onda, o "
            "(Vmáx + Vmín) / 2). Con «Probar este punto» la salida pasa a esa amplitud. "
            "Alcanza con dos puntos; con cinco queda mejor."))
        self.tabla = QTableWidget(0, 3)
        self.tabla.setHorizontalHeaderLabels(["Amplitud (%)", "Vpp medido (V)", "V media medida (V)"])
        self.tabla.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.tabla.verticalHeader().setVisible(False)
        self.tabla.setSelectionBehavior(QAbstractItemView.SelectRows)
        W.tam(self.tabla, "setMinimumSize", 460, 230)
        lay.addWidget(self.tabla, 1)
        filas = {round(p[0], 3): p for p in panel.c.cal}
        for pct in M.DDS_PUNTOS_CAL:
            filas.setdefault(round(pct, 3), [pct, None, None])
        for k in sorted(filas):
            self._agregar(*filas[k])

        botones = QHBoxLayout()
        botones.addWidget(W.boton("Probar este punto", self._probar))
        botones.addWidget(W.boton("Agregar fila", lambda: self._agregar(50.0, None, None)))
        botones.addWidget(W.boton("Quitar fila", self._quitar))
        botones.addStretch(1)
        lay.addLayout(botones)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("Guardar")
        bb.button(QDialogButtonBox.Cancel).setText("Cancelar")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def _agregar(self, pct, vpp, vmed):
        r = self.tabla.rowCount()
        self.tabla.insertRow(r)
        for col, v in enumerate((pct, vpp, vmed)):
            self.tabla.setItem(r, col, QTableWidgetItem(_fmt(v, 2 if col == 0 else 3)))

    def _quitar(self):
        r = self.tabla.currentRow()
        if r >= 0:
            self.tabla.removeRow(r)

    def _probar(self):
        r = self.tabla.currentRow()
        pct = _leer_num(self.tabla.item(r, 0).text()) if r >= 0 and self.tabla.item(r, 0) else None
        if pct is None:
            self.panel.tab.v.estado("Elegí una fila con la amplitud a probar.", W.ALERTA)
            return
        self.panel.poner_para_calibrar(min(max(pct, 0.0), 100.0))

    def puntos(self) -> list:
        salida = []
        for r in range(self.tabla.rowCount()):
            celdas = [self.tabla.item(r, c).text() if self.tabla.item(r, c) else "" for c in range(3)]
            pct, vpp, vmed = (_leer_num(t) for t in celdas)
            if pct is not None and vpp is not None:
                salida.append([pct, vpp, vmed])
        return M.limpiar_cal_dds(salida)


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
        lay.addWidget(W.fila("Forma", self.forma,
                             ayuda="Cuadrada f/2: la cuadrada del AD9833 a la mitad de la frecuencia."))
        lay.addWidget(W.fila("Frecuencia", self.frec))
        lay.addWidget(W.fila("Período", self.periodo))
        lay.addWidget(W.fila("Fase", self.fase, ayuda="Pasos de 0,088°. Sirve para FSK/PSK y "
                                                      "para alinear con otro generador."))
        lay.addWidget(W.fila("Amplitud", self.amp,
                             ayuda="Posición del potenciómetro digital (MCP41010) que fija la "
                                   "ganancia de la salida amplificada (PGA)."))
        self.fila_vpp = W.fila("Amplitud (Vpp en PGA)", self.vpp,
                               ayuda="Disponible después de calibrar la amplitud.")
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
        pct = M.dds_porcentaje_para_vpp(self.c.cal, vpp)
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

        # amplitud en volts (si está calibrada)
        vpp = M.dds_vpp(c.cal, c.amplitud)
        vmed = M.dds_vmedia(c.cal, c.amplitud)
        self.fila_vpp.setEnabled(vpp is not None)
        self.vpp.blockSignals(True)
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
                  f"{M.dds_paso_amplitud(c.amplitud)}/255"]
        if vpp is not None:
            t = f"≈ {M.si(vpp, 'V', 3)}pp"
            if vmed is not None:
                t += f" sobre {M.si(vmed, 'V', 3)} de continua (de {M.si(vmed - vpp / 2, 'V', 3)} a " \
                     f"{M.si(vmed + vpp / 2, 'V', 3)})"
                if vmed + vpp / 2 > 3.3 or vmed - vpp / 2 < 0:
                    avisos.append("⚠ Así no entra en los pines directos (0 a 3,3 V): usá la etapa de entrada.")
            lineas.append(f"Salida PGA {t} · calibrada con {len(c.cal)} punto(s)")
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
            return (f"Alterna la fase entre {c.fase:.1f}° y {c.psk_fase2:.1f}°, cada "
                    f"{M.si(1 / c.psk_tasa, 's', 3)}. Hasta {int(M.DDS_TASA_MAX)} símbolos/s.")
        if m == "Ráfaga":
            dur = c.raf_ciclos / max(c.frecuencia, 1e-9)
            t = (f"{int(c.raf_ciclos)} ciclos ({M.si(dur, 's', 3)}) cada {M.si(c.raf_periodo, 's', 3)}; "
                 "cada ráfaga arranca en fase 0. Los tiempos tienen ~20 µs de incertidumbre.")
            if dur >= c.raf_periodo:
                t = f"<span style='color:{W.ALERTA}'>⚠ La ráfaga dura más que el período: sale continua.</span> " + t
            return t
        if m == "AM":
            return (f"Varía la amplitud ±{c.am_prof:.0f} % a {M.si(c.am_frec, 'Hz', 3)} moviendo el "
                    "potenciómetro (256 pasos, hasta 200 Hz). Es una AM tosca, para pruebas.")
        return "Sin modulación."

    # ------------------------------------------------------------------ calibración de amplitud
    def calibrar_amplitud(self):
        dlg = DialogoCalDDS(self)
        if dlg.exec() != QDialog.Accepted:
            return
        self.c.cal = dlg.puntos()
        self._mostrar()
        self.tab.v.guardar_config_pronto()
        n = len(self.c.cal)
        self.tab.v.estado(f"Calibración de amplitud guardada ({n} punto{'s' if n != 1 else ''}).", W.OK)

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
