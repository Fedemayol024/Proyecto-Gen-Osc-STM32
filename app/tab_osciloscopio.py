"""Pestaña Osciloscopio."""
from __future__ import annotations
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPixmap

import csv
import math
import time

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtWidgets import (QAbstractItemView, QDialog, QCheckBox, QDoubleSpinBox, QFileDialog,
                               QGridLayout, QHBoxLayout, QHeaderView, QLabel, QScrollArea, QSlider,
                               QSpinBox, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

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

# ---------------------------------------------------------------------------
# Persistencia tipo fósforo
# ---------------------------------------------------------------------------
PERSISTENCIAS = ["Desactivada", "1 s", "2 s", "3 s", "Infinita"]
TIEMPOS_PERSIST = [0.0, 1.0, 2.0, 3.0, math.inf]


def _lut_canal(color: str) -> np.ndarray:
    """Tabla intensidad → RGBA: lo visitado una sola vez se ve tenue, lo repetido brilla."""
    c = QColor(color)
    base = np.array([c.red(), c.green(), c.blue()], float)
    v = np.arange(256) / 255.0
    lut = np.zeros((256, 4), np.uint8)
    lut[:, :3] = np.clip(base * (0.8 + 0.2 * v[:, None]) + (255 - base) * 0.35 * v[:, None] ** 2, 0, 255)
    lut[:, 3] = np.where(v > 0.004, 105 + 150 * np.sqrt(v), 0)     # lo raro también se ve claro
    lut[lut[:, 3] == 0, :3] = 0
    return lut


class Fosforo:
    """Imagen que acumula los trazos de cada canal y se va apagando con el tiempo elegido,
    como el fósforo de un osciloscopio analógico. Un transitorio que aparece en un solo
    cuadro queda marcado (tenue) durante ese tiempo, o para siempre en «Infinita»."""
    COLS, FILAS = 1000, 640          # 100 × 80 puntos por división
    APAGADO = 3.2                    # e^-3,2 ≈ 4 %: a los T segundos el trazo casi no se ve

    def __init__(self, plot):
        self.img = pg.ImageItem()
        self.img.setZValue(-5)
        plot.addItem(self.img)
        self.buf = {c: np.zeros((self.COLS, self.FILAS), np.float32) for c in (1, 2)}
        self.vivo = {1: False, 2: False}
        self.luts = {c: _lut_canal(COLORES[c]).view(np.uint32).ravel() for c in (1, 2)}
        self.tiempo = 0.0
        self.sucio = False
        self._t = time.monotonic()
        self.timer = QTimer()
        self.timer.timeout.connect(self._tic)

    @property
    def activo(self) -> bool:
        return self.tiempo > 0

    def set_tiempo(self, t: float):
        self.tiempo = t
        self.borrar()
        if t > 0:
            self._t = time.monotonic()
            self.timer.start(80)
        else:
            self.timer.stop()

    def borrar(self, canal: int | None = None):
        for c in ((canal,) if canal else (1, 2)):
            if self.vivo[c]:
                self.buf[c].fill(0)
                self.vivo[c] = False
                self.sucio = True
        if not any(self.vivo.values()):
            self.img.clear()
            self.sucio = False

    def agregar(self, canal: int, x: np.ndarray, y: np.ndarray):
        if not self.activo:
            return
        marca = M.rasterizar_trazo(x, y, self.COLS, self.FILAS, DIV_X, -DIV_Y / 2, DIV_Y / 2)
        b = self.buf[canal]
        b[marca] = np.minimum(1.0, b[marca] + 0.45)
        self.vivo[canal] = True
        self.sucio = True

    def _tic(self):
        ahora = time.monotonic()
        dt, self._t = ahora - self._t, ahora
        if math.isfinite(self.tiempo):
            k = math.exp(-self.APAGADO * dt / self.tiempo)
            for c in (1, 2):
                if self.vivo[c]:
                    b = self.buf[c]
                    b *= k
                    b[b < 1 / 255] = 0
                    if not b.any():
                        self.vivo[c] = False
                    self.sucio = True
        if self.sucio:
            self.dibujar()

    def dibujar(self):
        self.sucio = False
        out = None
        for c in (1, 2):
            if self.vivo[c]:
                col = np.take(self.luts[c], (self.buf[c] * 255).astype(np.uint8))   # RGBA en un uint32
                if out is None:
                    out = col
                else:                       # donde se cruzan, gana el canal más intenso
                    out = np.where((col >> 24) > (out >> 24), col, out)
        if out is None:
            self.img.clear()
        else:
            self.img.setImage(out.view(np.uint8).reshape(self.COLS, self.FILAS, 4), autoLevels=False)
            self.img.setRect(QRectF(0, -DIV_Y / 2, DIV_X, DIV_Y))


# ---------------------------------------------------------------------------
# Análisis del espectro (FFT)
# ---------------------------------------------------------------------------
PROMEDIOS_FFT = [("Desactivado", 1), ("4 cuadros", 4), ("8 cuadros", 8), ("16 cuadros", 16),
                 ("32 cuadros", 32), ("64 cuadros", 64)]
RUIDO_FFT = [("No eliminar", 0.0), ("Eliminar piso de ruido (suave)", 1.5),
             ("Eliminar piso de ruido (fuerte)", 3.0)]
RANGOS_FFT = [("−140 a +20 dBV", -140), ("−120 a +20 dBV", -120), ("−100 a +20 dBV", -100),
              ("−80 a +20 dBV", -80)]
FFT_POR_DEFECTO = {"ventana": "Blackman-Harris", "promedio": 0, "ruido": 0, "rango": 2, "canal": 1,
                   "umbral": -80.0, "sobre_piso": 10.0, "sep": 0.0, "max_picos": 10, "marcar": True,
                   "ignorar_dc": True}


class DialogoFFT(QDialog):
    """Ventana (no modal) de análisis del espectro: procesamiento, umbrales de detección,
    tabla de picos y mediciones de distorsión y ruido. Se actualiza en vivo."""

    def __init__(self, tab):
        super().__init__(tab)
        self.tab = tab
        self.setWindowTitle("Análisis de espectro (FFT)")
        W.tam(self, "resize", 760, 640)
        c = tab.fft_cfg
        raiz = QVBoxLayout(self)

        arriba = QHBoxLayout()
        g, lay = W.grupo("Procesamiento")
        self.ventana = W.combo(M.VENTANAS, c["ventana"])
        self.promedio = W.combo([t for t, _ in PROMEDIOS_FFT])
        self.promedio.setCurrentIndex(c["promedio"])
        self.ruido = W.combo([t for t, _ in RUIDO_FFT])
        self.ruido.setCurrentIndex(c["ruido"])
        self.rango = W.combo([t for t, _ in RANGOS_FFT])
        self.rango.setCurrentIndex(c["rango"])
        lay.addWidget(W.fila("Ventana", self.ventana, ayuda=(
            "Blackman-Harris: mejor para ver señales chicas al lado de grandes y medir SNR/THD.\n"
            "Flat-top: la amplitud más exacta. Hann: uso general. Rectangular: solo para señales "
            "que entran justo en la pantalla.")))
        lay.addWidget(W.fila("Promediado", self.promedio, ayuda=(
            "Promedia la potencia de varios cuadros: el ruido se vuelve parejo (desaparecen los "
            "micropicos) y las componentes reales quedan quietas. Suaviza la lectura.")))
        lay.addWidget(W.fila("Ruido blanco", self.ruido, ayuda=(
            "Estima el piso de ruido con una mediana móvil y lo resta (sustracción espectral). "
            "Quedan solo las componentes que sobresalen del ruido. Funciona mejor con promediado.")))
        lay.addWidget(W.fila("Escala vertical", self.rango))
        fila = QHBoxLayout()
        fila.addStretch(1)
        fila.addWidget(W.boton("Reiniciar promedio", tab.reiniciar_promedio_fft))
        lay.addLayout(fila)
        arriba.addWidget(g, 1)

        g, lay = W.grupo("Detección de picos")
        self.canal = W.combo(["CH1", "CH2"], f"CH{c['canal']}")
        self.umbral = QDoubleSpinBox()
        self.umbral.setRange(-160, 40)
        self.umbral.setDecimals(1)
        self.umbral.setSingleStep(1)
        self.umbral.setSuffix(" dBV")
        self.umbral.setValue(c["umbral"])
        self.sobre = QDoubleSpinBox()
        self.sobre.setRange(0, 100)
        self.sobre.setDecimals(1)
        self.sobre.setSuffix(" dB")
        self.sobre.setValue(c["sobre_piso"])
        self.sep = W.EntradaSI("Hz", 0, 10e6, c["sep"], 4, 100)
        self.max_picos = QSpinBox()
        self.max_picos.setRange(1, 50)
        self.max_picos.setValue(c["max_picos"])
        self.marcar = QCheckBox("Marcar en el gráfico")
        self.marcar.setChecked(c["marcar"])
        self.ignorar_dc = QCheckBox("Ignorar la continua")
        self.ignorar_dc.setChecked(c["ignorar_dc"])
        lay.addWidget(W.fila("Canal", self.canal))
        lay.addWidget(W.fila("Umbral absoluto", self.umbral,
                             ayuda="Solo se detectan picos por encima de este nivel. También se puede "
                                   "arrastrar la línea punteada del gráfico."))
        lay.addWidget(W.fila("Sobre el piso", self.sobre,
                             ayuda="Cuánto tiene que sobresalir un pico del piso de ruido local."))
        lay.addWidget(W.fila("Separación mínima", self.sep,
                             ayuda="Dos picos más cercanos que esto cuentan como uno (0 = automática)."))
        lay.addWidget(W.fila("Máximo de picos", self.max_picos))
        f2 = QHBoxLayout()
        f2.addWidget(self.marcar)
        f2.addWidget(self.ignorar_dc)
        lay.addLayout(f2)
        arriba.addWidget(g, 1)
        raiz.addLayout(arriba)

        g, lay = W.grupo("Mediciones")
        self.resumen = QGridLayout()
        self.resumen.setHorizontalSpacing(W.px(16))
        self.valores = {}
        claves = [("f0", "Fundamental"), ("a0", "Nivel"), ("thd", "THD"), ("snr", "SNR"),
                  ("sinad", "SINAD"), ("enob", "ENOB"), ("piso", "Piso de ruido"),
                  ("dens", "Densidad"), ("rbw", "RBW"), ("prom", "Promedios")]
        for i, (k, t) in enumerate(claves):
            fila_r, col = divmod(i, 5)
            lt = W.etiqueta_tenue(t)
            lt.setWordWrap(False)
            lv = QLabel("—")
            lv.setFont(W.MONO)
            self.resumen.addWidget(lt, fila_r * 2, col)
            self.resumen.addWidget(lv, fila_r * 2 + 1, col)
            self.valores[k] = lv
        lay.addLayout(self.resumen)
        self.aviso = W.etiqueta_tenue("")
        lay.addWidget(self.aviso)
        raiz.addWidget(g)

        self.tabla = QTableWidget(0, 7)
        self.tabla.setHorizontalHeaderLabels(["#", "Frecuencia", "Nivel", "V eficaz", "dBc",
                                              "Sobre piso", "Armónico"])
        self.tabla.verticalHeader().setVisible(False)
        self.tabla.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tabla.setSelectionMode(QAbstractItemView.NoSelection)
        self.tabla.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.tabla.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        raiz.addWidget(self.tabla, 1)

        abajo = QHBoxLayout()
        abajo.addWidget(W.etiqueta_tenue("Los niveles son valores eficaces (dBV = dB respecto de 1 V eficaz). "
                                         "dBc: respecto del pico mayor."), 1)
        abajo.addWidget(W.boton("Exportar CSV", self._exportar))
        abajo.addWidget(W.boton("Cerrar", self.close))
        raiz.addLayout(abajo)

        for w in (self.ventana, self.promedio, self.ruido, self.rango, self.canal):
            w.currentIndexChanged.connect(self._cambio)
        for w in (self.umbral, self.sobre):
            w.valueChanged.connect(self._cambio)
        self.max_picos.valueChanged.connect(self._cambio)
        self.sep.cambiado.connect(self._cambio)
        for w in (self.marcar, self.ignorar_dc):
            w.toggled.connect(self._cambio)
        self.picos, self.analisis = [], None

    def _cambio(self, *_):
        c = self.tab.fft_cfg
        reiniciar = (c["ventana"] != self.ventana.currentText()
                     or c["promedio"] != self.promedio.currentIndex())
        c.update({"ventana": self.ventana.currentText(), "promedio": self.promedio.currentIndex(),
                  "ruido": self.ruido.currentIndex(), "rango": self.rango.currentIndex(),
                  "canal": self.canal.currentIndex() + 1, "umbral": self.umbral.value(),
                  "sobre_piso": self.sobre.value(), "sep": self.sep.valor(),
                  "max_picos": self.max_picos.value(), "marcar": self.marcar.isChecked(),
                  "ignorar_dc": self.ignorar_dc.isChecked()})
        self.tab.fft_cambiada(reiniciar)

    def set_umbral(self, v: float):
        self.umbral.blockSignals(True)
        self.umbral.setValue(v)
        self.umbral.blockSignals(False)

    def mostrar(self, picos: list, analisis: dict | None, promedios: tuple[int, int]):
        self.picos, self.analisis = picos, analisis
        v = self.valores
        a = analisis
        if a:
            v["f0"].setText(M.si(a["f0"], "Hz", 6))
            v["a0"].setText(f"{20 * math.log10(max(a['a0'], 1e-12)):.2f} dBV".replace(".", ",").replace("-", "−"))
            if a["resolucion_ok"]:
                v["thd"].setText(f"{a['thd'] * 100:.3g} %  ({a['thd_db']:.1f} dB)".replace(".", ",").replace("-", "−"))
                v["sinad"].setText(f"{a['sinad']:.1f} dB".replace(".", ",").replace("-", "−"))
                v["enob"].setText(f"{a['enob']:.2f} bits".replace(".", ",").replace("-", "−"))
                self.aviso.setText("")
            else:
                for k in ("thd", "sinad", "enob"):
                    v[k].setText("—")
                self.aviso.setText("Hay pocos períodos en pantalla y los armónicos quedan pegados al "
                                   "fundamental: subí el tiempo/div para medir THD, SINAD y ENOB.")
            v["snr"].setText(f"{a['snr']:.1f} dB".replace(".", ",").replace("-", "−"))
            v["piso"].setText(f"{a['piso_db']:.1f} dBV".replace(".", ",").replace("-", "−"))
            v["dens"].setText(M.si(a["densidad"], "V/√Hz", 3))
            v["rbw"].setText(M.si(a["rbw"], "Hz", 3))
        else:
            for k in v:
                v[k].setText("—")
        v["prom"].setText(f"{promedios[0]} de {promedios[1]}")
        self.tabla.setRowCount(len(picos))
        ref = picos[0]["db"] if picos else 0.0
        for i, pk in enumerate(picos):
            arm = pk.get("armonico")
            celdas = [str(i + 1), M.si(pk["f"], "Hz", 6),
                      f"{pk['db']:.2f} dBV".replace(".", ",").replace("-", "−"),
                      M.si(10 ** (pk["db"] / 20), "V", 4),
                      f"{pk['db'] - ref:.1f}".replace(".", ",").replace("-", "−"),
                      f"{pk['sobre_piso']:.1f} dB".replace(".", ","),
                      ("fundamental" if arm == 1 else f"{arm}º") if arm else "—"]
            for j, t in enumerate(celdas):
                it = self.tabla.item(i, j)
                if it is None:
                    it = QTableWidgetItem()
                    it.setTextAlignment(Qt.AlignCenter)
                    self.tabla.setItem(i, j, it)
                it.setText(t)

    def _exportar(self):
        if not self.picos:
            self.tab.v.estado("No hay picos detectados para exportar.", W.ALERTA)
            return
        ruta, _ = QFileDialog.getSaveFileName(self, "Exportar picos", "picos_fft.csv", "CSV (*.csv)")
        if not ruta:
            return
        try:
            with open(ruta, "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f, delimiter=";")
                w.writerow(["n", "frecuencia_Hz", "nivel_dBV", "v_eficaz_V", "dBc", "sobre_piso_dB", "armonico"])
                ref = self.picos[0]["db"]
                for i, pk in enumerate(self.picos, 1):
                    w.writerow([i, M.num_csv(pk["f"], ".9g"), M.num_csv(pk["db"], ".4f"),
                                M.num_csv(10 ** (pk["db"] / 20)), M.num_csv(pk["db"] - ref, ".3f"),
                                M.num_csv(pk["sobre_piso"], ".2f"), pk.get("armonico") or ""])
                a = self.analisis
                if a:
                    w.writerow([])
                    for k, val in (("fundamental_Hz", a["f0"]), ("thd_pct", a["thd"] * 100),
                                   ("snr_dB", a["snr"]), ("sinad_dB", a["sinad"]), ("enob_bits", a["enob"]),
                                   ("piso_dBV", a["piso_db"]), ("densidad_V_raizHz", a["densidad"]),
                                   ("rbw_Hz", a["rbw"])):
                        w.writerow([k, M.num_csv(val, ".6g")])
        except OSError as e:
            self.tab.v.estado(f"No se pudo guardar {ruta}: {e.strerror or e}", W.ERROR)
            return
        self.tab.v.estado(f"Guardado: {ruta}", W.OK)


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
        # Single/Autoset pedidos mientras viajaba otra captura: se arrancan
        # cuando esa llega (no se le manda a la placa una captura encimada).
        self.accion_pendiente: str | None = None
        self._fps_t = time.monotonic()
        self._fps_n = 0
        self.fps = 0.0
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
        self.fosforo = Fosforo(self.plot)
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
        self.plot_fft.setLogMode(x=True, y=False)
        self.curvas_fft = {c: curva_rapida(self.plot_fft, COLORES[c]) for c in (1, 2)}
        self.fft_cfg = dict(FFT_POR_DEFECTO)
        self.fft_cfg.update({k: v for k, v in cfg.get("fft", {}).items() if k in FFT_POR_DEFECTO})
        self.prom_fft = {c: M.PromedioEspectro() for c in (1, 2)}
        self.fft_ult = {1: None, 2: None}
        self.dlg_fft = None
        self._t_dlg_fft = 0.0
        self.marcas_fft = self.plot_fft.plot([], [], pen=None, symbol="t", symbolSize=11,
                                             symbolPen=pg.mkPen(W.TEXTO, width=1), symbolBrush=W.ALERTA)
        self.textos_fft = []
        self.linea_umbral = pg.InfiniteLine(angle=0, movable=True,
                                            pen=pg.mkPen(W.ALERTA, width=1, style=Qt.DashLine))
        self.linea_umbral.setZValue(5)
        self.linea_umbral.sigPositionChangeFinished.connect(self._umbral_arrastrado)
        self.plot_fft.addItem(self.linea_umbral)
        self._aplicar_rango_fft()
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
        W.tam(scroll, "setFixedWidth", 340)
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
        W.tam(self.btn_run, "setMinimumHeight", 38)
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
        self.persistencia = W.combo(PERSISTENCIAS)
        self.persistencia.setCurrentIndex(int(cfg.get("persistencia", 0)))
        self.persistencia.currentIndexChanged.connect(self._cambio_persistencia)
        fila_p = QHBoxLayout()
        fila_p.addWidget(self.persistencia, 1)
        fila_p.addWidget(W.boton("Borrar", lambda: self.fosforo.borrar()))
        cont_p = QWidget()
        cont_p.setLayout(fila_p)
        fila_p.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(W.fila("Persistencia", cont_p, ayuda=(
            "Deja el rastro de los trazos anteriores, como el fósforo de un osciloscopio analógico: "
            "un transitorio que aparece una sola vez queda marcado ese tiempo (o para siempre en "
            "«Infinita»). Lo que se repite brilla más. Se borra al cambiar las escalas.")))
        self.modo_xy = QCheckBox("Modo XY (CH1 horizontal, CH2 vertical)")
        self.chk_fft = QCheckBox("Espectro (FFT)")
        self.chk_cur = QCheckBox("Cursores")
        for c in (self.modo_xy, self.chk_fft, self.chk_cur):
            c.toggled.connect(self._cambio_pantalla)
        lay.addWidget(self.modo_xy)
        fila_fft = QHBoxLayout()
        fila_fft.addWidget(self.chk_fft)
        fila_fft.addStretch(1)
        self.btn_fft = W.boton("Análisis de picos…", self.abrir_analisis_fft)
        self.btn_fft.setToolTip("Picos, umbrales de detección, promediado, eliminación del piso de "
                                "ruido, THD y SNR")
        fila_fft.addWidget(self.btn_fft)
        lay.addLayout(fila_fft)
        lay.addWidget(self.chk_cur)
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
        self._cambio_persistencia()

    # ------------------------------------------------------------ config
    def estado_config(self) -> dict:
        return {"tdiv": self.tdiv.currentIndex(), "pos_disp": self.pos_disp.value(),
                "fuente": self.fuente.currentText(), "flanco": self.flanco.currentText(),
                "modo": self.modo.currentText(), "nivel": self.nivel.valor(),
                "suavizado": self.suavizado.currentIndex(), "desplaz": self.desplaz.value(),
                "persistencia": self.persistencia.currentIndex(), "fft": dict(self.fft_cfg),
                "ch1": self.canales[1].estado(), "ch2": self.canales[2].estado()}

    @property
    def t_div(self) -> float:
        return TDIVS[self.tdiv.currentIndex()]

    def recta(self, c: int) -> M.Recta:
        return self.v.config.recta_entrada(c, self.canales[c].clave_entrada)

    # ------------------------------------------------------------ eje horizontal
    @property
    def desplazamiento(self) -> float:
        """Desplazamiento horizontal en divisiones. Solo existe con las bases de tiempo
        que capturan pantallas extra; con las lentas se ignora."""
        if self.t_div <= TDIV_DESPLAZ_MAX:
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
        n, pre, fs, fuente, nivel, flanco = self.parametros_captura()
        self.v.pedir_captura("osc", n, pre, fs, fuente, nivel, flanco, 20)
        self.esperando = True
        self.t_pedido = time.monotonic()
        total = n * (3 if fuente else 1)
        self.timeout = total / fs + 1.5

    def _vigilar(self):
        if self.v.dueno_captura != "osc" and self.v.dueno_captura is not None:
            return
        if self.esperando and time.monotonic() - self.t_pedido > self.timeout:
            self.esperando = False
            if self._ejecutar_pendiente():
                return
            if self.autoset_estado:
                self._autoset_pedir()
            elif self.corriendo:
                self.pedir()

    def _ejecutar_pendiente(self) -> bool:
        """Arranca el Single o Autoset que quedó esperando. True si había uno."""
        accion, self.accion_pendiente = self.accion_pendiente, None
        if accion == "unico":
            self._unico_iniciar()
        elif accion == "autoset":
            self._autoset_iniciar()
        return accion is not None

    def al_conectar(self):
        self.esperando = False
        self.accion_pendiente = None
        if not self.corriendo:
            self._alternar_run()

    def al_desconectar(self):
        self.esperando = False
        self.accion_pendiente = None
        self._set_run(False)

    def al_recibir(self, d: dict):
        self.esperando = False
        if self._ejecutar_pendiente():      # esta captura era de antes del botón
            return
        if self.autoset_estado:
            self._autoset_paso(d)
            return
        if not self.corriendo:
            return
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
            self.v.estado("Single: captura lista.", W.OK)
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
        self._dibujar(nuevo=True)
        self._fps_n += 1
        ahora = time.monotonic()
        if ahora - self._fps_t > 1.0:
            self.fps = self._fps_n / (ahora - self._fps_t)
            self._fps_n, self._fps_t = 0, ahora

    def _dibujar(self, nuevo: bool = False):
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
                if nuevo:
                    self.fosforo.agregar(c, x, y)
            else:
                self.fosforo.borrar(c)
        self.fosforo.img.setVisible(not xy)
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
            self._dibujar_fft(u, i0, i1, fs, nuevo)
        estado = {2: "Libre", 1: "Disparado", 0: "Auto (sin disparo)"}.get(u["disparado"], "Desconocido")
        if not self.corriendo:
            estado = "Detenido"
        self.txt_estado.setText(f"{estado}   {M.si(fs, 'S/s', 3)}   {self.fps:.0f} cuadros/s")
        self._actualizar_cursores()

    # ------------------------------------------------------------ controles
    def _cambio(self, *_):
        if hasattr(self, "fosforo"):
            self.fosforo.borrar()          # las escalas cambiaron: el rastro viejo ya no coincide
        self.marca_disparo.setPos(self._x0())
        fuente = {"CH1": 1, "CH2": 2, "Libre": 0}[self.fuente.currentText()]
        self.linea_nivel.setVisible(fuente != 0)
        if fuente:
            p = self.canales[fuente]
            self.linea_nivel.setPen(pg.mkPen(COLORES[fuente], width=1, style=Qt.DashLine))
            self.linea_nivel.blockSignals(True)
            self.linea_nivel.setPos(self.nivel.valor() / p.v_div + p.pos.valor())
            self.linea_nivel.blockSignals(False)
        n, pre, fs, *_ = self.parametros_captura()
        self.lbl_fs.setText(f"Muestreo: {M.si(fs, 'S/s', 3)} · {n} puntos")
        if self.t_div <= TDIV_DESPLAZ_MAX:
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
        self.fosforo.borrar()
        if not self.chk_fft.isChecked():
            self.reiniciar_promedio_fft()
        cur = self.chk_cur.isChecked()
        for c in self.cur_t + self.cur_v:
            c.setVisible(cur)
        self.lbl_cursores.setVisible(cur)
        self._dibujar()

    # ------------------------------------------------------------ persistencia
    def _cambio_persistencia(self, *_):
        self.fosforo.set_tiempo(TIEMPOS_PERSIST[self.persistencia.currentIndex()])
        self.v.guardar_config_pronto()

    # ------------------------------------------------------------ espectro
    def abrir_analisis_fft(self):
        if not self.chk_fft.isChecked():
            self.chk_fft.setChecked(True)
        if self.dlg_fft is None:
            self.dlg_fft = DialogoFFT(self)
        self.dlg_fft.show()
        self.dlg_fft.raise_()
        self.dlg_fft.activateWindow()
        self._dibujar()

    def reiniciar_promedio_fft(self):
        for c in (1, 2):
            self.prom_fft[c].reiniciar()
            self.fft_ult[c] = None
        if self.ultimo and self.chk_fft.isChecked():
            self._dibujar()

    def fft_cambiada(self, reiniciar: bool):
        if reiniciar:
            for c in (1, 2):
                self.prom_fft[c].reiniciar()
                self.fft_ult[c] = None
        self._aplicar_rango_fft()
        self._t_dlg_fft = 0.0
        self.v.guardar_config_pronto()
        self._dibujar()

    def _aplicar_rango_fft(self):
        piso = RANGOS_FFT[self.fft_cfg["rango"]][1]
        self.plot_fft.setYRange(piso, 20, padding=0)
        self.linea_umbral.setValue(self.fft_cfg["umbral"])
        self.linea_umbral.setVisible(bool(self.fft_cfg["marcar"]))

    def _umbral_arrastrado(self):
        v = round(float(self.linea_umbral.value()), 1)
        self.fft_cfg["umbral"] = v
        if self.dlg_fft is not None:
            self.dlg_fft.set_umbral(v)
        self.v.guardar_config_pronto()
        self._dibujar()

    def _espectro_canal(self, c: int, v: np.ndarray, fs: float, nuevo: bool) -> dict:
        """Espectro de un canal con el promediado aplicado (potencia por bin)."""
        cfg = self.fft_cfg
        n_prom = PROMEDIOS_FFT[cfg["promedio"]][1]
        clave = (len(v), round(fs, 3), cfg["ventana"])
        ult = self.fft_ult[c]
        if nuevo or ult is None or ult["clave"] != clave:      # si no, se reusa el último espectro
            f, p, enbw = M.espectro_potencia(v, fs, cfg["ventana"])
            p = self.prom_fft[c].agregar(clave, p, n_prom) if n_prom > 1 else p
            ult = {"clave": clave, "f": f, "p": p, "enbw": enbw,
                   "k": min(self.prom_fft[c].efectivos, n_prom) if n_prom > 1 else 1, "n": n_prom}
            ult["piso"] = M.piso_ruido(p, ult["k"])
            self.fft_ult[c] = ult
        return ult

    def _dibujar_fft(self, u: dict, i0: int, i1: int, fs: float, nuevo: bool):
        cfg = self.fft_cfg
        fuerza = RUIDO_FFT[cfg["ruido"]][1]
        datos = {}
        for c in (1, 2):
            vis = self.canales[c].visible.isChecked()
            self.curvas_fft[c].setVisible(vis)
            if not vis or i1 - i0 < 32:
                continue
            e = self._espectro_canal(c, u[c][i0:i1], fs, nuevo)
            datos[c] = e
            p = M.quitar_piso(e["p"], e["piso"], fuerza) if fuerza > 0 else e["p"]
            self.curvas_fft[c].setData(e["f"][1:], M.a_db(p)[1:])
        # picos del canal elegido
        c = cfg["canal"]
        picos, analisis = [], None
        if c in datos:
            e = datos[c]
            picos = M.buscar_picos(e["f"], e["p"], e["piso"], cfg["umbral"], cfg["sobre_piso"],
                                   cfg["sep"], cfg["max_picos"], cfg["ignorar_dc"], e["enbw"])
            analisis = M.analizar_armonicos(e["f"], e["p"], e["piso"], e["enbw"],
                                            picos[0]["f"] if picos else None)
            if analisis:
                f0 = analisis["f0"]
                for pk in picos:
                    n = round(pk["f"] / f0) if f0 > 0 else 0
                    tol = max(3 * (e["f"][1] - e["f"][0]), 0.01 * f0)
                    pk["armonico"] = n if n >= 1 and abs(pk["f"] - n * f0) <= tol else None
        self._marcar_picos(picos if cfg["marcar"] else [], COLORES.get(c, W.ALERTA))
        if self.dlg_fft is not None and self.dlg_fft.isVisible():
            ahora = time.monotonic()
            if ahora - self._t_dlg_fft > 0.25:
                self._t_dlg_fft = ahora
                e = datos.get(c)
                self.dlg_fft.mostrar(picos, analisis, (e["k"], e["n"]) if e else (0, 0))

    def _marcar_picos(self, picos: list, color: str):
        self.marcas_fft.setData([pk["f"] for pk in picos], [pk["db"] for pk in picos])
        self.marcas_fft.setSymbolBrush(color)
        self.marcas_fft.setSymbolSize(W.px(11))
        while len(self.textos_fft) < len(picos):
            t = pg.TextItem(color=W.TEXTO, anchor=(0.5, 1.15))
            t._puntos = 8.5
            t.setFont(W.fuente(puntos=8.5))
            self.plot_fft.addItem(t)
            self.textos_fft.append(t)
        for i, t in enumerate(self.textos_fft):
            if i < len(picos) and i < 12:
                pk = picos[i]
                t.setText(f"{i + 1}: {M.si(pk['f'], 'Hz', 4)}")
                t.setPos(math.log10(max(pk["f"], 1e-3)), pk["db"])
                t.setVisible(True)
            else:
                t.setVisible(False)

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
        self.accion_pendiente = None
        self.autoset_estado = None
        self._set_run(not self.corriendo)
        if self.corriendo and not self.esperando:
            self.pedir()

    # Single y Autoset no le piden una captura a la placa mientras otra está en
    # camino: el firmware hasta la 0.8.19 abortaba la captura a la mitad y el
    # ADC quedaba trabado (el trazo se congelaba hasta reconectar la placa).
    def _unico(self):
        if not self.v.disp.esta_conectado:
            self.v.estado("Conectá la placa primero.", W.ALERTA)
            return
        if self.esperando:
            self.accion_pendiente = "unico"
            self.unico = True
            self._set_run(True)
            return
        self._unico_iniciar()

    def _unico_iniciar(self):
        self.autoset_estado = None
        self.unico = True
        self._set_run(True)
        if self.fuente.currentText() != "Libre":
            self.v.estado("Single: esperando el disparo… (tocá STOP para cancelar)", W.TEXTO)
        self.pedir()

    # ------------------------------------------------------------ autoset
    def _autoset(self):
        if not self.v.disp.esta_conectado:
            self.v.estado("Conectá la placa primero.", W.ALERTA)
            return
        self.v.estado("Autoset: buscando la señal…", W.TEXTO)
        if self.esperando:
            self.accion_pendiente = "autoset"
            return
        self._autoset_iniciar()

    def _autoset_iniciar(self):
        self.unico = False
        self.autoset_estado = {"fs": self.v.disp.info.get("osc_fsmax", 1.6e6)}
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
