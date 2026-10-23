"""Pruebas del Bode: largo de las capturas, promedio adaptativo y un punto del barrido
con un RC simulado cuya salida es apenas un par de escalones del ADC (sin placa).

Uso, desde la carpeta del proyecto:
    python -m unittest discover -s tests -v
"""
import cmath
import math
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))

import numpy as np  # noqa: E402

import modelo as M  # noqa: E402

try:
    from PySide6.QtWidgets import QApplication
    HAY_QT = True
except ImportError:      # pragma: no cover
    HAY_QT = False

FS_MAX = 27e6 / 17
FC_RC = 152.8                                   # corte del RC que midió el usuario


def h_rc(f):
    return 1 / (1 + 1j * f / FC_RC)


class TestCapturaBode(unittest.TestCase):
    def test_usa_la_ventana_completa(self):
        for f in (10.0, 152.8, 1e3, 1e4, 1e5):
            with self.subTest(f=f):
                n, fs = M.captura_bode(f, FS_MAX)
                self.assertEqual(n, 8192)

    def test_respeta_muestreo_y_periodos(self):
        for f in (1.0, 10.0, 1e3, 3e4, 1e5):
            with self.subTest(f=f):
                n, fs = M.captura_bode(f, FS_MAX)
                self.assertLessEqual(fs, FS_MAX)
                self.assertGreaterEqual(fs, min(FS_MAX, 50 * f) - 1e-9)
                self.assertGreaterEqual(n / fs * f, 8 - 1e-9)        # al menos 8 períodos

    def test_no_tarda_mas_de_lo_necesario(self):
        n, fs = M.captura_bode(1e3, FS_MAX)
        self.assertLessEqual(n / fs, M.BODE_T_CAPTURA + 1e-9)
        n, fs = M.captura_bode(10.0, FS_MAX)                         # 8 períodos de 10 Hz
        self.assertAlmostEqual(n / fs, 0.8, places=6)


class TestFasor(unittest.TestCase):
    def test_amplitud_fase_y_residuo(self):
        fs, f = 1e5, 1234.5
        t = np.arange(4000) / fs
        ruido = np.random.default_rng(2).normal(0, 0.01, len(t))
        x, r = M.fasor_seno(0.7 * np.sin(2 * np.pi * f * t + 0.4) + 1.2 + ruido, fs, f)
        self.assertAlmostEqual(abs(x), 0.7, delta=1e-3)
        self.assertAlmostEqual(cmath.phase(x), 0.4, delta=2e-3)
        self.assertAlmostEqual(r, 0.01, delta=1e-3)


class TestRepeticiones(unittest.TestCase):
    def test_salida_grande_no_repite(self):
        self.assertEqual(M.repeticiones_bode(0.5, 0.002, 8192, 0.005), 1)

    def test_salida_chica_promedia(self):
        k = M.repeticiones_bode(1.8, 3.0, 8192, 0.005)               # en escalones del ADC
        self.assertTrue(2 <= k <= M.BODE_REP_MAX)

    def test_tope_de_tiempo_por_punto(self):
        self.assertEqual(M.repeticiones_bode(1e-6, 1.0, 8192, 0.8), 2)   # 2 s / 0,8 s
        self.assertEqual(M.repeticiones_bode(1e-6, 1.0, 8192, 0.005), M.BODE_REP_MAX)


@unittest.skipUnless(HAY_QT, "PySide6 no está instalado")
class TestPuntoDelBarrido(unittest.TestCase):
    def setUp(self):
        import main as A
        self._app = QApplication.instance() or QApplication(sys.argv)
        self._tmp = tempfile.TemporaryDirectory()
        self._appdata = os.environ.get("APPDATA")
        os.environ["APPDATA"] = self._tmp.name
        A.listar_puertos = lambda: []
        self.v = A.Ventana()
        self.enviados = []
        self.v.disp.enviar = lambda texto: self.enviados.append(texto) or True
        self.bode = self.v.tab_bode
        for c in (1, 2):
            self.v.tab_osc.canales[c].entrada.setCurrentText(M.MODOS_ENTRADA["DIRECTO"].nombre)

    def tearDown(self):
        self.v.close()
        if self._appdata is None:
            os.environ.pop("APPDATA", None)
        else:
            os.environ["APPDATA"] = self._appdata
        self._tmp.cleanup()

    def _medir(self, f, amp_entrada=1200.0, ruido_lsb=3.0, semilla=5):
        """Corre un barrido de un solo punto y devuelve (resultado, capturas pedidas)."""
        b, rng = self.bode, np.random.default_rng(semilla)
        b.activo, b.frecs, b.idx, b.resultados = True, [f], 0, []
        b.tabla = SimpleNamespace(reposo=2048)
        b._siguiente()
        b.espera.stop()
        capturas = 0
        while b.activo and capturas < 50:
            b._capturar()
            cap = self.enviados[-1].split()
            n, fs = int(cap[1]), float(cap[3])
            t = np.arange(n) / fs
            w = 2 * np.pi * b.f_real * t + rng.uniform(0, 2 * np.pi)   # cada captura arranca donde cae
            h = h_rc(b.f_real)
            ch1 = 2048 + amp_entrada * np.sin(w) + rng.normal(0, ruido_lsb, n)
            ch2 = 2048 + amp_entrada * abs(h) * np.sin(w + cmath.phase(h)) + rng.normal(0, ruido_lsb, n)
            cod = lambda x: np.clip(np.rint(x), 0, 4095).astype(np.uint16)
            b.al_recibir({"n": n, "pre": 0, "fs": fs, "disparado": 0, "ch1": cod(ch1), "ch2": cod(ch2)})
            capturas += 1
        return b.resultados[0], capturas

    def test_rc_a_100khz_con_salida_de_dos_escalones(self):
        (f, g, fase, *_), capturas = self._medir(100e3)
        h = h_rc(f)
        self.assertLess(abs(g - 20 * math.log10(abs(h))), 0.3)                  # teoría: −56,3 dB
        self.assertLess(abs(fase - math.degrees(cmath.phase(h))), 3.0)          # teoría: −89,9°
        self.assertGreater(capturas, 1)                                         # tuvo que promediar

    def test_salida_grande_mide_con_una_sola_captura(self):
        (f, g, fase, *_), capturas = self._medir(FC_RC)
        self.assertEqual(capturas, 1)
        self.assertAlmostEqual(g, -3.01, delta=0.05)
        self.assertAlmostEqual(fase, -45.0, delta=0.5)


if __name__ == "__main__":
    unittest.main()
