"""Estilo visual y controles comunes de la aplicación."""
from __future__ import annotations

import math
import weakref

import pyqtgraph as pg
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (QComboBox, QFrame, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
                               QPushButton, QSizePolicy, QVBoxLayout, QWidget)

import modelo as M

# Colores (tema oscuro de instrumento)
FONDO = "#0d1117"
PANEL = "#161b22"
BORDE = "#2b333d"
TEXTO = "#e6edf3"
TENUE = "#8b949e"
ACENTO = "#2f81f7"
OK = "#2ea043"
ALERTA = "#d29922"
ERROR = "#f85149"
CH1 = "#f7d046"     # amarillo, como en la mayoría de los osciloscopios
CH2 = "#3fd0e0"     # celeste
REJILLA = "#26303b"

# ---------------------------------------------------------------------------
# Escala de la interfaz (zoom): todo lo que tiene tamaño pasa por pt() o px()
# ---------------------------------------------------------------------------
ESCALA = 1.0
ZOOMS = [0.8, 0.9, 1.0, 1.1, 1.25, 1.4, 1.6, 1.8, 2.0]


def pt(n: float) -> float:
    """Tamaño de letra (puntos) escalado con el zoom."""
    return round(n * ESCALA, 1)


def px(n: float) -> int:
    """Medida en píxeles escalada con el zoom."""
    return max(1, int(round(n * ESCALA)))


def estilo() -> str:
    return f"""
QWidget {{ background: {FONDO}; color: {TEXTO}; font-size: {pt(10)}pt; }}
QMainWindow, QTabWidget::pane {{ background: {FONDO}; }}
QTabWidget::pane {{ border: {px(1)}px solid {BORDE}; border-radius: {px(6)}px; top: -{px(1)}px; }}
QTabBar::tab {{ background: {PANEL}; color: {TENUE}; padding: {px(8)}px {px(18)}px; border: {px(1)}px solid {BORDE};
               border-bottom: none; border-top-left-radius: {px(6)}px; border-top-right-radius: {px(6)}px; margin-right: {px(2)}px; }}
QTabBar::tab:selected {{ background: {FONDO}; color: {TEXTO}; font-weight: 600; }}
QGroupBox {{ background: {PANEL}; border: {px(1)}px solid {BORDE}; border-radius: {px(8)}px; margin-top: {px(14)}px;
            padding: {px(10)}px {px(8)}px {px(8)}px {px(8)}px; }}
QGroupBox::title {{ subcontrol-origin: margin; left: {px(10)}px; padding: 0 {px(4)}px; color: {TENUE};
                   font-weight: 600; background: transparent; }}
QGroupBox QWidget {{ background: transparent; }}
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {{ background: {FONDO}; border: {px(1)}px solid {BORDE};
            border-radius: {px(5)}px; padding: {px(4)}px {px(6)}px; selection-background-color: {ACENTO}; }}
QLineEdit:focus, QComboBox:focus {{ border-color: {ACENTO}; }}
QLineEdit:disabled, QComboBox:disabled {{ color: {TENUE}; }}
QComboBox QAbstractItemView {{ background: {PANEL}; border: {px(1)}px solid {BORDE}; selection-background-color: {ACENTO}; }}
QPushButton {{ background: #21262d; border: {px(1)}px solid {BORDE}; border-radius: {px(6)}px; padding: {px(6)}px {px(12)}px; }}
QPushButton:hover {{ background: #30363d; }}
QPushButton:pressed {{ background: #3b434c; }}
QPushButton:checked {{ background: {ACENTO}; border-color: {ACENTO}; color: white; }}
QPushButton:disabled {{ color: {TENUE}; }}
QPushButton#primario {{ background: {ACENTO}; border-color: {ACENTO}; color: white; font-weight: 600; }}
QPushButton#run[corriendo="true"] {{ background: {OK}; border-color: {OK}; color: white; font-weight: 700; }}
QPushButton#run[corriendo="false"] {{ background: {ERROR}; border-color: {ERROR}; color: white; font-weight: 700; }}
QCheckBox {{ background: transparent; spacing: {px(6)}px; }}
QLabel#tenue {{ color: {TENUE}; }}
QLabel#titulo {{ font-size: {pt(14)}pt; font-weight: 700; }}
QLabel#grande {{ font-family: Consolas, 'DejaVu Sans Mono', monospace; font-size: {pt(26)}pt; font-weight: 700; }}
QStatusBar {{ background: {PANEL}; color: {TENUE}; }}
QScrollArea {{ border: none; }}
QTableWidget {{ background: {FONDO}; gridline-color: {BORDE}; border: {px(1)}px solid {BORDE}; border-radius: {px(5)}px; }}
QHeaderView::section {{ background: {PANEL}; color: {TENUE}; border: none; border-bottom: {px(1)}px solid {BORDE};
                       padding: {px(4)}px {px(6)}px; font-weight: 600; }}
QSpinBox::up-button, QDoubleSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::down-button {{ width: {px(16)}px; }}
QToolTip {{ background: {PANEL}; color: {TEXTO}; border: {px(1)}px solid {BORDE}; }}
"""


