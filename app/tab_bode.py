"""Pestaña Bode: analizador de respuesta en frecuencia.

La fuente (el generador interno CH1, o el módulo AD9833) excita el circuito con
senoidales de frecuencia creciente. El osciloscopio mide al mismo tiempo la
entrada del circuito (CH1) y la salida (CH2); la ganancia y la fase salen de
ajustar una senoidal a cada canal.

Con el generador interno la frecuencia se conoce exacta (comparte el reloj con
el ADC). Con el AD9833 (reloj propio) se estima de los datos de CH1, y por
encima de ~fs/2,5 se mide submuestreando: la señal aparece plegada a ~fs/4, y
como los dos canales se muestrean en el mismo instante el cociente conserva la
ganancia y la fase reales (ver modelo.respuesta_bode).
"""
from __future__ import annotations

import csv
import math
import time

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QTimer
import datetime as dt

import os
import re

from PySide6.QtCore import QStandardPaths, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QCheckBox, QDialog, QDialogButtonBox, QFileDialog, QHBoxLayout,
                               QLabel, QLineEdit, QPlainTextEdit, QVBoxLayout, QWidget)

import modelo as M
import widgets as W


def nombre_archivo(titulo: str) -> str:
    """El título del informe como nombre de archivo válido en Windows (sin \\ / : * ? " < > |)."""
    t = re.sub(r'[\\/:*?"<>|\x00-\x1f]', " ", titulo)
    t = re.sub(r"\s+", " ", t).strip().rstrip(". ")
    return t[:120]

