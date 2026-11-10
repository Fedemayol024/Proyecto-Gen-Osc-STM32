"""Busca textos que quedaron en castellano con la app en otro idioma.

Abre la app en alemán contra el Nucleo simulado, recorre las pestañas y los diálogos,
hace un barrido de Bode, genera el informe PDF y lista todo texto mostrado que todavía
parezca castellano (palabras como «el», «de», «que», letras ñ/á/é…).

Uso (Linux, sin pantalla):
    python nucleo_simulado.py bode /tmp/reg.txt      # imprime el pty
    python revisar_idioma.py <pty> [de]
Para agregar una traducción, copiar el texto castellano exacto como clave en
app/traducciones_de.py.
"""
import json
import os
import re
import subprocess
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
CARPETA = tempfile.mkdtemp()
os.environ["APPDATA"] = CARPETA
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))

import serial  # noqa: E402
serial.Serial._update_dtr_state = lambda self: None
serial.Serial._update_rts_state = lambda self: None

PTY = sys.argv[1]
IDIOMA = sys.argv[2] if len(sys.argv) > 2 else "de"
os.makedirs(os.path.join(CARPETA, "InstrumentoF767"), exist_ok=True)
with open(os.path.join(CARPETA, "InstrumentoF767", "preferencias.json"), "w") as f:
    json.dump({"placa": "F767", "preguntar": False, "idioma": IDIOMA}, f)

import idioma  # noqa: E402
import main as A  # noqa: E402
import widgets as W  # noqa: E402
from PySide6.QtCore import Qt, QTimer  # noqa: E402
from PySide6.QtWidgets import (QAbstractButton, QApplication, QComboBox, QGroupBox, QLabel,  # noqa: E402
                               QLineEdit, QTabWidget, QWidget)

ESP = re.compile(r"[ñ¿¡áéíóú]|\b(el|la|los|las|del|que|con|para|por|una|es|se|y|sin|hasta|más|muy|al|lo|"
                 r"placa|señal|salida|entrada|canal|frecuencia|medir|medición|punto|puntos|barrido|"
                 r"ganancia|fase|corte|polo|cero|pico|ventana|tiempo|disparo|cuadros)\b", re.I)
IGNORAR = re.compile(r"^[\w\s.,:;/()+\-−–=×·%°±~≈<>|*#'\"«»↻⚙●○◉▶◀…]*$")    # nombres/números sueltos
vistos: dict[str, str] = {}

tr_original = idioma.tr


def tr_espia(texto):
    r = tr_original(texto)
    if isinstance(r, str) and ESP.search(r) and not r.startswith(("/", "C:", "COM")):
        vistos.setdefault(r, texto)
    return r


idioma.tr = tr_espia
A.listar_puertos = lambda: [(PTY, f"{PTY} · Instrumento (USB del Nucleo)")]

app = QApplication(sys.argv)
idioma.instalar(IDIOMA, app)
idioma.tr = tr_espia                       # instalar() no lo pisa, pero por las dudas
app.setStyleSheet(W.estilo())
v = A.Ventana("F767")
v.resize(1500, 900)
v.show()
pasos = []
resto = []


def barrer(raiz):
    """Textos que muestra cada widget (incluidos los que nunca pasaron por tr)."""
    for w in [raiz] + raiz.findChildren(QWidget):
        textos = []
        if isinstance(w, (QLabel, QAbstractButton)):
            textos.append(w.text())
        if isinstance(w, QGroupBox):
            textos.append(w.title())
        if isinstance(w, QLineEdit):
            textos.append(w.placeholderText())
        if isinstance(w, QComboBox):
            textos += [w.itemData(i, Qt.DisplayRole) for i in range(w.count())]
        if isinstance(w, QTabWidget):
            textos += [w.tabText(i) for i in range(w.count())]
        textos += [w.toolTip(), w.windowTitle() if w.isWindow() else ""]
        for t in textos:
            if isinstance(t, str) and t and ESP.search(t):
                vistos.setdefault(t, "(widget)")


def paso(ms, fn):
    pasos.append((ms, fn))


