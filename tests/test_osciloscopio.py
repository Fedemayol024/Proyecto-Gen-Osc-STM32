"""Pruebas de la pestaña Osciloscopio con un cuadro sintético (sin placa).

La app se levanta sin pantalla (Qt 'offscreen'). Uso, desde la carpeta del proyecto:
    python -m unittest discover -s tests -v
"""
import csv
import os
import sys
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))

import numpy as np  # noqa: E402

try:
    from PySide6.QtWidgets import QApplication, QFileDialog
    HAY_QT = True
except ImportError:      # pragma: no cover
    HAY_QT = False

if HAY_QT:
    import main as A  # noqa: E402
    import modelo as M  # noqa: E402
    import tab_osciloscopio as TO  # noqa: E402

    _app = QApplication.instance() or QApplication(sys.argv)


@unittest.skipUnless(HAY_QT, "PySide6 no está instalado")
class TestPestanaOsciloscopio(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._appdata = os.environ.get("APPDATA")
        os.environ["APPDATA"] = self._tmp.name
        self._guardar = QFileDialog.getSaveFileName
        A.listar_puertos = lambda: []
        self.v = A.Ventana()
        self.osc = self.v.tab_osc
        self.osc.tdiv.setCurrentIndex(TO.TDIVS.index(1e-3))      # 200 kS/s, 2000 puntos por pantalla
        self.osc.pos_disp.setValue(50)
        self.osc.desplaz.setValue(0)

    def tearDown(self):
        QFileDialog.getSaveFileName = self._guardar
        self.v.close()
        if self._appdata is None:
            os.environ.pop("APPDATA", None)
        else:
            os.environ["APPDATA"] = self._appdata
        self._tmp.cleanup()

    def _cuadro(self):
        """CH1: seno de 1 kHz. CH2: ruido. Con el tamaño y el disparo que pide la app."""
        n, pre, fs, *_ = self.osc.parametros_captura()
        t = np.arange(n) / fs
        ch1 = np.rint(2048 + 1000 * np.sin(2 * np.pi * 1000 * (t - (pre / fs)))).astype(np.uint16)
        ch2 = np.random.default_rng(1).integers(0, 4096, n).astype(np.uint16)
        return {"n": n, "pre": pre, "fs": fs, "disparado": 1, "ch1": ch1, "ch2": ch2}

    def _guardar_en(self, ruta):
        QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (str(ruta), ""))

    # --------------------------------------------------------------- captura
    def test_captura_tres_pantallas_en_bases_rapidas(self):
        n, pre, fs, *_ = self.osc.parametros_captura()
        self.assertEqual(n, 3 * 2000)
        self.assertEqual(pre, 1000 + 2000)

    def test_bases_lentas_capturan_una_pantalla(self):
        self.osc.tdiv.setCurrentIndex(TO.TDIVS.index(100e-3))
        n, *_ = self.osc.parametros_captura()
        self.assertEqual(n, 2000)
        self.osc.desplaz.setValue(80)
        self.assertEqual(self.osc.desplazamiento, 0.0)           # se ignora donde no hay datos extra

    # --------------------------------------------------------------- desplazamiento
    def test_ventana_visible_centrada(self):
        self.osc._mostrar(self._cuadro())
        self.assertEqual(self.osc._indices_visibles(self.osc.ultimo), (2000, 4000))

    def test_desplazar_mueve_la_ventana(self):
        self.osc._mostrar(self._cuadro())
        self.osc.desplaz.setValue(50)                            # +5 divisiones
        i0, i1 = self.osc._indices_visibles(self.osc.ultimo)
        self.assertEqual((i0, i1 - i0), (3000, 2000))
        self.osc.desplaz.setValue(-100)                          # -10 div: extremo izquierdo del cuadro
        i0, i1 = self.osc._indices_visibles(self.osc.ultimo)
        self.assertEqual((i0, i1 - i0), (0, 2000))
        self.osc.desplaz.setValue(100)                           # +10 div: extremo derecho del cuadro
        i0, i1 = self.osc._indices_visibles(self.osc.ultimo)
        self.assertEqual((i0, i1), (4000, 6000))

    def test_la_curva_dibuja_solo_lo_visible(self):
        self.osc._mostrar(self._cuadro())
        x, _ = self.osc.curvas[1].getData()
        self.assertEqual(len(x), 2000)
        self.assertGreaterEqual(float(x.min()), -1e-6)
        self.assertLessEqual(float(x.max()), TO.DIV_X + 1e-6)

    # --------------------------------------------------------------- referencias 0 s / 0 V
    def test_lineas_de_cero(self):
        self.osc.canales[1].pos.set_valor(1.5)
        self.osc.desplaz.setValue(20)                            # el 0 s se corre 2 divisiones
        self.osc._cambio()
        self.assertAlmostEqual(float(self.osc.marca_disparo.value()), 5.0 - 2.0)
        self.assertAlmostEqual(float(self.osc.cero_v[1].value()), 1.5)
        self.assertAlmostEqual(float(self.osc.cero_v[2].value()), self.osc.canales[2].pos.valor())

    # --------------------------------------------------------------- exportar CSV
    def test_csv_solo_del_canal_visible(self):
        self.osc._mostrar(self._cuadro())
        self.osc.canales[2].visible.setChecked(False)
        ruta = Path(self._tmp.name) / "uno.csv"
        self._guardar_en(ruta)
        self.osc._exportar_csv()
        with open(ruta, newline="", encoding="utf-8") as f:
            filas = list(csv.reader(f, delimiter=";"))
        self.assertEqual(filas[0], ["tiempo_s", "ch1_V"])
        self.assertEqual(len(filas) - 1, 2000)                   # solo lo que se ve

    def test_csv_de_los_dos_canales_si_ambos_se_ven(self):
        self.osc._mostrar(self._cuadro())
        ruta = Path(self._tmp.name) / "dos.csv"
        self._guardar_en(ruta)
        self.osc._exportar_csv()
        with open(ruta, newline="", encoding="utf-8") as f:
            self.assertEqual(next(csv.reader(f, delimiter=";")), ["tiempo_s", "ch1_V", "ch2_V"])

    def test_csv_exportado_se_carga_como_forma_arbitraria_del_canal_correcto(self):
        """Antes se exportaban los dos canales y la forma arbitraria leía la última columna
        (CH2). Con un solo canal visible, lo que se carga es ese canal."""
        self.osc._mostrar(self._cuadro())
        self.osc.canales[2].visible.setChecked(False)
        ruta = Path(self._tmp.name) / "forma.csv"
        self._guardar_en(ruta)
        self.osc._exportar_csv()
        forma = M.leer_csv_forma(str(ruta))
        i0, i1 = self.osc._indices_visibles(self.osc.ultimo)
        np.testing.assert_allclose(forma, self.osc.ultimo[1][i0:i1], rtol=1e-4, atol=1e-5)

    # --------------------------------------------------------------- tiempo equivalente
    def test_sin_canales_visibles_no_exporta(self):
        self.osc._mostrar(self._cuadro())
        for c in (1, 2):
            self.osc.canales[c].visible.setChecked(False)
        ruta = Path(self._tmp.name) / "nada.csv"
        self._guardar_en(ruta)
        self.osc._exportar_csv()
        self.assertFalse(ruta.exists())


if __name__ == "__main__":
    unittest.main()
