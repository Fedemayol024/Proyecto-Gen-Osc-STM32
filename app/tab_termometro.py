"""Pestaña Termómetro NTC: convierte la tensión del circuito NTC + AD620 en temperatura.

Circuito (demo de Medidas Electrónicas I, Unidad 8):
  3V3 ─ NTC ─ A ─ R1 ─ GND        3V3 ─ R2 ─ B ─ R3 ─ GND   (R1 = R2 = R3 = 5,1 kΩ)
  AD620: +IN = A, −IN = REF = B buffereado (1,65 V), G = 1 + 49,4 kΩ / RG
  CH1 = salida del AD620 (protegida)     CH2 = nodo A (opcional, directo)
Las dos entradas se usan en «Pin directo (0–3,3 V)».

Calibración de un punto: con la NTC a temperatura ambiente se mide la tensión y se
escribe la temperatura que marca el multímetro. Con el modelo B de la NTC se obtiene
la resistencia de referencia, y a partir de ahí cada lectura se convierte a temperatura.
"""
from __future__ import annotations

import csv
import math
import time
from datetime import datetime

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QDoubleSpinBox, QFileDialog, QHBoxLayout, QInputDialog, QLabel, QMessageBox,
                               QScrollArea, QVBoxLayout, QWidget)

import modelo as M
import widgets as W

T0_K = 273.15
UNIDADES = ["°C", "K", "°F"]
FS_LECTURA = 10000.0          # 2000 muestras a 10 kS/s = 200 ms: 10 ciclos de 50 Hz (el
N_LECTURA = 2000              # zumbido de la red se promedia y desaparece)
PERIODO_LECTURA_MS = 500
LECTURAS_CAL = 6              # la calibración promedia 3 s de lecturas
MAX_PUNTOS = 30000            # ~4 horas a 2 lecturas por segundo

# Valores de diseño del circuito de la demo
DISENO = {"canal": "CH1", "ganancia": 1 + 49.4 / 47, "r_serie": 5100.0, "vref": 1.65,
          "vexc": 3.3, "beta": 3950.0}


# ---------------------------------------------------------------------------
# Cálculos (sin interfaz: se prueban en tests/test_termometro.py)
# ---------------------------------------------------------------------------
def tension_nodo(v_canal: float, ganancia: float, vref: float) -> float:
    """Tensión del nodo A del puente a partir de lo que mide el canal.
    Por CH1 (salida del AD620): Vout = VREF + G·(VA − VREF). Por CH2, G = 1."""
    return vref + (v_canal - vref) / ganancia


def resistencia_ntc(v_a: float, r_serie: float, vexc: float) -> float:
    """La NTC está arriba en el divisor: VA = Vexc · Rserie / (Rserie + Rntc)."""
    if not 0 < v_a < vexc:
        return float("nan")
    return r_serie * (vexc - v_a) / v_a


def temperatura_k(r: float, r_cal: float, t_cal_k: float, beta: float) -> float:
    """Modelo B: 1/T = 1/Tcal + ln(R/Rcal)/B."""
    if not (r > 0 and r_cal > 0):
        return float("nan")
    inv = 1 / t_cal_k + math.log(r / r_cal) / beta
    return 1 / inv if inv > 0 else float("nan")


def a_unidad(t_k: float, unidad: str) -> float:
    if unidad == "K":
        return t_k
    c = t_k - T0_K
    return c * 9 / 5 + 32 if unidad == "°F" else c


def formato(valor: float, decimales: int = 2) -> str:
    if not math.isfinite(valor):
        return "—"
    return f"{valor:.{decimales}f}".replace(".", ",").replace("-", "−")


