"""Pruebas del modo de tiempo equivalente (plegado por fase) con señales simuladas.

La señal es una onda cuadrada de 1 Vpp pasada por un filtro de un polo en 4 MHz (como el
frontal analógico), cuantizada a 12 bits con 1,5 LSB de ruido y muestreada como la placa
(fs = 216 MHz / arr). Uso: python -m unittest discover -s tests -v
"""
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))
import modelo as M  # noqa: E402

N, BINS, FS_MAX = 8192, 256, 27e6 / 17          # ventana máxima y fs máxima del ADC del firmware


def onda(t, f, fc=4e6):
    y = np.zeros_like(t)
    for k in range(1, 40, 2):
        y += (4 / (np.pi * k)) / np.sqrt(1 + (k * f / fc) ** 2) * np.sin(2 * np.pi * k * f * t - np.arctan(k * f / fc))
    return 0.5 * y


def muestrear(f, arr, semilla=1, ruido_lsb=1.5, fm=None):
    """Captura simulada. 'fm' = (desvío relativo, frecuencia de modulación) para una señal inestable."""
    rng = np.random.default_rng(semilla)
    fs = M.fs_para_arr(arr)
    t = np.arange(N) / fs
    if fm:
        dev, fmod = fm
        # señal de frecuencia instantánea f·(1 + dev·sen(2π·fmod·t))
        v = onda(t + dev * np.sin(2 * np.pi * fmod * t) / (2 * np.pi * fmod), f)
    else:
        v = onda(t, f)
    cod = np.clip(np.rint((v + 1.65) / 3.3 * 4095 + rng.normal(0, ruido_lsb, N)), 0, 4095)
    return fs, cod / 4095 * 3.3 - 1.65


def error_vs_verdad(perfil, f_real, f_est):
    centros = (np.arange(len(perfil)) + 0.5) / len(perfil) / f_est
    return float(np.sqrt(np.mean((perfil - onda(centros, f_real)) ** 2)))


class TestEleccionDeArr(unittest.TestCase):
    def test_respeta_la_fs_maxima(self):
        arr, _ = M.elegir_arr(1.0e6, FS_MAX)
        self.assertLessEqual(M.fs_para_arr(arr), FS_MAX)

    def test_evita_relaciones_con_pocas_fases(self):
        f = 1.0e6                                  # 'redonda': con arr=144 la relación es 3/2
        arr, ocupados = M.elegir_arr(f, FS_MAX)
        self.assertNotEqual(arr, 144)
        malo = M._casilleros_ocupados(f, 144, N, BINS, M.TCLK_TIMER)
        self.assertLessEqual(malo, 5)
        self.assertGreater(ocupados, 150)


class TestFrecuencia(unittest.TestCase):
    def test_refina_con_menos_de_un_ppm(self):
        f = 1.2345678e6 * (1 + 3e-6)
        fs, v = muestrear(f, 137)
        f_est = M.refinar_frecuencia(v, fs, f * (1 + 1.5e-4))     # el frecuencímetro se equivoca 150 ppm
        self.assertLess(abs(f_est - f) / f, 1e-6)


class TestPlegado(unittest.TestCase):
    def _plegar(self, f, arr, **kw):
        fs, v = muestrear(f, arr, **kw)
        f_est = M.refinar_frecuencia(v, fs, f * (1 + 1e-4))
        perfil, cuenta = M.plegar_por_fase(v, fs, f_est, BINS)
        return v, fs, f_est, perfil, cuenta

    def test_reconstruye_senales_por_encima_de_nyquist(self):
        for f in (0.6e6, 1.2345678e6, 2.5e6):
            with self.subTest(f=f):
                f_real = f * (1 + 4e-6)
                arr, _ = M.elegir_arr(f_real, FS_MAX)
                _, _, f_est, perfil, _ = self._plegar(f_real, arr)
                self.assertLess(error_vs_verdad(perfil, f_real, f_est), 0.003)      # < 3 mV sobre 1 Vpp

    def test_bien_elegido_funciona_y_mal_elegido_falla(self):
        f = 1.0e6                                  # exacta: peor caso, reloj común con el muestreo
        arr_bueno, _ = M.elegir_arr(f, FS_MAX)
        _, _, f_est, perfil, _ = self._plegar(f, arr_bueno)
        self.assertLess(error_vs_verdad(perfil, f, f_est), 0.02)
        _, _, f_est, perfil, _ = self._plegar(f, 144)
        self.assertGreater(error_vs_verdad(perfil, f, f_est), 0.1)

    def test_el_modo_normal_no_reconoce_la_senal(self):
        """Lo que se ve hoy con puntos unidos con rectas, para tener la comparación."""
        f = 1.2345678e6
        fs, v = muestrear(f, 137)
        tf = np.linspace(0, 3 / f, 600)
        crudo = float(np.sqrt(np.mean((np.interp(tf, np.arange(N) / fs, v) - onda(tf, f)) ** 2)))
        self.assertGreater(crudo, 0.2)

    def test_cuenta_suma_todas_las_muestras(self):
        _, _, _, _, cuenta = self._plegar(1.2345678e6, 137)
        self.assertEqual(int(cuenta.sum()), N)

    def test_senal_sin_muestras_da_error(self):
        with self.assertRaises(ValueError):
            M.plegar_por_fase(np.array([]), 1e6, 1e5, 16)


