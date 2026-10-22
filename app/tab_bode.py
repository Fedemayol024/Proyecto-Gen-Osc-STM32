"""Pestaña Bode: analizador de respuesta en frecuencia.

El generador (CH1) excita el circuito con senoidales de frecuencia creciente.
El osciloscopio mide al mismo tiempo la entrada del circuito (CH1) y la
salida (CH2). Como las dos entradas se muestrean en el mismo instante y con
la misma base de tiempo que el generador, la ganancia y la fase se obtienen
ajustando una senoidal de frecuencia conocida a cada canal.
"""
from __future__ import annotations

import csv
import math
import time

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QFileDialog, QHBoxLayout, QLabel, QVBoxLayout, QWidget

import modelo as M
import widgets as W


class TabBode(QWidget):
    def __init__(self, ventana):
        super().__init__()
        self.v = ventana
        cfg = ventana.config.herramientas.get("bode", {})
        self.activo = False
        self.frecs: list[float] = []
        self.idx = 0
        self.resultados: list[tuple] = []
        self.t_pedido = 0.0
        self.timeout = 2.0
        self.esperando = False

        raiz = QHBoxLayout(self)
        raiz.setContentsMargins(8, 8, 8, 8)

        graf = QVBoxLayout()
        raiz.addLayout(graf, 1)
        self.p_mag = pg.PlotWidget(background=W.FONDO, axisItems={"bottom": W.EjeLogFrecuencia("bottom")})
        self.p_fase = pg.PlotWidget(background=W.FONDO, axisItems={"bottom": W.EjeLogFrecuencia("bottom")})
        for p, et, u in ((self.p_mag, "Ganancia", "dB"), (self.p_fase, "Fase", "°")):
            p.setLogMode(x=True, y=False)
            p.showGrid(x=True, y=True, alpha=0.3)
            p.setLabel("left", et, units=u)
            p.setMenuEnabled(False)
        self.p_fase.setLabel("bottom", "Frecuencia")
        self.p_fase.setXLink(self.p_mag)
        self.c_mag = self.p_mag.plot(pen=pg.mkPen(W.CH2, width=2), symbol="o", symbolSize=5,
                                     symbolBrush=W.CH2, symbolPen=None, antialias=True)
        self.c_fase = self.p_fase.plot(pen=pg.mkPen("#d2a8ff", width=2), symbol="o", symbolSize=5,
                                       symbolBrush="#d2a8ff", symbolPen=None, antialias=True)
        self.ref_3db = pg.InfiniteLine(angle=0, pen=pg.mkPen(W.TENUE, style=pg.QtCore.Qt.DashLine))
        self.p_mag.addItem(self.ref_3db)
        self.ref_3db.setVisible(False)
        graf.addWidget(self.p_mag, 1)
        graf.addWidget(self.p_fase, 1)

        panel = QVBoxLayout()
        cont = QWidget()
        cont.setFixedWidth(330)
        cont.setLayout(panel)
        raiz.addWidget(cont)

        g, lay = W.grupo("Conexión")
        lay.addWidget(W.etiqueta_tenue(
            "Generador CH1 → entrada del circuito y también a la entrada CH1 del osciloscopio.\n"
            "Salida del circuito → entrada CH2 del osciloscopio.\n"
            "Masa común. La escala de las entradas se toma de la pestaña Osciloscopio."))
        panel.addWidget(g)

        g, lay = W.grupo("Barrido")
        self.f1 = W.EntradaSI("Hz", 1, 100e3, cfg.get("f1", 10.0), 4)
        self.f2 = W.EntradaSI("Hz", 1, 100e3, cfg.get("f2", 100e3), 4)
        self.ppd = W.combo(["5", "10", "20", "40"], cfg.get("ppd", "10"))
        self.amp = W.EntradaSI("V", 0.01, 10, cfg.get("amp", 2.0), 4)
        lay.addWidget(W.fila("Desde", self.f1))
        lay.addWidget(W.fila("Hasta", self.f2))
        lay.addWidget(W.fila("Puntos por década", self.ppd))
        lay.addWidget(W.fila("Amplitud (Vpp)", self.amp))
        fila = QHBoxLayout()
        self.btn = W.boton("Iniciar barrido", self._alternar, primario=True)
        fila.addWidget(self.btn)
        fila.addWidget(W.boton("Exportar CSV", self._exportar))
        lay.addLayout(fila)
        self.lbl_prog = W.etiqueta_tenue("")
        lay.addWidget(self.lbl_prog)
        panel.addWidget(g)

        g, lay = W.grupo("Resultado")
        self.lbl_res = QLabel("—")
        self.lbl_res.setWordWrap(True)
        lay.addWidget(self.lbl_res)
        panel.addWidget(g)
        panel.addStretch(1)

        self.vigia = QTimer(self)
        self.vigia.timeout.connect(self._vigilar)
        self.vigia.start(250)
        self.espera = QTimer(self)
        self.espera.setSingleShot(True)
        self.espera.timeout.connect(self._capturar)

    def estado_config(self) -> dict:
        return {"f1": self.f1.valor(), "f2": self.f2.valor(), "ppd": self.ppd.currentText(),
                "amp": self.amp.valor()}

    # ------------------------------------------------------------------
    def _alternar(self):
        if self.activo:
            self._terminar("Barrido detenido.")
            return
        if not self.v.disp.esta_conectado:
            self.v.estado("Conectá la placa primero.", W.ALERTA)
            return
        f1, f2 = sorted((self.f1.valor(), self.f2.valor()))
        ppd = int(self.ppd.currentText())
        n = max(2, int(round(math.log10(f2 / f1) * ppd)) + 1)
        self.frecs = list(np.logspace(math.log10(f1), math.log10(f2), n))
        self.idx = 0
        self.resultados = []
        self.c_mag.setData([], [])
        self.c_fase.setData([], [])
        self.activo = True
        self.btn.setText("Detener")
        self.v.tab_osc._set_run(False)
        self.v.cancelar_captura()
        self.v.dueno_captura = "bode"

        # Tabla senoidal en CH1 con la salida y calibración elegidas en el generador
        pg1 = self.v.tab_gen.paneles[1]
        canal = M.CanalGen(forma="Senoidal", vpp=self.amp.valor(),
                           offset=0.0 if pg1.c.modo_salida == "PLACA" else 1.65,
                           modo_salida=pg1.c.modo_salida)
        self.tabla = M.armar_tabla(canal, pg1.recta())
        self.v.disp.enviar_tabla(1, self.tabla.codigos)
        self.v.disp.enviar("GMOD 1 NO 0 0 0")
        self.v.disp.enviar("GSWP 1 NO")
        self._siguiente()

    def _siguiente(self):
        if not self.activo:
            return
        if self.idx >= len(self.frecs):
            self._terminar("Barrido terminado.")
            return
        f = self.frecs[self.idx]
        self.v.disp.enviar(f"GSET 1 {f:.6f} 0 1 {self.tabla.reposo}")
        fs_gen = self.v.disp.info.get("gen_fs", 1e6)
        inc = round(f / fs_gen * 2 ** 32)
        self.f_real = inc * fs_gen / 2 ** 32
        self.lbl_prog.setText(f"Punto {self.idx + 1} de {len(self.frecs)}: {M.si(f, 'Hz')}")
        # esperar que el circuito llegue al régimen permanente
        self.espera.start(int(max(60, 8000 / f)))

    def _capturar(self):
        f = self.f_real
        fsmax = self.v.disp.info.get("osc_fsmax", 1.6e6)
        fs = min(fsmax, 50 * f)
        periodos = max(8.0, 400 * f / fs)
        n = int(min(8192, max(400, round(periodos * fs / f))))
        self.v.pedir_captura("bode", n, 0, fs)
        self.esperando = True
        self.t_pedido = time.monotonic()
        self.timeout = n / fs + 2.0

    def _vigilar(self):
        if self.activo and self.esperando and time.monotonic() - self.t_pedido > self.timeout:
            self._capturar()

    def al_recibir(self, d: dict):
        if not self.activo:
            return
        self.esperando = False
        osc = self.v.tab_osc
        v1 = osc.recta(1).volt(d["ch1"]) * osc.canales[1].factor
        v2 = osc.recta(2).volt(d["ch2"]) * osc.canales[2].factor
        a1, f1, _ = M.ajuste_seno(v1, d["fs"], self.f_real)
        a2, f2, _ = M.ajuste_seno(v2, d["fs"], self.f_real)
        if a1 < 1e-4:
            self._terminar("No llega señal a la entrada CH1: revisá la conexión del generador.")
            return
        g = 20 * math.log10(max(a2, 1e-9) / a1)
        fase = math.degrees(f2 - f1)
        fase = (fase + 180) % 360 - 180
        if self.resultados:          # continuidad de la fase (sin saltos de 360°)
            ant = self.resultados[-1][2]
            while fase - ant > 180:
                fase -= 360
            while fase - ant < -180:
                fase += 360
        self.resultados.append((self.f_real, g, fase, a1 * 2, a2 * 2))
        arr = np.array(self.resultados)
        self.c_mag.setData(arr[:, 0], arr[:, 1])
        self.c_fase.setData(arr[:, 0], arr[:, 2])
        self.idx += 1
        self._siguiente()

    def _terminar(self, msg: str):
        self.activo = False
        self.esperando = False
        self.espera.stop()
        self.btn.setText("Iniciar barrido")
        self.lbl_prog.setText(msg)
        self.v.dueno_captura = None
        self.v.tab_gen.reenviar_todo()
        self._resumen()
        self.v.estado(msg, W.TEXTO)

    def _resumen(self):
        if len(self.resultados) < 2:
            return
        arr = np.array(self.resultados)
        f, g = arr[:, 0], arr[:, 1]
        gmax = g.max()
        txt = [f"Ganancia máxima: {gmax:.2f} dB a {M.si(f[g.argmax()], 'Hz')}".replace(".", ",")]
        corte = []
        for i in range(1, len(g)):
            a, b = g[i - 1] - (gmax - 3), g[i] - (gmax - 3)
            if a * b < 0:
                x = math.log10(f[i - 1]) + (math.log10(f[i]) - math.log10(f[i - 1])) * a / (a - b)
                corte.append(10 ** x)
        if corte:
            txt.append("Frecuencia de corte (−3 dB): " + ", ".join(M.si(c, "Hz") for c in corte))
        self.ref_3db.setPos(gmax - 3)
        self.ref_3db.setVisible(True)
        self.lbl_res.setText("\n".join(txt))

    def _exportar(self):
        if not self.resultados:
            return
        ruta, _ = QFileDialog.getSaveFileName(self, "Exportar Bode", "bode.csv", "CSV (*.csv)")
        if not ruta:
            return
        try:
            with open(ruta, "w", newline="", encoding="utf-8") as fh:
                w = csv.writer(fh, delimiter=";")
                w.writerow(["frecuencia_Hz", "ganancia_dB", "fase_grados", "vpp_entrada_V", "vpp_salida_V"])
                for r in self.resultados:
                    w.writerow([f"{x:.6g}" for x in r])
        except OSError as e:
            self.v.estado(f"No se pudo guardar {ruta}: {e.strerror or e}", W.ERROR)
            return
        self.v.estado(f"Guardado: {ruta}", W.OK)