class TabTermometro(QWidget):
    def __init__(self, ventana):
        super().__init__()
        self.v = ventana
        cfg = ventana.config.herramientas.get("termo", {})
        self.par = {k: cfg.get(k, d) for k, d in DISENO.items()}
        # calibración guardada (si no hay, se usa la NTC nominal: 5 kΩ a 25 °C)
        self.cal = cfg.get("cal") or None
        self.cal_sesion = False           # ya se calibró (o se eligió la guardada) en esta sesión
        self.calibrando = None            # lista de lecturas mientras calibra
        self.t_cal_c = None
        self.esperando = False
        self.t_pedido = 0.0
        # lecturas: tiempo (epoch), tensión del canal, temperatura en K
        self.t: list[float] = []
        self.vs: list[float] = []
        self.tk: list[float] = []
        self.registro: list[tuple[datetime, float, float, float]] = []   # (fecha y hora, K, V, intervalo s)
        self.acum: list[tuple[float, float]] = []                  # lecturas del intervalo en curso

        raiz = QHBoxLayout(self)
        raiz.setContentsMargins(8, 8, 8, 8)

        # ------------------------------------------------ panel izquierdo
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        W.tam(scroll, "setFixedWidth", 360)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        panel = QWidget()
        izq = QVBoxLayout(panel)
        izq.setContentsMargins(0, 0, 6, 0)
        scroll.setWidget(panel)
        raiz.addWidget(scroll)

        g, lay = W.grupo("Termómetro NTC")
        lay.addWidget(W.etiqueta_tenue(
            "Circuito NTC + puente + AD620 de la demo. Conectá la salida protegida a A0 (CH1) "
            "y, si querés, el nodo A del puente a A1 (CH2). Las entradas se leen en «Pin directo»."))
        self.canal = W.combo(["CH1 · salida del AD620", "CH2 · nodo A del puente"])
        self.canal.setCurrentIndex(0 if self.par["canal"] == "CH1" else 1)
        self.canal.currentIndexChanged.connect(self._cambio_canal)
        lay.addWidget(W.fila("Leer por", self.canal))
        self.unidad = W.combo(UNIDADES, cfg.get("unidad", "°C"))
        self.unidad.currentIndexChanged.connect(self._redibujar)
        lay.addWidget(W.fila("Unidad", self.unidad))
        self.btn_cal = W.boton("Calibrar con la temperatura ambiente…", self._pedir_calibracion, primario=True)
        lay.addWidget(self.btn_cal)
        self.lbl_cal = W.etiqueta_tenue("")
        lay.addWidget(self.lbl_cal)
        izq.addWidget(g)

        g, lay = W.grupo("Circuito")
        self.e_g = W.EntradaSI("", 0.5, 1000, self.par["ganancia"], 4, 100)
        self.e_rs = W.EntradaSI("Ω", 100, 1e6, self.par["r_serie"], 4, 100)
        self.e_vref = W.EntradaSI("V", 0.5, 3.0, self.par["vref"], 4, 100)
        self.e_vexc = W.EntradaSI("V", 1.0, 5.0, self.par["vexc"], 4, 100)
        self.e_beta = QDoubleSpinBox()
        self.e_beta.setRange(1000, 10000)
        self.e_beta.setDecimals(0)
        self.e_beta.setSingleStep(10)
        self.e_beta.setSuffix(" K")
        self.e_beta.setValue(self.par["beta"])
        W.tam(self.e_beta, "setFixedWidth", 100)
        lay.addWidget(W.fila("Ganancia AD620", self.e_g, ayuda="G = 1 + 49,4 kΩ / RG. Con RG = 47 kΩ, G ≈ 2,051"))
        lay.addWidget(W.fila("R serie (R1)", self.e_rs, ayuda="La resistencia de abajo del brazo de la NTC"))
        lay.addWidget(W.fila("VREF", self.e_vref, ayuda="Tensión del pin REF del AD620 (nodo B buffereado)"))
        lay.addWidget(W.fila("Excitación", self.e_vexc, ayuda="Tensión que alimenta el puente (3V3 de la Nucleo)"))
        lay.addWidget(W.fila("B de la NTC", self.e_beta, ayuda="Está en la hoja de datos del termistor (típico 3950 K)"))
        for e in (self.e_g, self.e_rs, self.e_vref, self.e_vexc):
            e.cambiado.connect(self._cambio_parametros)
        self.e_beta.valueChanged.connect(self._cambio_parametros)
        lay.addWidget(W.etiqueta_tenue("Si medís VREF y los 3,3 V con el multímetro y los cargás acá, "
                                       "la conversión queda más exacta. Al cambiar algo, recalibrá."))
        izq.addWidget(g)

        g, lay = W.grupo("Registro")
        self.e_int = W.EntradaSI("s", 1, 3600, cfg.get("intervalo", 30.0), 3, 100)
        lay.addWidget(W.fila("Guardar cada", self.e_int))
        f = QHBoxLayout()
        self.btn_reg = W.boton("Iniciar registro", self._alternar_registro)
        f.addWidget(self.btn_reg)
        f.addWidget(W.boton("Exportar CSV…", self._exportar))
        lay.addLayout(f)
        f = QHBoxLayout()
        f.addWidget(W.boton("Borrar registro", self._borrar_registro))
        f.addWidget(W.boton("Limpiar gráficos", self._limpiar))
        lay.addLayout(f)
        self.lbl_reg = W.etiqueta_tenue("Sin registro.")
        lay.addWidget(self.lbl_reg)
        izq.addWidget(g)
        izq.addStretch(1)

        # ------------------------------------------------ lectura grande y gráficos
        der = QVBoxLayout()
        raiz.addLayout(der, 1)
        fila_t = QHBoxLayout()
        self.lbl_temp = QLabel("—")
        self.lbl_temp.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        fila_t.addWidget(self.lbl_temp)
        fila_t.addStretch(1)
        self.lbl_det = QLabel("")
        self.lbl_det.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        fila_t.addWidget(self.lbl_det)
        der.addLayout(fila_t)
        W.al_cambiar_escala(self._estilo_lectura)
        self._estilo_lectura()

        self.p_v = pg.PlotWidget(background=W.FONDO, axisItems={"bottom": pg.DateAxisItem("bottom")})
        self.p_t = pg.PlotWidget(background=W.FONDO, axisItems={"bottom": pg.DateAxisItem("bottom")})
        for p in (self.p_v, self.p_t):
            p.showGrid(x=True, y=True, alpha=0.3)
            p.getPlotItem().setMenuEnabled(False)
        self.p_t.setXLink(self.p_v)
        self.p_v.setLabel("left", "Tensión", units="V")
        self.p_v.setTitle("Tensión medida", color=W.TENUE)
        self.c_v = self.p_v.plot(pen=pg.mkPen(W.CH1, width=2))
        self.c_t = self.p_t.plot(pen=pg.mkPen("#ff7b72", width=2))
        self.c_reg = self.p_t.plot(pen=None, symbol="o", symbolSize=7, symbolBrush=W.ACENTO, symbolPen=None)
        der.addWidget(self.p_v, 1)
        der.addWidget(self.p_t, 1)

        # ------------------------------------------------ temporizadores
        self.t_lect = QTimer(self)
        self.t_lect.timeout.connect(self._leer)
        self.t_lect.start(PERIODO_LECTURA_MS)
        self.t_reg = QTimer(self)
        self.t_reg.timeout.connect(self._guardar_punto)
        self._cambio_canal()
        self._mostrar_cal()
        self._redibujar()

    # ------------------------------------------------------------ configuración
    def estado_config(self) -> dict:
        d = dict(self.par)
        d.update({"unidad": self.unidad.currentText(), "intervalo": self.e_int.valor(), "cal": self.cal})
        return d

    def _estilo_lectura(self):
        self.lbl_temp.setStyleSheet(f"font-size: {W.pt(40)}pt; font-weight: 700; color: #ff7b72;")
        self.lbl_det.setStyleSheet(f"font-size: {W.pt(11)}pt; color: {W.TENUE};")

    @property
    def num_canal(self) -> int:
        return 1 if self.canal.currentIndex() == 0 else 2

    def _cambio_canal(self, *_):
        c = self.num_canal
        self.par["canal"] = f"CH{c}"
        self.e_g.setEnabled(c == 1)
        self.c_v.setPen(pg.mkPen(W.CH1 if c == 1 else W.CH2, width=2))
        self.p_v.setTitle(f"Tensión medida por CH{c}", color=W.TENUE)
        self.v.guardar_config_pronto()
        if self.t:          # las tensiones viejas son de otro canal: no se mezclan
            self._limpiar()
        if self.cal and self.cal.get("canal") != f"CH{c}":
            self.lbl_cal.setText("La calibración guardada es de otro canal: recalibrá.")
            self.lbl_cal.setStyleSheet(f"color: {W.ALERTA};")

    def _cambio_parametros(self, *_):
        self.par.update({"ganancia": self.e_g.valor(), "r_serie": self.e_rs.valor(),
                         "vref": self.e_vref.valor(), "vexc": self.e_vexc.valor(),
                         "beta": self.e_beta.value()})
        self.v.guardar_config_pronto()
        self._mostrar_cal()
        self._recalcular()

    # ------------------------------------------------------------ conversión
    def _ganancia(self) -> float:
        return self.par["ganancia"] if self.num_canal == 1 else 1.0

    def resistencia(self, v_canal: float) -> float:
        va = tension_nodo(v_canal, self._ganancia(), self.par["vref"])
        return resistencia_ntc(va, self.par["r_serie"], self.par["vexc"])

    def a_kelvin(self, v_canal: float) -> float:
        r = self.resistencia(v_canal)
        if self.cal:
            return temperatura_k(r, self.cal["r"], self.cal["t_k"], self.par["beta"])
        return temperatura_k(r, 5000.0, 25 + T0_K, self.par["beta"])     # NTC nominal

    # ------------------------------------------------------------ visibilidad
    def showEvent(self, e):
        super().showEvent(e)
        # el osciloscopio y el termómetro usan el mismo ADC: mientras se mira esta
        # pestaña, el osciloscopio queda en pausa
        if self.v.tab_osc.corriendo:
            self.v.tab_osc._set_run(False)
            self.v.cancelar_captura()
        if not self.cal_sesion and self.v.disp.esta_conectado:
            QTimer.singleShot(300, self._preguntar_al_entrar)

    def al_conectar(self):
        self.esperando = False
        if self.isVisible():
            self.v.tab_osc._set_run(False)
            self.v.cancelar_captura()
            if not self.cal_sesion:
                QTimer.singleShot(300, self._preguntar_al_entrar)

    def _preguntar_al_entrar(self):
        if self.cal_sesion or not self.isVisible():
            return
        if self.cal:
            caja = QMessageBox(self)
            caja.setWindowTitle("Termómetro NTC")
            caja.setText(f"Hay una calibración guardada ({formato(self.cal['t_k'] - T0_K, 1)} °C con "
                         f"{formato(self.cal['v'], 3)} V, del {self.cal.get('fecha', '—')}).\n\n"
                         "¿Calibrás de nuevo con la temperatura ambiente de ahora?")
            b_nueva = caja.addButton("Calibrar ahora", QMessageBox.AcceptRole)
            caja.addButton("Usar la guardada", QMessageBox.RejectRole)
            caja.exec()
            if caja.clickedButton() is not b_nueva:
                self.cal_sesion = True
                return
        self._pedir_calibracion()

    # ------------------------------------------------------------ calibración
    def _pedir_calibracion(self):
        if not self.v.disp.esta_conectado:
            self.v.estado("Conectá la placa para calibrar el termómetro.", W.ALERTA)
            return
        t, ok = QInputDialog.getDouble(
            self, "Temperatura ambiente",
            "Dejá la NTC quieta, sin tocarla, y medí la temperatura ambiente con el multímetro.\n"
            "¿Cuánto marca? (°C)", 25.0, -20.0, 80.0, 1)
        self.cal_sesion = True
        if not ok:
            return
        self.t_cal_c = t
        self.calibrando = []
        self.btn_cal.setEnabled(False)
        self.lbl_cal.setStyleSheet(f"color: {W.ALERTA};")
        self.lbl_cal.setText("Calibrando: midiendo la tensión durante 3 s, no toques la NTC…")

    def _fin_calibracion(self):
        lect = self.calibrando
        self.calibrando = None
        self.btn_cal.setEnabled(True)
        v = float(np.mean(lect))
        r = self.resistencia(v)
        if not (math.isfinite(r) and r > 0):
            self.lbl_cal.setStyleSheet(f"color: {W.ERROR};")
            self.lbl_cal.setText(f"No se pudo calibrar: con {formato(v, 3)} V el puente da una resistencia "
                                 "imposible. Revisá el canal elegido y las conexiones.")
            return
        self.cal = {"t_k": self.t_cal_c + T0_K, "v": v, "r": r, "canal": self.par["canal"],
                    "fecha": datetime.now().strftime("%d/%m/%Y %H:%M")}
        self._mostrar_cal()
        self._recalcular()
        self.v.guardar_config_pronto()
        self.v.estado(f"Termómetro calibrado: {formato(self.t_cal_c, 1)} °C ↔ {formato(v, 3)} V.", W.OK)

    def _recalcular(self):
        """Con la calibración o los parámetros nuevos se recalcula toda la historia (se
        guardan las tensiones), así el gráfico no queda con un salto en el momento de calibrar."""
        self.tk = [self.a_kelvin(v) for v in self.vs]
        self.registro = [(fh, self.a_kelvin(v), v, dt) for fh, _, v, dt in self.registro]
        self._redibujar()

    def _mostrar_cal(self):
        if self.cal is None:
            self.lbl_cal.setStyleSheet(f"color: {W.ALERTA};")
            self.lbl_cal.setText("Sin calibrar: se usa la NTC nominal (5 kΩ a 25 °C).")
            return
        self.lbl_cal.setStyleSheet(f"color: {W.OK};")
        self.lbl_cal.setText(f"Calibrado el {self.cal.get('fecha', '—')}: {formato(self.cal['t_k'] - T0_K, 1)} °C "
                             f"con {formato(self.cal['v'], 3)} V por {self.cal.get('canal', 'CH1')}\n"
                             f"(NTC = {M.si(self.cal['r'], 'Ω', 4)} a esa temperatura).")

    # ------------------------------------------------------------ adquisición
    def _activo(self) -> bool:
        return self.isVisible() or self.t_reg.isActive()

    def _leer(self):
        if not self.v.disp.esta_conectado or not self._activo():
            return
        if self.esperando and time.monotonic() - self.t_pedido < 2.0:
            return
        # si otra pestaña (osciloscopio, Bode, calibración) está capturando, se le deja el ADC
        if self.v._esperado is not None and self.v.dueno_captura != "termo":
            return
        self.v.pedir_captura("termo", N_LECTURA, 0, FS_LECTURA)
        self.esperando = True
        self.t_pedido = time.monotonic()

    def al_recibir(self, d: dict):
        self.esperando = False
        self.v.dueno_captura = None
        c = self.num_canal
        cod = float(np.mean(d[f"ch{c}"]))
        volt = float(self.v.config.recta_entrada(c, "DIRECTO").volt(cod))
        if self.calibrando is not None:
            self.calibrando.append(volt)
            if len(self.calibrando) >= LECTURAS_CAL:
                self._fin_calibracion()
        tk = self.a_kelvin(volt)
        ahora = time.time()
        self.t.append(ahora)
        self.vs.append(volt)
        self.tk.append(tk)
        if len(self.t) > MAX_PUNTOS:
            del self.t[0], self.vs[0], self.tk[0]
        if self.t_reg.isActive() and math.isfinite(tk):
            self.acum.append((tk, volt))
        u = self.unidad.currentText()
        self.lbl_temp.setText(f"{formato(a_unidad(tk, u), 2)} {u}")
        recorte = cod <= 2 or cod >= 4093
        self.lbl_det.setText(f"CH{c}: {formato(volt, 4)} V   ·   NTC: {M.si(self.resistencia(volt), 'Ω', 4)}"
                             + ("   ·   ⚠ fuera del rango del ADC" if recorte else ""))
        self._redibujar()

    # ------------------------------------------------------------ registro
    def _alternar_registro(self):
        if self.t_reg.isActive():
            self.t_reg.stop()
            self.acum = []
            self.btn_reg.setText("Iniciar registro")
            self._texto_registro("Registro detenido.")
            return
        if not self.v.disp.esta_conectado:
            self.v.estado("Conectá la placa para registrar.", W.ALERTA)
            return
        self.acum = []
        self.t_reg.start(int(self.e_int.valor() * 1000))
        self.btn_reg.setText("Detener registro")
        self._texto_registro("Registrando…")

    def _guardar_punto(self):
        if not self.acum:
            return
        tk = float(np.mean([a[0] for a in self.acum]))
        v = float(np.mean([a[1] for a in self.acum]))
        self.acum = []
        self.registro.append((datetime.now(), tk, v, self.t_reg.interval() / 1000))
        self._texto_registro("Registrando…")
        self._redibujar()

    def _texto_registro(self, estado: str):
        n = len(self.registro)
        cada = formato(self.e_int.valor(), 0)
        self.lbl_reg.setText(f"{estado} {n} punto{'s' if n != 1 else ''} guardado{'s' if n != 1 else ''} "
                             f"(promedio de cada {cada} s). Se ven como puntos azules en el gráfico.")

    def _borrar_registro(self):
        if self.registro and QMessageBox.question(self, "Borrar registro",
                                                  f"¿Borrar los {len(self.registro)} puntos registrados?") != QMessageBox.Yes:
            return
        self.registro = []
        self._texto_registro("Registro borrado.")
        self._redibujar()

    def _limpiar(self):
        self.t, self.vs, self.tk = [], [], []
        self._redibujar()

    def exportar_csv(self, ruta: str, unidad: str):
        """CSV con ; y coma decimal, para que Excel en castellano lo abra bien."""
        with open(ruta, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f, delimiter=";")
            w.writerow(["Fecha", "Hora", f"Temperatura [{unidad}]", f"Tensión CH{self.num_canal} [V]"])
            for fh, tk, v, _ in self.registro:
                w.writerow([fh.strftime("%d/%m/%Y"), fh.strftime("%H:%M:%S"),
                            formato(a_unidad(tk, unidad), 2).replace("−", "-"), formato(v, 4)])

    def _exportar(self):
        if not self.registro:
            self.v.estado("Todavía no hay puntos registrados: tocá «Iniciar registro».", W.ALERTA)
            return
        u = self.unidad.currentText()
        nombre = f"registro_temperatura_{datetime.now():%Y%m%d_%H%M}.csv"
        ruta, _ = QFileDialog.getSaveFileName(self, "Exportar registro", nombre, "CSV (*.csv)")
        if not ruta:
            return
        try:
            self.exportar_csv(ruta, u)
        except OSError as e:
            self.v.estado(f"No se pudo guardar el CSV: {e}", W.ERROR)
            return
        self.v.estado(f"Registro exportado en {u}: {ruta}", W.OK)

    # ------------------------------------------------------------ gráficos
    def _redibujar(self, *_):
        u = self.unidad.currentText()
        self.p_t.setLabel("left", "Temperatura", units=u)
        self.p_t.setTitle(f"Temperatura ({u})", color=W.TENUE)
        if self.t:
            t = np.array(self.t)
            self.c_v.setData(t, np.array(self.vs))
            self.c_t.setData(t, np.array([a_unidad(x, u) for x in self.tk]), connect="finite")
        else:
            self.c_v.setData([], [])
            self.c_t.setData([], [])
        if self.registro:
            # cada punto es el promedio de su intervalo: se dibuja en el medio del intervalo
            self.c_reg.setData([fh.timestamp() - dt / 2 for fh, _, _, dt in self.registro],
                               [a_unidad(tk, u) for _, tk, _, _ in self.registro])
        else:
            self.c_reg.setData([], [])
