"""Idioma de la interfaz (castellano / alemán).

Los enganches del alemán cambian clases de Qt para todo el proceso, así que las pruebas
con el alemán activo corren en un proceso aparte (no afectan a las demás pruebas)."""
import os
import re
import subprocess
import sys
import textwrap
import unittest

APP = os.path.join(os.path.dirname(__file__), "..", "app")
sys.path.insert(0, APP)

import idioma  # noqa: E402
import traducciones_de as T  # noqa: E402


def correr(codigo: str) -> str:
    entorno = dict(os.environ, QT_QPA_PLATFORM="offscreen", PYTHONPATH=APP)
    r = subprocess.run([sys.executable, "-c", textwrap.dedent(codigo)], capture_output=True, text=True,
                       env=entorno, timeout=120, cwd=APP)
    if r.returncode != 0:
        raise AssertionError(r.stdout + r.stderr)
    return r.stdout


class TestTabla(unittest.TestCase):
    def test_castellano_no_toca_nada(self):
        self.assertEqual(idioma.actual, "es")
        self.assertEqual(idioma.tr("Conectar"), "Conectar")

    def test_plantillas_con_los_mismos_huecos(self):
        for es, de in T.TEXTOS.items():
            if "{0}" not in de:
                self.assertEqual(es.count("{}"), de.count("{}"), es)

    def test_traducciones_compuestas(self):
        try:
            idioma._cargar(T.TEXTOS)
            idioma.actual = "de"
            casos = {
                "Punto 3 de 41: 1 kHz · AD9833, submuestreando a 1,48 MS/s":
                    "Punkt 3 von 41: 1 kHz · AD9833, Unterabtastung mit 1,48 MS/s",
                "Pasabajos de 1er orden": "Tiefpass 1. Ordnung",
                "• Cero en 12 kHz": "• Nullstelle bei 12 kHz",
                "1280×720   (todo más grande · 150 %)": "1280×720   (alles größer · 150 %)",
                "<b>Pasabanda / resonancia</b><br>Pico de -4,3 dB en 100 kHz":
                    "<b>Bandpass / Resonanz</b><br>Maximum von -4,3 dB bei 100 kHz",
                "1,234 V": "1,234 V",
            }
            for es, de in casos.items():
                self.assertEqual(idioma.tr(es), de)
        finally:
            idioma.actual = "es"
            idioma._cache.clear()


class TestAleman(unittest.TestCase):
    def test_widgets_y_combos(self):
        salida = correr("""
            from PySide6.QtWidgets import QApplication, QComboBox, QLabel, QPushButton, QWidget, QVBoxLayout
            import idioma
            app = QApplication([])
            idioma.instalar("de", app)
            c = QComboBox(); c.addItems(["Senoidal", "Cuadrada"])
            c.setCurrentText("Cuadrada")
            print(c.itemData(0, 0), c.currentText(), c.currentIndex(), c.findText("Senoidal"))
            l = QLabel(); l.setText("Conectar")
            w = QWidget(); lay = QVBoxLayout(w); b = QPushButton("Cancelar"); lay.addWidget(b)
            w.show()
            print(l.text(), b.text())
        """).splitlines()
        self.assertEqual(salida[0].split(), ["Sinus", "Cuadrada", "1", "0"])
        self.assertEqual(salida[1].strip(), "Verbinden Abbrechen")

    def test_ventana_completa_en_aleman(self):
        salida = correr("""
            import json, os, tempfile
            d = tempfile.mkdtemp(); os.environ["APPDATA"] = d
            os.makedirs(d + "/InstrumentoF767")
            json.dump({"placa": "F767", "preguntar": False, "idioma": "de"},
                      open(d + "/InstrumentoF767/preferencias.json", "w"))
            from PySide6.QtWidgets import QApplication
            import idioma, main as A, modelo as M, widgets as W
            app = QApplication([])
            idioma.instalar(M.idioma_guardado(), app)
            A.listar_puertos = lambda: []
            v = A.Ventana("F767"); v.show(); app.processEvents()
            print("|".join(v.tabs.tabText(i) for i in range(v.tabs.count())))
            print(v.tab_osc.fuente.currentText(), v.tab_osc.flanco.currentText())
            v.tab_osc.flanco.setCurrentText("Bajada")
            print(v.tab_osc.parametros_captura()[5])
            v.close()
        """).strip().splitlines()
        self.assertEqual(salida[0], "Oszilloskop|Generator|Bode|Frequenzzähler und PWM|Kalibrierung|Platine")
        self.assertEqual(salida[1], "CH1 Subida")            # la lógica sigue en castellano
        self.assertEqual(salida[2], "1")                     # flanco de bajada

    def test_idioma_guardado(self):
        salida = correr("""
            import os, tempfile
            os.environ["APPDATA"] = tempfile.mkdtemp()
            import modelo as M
            print(M.idioma_guardado()); M.guardar_idioma("de"); print(M.idioma_guardado())
        """).split()
        self.assertEqual(salida, ["es", "de"])


if __name__ == "__main__":
    unittest.main()
