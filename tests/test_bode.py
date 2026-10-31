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


class TestBodeSubmuestreo(unittest.TestCase):
    """Bode con el AD9833: por encima de Nyquist se mide submuestreando."""

    def test_alias_con_signo(self):
        self.assertAlmostEqual(M.alias(1e3, 1e6), 1e3)
        self.assertAlmostEqual(M.alias(1.25e6, 1e6), 0.25e6)
        self.assertAlmostEqual(M.alias(0.75e6, 1e6), -0.25e6)     # llega dado vuelta
        self.assertAlmostEqual(M.alias(3.3e6, 1.3e6), -0.6e6)       # 3,3 − 3·1,3 = −0,6 MHz
        for f in np.linspace(1e3, 10e6, 97):
            a = M.alias(f, 1.5e6)
            self.assertTrue(-0.75e6 < a <= 0.75e6)
            self.assertAlmostEqual(((f - a) / 1.5e6) % 1, 0, places=6)

    def test_elige_fs_con_el_alias_cerca_de_un_cuarto(self):
        for f in (700e3, 1e6, 2.2e6, 5e6, 9.9e6):
            with self.subTest(f=f):
                fs = M.fs_submuestreo(f, FS_MAX)
                self.assertLessEqual(fs, FS_MAX)
                self.assertGreaterEqual(fs, FS_MAX * 0.5)
                self.assertAlmostEqual(abs(M.alias(f, fs)) / fs, 0.25, delta=0.02)

    def test_directo_hasta_nyquist_y_submuestreo_arriba(self):
        n, fs, sub = M.captura_bode_dds(100e3, FS_MAX)
        self.assertFalse(sub)
        self.assertEqual(fs, FS_MAX)
        n, fs, sub = M.captura_bode_dds(2e6, FS_MAX)
        self.assertTrue(sub)
        self.assertEqual(n, 8192)

    def test_estima_la_frecuencia_de_los_datos(self):
        fs, n = 1.4e6, 8192
        t = np.arange(n) / fs
        f = 351_234.5
        v = 1 + 0.5 * np.sin(2 * np.pi * f * t + 1) + np.random.default_rng(2).normal(0, 0.01, n)
        self.assertAlmostEqual(M.estimar_frecuencia(v, fs, 351_100), f, delta=0.5)

    def test_rc_hasta_mhz_con_cristal_desviado(self):
        rng = np.random.default_rng(0)
        for f in (1e3, 300e3, 700e3, 1.5e6, 3e6, 5e6, 9e6):
            with self.subTest(f=f):
                n, fs, _ = M.captura_bode_dds(f, FS_MAX)
                f_real = f * (1 + 20e-6)                 # el AD9833 sale corrido 20 ppm
                t = np.arange(n) / fs + rng.uniform(0, 1)
                h = 1 / (1 + 1j * f_real / 100e3)
                v1 = 2.0 + 0.9 * np.sin(2 * np.pi * f_real * t + 0.4) + rng.normal(0, 0.004, n)
                v2 = 1.0 + 0.9 * abs(h) * np.sin(2 * np.pi * f_real * t + 0.4 + cmath.phase(h)) \
                    + rng.normal(0, 0.004, n)
                v1 = np.round(v1 / 3.3 * 4095) * 3.3 / 4095   # cuantización del ADC
                v2 = np.round(v2 / 3.3 * 4095) * 3.3 / 4095
                hm, a1, _, _ = M.respuesta_bode(v1, v2, fs, f)
                self.assertAlmostEqual(a1, 0.9, delta=0.01)
                self.assertAlmostEqual(20 * math.log10(abs(hm)), 20 * math.log10(abs(h)), delta=0.1)
                self.assertAlmostEqual(math.degrees(cmath.phase(hm / h)), 0, delta=1.0)