def correr(i=0):
    if i >= len(pasos):
        if pasos is resto:
            terminar()
        return                                      # el Bode sigue solo (esperar_bode)
    ms, fn = pasos[i]

    def f():
        try:
            fn()
        except Exception as e:                      # noqa: BLE001
            print("ERROR en paso", i, repr(e))
        correr(i + 1)
    QTimer.singleShot(ms, f)


def conectar():
    v.actualizar_puertos()
    v.alternar_conexion()


def recorrer_pestanas():
    for i in range(v.tabs.count()):
        v.tabs.setCurrentIndex(i)
        app.processEvents()
    v.tabs.setCurrentIndex(0)


def osciloscopio():
    o = v.tab_osc
    o._autoset()


def dialogos():
    o = v.tab_osc
    for d in [o.__dict__.get("dlg_fft")]:
        if d is not None:
            d.show(); app.processEvents(); barrer(d); d.hide()
    o.abrir_analisis_fft()
    app.processEvents(); barrer(o.dlg_fft)
    from tab_osciloscopio import DialogoExportarImagen
    d = DialogoExportarImagen(v)
    d.show(); app.processEvents(); barrer(d); d.close()
    from panel_dds import DialogoCalDDS
    try:
        d = DialogoCalDDS(v.tab_gen.dds)
        d.show(); app.processEvents(); barrer(d); d.close()
    except TypeError as e:
        print("DialogoCalDDS:", e)
    v._armar_menu_opciones()
    for a in v.menu_opciones.actions():
        if ESP.search(a.text()):
            vistos.setdefault(a.text(), "(menú)")
    # todos los esquemas de la pestaña Placa
    c = v.tab_placa.combo
    for i in range(c.count()):
        c.setCurrentIndex(i)
        v.tab_placa.dib_con.repaint()
    v.tab_placa.dib_placa.repaint() if hasattr(v.tab_placa, "dib_placa") else None


def generador():
    g = v.tab_gen
    for p in g.paneles.values():
        for i in range(p.forma.count()):
            p.forma.setCurrentIndex(i)
        for i in range(p.mod.count()):
            p.mod.setCurrentIndex(i)
        p.forma.setCurrentIndex(0); p.mod.setCurrentIndex(0)
    d = g.dds
    for i in range(d.mod.count()):
        d.mod.setCurrentIndex(i)
        app.processEvents()
    d.mod.setCurrentIndex(0)


def bode():
    b = v.tab_bode
    b.f1.set_valor(100) if hasattr(b.f1, "set_valor") else None
    b.f2.set_valor(20000) if hasattr(b.f2, "set_valor") else None
    b._alternar()


def esperar_bode(n=[0]):
    if v.tab_bode.activo and n[0] < 120:
        n[0] += 1
        QTimer.singleShot(500, esperar_bode)
        return
    b = v.tab_bode
    print("Bode:", len(b.resultados), "puntos, modelo:", b.modelo is not None)
    ruta = os.path.join(CARPETA, "informe.pdf")
    b.generar_informe(ruta, "Prueba RC", "Notas de prueba")
    texto = subprocess.run(["pdftotext", ruta, "-"], capture_output=True, text=True).stdout
    for linea in texto.splitlines():
        if ESP.search(linea):
            vistos.setdefault(linea.strip(), "(PDF)")
    correr_resto()


def herramientas():
    h = v.tab_herr
    h._alternar_f()


def terminar():
    barrer(v)
    v.close()
    utiles = {k: o for k, o in vistos.items() if not IGNORAR.match(k)}
    print(f"\n{len(utiles)} textos en castellano:")
    for k, o in sorted(utiles.items()):
        print(f"  {k!r}" + (f"   <- {o!r}" if o != k else ""))
    app.quit()


def correr_resto():
    global pasos
    pasos = resto
    correr(0)


paso(300, conectar)
paso(2500, recorrer_pestanas)
paso(500, osciloscopio)
paso(3000, generador)
paso(800, dialogos)
paso(800, herramientas)
paso(2500, bode)
paso(1000, esperar_bode)
resto[:] = [(500, lambda: v.tab_osc._unico()), (1500, lambda: None)]
correr(0)
app.exec()
