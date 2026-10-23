"""Pestaña Osciloscopio."""
from __future__ import annotations
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPixmap

import csv
import math
import time

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QDialog, QCheckBox, QFileDialog, QGridLayout, QHBoxLayout, QLabel,
                               QScrollArea, QSlider, QVBoxLayout, QWidget)

import modelo as M
import widgets as W

DIV_X, DIV_Y = 10, 8
PUNTOS_DIV = 200
TDIVS = [2e-6, 5e-6, 10e-6, 20e-6, 50e-6, 100e-6, 200e-6, 500e-6, 1e-3, 2e-3, 5e-3, 10e-3,
         20e-3, 50e-3, 100e-3, 200e-3, 500e-3, 1.0]
VDIVS = [1e-3, 2e-3, 5e-3, 10e-3, 20e-3, 50e-3, 0.1, 0.2, 0.5, 1.0, 2.0, 5.0, 10.0, 20.0]
COLORES = {1: W.CH1, 2: W.CH2}
# Hasta esta base de tiempo se capturan 3 pantallas (una extra a cada lado) para poder desplazar.
# Más lento, el cuadro tardaría demasiado en llegar (la placa además busca el disparo en 2
# capturas más, así que una captura de 3 pantallas cuesta 9 pantallas de tiempo).
TDIV_DESPLAZ_MAX = 2e-3
FCNT_MS_EQ = 100        # compuerta del frecuencímetro al medir la señal en tiempo equivalente
FREC_MIN_EQ = 400.0     # por debajo, 8192 muestras no alcanzan a tener 2 períodos


def curva_rapida(plot, color, ancho=1.0):
    """Curva optimizada para refrescar muchas veces por segundo: sin antialiasing (el
    antialiasing con trazo grueso era lo que trababa la app: 40-100 ms por cuadro),
    sin chequeo de NaN y dibujando solo lo visible, con diezmado por picos."""
    c = plot.plot(pen=pg.mkPen(color, width=ancho), antialias=False, skipFiniteCheck=True)
    c.setClipToView(True)
    c.setDownsampling(auto=True, method="peak")
    return c