class TestModeloBode(unittest.TestCase):
    """Ajuste de polos y ceros a la curva medida y descripción de la respuesta."""

    F = np.logspace(1, math.log10(5e6), 230)

    def _medir(self, h, semilla=1):
        rng = np.random.default_rng(semilla)
        return h * np.exp(rng.normal(0, 0.003, len(h)) + 1j * np.radians(rng.normal(0, 0.3, len(h))))

    def _analizar(self, h):
        m = M.mejor_modelo_bode(self.F, self._medir(h))
        self.assertIsNotNone(m)
        return m, M.analizar_modelo_bode(m, self.F)

    def test_rc_con_piso_de_acople(self):
        s = 2j * np.pi * self.F
        m, a = self._analizar(1 / (1 + s / (2 * np.pi * 3193)) + 10 ** (-55 / 20))
        self.assertEqual(a["tipo"], "Pasabajos de 1er orden")
        self.assertAlmostEqual(a["f3db"][0], 3193, delta=30)
        self.assertIsNotNone(a["piso"])                     # el acople se reconoce como tal
        self.assertLess(m.error_db, 0.1)

    def test_rl_pasaaltos_con_dcr_y_autorresonancia(self):
        s = 2j * np.pi * self.F
        L, rdc, r = 1.06e-3, 27, 220
        cp = 1 / ((2 * np.pi * 1.8e6) ** 2 * L)
        zl = (rdc + s * L) / (1 + (rdc + s * L) * s * cp)
        m, a = self._analizar(zl / (r + zl))
        self.assertIn("Pasaaltos con pérdida", a["tipo"])
        ceros = sorted(abs(z) / 2 / np.pi for z in m.ceros)
        polos = sorted(abs(p) / 2 / np.pi for p in m.polos)
        self.assertAlmostEqual(ceros[0], rdc / (2 * np.pi * L), delta=100)           # 4,05 kHz
        self.assertAlmostEqual(polos[0], (r + rdc) / (2 * np.pi * L), delta=800)     # 37 kHz
        self.assertTrue(any("-19," in d for d in a["detalles"]))                     # DCR

    def test_escalon_con_meseta_y_resonancia_de_protoboard(self):
        """Lo que midió el usuario: meseta de −19 dB, subida, meseta cerca de −6 dB y otra
        subida en MHz. Antes el ajuste se quedaba con un modelo simple, descartaba toda la
        subida y el corte salía corrido; ahora usa orden 3 y mide desde la meseta."""
        f = np.logspace(1, 7, 241)
        s = 2j * np.pi * f
        w = 2 * np.pi * 14e6
        h = 10 ** (-19.3 / 20) * (1 + s / (2 * np.pi * 6e3)) / (1 + s / (2 * np.pi * 27.6e3)) \
            * (1 + s / w / 1.2 + (s / w) ** 2)
        m = M.mejor_modelo_bode(f, self._medir(h))
        a = M.analizar_modelo_bode(m, f)
        self.assertGreater(m.usados.mean(), 0.95)           # no tira la subida
        self.assertLess(m.error_db, 0.1)
        self.assertIn("Pasaaltos con pérdida", a["tipo"])
        self.assertAlmostEqual(a["ref_db"], -6.07, delta=0.3)                    # la meseta, no el pico
        self.assertAlmostEqual(a["f3db"][0], 26.2e3, delta=1.5e3)

    def test_rl_pasabajos_con_autorresonancia(self):
        s = 2j * np.pi * self.F
        L, rdc, r = 1.06e-3, 27, 220
        cp = 1 / ((2 * np.pi * 1.8e6) ** 2 * L)
        zl = (rdc + s * L) / (1 + (rdc + s * L) * s * cp)
        _, a = self._analizar(r / (r + zl))
        self.assertEqual(a["tipo"], "Pasabajos de 1er orden")
        self.assertTrue(any("autorresonancia en 1,8 MHz" in d for d in a["detalles"]))

    def test_rlc_pasabanda(self):
        s = 2j * np.pi * self.F
        w0, q = 2 * np.pi * 10e3, 5
        m, a = self._analizar((s * w0 / q) / (s ** 2 + s * w0 / q + w0 ** 2))
        self.assertEqual(a["tipo"], "Pasabanda / resonancia")
        self.assertAlmostEqual(a["f3db"][0], 9050, delta=100)
        self.assertAlmostEqual(a["f3db"][1], 11050, delta=100)
        self.assertTrue(any("Q = 5,0" in d or "Q = 4,9" in d for d in a["detalles"]))

    def test_segundo_orden_con_acople_no_inventa_un_rechazo(self):
        s = 2j * np.pi * self.F
        w0 = 2 * np.pi * 20e3
        _, a = self._analizar(w0 ** 2 / (s ** 2 + s * w0 * math.sqrt(2) + w0 ** 2) + 10 ** (-55 / 20))
        self.assertEqual(a["tipo"], "Pasabajos de 2º orden")
        self.assertFalse(any("Rechazo" in d for d in a["detalles"]))
        self.assertAlmostEqual(a["f3db"][0], 20e3, delta=300)

    def test_ignora_puntos_sueltos(self):
        s = 2j * np.pi * self.F
        h = self._medir(1 / (1 + s / (2 * np.pi * 5e3)))
        h[[50, 120, 200]] *= 3                                  # tres puntos malos
        m = M.mejor_modelo_bode(self.F, h)
        a = M.analizar_modelo_bode(m, self.F)
        self.assertAlmostEqual(a["f3db"][0], 5e3, delta=60)
        self.assertEqual(int((~m.usados).sum()), 3)