ESTILO = estilo()

_tamanos: list = []        # (referencia débil al widget, método, medidas base)
_avisos: list = []         # funciones a llamar cuando cambia la escala


def tam(widget, metodo: str, *base):
    """Fija un tamaño (setFixedWidth, setMinimumHeight, setMinimumSize…) que acompaña al zoom."""
    getattr(widget, metodo)(*[px(b) for b in base])
    try:
        _tamanos.append((weakref.ref(widget), metodo, base))
    except TypeError:
        pass
    return widget


def al_cambiar_escala(funcion):
    """Registra una función (o método) a llamar cuando cambia el zoom. Se guarda una
    referencia débil: no mantiene viva una ventana que ya se cerró."""
    try:
        _avisos.append(weakref.WeakMethod(funcion))
    except TypeError:
        _avisos.append(lambda f=funcion: f)


def fuente(familia: str | None = None, puntos: float = 10, negrita: bool = False) -> QFont:
    f = QFont(familia) if familia else QFont()
    f.setPointSizeF(pt(puntos))
    f.setBold(negrita)
    return f


def escalar_graficos(raiz: QWidget):
    """Letras de los ejes y textos de los gráficos de pyqtgraph."""
    for pw in raiz.findChildren(pg.PlotWidget):
        pi = pw.getPlotItem()
        f = fuente(puntos=9)
        for nombre in ("left", "bottom", "right", "top"):
            ax = pi.getAxis(nombre)
            ax.setStyle(tickFont=f)
            ax.label.setFont(f)
            ax.picture = None
            ax.update()
        for item in list(pi.items) + list(pi.vb.addedItems):
            if isinstance(item, pg.TextItem):
                item.setFont(fuente(puntos=getattr(item, "_puntos", 9.5), negrita=getattr(item, "_negrita", False)))


def aplicar_escala(app, escala: float):
    """Cambia el zoom en vivo: estilo, tamaños registrados y gráficos."""
    global ESCALA
    escala = float(min(max(escala, ZOOMS[0]), ZOOMS[-1]))
    if abs(escala - ESCALA) < 1e-9:
        return
    ESCALA = escala
    app.setStyleSheet(estilo())
    vivos = []
    for ref, metodo, base in _tamanos:
        w = ref()
        if w is None:
            continue
        try:
            getattr(w, metodo)(*[px(b) for b in base])
            vivos.append((ref, metodo, base))
        except RuntimeError:          # el widget ya se destruyó
            pass
    _tamanos[:] = vivos
    for ref in list(_avisos):
        funcion = ref()
        if funcion is None:
            _avisos.remove(ref)
            continue
        try:
            funcion()
        except RuntimeError:          # la ventana ya se destruyó
            _avisos.remove(ref)


MONO = QFont("Consolas")
MONO.setStyleHint(QFont.Monospace)