FUENTE_GEN = "Generador interno (CH1)"
FUENTE_DDS = "Módulo AD9833"
FUENTES = [FUENTE_GEN, FUENTE_DDS]


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
        # curva del modelo ajustado (punteada, encima de la medida)
        estilo_mod = pg.QtCore.Qt.DashLine
        self.c_mag_mod = self.p_mag.plot(pen=pg.mkPen("#f0883e", width=2, style=estilo_mod))
        self.c_fase_mod = self.p_fase.plot(pen=pg.mkPen("#f0883e", width=2, style=estilo_mod))
        self.modelo = None
        self.analisis = None
        self.ref_3db = pg.InfiniteLine(angle=0, pen=pg.mkPen(W.TENUE, style=pg.QtCore.Qt.DashLine))
        self.p_mag.addItem(self.ref_3db)
        self.ref_3db.setVisible(False)
        graf.addWidget(self.p_mag, 1)
        graf.addWidget(self.p_fase, 1)

        panel = QVBoxLayout()
        cont = QWidget()
        W.tam(cont, "setFixedWidth", 330)
        cont.setLayout(panel)
        raiz.addWidget(cont)

        g, lay = W.grupo("Fuente y conexión")
        self.fuente = W.combo(FUENTES, cfg.get("fuente", FUENTE_GEN))
        self.fuente.setToolTip("El generador interno llega a ~100 kHz; el AD9833 hasta 10 MHz "
                               "(arriba de ~600 kHz se mide submuestreando).")
        lay.addWidget(W.fila("Fuente", self.fuente))
        self.lbl_con = W.etiqueta_tenue("")
        self.lbl_con.setWordWrap(True)
        lay.addWidget(self.lbl_con)
        panel.addWidget(g)

        g, lay = W.grupo("Barrido")
        self.f1 = W.EntradaSI("Hz", 1, M.BODE_DDS_FMAX, cfg.get("f1", 10.0), 4)
        self.f2 = W.EntradaSI("Hz", 1, M.BODE_DDS_FMAX, cfg.get("f2", 100e3), 4)
        self.ppd = W.combo(["5", "10", "20", "40"], cfg.get("ppd", "10"))
        self.amp = W.EntradaSI("V", 0.01, 10, cfg.get("amp", 2.0), 4)
        lay.addWidget(W.fila("Desde", self.f1))
        lay.addWidget(W.fila("Hasta", self.f2))
        lay.addWidget(W.fila("Puntos por década", self.ppd))
        self.fila_amp = W.fila("Amplitud (Vpp)", self.amp)
        lay.addWidget(self.fila_amp)
        self.lbl_amp_dds = W.etiqueta_tenue("")
        self.lbl_amp_dds.setWordWrap(True)
        lay.addWidget(self.lbl_amp_dds)
        fila = QHBoxLayout()
        self.btn = W.boton("Iniciar barrido", self._alternar, primario=True)
        fila.addWidget(self.btn)
        fila.addWidget(W.boton("Exportar CSV", self._exportar))
        lay.addLayout(fila)
        self.btn_pdf = W.boton("Informe PDF…", self._informe)
        self.btn_pdf.setToolTip("Informe con los datos del ensayo, la tabla de frecuencias "
                                "características, H(s), los gráficos medición vs. modelo y la "
                                "constelación de polos y ceros.")
        self.btn_pdf.setEnabled(False)
        lay.addWidget(self.btn_pdf)
        self.lbl_prog = W.etiqueta_tenue("")
        lay.addWidget(self.lbl_prog)
        panel.addWidget(g)

        g, lay = W.grupo("Resultado")
        self.lbl_res = QLabel("—")
        self.lbl_res.setWordWrap(True)
        self.lbl_res.setTextFormat(pg.QtCore.Qt.RichText)
        lay.addWidget(self.lbl_res)
        self.chk_modelo = QCheckBox("Mostrar el modelo (punteado)")
        self.chk_modelo.setChecked(cfg.get("modelo", True))
        self.chk_modelo.setToolTip("Curva de los polos y ceros ajustados a la medición, en línea punteada naranja.")
        self.chk_modelo.toggled.connect(self._mostrar_modelo)
        lay.addWidget(self.chk_modelo)
        panel.addWidget(g)
        panel.addStretch(1)

        self.vigia = QTimer(self)
        self.vigia.timeout.connect(self._vigilar)
        self.vigia.start(250)
        self.espera = QTimer(self)
        self.espera.setSingleShot(True)
        self.espera.timeout.connect(self._capturar)
        self.fuente.currentIndexChanged.connect(self._cambio_fuente)
        self._cambio_fuente()

    def estado_config(self) -> dict:
        return {"f1": self.f1.valor(), "f2": self.f2.valor(), "ppd": self.ppd.currentText(),
                "amp": self.amp.valor(), "fuente": self.fuente.currentText(),
                "modelo": self.chk_modelo.isChecked()}

    @property
    def con_dds(self) -> bool:
        return self.fuente.currentText() == FUENTE_DDS

    def _cambio_fuente(self, *_):
        dds = self.con_dds
        fmax = M.BODE_DDS_FMAX if dds else 100e3
        for e in (self.f1, self.f2):
            e.set_rango(1, fmax)
            e.set_valor(min(e.valor(), fmax))
        self.fila_amp.setVisible(not dds)
        self.lbl_amp_dds.setVisible(dds)
        if dds:
            self.lbl_con.setText(
                "PGA del AD9833 → entrada del circuito y A0 (CH1).\n"
                "Salida del circuito → A1 (CH2). Masa común.\n"
                "Arriba de ~600 kHz mide submuestreando.")
            self.lbl_con.setToolTip(
                "Hasta ~fs/2,5 se mide directo. Más arriba la señal se muestrea a una fs elegida "
                "para que aparezca plegada a ~fs/4; como CH1 y CH2 se muestrean en el mismo "
                "instante, el cociente conserva la ganancia y la fase reales.\n"
                "Arriba de ~2 MHz pesan el ancho de banda del ADC y de la etapa de entrada: como "
                "la entrada se mide con CH1, el cociente sigue valiendo mientras la señal se vea.")
            self.actualizar_amplitud_dds()
        else:
            self.lbl_con.setToolTip("")
            self.lbl_con.setText(
                "Generador CH1 → entrada del circuito y también a la entrada CH1 del osciloscopio.\n"
                "Salida del circuito → entrada CH2 del osciloscopio.\n"
                "Masa común. La escala de las entradas se toma de la pestaña Osciloscopio.")
        self.v.guardar_config_pronto()

    def actualizar_amplitud_dds(self):
        if not hasattr(self.v, "tab_gen"):
            return
        c = self.v.tab_gen.dds.c
        vpp = M.dds_vpp(M.dds_cal_selector(c.cal), M.dds_porcentaje_cuantizado(c.amplitud))
        cuanto = f"≈ {M.si(vpp, 'V', 3)}pp" if vpp is not None else f"{c.amplitud:.0f} % (sin calibrar)"
        self.lbl_amp_dds.setText(f"Amplitud: la del panel AD9833 ({cuanto})")
        self.lbl_amp_dds.setToolTip("Se cambia en Generador → Módulo AD9833. Elegila para que la "
                                    "salida del circuito no se recorte en CH2.")

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
        self.c_mag_mod.setData([], [])
        self.c_fase_mod.setData([], [])
        self.modelo = self.analisis = None
        self.lbl_res.setText("—")
        if self.con_dds:
            gen = self.v.tab_gen
            if not gen.dds_soportado():
                self.v.estado("El firmware de la placa no maneja el AD9833: cargá el firmware nuevo.",
                              W.ALERTA)
                return
            if f2 > self.v.disp.info.get("osc_fsmax", 1.6e6) * M.BODE_DIRECTO_MAX and \
                    not gen.dds_extendido():
                self.v.estado("Para pasar de ~600 kHz hace falta el firmware nuevo del AD9833.", W.ALERTA)
                return
        self.meta = self._datos_del_ensayo(f1, f2, ppd, len(self.frecs))
        self._ultimo_titulo = self._ultimas_notas = ""     # informe nuevo: sin lo del anterior
        self.t_inicio = time.monotonic()
        self.btn_pdf.setEnabled(False)
        self.activo = True
        self.btn.setText("Detener")
        self.v.tab_osc._set_run(False)
        self.v.cancelar_captura()
        self.v.dueno_captura = "bode"

        if self.con_dds:
            c = self.v.tab_gen.dds.c
            self.mclk = c.mclk
            if self.v.tab_gen.dds_extendido():
                self.v.disp.enviar(f"DDSCLK {c.mclk:.1f}")
                self.v.disp.enviar("DDSMOD NO")
            self.v.disp.enviar(f"DDSA {M.dds_paso_amplitud(c.amplitud)}")
            self._siguiente()
            return

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
        if self.con_dds:
            self.v.disp.enviar(f"DDS {f:.4f} 0 1")
            self.f_real = M.dds_frecuencia_real(f, self.mclk)
        else:
            self.v.disp.enviar(f"GSET 1 {f:.6f} 0 1 {self.tabla.reposo}")
            fs_gen = self.v.disp.info.get("gen_fs", 1e6)
            inc = round(f / fs_gen * 2 ** 32)
            self.f_real = inc * fs_gen / 2 ** 32
        self.submuestreo = False
        self.acum = []               # (H = salida/entrada, amplitud de entrada) de cada captura
        self.rep = 1
        self.lbl_prog.setText(f"Punto {self.idx + 1} de {len(self.frecs)}: {M.si(f, 'Hz')}"
                              + (" · AD9833" if self.con_dds else ""))
        # esperar que el circuito llegue al régimen permanente
        self.espera.start(int(max(60, 8000 / f)))

    def _capturar(self):
        fsmax = self.v.disp.info.get("osc_fsmax", 1.6e6)
        ventana = int(self.v.disp.info.get("ventana", 8192))
        if self.con_dds:
            n, fs, self.submuestreo = M.captura_bode_dds(self.f_real, fsmax, ventana)
            if self.submuestreo and not self.acum:
                self.lbl_prog.setText(f"Punto {self.idx + 1} de {len(self.frecs)}: "
                                      f"{M.si(self.f_real, 'Hz')} · AD9833, submuestreando a "
                                      f"{M.si(fs, 'S/s', 4)}")
        else:
            n, fs = M.captura_bode(self.f_real, fsmax, ventana)
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
        # Con el AD9833 la frecuencia se estima de CH1 (reloj propio) y puede estar submuestreada
        h, a1, a2, r2 = M.respuesta_bode(v1, v2, d["fs"], self.f_real, estimar=self.con_dds)
        if a1 < 1e-4:
            fuente = "del AD9833 (salida PGA)" if self.con_dds else "del generador"
            self._terminar(f"No llega señal a la entrada CH1: revisá la conexión {fuente}.")
            return
        # Se promedia H complejo (no el módulo): el ruido se cancela en vez de sumar amplitud.
        # La fase de CH1 de cada captura hace de referencia, así no importa dónde arrancó.
        self.acum.append((h, a1))
        if len(self.acum) == 1:
            self.rep = M.repeticiones_bode(a2, r2, d["n"], d["n"] / d["fs"])
        if len(self.acum) < self.rep:
            self.lbl_prog.setText(f"Punto {self.idx + 1} de {len(self.frecs)}: "
                                  f"{M.si(self.f_real, 'Hz')} · salida chica, promediando "
                                  f"{len(self.acum) + 1} de {self.rep}")
            self._capturar()
            return
        h = complex(np.mean([h for h, _ in self.acum]))
        a1 = float(np.mean([a for _, a in self.acum]))
        a2 = abs(h) * a1
        g = 20 * math.log10(max(abs(h), 1e-9))
        fase = math.degrees(math.atan2(h.imag, h.real))
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
        if getattr(self, "meta", None) is not None and self.activo:
            dur = time.monotonic() - getattr(self, "t_inicio", time.monotonic())
            self.meta["Duración del barrido"] = f"{dur:.0f} s".replace(".", ",")
            self.meta["Puntos medidos"] = f"{len(self.resultados)} de {len(self.frecs)}"
        self.activo = False
        self.esperando = False
        self.espera.stop()
        self.btn.setText("Iniciar barrido")
        self.lbl_prog.setText(msg)
        self.v.dueno_captura = None
        self.v.tab_gen.reenviar_todo()
        self._resumen()
        self.btn_pdf.setEnabled(len(self.resultados) >= 2)
        self.v.estado(msg, W.TEXTO)

    # ------------------------------------------------------------------ informe
    def _datos_del_ensayo(self, f1, f2, ppd, n) -> dict:
        v = self.v
        osc = v.tab_osc
        entradas = " · ".join(f"CH{c}: {osc.canales[c].entrada.currentText()} "
                              f"{osc.canales[c].punta.currentText()}" for c in (1, 2))
        if self.con_dds:
            c = v.tab_gen.dds.c
            ppm = (c.mclk / M.DDS_MCLK - 1) * 1e6
            fuente = f"Módulo AD9833 · reloj {M.si(c.mclk, 'Hz', 9)}" + \
                (" (nominal)" if abs(ppm) < 0.05 else f" ({ppm:+.1f} ppm, medido)".replace(".", ","))
            vpp = M.dds_vpp(M.dds_cal_selector(c.cal), M.dds_porcentaje_cuantizado(c.amplitud))
            amp = (f"≈ {M.si(vpp, 'V', 3)}pp (calibrada)" if vpp is not None
                   else f"{c.amplitud:.0f} % del potenciómetro (sin calibrar)")
            metodo = ("directo hasta ~fs/2,5; más arriba submuestreo con la frecuencia estimada "
                      "de los datos de CH1")
        else:
            fuente = "Generador interno CH1 (DAC)"
            amp = f"{M.si(self.amp.valor(), 'V', 3)}pp"
            metodo = "directo, ajuste senoidal a la frecuencia exacta del generador"
        d = {
            "Fecha": dt.datetime.now().strftime("%d/%m/%Y %H:%M"),
            "Placa": M.nombre_placa(v.placa),
            "Versión de la app": getattr(v, "version_app", ""),
            "Firmware de la placa": v.disp.version or "",
            "Fuente": fuente,
            "Barrido": f"{M.si(f1, 'Hz', 4)} a {M.si(f2, 'Hz', 4)} · {ppd} puntos por década · {n} puntos",
            "Amplitud": amp,
            "Entradas del osciloscopio": entradas,
            "Muestreo máximo": M.si(v.disp.info.get("osc_fsmax", 0), "S/s", 4),
            "Método": metodo,
        }
        return {k: x for k, x in d.items() if x and not x.startswith("0 ")}

    def _informe(self):
        if len(self.resultados) < 2:
            return
        dlg = QDialog(self)
        dlg.setWindowTitle("Informe PDF del Bode")
        lay = QVBoxLayout(dlg)
        lay.addWidget(QLabel("Título (qué circuito es):"))
        e_tit = QLineEdit(getattr(self, "_ultimo_titulo", ""))
        e_tit.setPlaceholderText("p. ej. RL pasaaltos · 1 mH + 220 Ω")
        lay.addWidget(e_tit)
        lay.addWidget(QLabel("Notas (opcional):"))
        e_not = QPlainTextEdit(getattr(self, "_ultimas_notas", ""))
        e_not.setPlaceholderText("Cómo estaba armado, qué se quería ver…")
        W.tam(e_not, "setMinimumSize", 420, 90)
        lay.addWidget(e_not)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("Elegir dónde guardar…")
        bb.button(QDialogButtonBox.Cancel).setText("Cancelar")
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        lay.addWidget(bb)
        if dlg.exec() != QDialog.Accepted:
            return
        self._ultimo_titulo, self._ultimas_notas = e_tit.text(), e_not.toPlainText()
        nombre = nombre_archivo(self._ultimo_titulo) or \
            "bode_" + dt.datetime.now().strftime("%Y-%m-%d_%H%M")
        carpeta = getattr(self, "_carpeta_informes", "") or \
            QStandardPaths.writableLocation(QStandardPaths.DocumentsLocation)
        ruta, _ = QFileDialog.getSaveFileName(self, "Guardar informe",
                                              os.path.join(carpeta, nombre + ".pdf"), "PDF (*.pdf)")
        if not ruta:
            return
        if not ruta.lower().endswith(".pdf"):
            ruta += ".pdf"
        self._carpeta_informes = os.path.dirname(ruta)
        self.generar_informe(ruta, self._ultimo_titulo, self._ultimas_notas, abrir=True)

    def generar_informe(self, ruta: str, titulo: str = "", notas: str = "", abrir: bool = False) -> bool:
        import informe_bode
        meta = dict(getattr(self, "meta", None) or {"Fecha": dt.datetime.now().strftime("%d/%m/%Y %H:%M")})
        try:
            paginas = informe_bode.generar(ruta, self.resultados, self.modelo, self.analisis, meta,
                                           titulo, notas)
        except OSError as e:
            self.v.estado(f"No se pudo guardar {ruta}: {e.strerror or e}", W.ERROR)
            return False
        self.v.estado(f"Informe guardado ({paginas} páginas): {ruta}", W.OK)
        if abrir:
            QDesktopServices.openUrl(QUrl.fromLocalFile(ruta))
        return True

    def _resumen(self):
        if len(self.resultados) < 2:
            return
        arr = np.array(self.resultados)
        f, g, fase = arr[:, 0], arr[:, 1], arr[:, 2]
        self.modelo = self.analisis = None
        if len(f) >= 6:
            h = 10 ** (g / 20) * np.exp(1j * np.radians(fase))
            try:
                self.modelo = M.mejor_modelo_bode(f, h)
            except (np.linalg.LinAlgError, ValueError):
                self.modelo = None
            if self.modelo is not None:
                self.analisis = M.analizar_modelo_bode(self.modelo, f)
        if self.analisis is None:
            self._resumen_simple(f, g)
            return
        a = self.analisis
        lineas = [f"<b>{a['tipo']}</b>"]
        if a["f3db"]:
            ref = "del pico" if "Pasabanda" in a["tipo"] else "de la meseta"
            lineas.append(f"Frecuencia de corte (−3 dB {ref}): "
                          + ", ".join(f"<b>{M.si(x, 'Hz', 4)}</b>" for x in a["f3db"]))
        lineas += a["detalles"]
        orden = {(0, 1): "1 polo", (1, 1): "1 polo y 1 cero", (0, 2): "2 polos",
                 (1, 2): "2 polos y 1 cero", (2, 2): "2 polos y 2 ceros"}.get(a["orden"], "")
        usados = int(self.modelo.usados.sum())
        lineas.append(f"<span style='color:{W.TENUE}'>Modelo de {orden}: error "
                      f"{a['error_db']:.2f} dB / {a['error_fase']:.1f}° en {usados} de {len(f)} puntos"
                      .replace(".", ",") + "</span>")
        self.lbl_res.setText("<br>".join(lineas))
        if a["ref_db"] is not None:
            self.ref_3db.setPos(a["ref_db"] - 3)
            self.ref_3db.setVisible(True)
        else:
            self.ref_3db.setVisible(False)
        self._mostrar_modelo()

    def _resumen_simple(self, f, g):
        """Sin modelo (pocos puntos): máximo y cruces de −3 dB respecto del máximo."""
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
        self.lbl_res.setText("<br>".join(txt))

    def _curva_modelo(self, f: np.ndarray):
        """Ganancia (dB) y fase (°) del modelo, con la fase llevada a la rama de la medida."""
        hm = self.modelo.h(f)
        g = 20 * np.log10(np.maximum(np.abs(hm), 1e-15))
        fase = np.degrees(np.unwrap(np.angle(hm)))
        if self.resultados:
            f0, fase0 = self.resultados[0][0], self.resultados[0][2]
            d = fase0 - np.degrees(np.angle(self.modelo.h([f0])[0]))
            fase = fase + 360 * round(d / 360)
        return g, fase

    def _mostrar_modelo(self, *_):
        ver = self.chk_modelo.isChecked() and self.modelo is not None and bool(self.resultados)
        if not ver:
            self.c_mag_mod.setData([], [])
            self.c_fase_mod.setData([], [])
        else:
            arr = np.array(self.resultados)
            fg = np.logspace(math.log10(arr[:, 0].min()), math.log10(arr[:, 0].max()), 600)
            g, fase = self._curva_modelo(fg)
            self.c_mag_mod.setData(fg, g)
            self.c_fase_mod.setData(fg, fase)
        self.v.guardar_config_pronto()

    def _exportar(self):
        if not self.resultados:
            return
        ruta, _ = QFileDialog.getSaveFileName(self, "Exportar Bode", "bode.csv", "CSV (*.csv)")
        if not ruta:
            return
        try:
            with open(ruta, "w", newline="", encoding="utf-8") as fh:
                w = csv.writer(fh, delimiter=";")
                cab = ["frecuencia_Hz", "ganancia_dB", "fase_grados", "vpp_entrada_V", "vpp_salida_V"]
                if self.modelo is not None:
                    cab += ["modelo_ganancia_dB", "modelo_fase_grados"]
                    gm, fm = self._curva_modelo(np.array([r[0] for r in self.resultados]))
                w.writerow(cab)
                for i, r in enumerate(self.resultados):
                    fila = list(r)
                    if self.modelo is not None:
                        fila += [gm[i], fm[i]]
                    w.writerow([M.num_csv(x) for x in fila])
        except OSError as e:
            self.v.estado(f"No se pudo guardar {ruta}: {e.strerror or e}", W.ERROR)
            return
        self.v.estado(f"Guardado: {ruta}", W.OK)