class DialogoExportarImagen(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Opciones de exportación de imagen")
        self.resize(380, 300)
        
        layout = QVBoxLayout(self)
        
        g_ch, lay_ch = W.grupo("Canales a incluir")
        self.chk_ch1 = QCheckBox("Canal 1 (CH1)")
        self.chk_ch1.setChecked(True)
        self.chk_ch2 = QCheckBox("Canal 2 (CH2)")
        self.chk_ch2.setChecked(True)
        lay_ch.addWidget(self.chk_ch1)
        lay_ch.addWidget(self.chk_ch2)
        layout.addWidget(g_ch)
        
        g_med, lay_med = W.grupo("Mediciones a incluir")
        self.mediciones_opts = [
            ("frec", "Frecuencia", True),
            ("periodo", "Período", True),
            ("vpp", "Vpp", True),
            ("vmax", "V máx", False),
            ("vmin", "V mín", False),
            ("media", "V media", True),
            ("rms", "V rms", True),
            ("ciclo", "Ciclo útil", True),
        ]
        self.chks_med = {}
        grid = QGridLayout()
        for idx, (clave, nombre, defecto) in enumerate(self.mediciones_opts):
            chk = QCheckBox(nombre)
            chk.setChecked(defecto)
            self.chks_med[clave] = chk
            grid.addWidget(chk, idx // 2, idx % 2)
        lay_med.addLayout(grid)
        layout.addWidget(g_med)
        
        btns = QHBoxLayout()
        btn_ok = W.boton("Guardar imagen", self.accept, primario=True)
        btn_cancel = W.boton("Cancelar", self.reject)
        btns.addStretch(1)
        btns.addWidget(btn_cancel)
        btns.addWidget(btn_ok)
        layout.addLayout(btns)

    def opciones_seleccionadas(self):
        canales = []
        if self.chk_ch1.isChecked(): canales.append(1)
        if self.chk_ch2.isChecked(): canales.append(2)
        meds = [clave for clave, chk in self.chks_med.items() if chk.isChecked()]
        return canales, meds

class PanelCanal(QWidget):
    def __init__(self, canal: int, cfg: dict, al_cambiar):
        super().__init__()
        self.canal = canal
        g, lay = W.grupo(f"Canal {canal}")
        g.setStyleSheet(f"QGroupBox::title {{ color: {COLORES[canal]}; }}")
        raiz = QVBoxLayout(self)
        raiz.setContentsMargins(0, 0, 0, 0)
        raiz.addWidget(g)
        self.visible = QCheckBox("Mostrar")
        self.visible.setChecked(cfg.get("visible", True))
        self.vdiv = W.combo([M.si(v, "V") + "/div" for v in VDIVS])
        self.vdiv.setCurrentIndex(cfg.get("vdiv", VDIVS.index(1.0)))
        self.pos = W.EntradaSI("div", -4, 4, cfg.get("pos", 0.0), 3, 80)
        self.entrada = W.combo([m.nombre for m in M.MODOS_ENTRADA.values()])
        self.entrada.setCurrentText(M.MODOS_ENTRADA[cfg.get("entrada", "ALTO")].nombre)
        self.punta = W.combo(["×1", "×10"], cfg.get("punta", "×1"))
        self.acople = W.combo(["DC", "AC"], cfg.get("acople", "DC"))
        lay.addWidget(W.fila("Visible", self.visible))
        lay.addWidget(W.fila("Escala", self.vdiv))
        lay.addWidget(W.fila("Posición", self.pos, ayuda="Desplazamiento vertical en divisiones"))
        lay.addWidget(W.fila("Entrada", self.entrada,
                             ayuda="Tiene que coincidir con la llave de rango de la placa"))
        lay.addWidget(W.fila("Punta", self.punta))
        lay.addWidget(W.fila("Acople", self.acople, ayuda="AC: se resta el valor medio (en software)"))
        for w in (self.visible,):
            w.toggled.connect(al_cambiar)
        for c in (self.vdiv, self.entrada, self.punta, self.acople):
            c.currentIndexChanged.connect(al_cambiar)
        self.pos.cambiado.connect(al_cambiar)

    @property
    def clave_entrada(self) -> str:
        return next(k for k, m in M.MODOS_ENTRADA.items() if m.nombre == self.entrada.currentText())

    @property
    def factor(self) -> float:
        return 10.0 if self.punta.currentText() == "×10" else 1.0

    @property
    def v_div(self) -> float:
        return VDIVS[self.vdiv.currentIndex()]

    def estado(self) -> dict:
        return {"visible": self.visible.isChecked(), "vdiv": self.vdiv.currentIndex(),
                "pos": self.pos.valor(), "entrada": self.clave_entrada,
                "punta": self.punta.currentText(), "acople": self.acople.currentText()}


class TabOsciloscopio(QWidget):
    def __init__(self, ventana):
        super().__init__()
        self.v = ventana
        cfg = ventana.config.osc
        self.corriendo = False
        self.unico = False
        self.esperando = False
        self.t_pedido = 0.0
        self.timeout = 2.0
        self.ultimo = None          # último cuadro (dict) en volts
        self.autoset_estado = None
        self._fps_t = time.monotonic()
        self._fps_n = 0
        self.fps = 0.0
        # tiempo equivalente
        self.ets = None             # perfiles plegados y frecuencia del último cuadro bueno
        self.ets_estado = None      # None | "freq" (esperando al frecuencímetro) | "cap" (esperando la captura)
        self.ets_f0 = None          # frecuencia de la señal (Hz); None = hay que medirla
        self.ets_afinada = False    # f0 ya viene de afinar un cuadro (búsqueda más angosta)
        self.ets_fallos = 0
        self.ets_arr = None
        self.ets_tclk = M.TCLK_TIMER

        raiz = QHBoxLayout(self)
        raiz.setContentsMargins(8, 8, 8, 8)

        # ------------------------------------------------ gráfico
        izq = QVBoxLayout()
        raiz.addLayout(izq, 1)
        self.plot = pg.PlotWidget(background=W.FONDO)
        self.plot.setMenuEnabled(False)
        self.plot.setMouseEnabled(False, False)
        self.plot.hideButtons()
        self.plot.setRange(xRange=(0, DIV_X), yRange=(-DIV_Y / 2, DIV_Y / 2), padding=0)
        for eje in ("left", "bottom"):
            self.plot.getAxis(eje).setStyle(showValues=False)
            self.plot.getAxis(eje).setPen(pg.mkPen(W.BORDE))
            self.plot.getAxis(eje).setTicks([[(i, "") for i in range(-10, 11)]])
        self.plot.showGrid(x=True, y=True, alpha=0.25)
        for x in range(DIV_X + 1):
            self.plot.addItem(pg.InfiniteLine(pos=x, angle=90, pen=pg.mkPen(W.REJILLA)))
        for y in range(-DIV_Y // 2, DIV_Y // 2 + 1):
            self.plot.addItem(pg.InfiniteLine(pos=y, angle=0, pen=pg.mkPen(W.REJILLA)))
        self.plot.addItem(pg.InfiniteLine(pos=DIV_X / 2, angle=90, pen=pg.mkPen("#3b4654", width=1)))
        self.plot.addItem(pg.InfiniteLine(pos=0, angle=0, pen=pg.mkPen("#3b4654", width=1)))
        self.curvas = {c: curva_rapida(self.plot, COLORES[c]) for c in (1, 2)}
        self.curva_xy = self.plot.plot(pen=pg.mkPen("#a5d6ff", width=1), antialias=False,
                                       skipFiniteCheck=True)

        self.linea_nivel = pg.InfiniteLine(angle=0, movable=True, pen=pg.mkPen(W.ALERTA, width=1,
                                                                               style=Qt.DashLine))
        self.linea_nivel.sigPositionChangeFinished.connect(self._nivel_arrastrado)
        self.plot.addItem(self.linea_nivel)
        # Referencias: 0 s = instante del disparo; 0 V = nivel cero de cada canal
        self.marca_disparo = pg.InfiniteLine(angle=90, pen=pg.mkPen(QColor(230, 237, 243, 235), width=1.8))
        self.plot.addItem(self.marca_disparo)
        self.txt_cero_t = pg.TextItem("0 s", color=W.TEXTO, anchor=(0, 0))
        self.plot.addItem(self.txt_cero_t)
        self.cero_v, self.txt_cero_v = {}, {}
        for c in (1, 2):
            col = QColor(COLORES[c])
            col.setAlpha(225)
            self.cero_v[c] = pg.InfiniteLine(angle=0, pen=pg.mkPen(col, width=1.7))
            self.txt_cero_v[c] = pg.TextItem(f"CH{c} 0 V", color=COLORES[c], anchor=(0, 1))
            self.plot.addItem(self.cero_v[c])
            self.plot.addItem(self.txt_cero_v[c])

        # cursores
        pc = pg.mkPen("#d2a8ff", width=1, style=Qt.DashLine)
        self.cur_t = [pg.InfiniteLine(pos=p, angle=90, movable=True, pen=pc) for p in (3, 7)]
        self.cur_v = [pg.InfiniteLine(pos=p, angle=0, movable=True, pen=pc) for p in (-1, 1)]
        for c in self.cur_t + self.cur_v:
            c.sigPositionChanged.connect(self._actualizar_cursores)
            c.setVisible(False)
            self.plot.addItem(c)

        self.txt_estado = pg.TextItem(anchor=(0, 0), color=W.TEXTO)
        self.txt_escalas = pg.TextItem(anchor=(0, 1), color=W.TENUE)
        self.plot.addItem(self.txt_estado)
        self.plot.addItem(self.txt_escalas)
        self.txt_estado.setPos(0.05, DIV_Y / 2 - 0.05)
        self.txt_escalas.setPos(0.05, -DIV_Y / 2 + 0.05)
        izq.addWidget(self.plot, 3)

        self.plot_fft = pg.PlotWidget(background=W.FONDO, axisItems={"bottom": W.EjeLogFrecuencia("bottom")})
        self.plot_fft.setLabel("bottom", "Frecuencia")
        self.plot_fft.setLabel("left", "dBV")
        self.plot_fft.showGrid(x=True, y=True, alpha=0.3)
        self.plot_fft.setYRange(-100, 20)
        self.plot_fft.setLogMode(x=True, y=False)
        self.curvas_fft = {c: curva_rapida(self.plot_fft, COLORES[c]) for c in (1, 2)}
        self.plot_fft.setVisible(False)
        izq.addWidget(self.plot_fft, 2)

        # mediciones
        self.tabla = QGridLayout()
        self.tabla.setHorizontalSpacing(18)
        cols = ["", "Frecuencia", "Período", "Vpp", "V máx", "V mín", "V media", "V rms", "Ciclo útil"]
        for j, t in enumerate(cols):
            l = W.etiqueta_tenue(t)
            self.tabla.addWidget(l, 0, j)
        self.celdas = {}
        for i, c in enumerate((1, 2), start=1):
            l = QLabel(f"CH{c}")
            l.setStyleSheet(f"color:{COLORES[c]}; font-weight:700;")
            self.tabla.addWidget(l, i, 0)
            for j, k in enumerate(["frec", "periodo", "vpp", "vmax", "vmin", "media", "rms", "ciclo"], 1):
                x = QLabel("—")
                x.setFont(W.MONO)
                self.tabla.addWidget(x, i, j)
                self.celdas[(c, k)] = x
        self.lbl_cursores = W.etiqueta_tenue("")
        cont = QWidget()
        cv = QVBoxLayout(cont)
        cv.setContentsMargins(4, 4, 4, 4)
        cv.addLayout(self.tabla)
        cv.addWidget(self.lbl_cursores)
        izq.addWidget(cont)

        # ------------------------------------------------ controles
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFixedWidth(340)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        panel = QWidget()
        pl = QVBoxLayout(panel)
        pl.setContentsMargins(0, 0, 6, 0)
        scroll.setWidget(panel)
        raiz.addWidget(scroll)

        filab = QHBoxLayout()
        self.btn_run = W.boton("RUN", self._alternar_run)
        self.btn_run.setObjectName("run")
        self.btn_run.setProperty("corriendo", "false")
        self.btn_run.setMinimumHeight(38)
        self.btn_unico = W.boton("Único", self._unico)
        self.btn_auto = W.boton("Autoset", self._autoset)
        for b in (self.btn_run, self.btn_unico, self.btn_auto):
            filab.addWidget(b)
        pl.addLayout(filab)

        g, lay = W.grupo("Suavizado")
        self.suavizado = W.combo(["Desactivado", "x4", "x8", "x16", "x32"])
        self.suavizado.setCurrentIndex(cfg.get("suavizado", 0))
        self.suavizado.currentIndexChanged.connect(self._cambio)
        lay.addWidget(W.fila("Promedio (Average)", self.suavizado))
        pl.addWidget(g)

        g, lay = W.grupo("Horizontal")
        self.tdiv = W.combo([M.si(t, "s") + "/div" for t in TDIVS])
        self.tdiv.setCurrentIndex(cfg.get("tdiv", TDIVS.index(1e-3)))
        self.tdiv.currentIndexChanged.connect(self._cambio)
        self.pos_disp = QSlider(Qt.Horizontal)
        self.pos_disp.setRange(0, 100)
        self.pos_disp.setValue(cfg.get("pos_disp", 50))
        self.pos_disp.valueChanged.connect(self._cambio)
        self.desplaz = QSlider(Qt.Horizontal)
        self.desplaz.setRange(-100, 100)          # décimas de división: ±10 div
        self.desplaz.setValue(int(cfg.get("desplaz", 0)))
        self.desplaz.valueChanged.connect(self._cambio)
        self.adquisicion = W.combo(["Tiempo real", "Tiempo equivalente"])
        self.adquisicion.setCurrentIndex(int(cfg.get("adquisicion", 0)))
        self.adquisicion.currentIndexChanged.connect(self._cambio_adquisicion)
        self.lbl_eq = W.etiqueta_tenue("Para señales repetitivas y estables: conectá la misma señal al canal y a "
                                       "PA0 (frecuencímetro). El ancho de banda lo limita el frontal analógico.")
        self.lbl_eq.setWordWrap(True)
        self.lbl_eq.setVisible(self.modo_eq)
        lay.addWidget(W.fila("Adquisición", self.adquisicion,
                             ayuda="Tiempo real: cualquier señal, con disparo y eventos únicos. Tiempo equivalente: "
                                   "reconstruye un período de una señal repetitiva a partir de una captura larga."))
        lay.addWidget(self.lbl_eq)
        lay.addWidget(W.fila("Tiempo", self.tdiv))
        lay.addWidget(W.fila("Posición disparo", self.pos_disp))
        lay.addWidget(W.fila("Desplazar", self.desplaz,
                             ayuda=f"Mueve la señal en el tiempo, hasta ±10 div. Disponible hasta "
                                   f"{M.si(TDIV_DESPLAZ_MAX, 's')}/div (captura 3 pantallas)."))
        fila_d = QHBoxLayout()
        self.lbl_desplaz = W.etiqueta_tenue("")
        fila_d.addWidget(self.lbl_desplaz)
        fila_d.addStretch(1)
        fila_d.addWidget(W.boton("Centrar", lambda: self.desplaz.setValue(0)))
        lay.addLayout(fila_d)
        self.lbl_fs = W.etiqueta_tenue("")
        lay.addWidget(self.lbl_fs)
        pl.addWidget(g)

        self.canales = {}
        for c in (1, 2):
            p = PanelCanal(c, cfg.get(f"ch{c}", {}), self._cambio)
            self.canales[c] = p
            pl.addWidget(p)

        g, lay = W.grupo("Disparo (trigger)")
        self.fuente = W.combo(["CH1", "CH2", "Libre"], cfg.get("fuente", "CH1"))
        self.flanco = W.combo(["Subida", "Bajada"], cfg.get("flanco", "Subida"))
        self.modo = W.combo(["Auto", "Normal"], cfg.get("modo", "Auto"))
        self.nivel = W.EntradaSI("V", -200, 200, cfg.get("nivel", 0.0), 4, 100)
        for c in (self.fuente, self.flanco, self.modo):
            c.currentIndexChanged.connect(self._cambio)
        self.nivel.cambiado.connect(self._cambio)
        lay.addWidget(W.fila("Fuente", self.fuente))
        lay.addWidget(W.fila("Flanco", self.flanco))
        lay.addWidget(W.fila("Modo", self.modo,
                             ayuda="Auto: muestra aunque no haya disparo. Normal: solo cuadros disparados."))
        lay.addWidget(W.fila("Nivel", self.nivel, ayuda="También se puede arrastrar la línea naranja"))
        pl.addWidget(g)

        g, lay = W.grupo("Pantalla")
        self.modo_xy = QCheckBox("Modo XY (CH1 horizontal, CH2 vertical)")
        self.chk_fft = QCheckBox("Espectro (FFT)")
        self.chk_cur = QCheckBox("Cursores")
        for c in (self.modo_xy, self.chk_fft, self.chk_cur):
            c.toggled.connect(self._cambio_pantalla)
            lay.addWidget(c)
        fila = QHBoxLayout()
        fila.addWidget(W.boton("Exportar CSV", self._exportar_csv))
        fila.addWidget(W.boton("Guardar imagen", self._exportar_png))
        lay.addLayout(fila)
        pl.addWidget(g)
        pl.addStretch(1)

        self.vigia = QTimer(self)
        self.vigia.timeout.connect(self._vigilar)
        self.vigia.start(200)
        self._cambio()

    # ------------------------------------------------------------ config
    def estado_config(self) -> dict:
        return {"tdiv": self.tdiv.currentIndex(), "pos_disp": self.pos_disp.value(),
                "fuente": self.fuente.currentText(), "flanco": self.flanco.currentText(),
                "modo": self.modo.currentText(), "nivel": self.nivel.valor(),
                "suavizado": self.suavizado.currentIndex(), "desplaz": self.desplaz.value(),
                "adquisicion": self.adquisicion.currentIndex(),
                "ch1": self.canales[1].estado(), "ch2": self.canales[2].estado()}

    @property
    def t_div(self) -> float:
        return TDIVS[self.tdiv.currentIndex()]

    @property
    def modo_eq(self) -> bool:
        return self.adquisicion.currentIndex() == 1

    def recta(self, c: int) -> M.Recta:
        return self.v.config.recta_entrada(c, self.canales[c].clave_entrada)

    # ------------------------------------------------------------ eje horizontal
    @property
    def desplazamiento(self) -> float:
        """Desplazamiento horizontal en divisiones. Solo existe con las bases de tiempo
        que capturan pantallas extra; con las lentas se ignora."""
        if self.modo_eq or self.t_div <= TDIV_DESPLAZ_MAX:
            return self.desplaz.value() / 10.0
        return 0.0

    def _x0(self) -> float:
        """Posición en pantalla (en divisiones) del instante 0 s, el del disparo."""
        return DIV_X * self.pos_disp.value() / 100 - self.desplazamiento

    def _indices_visibles(self, u: dict) -> tuple[int, int]:
        """Rango [i0, i1) de las muestras del cuadro que caen dentro de la pantalla."""
        n, pre = u["n"], u["pre"]
        por_div = u["fs"] * self.t_div
        x0 = self._x0()
        i0 = int(np.clip(np.rint(pre - x0 * por_div), 0, n))
        i1 = int(np.clip(np.rint(pre + (DIV_X - x0) * por_div), 0, n))
        return i0, max(i0, i1)

    def _actualizar_ceros(self):
        """Marca 0 s (instante del disparo) y el 0 V de cada canal."""
        xy = self.modo_xy.isChecked()
        x0 = self._x0()
        self.marca_disparo.setPos(x0)
        self.marca_disparo.setVisible(not xy)
        self.txt_cero_t.setVisible(not xy and 0 <= x0 <= DIV_X)
        self.txt_cero_t.setPos(x0 + 0.08, DIV_Y / 2 - 0.1)
        for c in (1, 2):
            p = self.canales[c]
            y = p.pos.valor()
            visible = p.visible.isChecked() and not xy
            self.cero_v[c].setVisible(visible)
            self.cero_v[c].setPos(y)
            self.txt_cero_v[c].setVisible(visible and -DIV_Y / 2 <= y <= DIV_Y / 2)
            self.txt_cero_v[c].setPos(0.05 + (c - 1) * 1.3, y)

    # ------------------------------------------------------------ adquisición
    def parametros_captura(self):
        fsmax = self.v.disp.info.get("osc_fsmax", 1.6e6) if self.v.disp.esta_conectado else 1.6e6
        tdiv = self.t_div
        fs = min(PUNTOS_DIV / tdiv, fsmax)
        n = int(round(fs * DIV_X * tdiv))
        n = max(16, min(8192, n))
        pre = int(round(n * self.pos_disp.value() / 100))
        if tdiv <= TDIV_DESPLAZ_MAX:        # una pantalla extra a cada lado, para poder desplazar
            extra = min(n, (8192 - n) // 2)
            n += 2 * extra
            pre += extra
        fuente = {"CH1": 1, "CH2": 2, "Libre": 0}[self.fuente.currentText()]
        # Base de tiempo lenta en modo automático: sin buscar disparo (si no,
        # habría que esperar 3 pantallas)
        if fuente and self.modo.currentText() == "Auto" and not self.unico and tdiv >= 50e-3:
            fuente = 0
        nivel_cod = 2048
        if fuente:
            c = self.canales[fuente]
            nivel_cod = int(np.clip(np.rint(self.recta(fuente).codigo(self.nivel.valor() / c.factor)), 0, 4095))
        flanco = 0 if self.flanco.currentText() == "Subida" else 1
        return n, pre, fs, fuente, nivel_cod, flanco

    def pedir(self):
        if not self.v.disp.esta_conectado:
            return
        if self.modo_eq:
            self._pedir_eq()
            return
        n, pre, fs, fuente, nivel, flanco = self.parametros_captura()
        self.v.pedir_captura("osc", n, pre, fs, fuente, nivel, flanco, 20)
        self.esperando = True
        self.t_pedido = time.monotonic()
        total = n * (3 if fuente else 1)
        self.timeout = total / fs + 1.5

    # ------------------------------------------------------------ tiempo equivalente
    def _reiniciar_eq(self):
        self.ets, self.ets_estado, self.ets_f0 = None, None, None
        self.ets_afinada, self.ets_fallos = False, 0

    def _pedir_eq(self):
        """Paso 1: la frecuencia de la señal, con el frecuencímetro (PA0). Paso 2: una captura larga,
        sin disparo, con el ARR del timer que mejor reparte las fases."""
        self.esperando = True
        self.t_pedido = time.monotonic()
        if self.ets_f0 is None:
            self.ets_estado = "freq"
            self.v.disp.enviar(f"FCNT {FCNT_MS_EQ} 0")
            self.timeout = FCNT_MS_EQ / 1000 + 2.0
            self.v.estado("Tiempo equivalente: midiendo la frecuencia en PA0…", W.TEXTO)
            return
        fsmax = self.v.disp.info.get("osc_fsmax", 1.6e6)
        self.ets_arr, _ = M.elegir_arr(self.ets_f0, fsmax, 8192, M.BINS_EQ, self.ets_tclk)
        fs = M.fs_para_arr(self.ets_arr, self.ets_tclk)
        self.ets_estado = "cap"
        self.v.pedir_captura("osc", 8192, 0, fs, 0, 2048, 0, 20)
        self.timeout = 8192 / fs + 1.5

    def al_linea(self, linea: str):
        """Respuesta del frecuencímetro ('FREQ f método flancos ms') cuando se está midiendo la señal."""
        if self.ets_estado != "freq" or not linea.startswith("FREQ "):
            return
        try:
            f = float(linea.split()[1])
        except (IndexError, ValueError):
            return
        self.ets_estado = None
        if f < FREC_MIN_EQ:
            self.v.estado("Tiempo equivalente: no hay señal en PA0 (conectá la misma señal al frecuencímetro) "
                          f"o es de menos de {FREC_MIN_EQ:.0f} Hz.", W.ALERTA)
            self.esperando, self.t_pedido, self.timeout = True, time.monotonic(), 1.0    # el vigía reintenta
            return
        self.ets_f0, self.ets_afinada = f, False
        if self.corriendo:
            self._pedir_eq()
        else:
            self.esperando = False

    def _procesar_eq(self, d: dict) -> bool:
        """Pliega una captura larga y arma el cuadro. Devuelve False si la señal no sirve para este modo."""
        u = self._a_volts(d, suavizar=False)            # promediar antes de plegar arruinaría el pliegue
        fs = u["fs"]
        if self.ets_arr:
            self.ets_tclk = fs * self.ets_arr           # reloj real del timer (PSC = 1)
        visibles = [c for c in (1, 2) if self.canales[c].visible.isChecked()] or [1]
        ref = {"CH1": 1, "CH2": 2}.get(self.fuente.currentText(), visibles[0])
        if ref not in visibles:
            ref = visibles[0]
        rango, puntos = (3e-5, 41) if self.ets_afinada else (3e-4, 121)
        res = M.plegar_captura({1: u[1], 2: u[2]}, fs, self.ets_f0, ref, M.BINS_EQ, rango, puntos)

        def umbral(c):
            lsb = abs(self.recta(c).pendiente) * self.canales[c].factor
            return M.umbral_repetitivo(lsb, float(np.ptp(u[c])))

        fuera = res["desvio"] > 0.9 * rango             # el máximo quedó en el borde: f0 estaba lejos
        if fuera or res["residuo"][ref] > umbral(ref):
            self.ets_fallos += 1
            self.ets_afinada = False
            if fuera or self.ets_fallos >= 2:
                self.ets_f0 = None                      # volver a medir con el frecuencímetro
            self.v.estado("Tiempo equivalente: la señal no es repetitiva o es inestable (probá en Tiempo real).",
                          W.ALERTA)
            return False
        self.ets_fallos = 0
        self.ets_f0, self.ets_afinada = res["f"], True
        perfiles, avisos = dict(res["perfiles"]), []
        for c in visibles:
            if c != ref and res["residuo"][c] > umbral(c):
                perfiles[c] = np.full(M.BINS_EQ, float(u[c].mean()))
                avisos.append(f"CH{c} no repite a la frecuencia de CH{ref}")
        self.ets = {"f": res["f"], "perfiles": perfiles}
        if avisos:
            self.v.estado("Tiempo equivalente: " + "; ".join(avisos) + ".", W.ALERTA)
        return self._cuadro_eq()

    def _cuadro_eq(self) -> bool:
        """Arma el cuadro que se dibuja a partir del perfil plegado y la escala de tiempo actual."""
        if not self.ets:
            return False
        try:
            cuadro = M.teselar_perfiles(self.ets["perfiles"], self.ets["f"], self.t_div, DIV_X,
                                        self.pos_disp.value())
        except ValueError as e:
            self.ultimo = None
            for c in (1, 2):
                self.curvas[c].setData([], [])
            self.v.estado(f"Tiempo equivalente: {e}.", W.ALERTA)
            return False
        cuadro.update({"disparado": 1, "ets": True})
        self.ultimo = cuadro
        return True

    def _cambio_adquisicion(self, *_):
        self._reiniciar_eq()
        self.ultimo = None
        for c in (1, 2):
            self.curvas[c].setData([], [])
        self.lbl_eq.setVisible(self.modo_eq)
        self.esperando = False
        self._cambio()
        if self.corriendo and self.v.disp.esta_conectado:
            self.pedir()

    def _vigilar(self):
        if self.v.dueno_captura != "osc" and self.v.dueno_captura is not None:
            return
        if self.esperando and time.monotonic() - self.t_pedido > self.timeout:
            self.esperando = False
            if self.corriendo or self.autoset_estado:
                self.pedir()

    def al_conectar(self):
        self.esperando = False
        if not self.corriendo:
            self._alternar_run()

    def al_desconectar(self):
        self.esperando = False
        self._reiniciar_eq()
        self._set_run(False)

    def al_recibir(self, d: dict):
        self.esperando = False
        if self.autoset_estado:
            self._autoset_paso(d)
            return
        if not self.corriendo:
            return
        if self.ets_estado == "cap":
            self.ets_estado = None
            if not self._procesar_eq(d):
                self.pedir()                # RUN o Único: sigue intentando
                return
            self._refrescar()
        else:
            if self.modo.currentText() == "Normal" and d["disparado"] == 0:
                self.pedir()
                return
            if self.unico and d["disparado"] == 0:
                self.pedir()
                return
            self._mostrar(d)
        if self.unico:
            self.unico = False
            self._set_run(False)
        else:
            self.pedir()

    def _a_volts(self, d: dict, suavizar: bool = True) -> dict:
        r = {"fs": d["fs"], "pre": d["pre"], "n": d["n"], "disparado": d["disparado"]}
        
        # Tamaño de la ventana de suavizado ("Desactivado"=0, "x4"=1, "x8"=2...)
        ventana = [1, 4, 8, 16, 32][self.suavizado.currentIndex()] if suavizar else 1
        
        for c in (1, 2):
            v = self.recta(c).volt(d[f"ch{c}"]) * self.canales[c].factor
            
            # Aplicar filtro de Promedio Móvil si está activado
            v = M.suavizar(v, ventana)
            
            if self.canales[c].acople.currentText() == "AC":
                v = v - v.mean()
            r[c] = v
        return r
    def _mostrar(self, d: dict):
        self.ultimo = self._a_volts(d)
        self._refrescar()

    def _refrescar(self):
        self._dibujar()
        self._fps_n += 1
        ahora = time.monotonic()
        if ahora - self._fps_t > 1.0:
            self.fps = self._fps_n / (ahora - self._fps_t)
            self._fps_n, self._fps_t = 0, ahora

    def _dibujar(self):
        self._actualizar_ceros()
        u = self.ultimo
        if not u:
            return
        fs, pre = u["fs"], u["pre"]
        tdiv = self.t_div
        i0, i1 = self._indices_visibles(u)      # solo lo que cae dentro de la pantalla
        x = self._x0() + (np.arange(i0, i1) - pre) / fs / tdiv
        xy = self.modo_xy.isChecked()
        for c in (1, 2):
            p = self.canales[c]
            visible = p.visible.isChecked() and not xy
            self.curvas[c].setVisible(visible)
            if visible:
                y = np.clip(u[c][i0:i1] / p.v_div + p.pos.valor(), -DIV_Y, DIV_Y)
                self.curvas[c].setData(x, y)
        self.curva_xy.setVisible(xy)
        self.marca_disparo.setVisible(not xy)
        self.linea_nivel.setVisible(not xy and self.fuente.currentText() != "Libre")
        if xy:
            p1, p2 = self.canales[1], self.canales[2]
            self.curva_xy.setData(np.clip(u[1][i0:i1] / p1.v_div + p1.pos.valor() + DIV_X / 2, -1, DIV_X + 1),
                                  np.clip(u[2][i0:i1] / p2.v_div + p2.pos.valor(), -DIV_Y, DIV_Y))
        # mediciones
        for c in (1, 2):
            m = M.medir(u[c][i0:i1], fs) if self.canales[c].visible.isChecked() else {}
            for k in ("frec", "periodo", "vpp", "vmax", "vmin", "media", "rms", "ciclo"):
                val = m.get(k)
                unidad = {"frec": "Hz", "periodo": "s", "ciclo": "%"}.get(k, "V")
                txt = "—" if val is None else (f"{val:.1f} %".replace(".", ",") if k == "ciclo"
                                               else M.si(val, unidad, 4))
                self.celdas[(c, k)].setText(txt)
        # FFT
        if self.chk_fft.isChecked():
            for c in (1, 2):
                vis = self.canales[c].visible.isChecked()
                self.curvas_fft[c].setVisible(vis)
                if vis and i1 - i0 >= 32:
                    f, db = M.espectro(u[c][i0:i1], fs)
                    self.curvas_fft[c].setData(f[1:], db[1:])
        estado = {2: "Libre", 1: "Disparado", 0: "Auto (sin disparo)"}.get(u["disparado"], "Desconocido")
        if not self.corriendo:
            estado = "Detenido"
        if u.get("ets"):
            estado = "Equivalente" if self.corriendo else "Equivalente (detenido)"
            self.txt_estado.setText(f"{estado}   f = {M.si(u['f'], 'Hz', 6)}   {M.si(fs, 'S/s', 3)} equiv.   "
                                    f"{self.fps:.0f} cuadros/s")
        else:
            self.txt_estado.setText(f"{estado}   {M.si(fs, 'S/s', 3)}   {self.fps:.0f} cuadros/s")
        self._actualizar_cursores()

    # ------------------------------------------------------------ controles
    def _cambio(self, *_):
        self.marca_disparo.setPos(self._x0())
        fuente = {"CH1": 1, "CH2": 2, "Libre": 0}[self.fuente.currentText()]
        self.linea_nivel.setVisible(fuente != 0)
        if fuente:
            p = self.canales[fuente]
            self.linea_nivel.setPen(pg.mkPen(COLORES[fuente], width=1, style=Qt.DashLine))
            self.linea_nivel.blockSignals(True)
            self.linea_nivel.setPos(self.nivel.valor() / p.v_div + p.pos.valor())
            self.linea_nivel.blockSignals(False)
        if self.modo_eq:
            if self.ets:
                self.lbl_fs.setText(f"Equivalente: {M.si(self.ets['f'] * M.BINS_EQ, 'S/s', 3)} · "
                                    f"f = {M.si(self.ets['f'], 'Hz', 6)}")
            else:
                self.lbl_fs.setText("Equivalente: esperando la captura")
            self._cuadro_eq()
        else:
            n, pre, fs, *_ = self.parametros_captura()
            self.lbl_fs.setText(f"Muestreo: {M.si(fs, 'S/s', 3)} · {n} puntos")
        if self.modo_eq or self.t_div <= TDIV_DESPLAZ_MAX:
            self.lbl_desplaz.setText(f"Desplazamiento: {self.desplaz.value() / 10:+.1f} div".replace(".", ","))
        else:
            self.lbl_desplaz.setText(f"Solo hasta {M.si(TDIV_DESPLAZ_MAX, 's')}/div")
        partes = []
        for c in (1, 2):
            if self.canales[c].visible.isChecked():
                partes.append(f"<span style='color:{COLORES[c]}'>CH{c} {M.si(self.canales[c].v_div, 'V')}/div</span>")
        partes.append(f"{M.si(self.t_div, 's')}/div")
        self.txt_escalas.setHtml("&nbsp;&nbsp;&nbsp;".join(partes))
        self._dibujar()
        self.v.guardar_config_pronto()

    def _nivel_arrastrado(self):
        fuente = {"CH1": 1, "CH2": 2, "Libre": 0}[self.fuente.currentText()]
        if not fuente:
            return
        p = self.canales[fuente]
        self.nivel.set_valor((self.linea_nivel.value() - p.pos.valor()) * p.v_div)
        self._cambio()

    def _cambio_pantalla(self, *_):
        self.plot_fft.setVisible(self.chk_fft.isChecked())
        cur = self.chk_cur.isChecked()
        for c in self.cur_t + self.cur_v:
            c.setVisible(cur)
        self.lbl_cursores.setVisible(cur)
        self._dibujar()

    def _actualizar_cursores(self, *_):
        if not self.chk_cur.isChecked():
            return
        t1, t2 = (c.value() for c in self.cur_t)
        dt = abs(t2 - t1) * self.t_div
        partes = [f"ΔT = {M.si(dt, 's')}", f"1/ΔT = {M.si(1 / dt, 'Hz') if dt > 0 else '—'}"]
        y1, y2 = (c.value() for c in self.cur_v)
        for c in (1, 2):
            if self.canales[c].visible.isChecked():
                partes.append(f"ΔV CH{c} = {M.si(abs(y2 - y1) * self.canales[c].v_div, 'V')}")
        self.lbl_cursores.setText("    ".join(partes))

    def _set_run(self, si: bool):
        self.corriendo = si
        self.btn_run.setText("RUN" if si else "STOP")
        self.btn_run.setProperty("corriendo", "true" if si else "false")
        self.btn_run.style().unpolish(self.btn_run)
        self.btn_run.style().polish(self.btn_run)

    def _alternar_run(self):
        if not self.v.disp.esta_conectado:
            self.v.estado("Conectá la placa primero.", W.ALERTA)
            return
        self.unico = False
        self._set_run(not self.corriendo)
        if self.corriendo and not self.esperando:
            self.pedir()

    def _unico(self):
        if not self.v.disp.esta_conectado:
            return
        self.unico = True
        self._set_run(True)
        self.pedir()

    # ------------------------------------------------------------ autoset
    def _autoset(self):
        if not self.v.disp.esta_conectado:
            return
        self.autoset_estado = {"fs": self.v.disp.info.get("osc_fsmax", 1.6e6)}
        self.v.estado("Autoset: buscando la señal…", W.TEXTO)
        self._autoset_pedir()

    def _autoset_pedir(self):
        fs = self.autoset_estado["fs"]
        self.v.pedir_captura("osc", 8192, 0, fs)
        self.esperando = True
        self.t_pedido = time.monotonic()
        self.timeout = 8192 / fs + 1.5

    def _autoset_paso(self, d):
        u = self._a_volts(d)
        fs = u["fs"]
        fuente = 1 if self.canales[1].visible.isChecked() or not self.canales[2].visible.isChecked() else 2
        m = M.medir(u[fuente], fs)
        if (m.get("frec") is None or m["frec"] * 8192 / fs < 3) and fs > 20e3:
            self.autoset_estado["fs"] = fs / 10
            self._autoset_pedir()
            return
        self.autoset_estado = None
        # base de tiempo: ~2,5 períodos en pantalla
        if m.get("frec"):
            objetivo = 2.5 / m["frec"] / DIV_X
            idx = min(range(len(TDIVS)), key=lambda i: abs(math.log(TDIVS[i] / objetivo)))
        else:
            idx = TDIVS.index(1e-3)
        self.tdiv.setCurrentIndex(idx)
        for c in (1, 2):
            p = self.canales[c]
            mc = M.medir(u[c], fs)
            if not mc:
                continue
            vpp = max(mc["vpp"], 1e-3)
            vdiv_idx = next((i for i, vd in enumerate(VDIVS) if vpp / vd <= 6), len(VDIVS) - 1)
            p.vdiv.setCurrentIndex(vdiv_idx)
            centro = mc["media"] if p.acople.currentText() == "DC" else 0
            p.pos.set_valor(-centro / VDIVS[vdiv_idx])
        self.fuente.setCurrentText(f"CH{fuente}")
        self.modo.setCurrentText("Auto")
        self.flanco.setCurrentText("Subida")
        self.nivel.set_valor(m.get("media", 0.0) if self.canales[fuente].acople.currentText() == "DC" else 0)
        self.pos_disp.setValue(50)
        self.desplaz.setValue(0)
        self._cambio()
        txt = f"Autoset listo: {M.si(m['frec'], 'Hz')}" if m.get("frec") else "Autoset: no se detectó una señal periódica."
        self.v.estado(txt, W.OK if m.get("frec") else W.ALERTA)
        self._set_run(True)
        self.pedir()

    # ------------------------------------------------------------ exportar
    def _avisar_guardado(self, guardado: bool, ruta: str):
        """QPixmap.save() devuelve False si falla: no hay que decir 'Guardado' en ese caso."""
        if guardado:
            self.v.estado(f"Guardado: {ruta}", W.OK)
        else:
            self.v.estado(f"No se pudo guardar {ruta} (¿archivo en uso o carpeta de solo lectura?)", W.ERROR)

    def _exportar_csv(self):
        """Exporta lo que se ve en pantalla: solo los canales visibles y solo el tramo visible."""
        if not self.ultimo:
            return
        canales = [c for c in (1, 2) if self.canales[c].visible.isChecked()]
        if not canales:
            self.v.estado("No hay ningún canal visible para exportar.", W.ALERTA)
            return
        u = self.ultimo
        i0, i1 = self._indices_visibles(u)
        if i1 - i0 < 2:
            self.v.estado("No hay datos dentro de la pantalla para exportar.", W.ALERTA)
            return
        ruta, _ = QFileDialog.getSaveFileName(self, "Exportar captura", "captura.csv", "CSV (*.csv)")
        if not ruta:
            return
        t = (np.arange(i0, i1) - u["pre"]) / u["fs"]
        try:
            with open(ruta, "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f, delimiter=";")
                w.writerow(["tiempo_s"] + [f"ch{c}_V" for c in canales])
                for k in range(i1 - i0):
                    w.writerow([M.num_csv(t[k], ".9g")] + [M.num_csv(u[c][i0 + k]) for c in canales])
        except OSError as e:
            self.v.estado(f"No se pudo guardar {ruta}: {e.strerror or e}", W.ERROR)
            return
        self.v.estado(f"Guardado: {ruta}", W.OK)

    def _exportar_png(self):
        if not self.ultimo:
            return
        
        dlg = DialogoExportarImagen(self)
        if dlg.exec() != QDialog.Accepted:
            return
            
        canales_sel, meds_sel = dlg.opciones_seleccionadas()
        ruta, _ = QFileDialog.getSaveFileName(self, "Guardar imagen", "osciloscopio.png", "PNG (*.png)")
        if not ruta:
            return
            
        pix_plot = self.plot.grab()
        cursores_activos = self.chk_cur.isChecked()
        texto_cursores = self.lbl_cursores.text() if cursores_activos else ""
        
        if (not canales_sel or not meds_sel) and not cursores_activos:
            self._avisar_guardado(pix_plot.save(ruta), ruta)
            return
            
        nombres_med = {
            "frec": "Frecuencia", "periodo": "Período", "vpp": "Vpp",
            "vmax": "V máx", "vmin": "V mín", "media": "V media",
            "rms": "V rms", "ciclo": "Ciclo útil"
        }
        
        ancho = pix_plot.width()
        alto_plot = pix_plot.height()
        
        filas_canales = [c for c in canales_sel if self.canales[c].visible.isChecked()]
        if not filas_canales and canales_sel:
            filas_canales = canales_sel
            
        alto_banner = 15
        if canales_sel and meds_sel:
            alto_banner += 35 + len(filas_canales) * 28
        if cursores_activos:
            alto_banner += 35 if (canales_sel and meds_sel) else 40
            
        alto_total = alto_plot + alto_banner
        
        imagen_final = QPixmap(ancho, alto_total)
        painter = QPainter(imagen_final)
        painter.setRenderHint(QPainter.Antialiasing)
        
        painter.fillRect(0, 0, ancho, alto_total, QColor(W.FONDO))
        painter.drawPixmap(0, 0, pix_plot)
        
        painter.setPen(QPen(QColor(W.BORDE), 2))
        painter.drawLine(0, alto_plot, ancho, alto_plot)
        
        font_header = QFont("Consolas", 10, QFont.Bold)
        font_data = QFont("Consolas", 10)
        
        y_cursor = alto_plot
        margen_x = 20
        
        if canales_sel and meds_sel:
            y_cursor += 25
            cols = ["Canal"] + [nombres_med[k] for k in meds_sel]
            num_cols = len(cols)
            ancho_col = (ancho - 2 * margen_x) / max(1, num_cols)
            
            painter.setFont(font_header)
            painter.setPen(QColor(W.TENUE))
            for col_idx, col_name in enumerate(cols):
                x = margen_x + col_idx * ancho_col
                painter.drawText(int(x), int(y_cursor), col_name)
                
            for c in filas_canales:
                y_cursor += 28
                colores = {1: QColor(W.CH1), 2: QColor(W.CH2)}
                painter.setPen(colores.get(c, QColor(W.TEXTO)))
                
                painter.setFont(font_header)
                painter.drawText(int(margen_x), int(y_cursor), f"CH{c}")
                
                painter.setFont(font_data)
                for col_idx, k in enumerate(meds_sel, start=1):
                    x = margen_x + col_idx * ancho_col
                    txt = self.celdas[(c, k)].text() if (c, k) in self.celdas else "—"
                    painter.drawText(int(x), int(y_cursor), txt)
        
        if cursores_activos:
            y_cursor += 30 if (canales_sel and meds_sel) else 25
            painter.setFont(font_header)
            painter.setPen(QColor("#d2a8ff"))
            painter.drawText(int(margen_x), int(y_cursor), f"Cursores: {texto_cursores}")
                
        painter.end()
        self._avisar_guardado(imagen_final.save(ruta), ruta)
