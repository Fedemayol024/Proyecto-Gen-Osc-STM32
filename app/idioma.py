"""
Idioma de la interfaz: castellano (el del código) o alemán.

Cómo funciona
-------------
Todos los textos del programa están escritos en castellano y así se quedan: son también
los valores internos (lo que devuelve un ComboBox, lo que se guarda en la configuración).
Si se elige otro idioma, instalar() «engancha» los puntos donde Qt muestra un texto
(setText, setToolTip, addTab, addItem, showMessage, drawText, los ejes de pyqtgraph...)
y los pasa por tr(), que busca la traducción en traducciones_de.py. Así:

  - la lógica no cambia: los ComboBox muestran el texto traducido pero currentText()
    sigue devolviendo el original;
  - un texto armado con números ("Punto 3 de 41: 1 kHz") se traduce con plantillas
    ("Punto {} de {}: {}" -> "Punkt {} von {}: {}");
  - con el castellano no se engancha nada: la app funciona exactamente igual que antes.

El idioma se elige en ⚙ y se aplica al reiniciar la app (se guarda en preferencias.json).
"""
from __future__ import annotations

import re

IDIOMAS = {"es": "Español", "de": "Deutsch"}
POR_DEFECTO = "es"

actual = POR_DEFECTO
_exactos: dict[str, str] = {}
_plantillas: list[tuple[re.Pattern, list[str], str]] = []   # (regex, literales, traducción)
_prefijos: list[tuple[str, str]] = []                        # claves que terminan en espacio
_sufijos: list[tuple[str, str]] = []                         # claves que empiezan con espacio
_cache: dict[str, str] = {}
_CACHE_MAX = 8000
_LETRAS = re.compile(r"[A-Za-zÁÉÍÓÚáéíóúÑñ]{2}")
_HTML = re.compile(r"(<[^>]*>|&nbsp;)")
_BORDE = re.compile(r"^(\s*)(.*?)(\s*)$", re.S)
_VINETA = re.compile(r"^([•●○◉⚠▶]\s*)(.+)$", re.S)
_PARENTESIS = re.compile(r"\(([^()]*)\)")


# ---------------------------------------------------------------------------
# Traducción de un texto
# ---------------------------------------------------------------------------
def tr(texto):
    """Traducción de un texto al idioma elegido (el mismo texto si no hay traducción)."""
    if actual == POR_DEFECTO or not isinstance(texto, str) or not _LETRAS.search(texto):
        return texto
    r = _cache.get(texto)
    if r is None:
        r = _traducir(texto, 0)
        if len(_cache) > _CACHE_MAX:
            _cache.clear()
        _cache[texto] = r
    return r


def _traducir(s: str, prof: int) -> str:
    if prof > 5 or not _LETRAS.search(s):
        return s
    # 1. exacto (respetando los espacios de los bordes)
    a, nucleo, z = _BORDE.match(s).groups()
    if nucleo in _exactos:
        return a + _exactos[nucleo] + z
    # 2. HTML: se traducen solo los pedazos de texto entre etiquetas
    if "<" in s or "&nbsp;" in s:
        partes = _HTML.split(s)
        if len(partes) > 1:
            return "".join(p if (i % 2 or not p.strip()) else _traducir(p, prof + 1)
                           for i, p in enumerate(partes))
    # 3. plantillas con huecos ("Punto {} de {}")
    for rx, literales, trad in _plantillas:
        if all(l in nucleo for l in literales):
            m = rx.fullmatch(nucleo)
            if m:
                grupos = [_traducir(g, prof + 1) for g in m.groups()]
                try:
                    return a + trad.format(*grupos) + z
                except (IndexError, KeyError):
                    break
    # 4. viñeta adelante
    m = _VINETA.match(nucleo)                     # «• Polo en 1 kHz», «⚠ …»: sin la viñeta
    if m:
        return a + m.group(1) + _traducir(m.group(2), prof + 1) + z
    # 4b. varias líneas: cada una por separado
    if "\n" in nucleo:
        return a + "\n".join(_traducir(p, prof + 1) for p in nucleo.split("\n")) + z
    # 5. prefijos y sufijos conocidos ("Cero en " + ..., ... + " (nominal)")
    for clave, trad in _prefijos:
        if nucleo.startswith(clave):
            return a + trad + _traducir(nucleo[len(clave):], prof + 1) + z
    for clave, trad in _sufijos:
        if nucleo.endswith(clave) and len(nucleo) > len(clave):
            return a + _traducir(nucleo[:-len(clave)], prof + 1) + trad + z
    # 6. lo que esté entre paréntesis ("1280×720   (todo más grande · 150 %)")
    if "(" in nucleo:
        r = _PARENTESIS.sub(lambda m: "(" + _traducir(m.group(1), prof + 1) + ")", nucleo)
        if r != nucleo:
            return a + r + z
    # 7. textos unidos con « · »
    if " · " in nucleo:
        r = " · ".join(_traducir(p, prof + 1) for p in nucleo.split(" · "))
        if r != nucleo:
            return a + r + z
    return s