class TestCalidad(unittest.TestCase):
    def test_periodica_da_solo_el_ruido_del_adc(self):
        f = 1.2345678e6
        fs, v = muestrear(f, 137)
        f_est = M.refinar_frecuencia(v, fs, f * (1 + 1e-4))
        self.assertLess(M.calidad_plegado(v, fs, f_est, BINS), 0.003)

    def test_senal_inestable_se_detecta(self):
        f = 1.2345678e6
        fs, v = muestrear(f, 137, fm=(0.002, 200.0))      # frecuencia modulada: no es repetitiva
        f_est = M.refinar_frecuencia(v, fs, f * (1 + 1e-4))
        self.assertGreater(M.calidad_plegado(v, fs, f_est, BINS), 0.03)


class TestCuadroEquivalente(unittest.TestCase):
    def test_umbral(self):
        self.assertAlmostEqual(M.umbral_repetitivo(0.0008, 1.0), 0.024)

    def test_teselar_da_un_cuadro_con_formato_de_captura(self):
        perfil = np.arange(256, dtype=float)
        c = M.teselar_perfiles({1: perfil}, 1e6, 1e-6, 10, 50)     # 10 períodos por pantalla
        n_pant = 2560
        self.assertAlmostEqual(c["fs"], 256e6)
        self.assertEqual(c["n"], 3 * n_pant)
        self.assertEqual(c["pre"], 1280 + n_pant)
        self.assertEqual(c[1][c["pre"]], 0.0)                      # el 0 s cae en el primer punto del perfil
        self.assertEqual(c[1][c["pre"] + 5], 5.0)
        self.assertEqual(c[1][c["pre"] + 256], 0.0)                # y se repite cada período

    def test_teselar_rechaza_demasiados_periodos(self):
        with self.assertRaises(ValueError):
            M.teselar_perfiles({1: np.zeros(256)}, 1e6, 1e-3, 10, 50)

    def test_dos_canales_conservan_la_fase(self):
        f, arr = 1.2345678e6, 137
        fs = M.fs_para_arr(arr)
        t = np.arange(N) / fs
        v1, v2 = onda(t, f), onda(t - 0.25 / f, f)                 # CH2 atrasado 90°
        res = M.plegar_captura({1: v1, 2: v2}, fs, f * (1 + 1e-4), ref=1)
        a, b = np.fft.rfft(res["perfiles"][1])[1], np.fft.rfft(res["perfiles"][2])[1]
        desfase = (np.angle(b) - np.angle(a) + np.pi) % (2 * np.pi) - np.pi
        self.assertAlmostEqual(float(desfase), -np.pi / 2, delta=0.05)
        self.assertLess(abs(res["f"] - f) / f, 1e-6)


class TestAlineacion(unittest.TestCase):
    def test_arranca_en_el_flanco_ascendente(self):
        x = np.sin(2 * np.pi * (np.arange(256) + 40.3) / 256)
        rot, s = M.alinear_a_flanco(x)
        media = x.mean()
        self.assertGreater(rot[0], media)
        self.assertLessEqual(rot[-1], media)
        self.assertTrue(0 <= s < 256)

    def test_mismo_desplazamiento_conserva_la_fase_entre_canales(self):
        t = (np.arange(256) + 17.0) / 256
        a, b = np.sin(2 * np.pi * t), np.sin(2 * np.pi * t - 0.5)      # b atrasada 0,5 rad
        ra, s = M.alinear_a_flanco(a)
        rb = np.roll(b, -s)
        desfase = np.angle(np.fft.rfft(rb)[1]) - np.angle(np.fft.rfft(ra)[1])
        self.assertAlmostEqual(float((desfase + np.pi) % (2 * np.pi) - np.pi), -0.5, delta=0.02)


if __name__ == "__main__":
    unittest.main()