class EjeLogFrecuencia(pg.AxisItem):
    """Eje logarítmico de frecuencia con rótulos limpios (1, 2, 5 por década)."""

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.enableAutoSIPrefix(False)

    def tickValues(self, minVal, maxVal, size):
        if not self.logMode:
            return super().tickValues(minVal, maxVal, size)
        d0, d1 = int(math.floor(minVal)), int(math.ceil(maxVal))
        mayores, menores = [], []
        for d in range(d0, d1 + 1):
            for k in range(1, 10):
                x = d + math.log10(k)
                if minVal <= x <= maxVal:
                    (mayores if k == 1 else menores).append(x)
        return [(1.0, mayores), (0.1, menores)]

    def tickStrings(self, values, scale, spacing):
        if not self.logMode:
            return super().tickStrings(values, scale, spacing)
        salida = []
        for x in values:
            v = 10 ** x
            k = round(v / 10 ** math.floor(x + 1e-9))
            salida.append(M.si(v, "Hz", 3) if k in (1, 2, 5) else "")
        return salida


class EntradaSI(QWidget):
    """Campo numérico que acepta prefijos (2k, 1,5 m, 10 µ...). La rueda del
    mouse modifica la segunda cifra significativa."""
    cambiado = Signal(float)

    def __init__(self, unidad: str, vmin: float, vmax: float, valor: float, cifras: int = 5,
                 ancho: int = 110, parent=None):
        super().__init__(parent)
        self.unidad, self.vmin, self.vmax, self.cifras = unidad, vmin, vmax, cifras
        self._valor = valor
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.edit = QLineEdit()
        self.edit.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.edit.setFont(MONO)
        tam(self.edit, "setFixedWidth", ancho)
        self.edit.editingFinished.connect(self._editado)
        lay.addWidget(self.edit)
        self._mostrar()

    def valor(self) -> float:
        return self._valor

    def set_valor(self, v: float, emitir: bool = False):
        v = min(max(v, self.vmin), self.vmax)
        cambio = v != self._valor
        self._valor = v
        self._mostrar()
        if emitir and cambio:
            self.cambiado.emit(v)

    def set_rango(self, vmin, vmax):
        self.vmin, self.vmax = vmin, vmax
        self.set_valor(self._valor)

    def _mostrar(self):
        if self.unidad == "div":
            self.edit.setText(f"{self._valor:.2f} div".replace(".", ",").replace("-", "−"))
        else:
            self.edit.setText(M.si(self._valor, self.unidad, self.cifras))

    def _editado(self):
        try:
            v = M.leer_si(self.edit.text())
        except ValueError:
            self._mostrar()
            return
        self.set_valor(v, emitir=True)

    def wheelEvent(self, e):
        if not self.isEnabled():
            return
        paso_dir = 1 if e.angleDelta().y() > 0 else -1
        v = self._valor
        if v == 0:
            paso = 10 ** math.floor(math.log10(max(abs(self.vmax), 1e-9))) / 100
        else:
            paso = 10 ** (math.floor(math.log10(abs(v))) - 1)
        self.set_valor(round((v + paso_dir * paso) / paso) * paso, emitir=True)
        e.accept()


def fila(etiqueta: str, *widgets, ayuda: str = "") -> QWidget:
    w = QWidget()
    lay = QHBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    lbl = QLabel(etiqueta)
    tam(lbl, "setMinimumWidth", 120)
    if ayuda:
        lbl.setToolTip(ayuda)
    lay.addWidget(lbl)
    lay.addStretch(1)
    for x in widgets:
        lay.addWidget(x)
    return w


def combo(opciones, actual=None) -> QComboBox:
    c = QComboBox()
    c.addItems(opciones)
    if actual in opciones:
        c.setCurrentText(actual)
    return c


def grupo(titulo: str) -> tuple[QGroupBox, QVBoxLayout]:
    g = QGroupBox(titulo)
    lay = QVBoxLayout(g)
    lay.setSpacing(6)
    return g, lay


def etiqueta_tenue(texto: str) -> QLabel:
    l = QLabel(texto)
    l.setObjectName("tenue")
    l.setWordWrap(True)
    return l


def separador() -> QFrame:
    f = QFrame()
    f.setFrameShape(QFrame.HLine)
    f.setStyleSheet(f"color: {BORDE};")
    return f


def boton(texto: str, cb=None, primario=False, chequeable=False) -> QPushButton:
    b = QPushButton(texto)
    if primario:
        b.setObjectName("primario")
    b.setCheckable(chequeable)
    if cb:
        b.clicked.connect(cb)
    b.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
    return b