def _cargar(tabla: dict[str, str]):
    _exactos.clear(); _plantillas.clear(); _prefijos.clear(); _sufijos.clear(); _cache.clear()
    for es, de in tabla.items():
        if not de or (es == de and ("{}" not in es or not _LETRAS.search(es.replace("{}", "")))):
            continue
        if "{}" in es:
            literales = [p for p in es.replace("{{", "{").replace("}}", "}").split("{}") if p]
            patron = "".join("(.+?)" if p == "{}" else re.escape(p.replace("{{", "{").replace("}}", "}"))
                             for p in re.split(r"(\{\})", es))
            _plantillas.append((re.compile(patron, re.S), literales, de))
        elif es != es.lstrip():
            _sufijos.append((es, de))
        elif es != es.rstrip():
            _prefijos.append((es, de))
        else:
            _exactos[es] = de
    # las plantillas más específicas (más texto fijo) primero
    _plantillas.sort(key=lambda t: -sum(len(l) for l in t[1]))
    _prefijos.sort(key=lambda t: -len(t[0]))
    _sufijos.sort(key=lambda t: -len(t[0]))


# ---------------------------------------------------------------------------
# Enganches con Qt y pyqtgraph
# ---------------------------------------------------------------------------
def _envolver(clase, nombre, posiciones=None, claves=()):
    """Reemplaza clase.nombre por una versión que traduce los argumentos de texto."""
    original = getattr(clase, nombre)

    def nuevo(self, *args, **kwargs):
        args = list(args)
        for i, x in enumerate(args):
            if isinstance(x, str) and (posiciones is None or i in posiciones):
                args[i] = tr(x)
        for k in claves:
            if isinstance(kwargs.get(k), str):
                kwargs[k] = tr(kwargs[k])
        return original(self, *args, **kwargs)

    nuevo.__name__ = nombre
    setattr(clase, nombre, nuevo)


def _envolver_estatico(clase, nombre):
    original = getattr(clase, nombre)

    def nuevo(*args, **kwargs):
        return original(*[tr(x) if isinstance(x, str) and not x.startswith(("/", "\\")) and ":" not in x[:3]
                          else x for x in args], **kwargs)

    setattr(clase, nombre, staticmethod(nuevo))


def _enganchar_combos(QComboBox):
    """Los ComboBox muestran el texto traducido y guardan el original como dato: así
    currentText(), setCurrentText(), findText() e itemText() siguen usando el castellano."""
    add, ins = QComboBox.addItem, QComboBox.insertItem
    current, set_current = QComboBox.currentText, QComboBox.setCurrentText
    find, item_text = QComboBox.findText, QComboBox.itemText

    def addItem(self, *args):
        if args and isinstance(args[0], str) and len(args) == 1:
            return add(self, tr(args[0]), args[0])
        return add(self, *args)

    def addItems(self, textos):
        for t in textos:
            add(self, tr(t), t)

    def insertItem(self, i, *args):
        if args and isinstance(args[0], str) and len(args) == 1:
            return ins(self, i, tr(args[0]), args[0])
        return ins(self, i, *args)

    def insertItems(self, i, textos):
        for k, t in enumerate(textos):
            ins(self, i + k, tr(t), t)

    def original(self, i):
        d = self.itemData(i)
        return d if isinstance(d, str) else None

    def currentText(self):
        o = original(self, self.currentIndex())
        return o if o is not None else current(self)

    def setCurrentText(self, t):
        i = self.findData(t)
        if i >= 0:
            self.setCurrentIndex(i)
        else:
            set_current(self, t)

    def findText(self, t, *args):
        i = self.findData(t)
        return i if i >= 0 else find(self, t, *args)

    def itemText(self, i):
        o = original(self, i)
        return o if o is not None else item_text(self, i)

    for nombre, f in list(locals().items()):
        if nombre in ("addItem", "addItems", "insertItem", "insertItems", "currentText",
                      "setCurrentText", "findText", "itemText"):
            setattr(QComboBox, nombre, f)