@unittest.skipUnless(HAY_QT, "PySide6 no está instalado")
class TestInformeBode(unittest.TestCase):
    """El informe PDF se genera desde la pestaña Bode, con y sin modelo."""

    def setUp(self):
        import main as A
        self._app = QApplication.instance() or QApplication(sys.argv)
        self._tmp = tempfile.TemporaryDirectory()
        self._appdata = os.environ.get("APPDATA")
        os.environ["APPDATA"] = self._tmp.name
        A.listar_puertos = lambda: []
        self.v = A.Ventana()
        self.v.disp.enviar = lambda texto: True
        self.bode = self.v.tab_bode

    def tearDown(self):
        self.v.close()
        if self._appdata is None:
            os.environ.pop("APPDATA", None)
        else:
            os.environ["APPDATA"] = self._appdata
        self._tmp.cleanup()

    def _barrido(self, h, f):
        b = self.bode
        b.meta = b._datos_del_ensayo(f[0], f[-1], 10, len(f))
        b.resultados = [(fi, 20 * math.log10(abs(hi)), math.degrees(cmath.phase(hi)), 2.0, 2 * abs(hi))
                        for fi, hi in zip(f, h)]
        b._resumen()

    def _paginas(self, ruta):
        datos = Path(ruta).read_bytes()
        self.assertTrue(datos.startswith(b"%PDF"))
        return datos.count(b"/Type /Page\n") + datos.count(b"/Type /Page\r") + \
            datos.count(b"/Type /Page ") + datos.count(b"/Type /Page>")

    def test_rl_con_modelo(self):
        f = np.logspace(2, 6, 41)
        s = 2j * np.pi * f
        h = (25 + s * 1.06e-3) / (245 + s * 1.06e-3)
        self._barrido(h, f)
        self.assertIsNotNone(self.bode.modelo)
        ruta = os.path.join(self._tmp.name, "rl.pdf")
        self.assertTrue(self.bode.generar_informe(ruta, "RL de prueba", "notas\ncon dos líneas"))
        self.assertGreaterEqual(self._paginas(ruta), 3)

    def test_pocos_puntos_sin_modelo(self):
        f = np.array([100.0, 1e3, 1e4])
        self._barrido(h_rc(f), f)
        self.assertIsNone(self.bode.modelo)
        ruta = os.path.join(self._tmp.name, "rc.pdf")
        self.assertTrue(self.bode.generar_informe(ruta))
        self.assertGreaterEqual(self._paginas(ruta), 1)

    def test_nombre_de_archivo_desde_el_titulo(self):
        from tab_bode import nombre_archivo
        self.assertEqual(nombre_archivo("RC pasabajos "), "RC pasabajos")
        self.assertEqual(nombre_archivo("RC 4k7/103: ¿corte?"), "RC 4k7 103 ¿corte")
        self.assertEqual(nombre_archivo("RL · 1 mH + 220 Ω"), "RL · 1 mH + 220 Ω")
        self.assertEqual(nombre_archivo("  ... "), "")

    def test_barrido_nuevo_borra_titulo_y_notas(self):
        b = self.bode
        b._ultimo_titulo, b._ultimas_notas = "RC viejo", "notas viejas"
        from unittest import mock
        with mock.patch.object(type(b.v.disp), "esta_conectado", new_callable=mock.PropertyMock,
                               return_value=True):
            b._alternar()                                   # arranca un barrido nuevo
            if b.activo:
                b._terminar("prueba")
        self.assertEqual((b._ultimo_titulo, b._ultimas_notas), ("", ""))

    def test_carpeta_inexistente_no_rompe(self):
        f = np.logspace(2, 4, 9)
        self._barrido(h_rc(f), f)
        ruta = os.path.join(self._tmp.name, "no", "existe", "x.pdf")
        self.assertFalse(self.bode.generar_informe(ruta))


if __name__ == "__main__":
    unittest.main()