def traducir_ventana(w):
    """Traduce los textos que se pusieron al crear los widgets (QLabel("…"), QPushButton("…"))
    en w y en todos sus hijos. Se llama al mostrar cada ventana o diálogo."""
    from PySide6.QtWidgets import (QAbstractButton, QGroupBox, QLabel, QLineEdit, QPlainTextEdit,
                                   QTabWidget, QWidget)
    for x in [w] + w.findChildren(QWidget):
        if x.property("_tr_hecho"):
            continue
        x.setProperty("_tr_hecho", True)
        if isinstance(x, (QLabel, QAbstractButton)) and x.text():
            x.setText(x.text())                       # setText ya está enganchado: traduce
        if isinstance(x, QGroupBox) and x.title():
            x.setTitle(x.title())
        if isinstance(x, (QLineEdit, QPlainTextEdit)) and x.placeholderText():
            x.setPlaceholderText(x.placeholderText())
        if isinstance(x, QTabWidget):
            for i in range(x.count()):
                x.setTabText(i, tr(x.tabText(i)))
        if x.toolTip():
            x.setToolTip(x.toolTip())
        if x.isWindow() and x.windowTitle():
            x.setWindowTitle(x.windowTitle())


def instalar(codigo: str, app=None):
    """Activa el idioma. Hay que llamarlo antes de crear cualquier ventana."""
    global actual
    actual = codigo if codigo in IDIOMAS else POR_DEFECTO
    if actual == POR_DEFECTO:
        return
    # import explícito (no armado con el nombre) para que PyInstaller lo meta en el .exe
    import traducciones_de
    _cargar({"de": traducciones_de.TEXTOS}[actual])

    from PySide6.QtCore import QLibraryInfo, QLocale, QTranslator
    from PySide6.QtGui import QAction, QPainter
    from PySide6.QtWidgets import (QAbstractButton, QComboBox, QDialog, QFileDialog, QGroupBox, QLabel,
                                   QLineEdit, QMenu, QMessageBox, QPlainTextEdit, QStatusBar,
                                   QTableWidget, QTabWidget, QTextEdit, QWidget)
    import pyqtgraph as pg

    # traducciones propias de Qt (botones Sí/No, diálogo de archivos...)
    if app is not None:
        t = QTranslator(app)
        if t.load(QLocale(actual), "qtbase", "_", QLibraryInfo.path(QLibraryInfo.TranslationsPath)):
            app.installTranslator(t)
            app._traductor_qt = t

    _envolver(QLabel, "setText")
    _envolver(QAbstractButton, "setText")
    _envolver(QGroupBox, "setTitle")
    _envolver(QWidget, "setToolTip")
    _envolver(QWidget, "setWindowTitle")
    _envolver(QLineEdit, "setPlaceholderText")
    _envolver(QPlainTextEdit, "setPlaceholderText")
    _envolver(QTextEdit, "setHtml")
    _envolver(QTabWidget, "addTab")
    _envolver(QTabWidget, "setTabText")
    _envolver(QStatusBar, "showMessage")
    _envolver(QMenu, "addAction")
    _envolver(QAction, "setText")
    _envolver(QTableWidget, "setHorizontalHeaderLabels")
    _envolver(QPainter, "drawText")
    _envolver(QMessageBox, "setText")
    _envolver(QMessageBox, "setInformativeText")
    for f in ("question", "warning", "information", "critical"):
        _envolver_estatico(QMessageBox, f)
    for f in ("getSaveFileName", "getOpenFileName"):
        original = getattr(QFileDialog, f)

        def dialogo(*args, _o=original, **kwargs):
            args = list(args)
            if len(args) > 1:
                args[1] = tr(args[1])                     # título
            if len(args) > 3:
                args[3] = tr(args[3])                     # filtro ("PDF (*.pdf)")
            return _o(*args, **kwargs)
        setattr(QFileDialog, f, staticmethod(dialogo))
    _enganchar_combos(QComboBox)

    # pyqtgraph: títulos de ejes y textos sobre los gráficos
    _envolver(pg.AxisItem, "setLabel", claves=("text",))
    _envolver(pg.PlotItem, "setTitle")
    _envolver(pg.TextItem, "setText")
    _envolver(pg.LabelItem, "setText")
    init_texto = pg.TextItem.__init__

    def texto_init(self, text="", *args, **kwargs):
        init_texto(self, tr(text), *args, **kwargs)
    pg.TextItem.__init__ = texto_init

    # textos puestos en el constructor: se traducen al mostrar cada ventana o diálogo
    for clase, metodo in ((QDialog, "exec"), (QDialog, "show"), (QDialog, "open"), (QWidget, "show")):
        original = getattr(clase, metodo)

        def mostrar(self, *args, _o=original, **kwargs):
            traducir_ventana(self)
            return _o(self, *args, **kwargs)
        setattr(clase, metodo, mostrar)
