"""Pruebas unitarias de app/modelo.py (sin placa, sin pantalla, sin Qt).

Uso, desde la carpeta del proyecto:
    python -m unittest discover -s tests -v
"""
import json
import math
import os
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))
import modelo as M  # noqa: E402


class TestRecta(unittest.TestCase):
    def test_ida_y_vuelta(self):
        r = M.Recta(0, -5.0, 4095, 5.0)
        for c in (0, 1000, 2048, 4095):
            self.assertAlmostEqual(float(r.codigo(r.volt(c))), c, places=6)

    def test_invalida_si_los_codigos_coinciden(self):
        self.assertFalse(M.Recta(100, 1.0, 100, 2.0).valida())

    def test_desde_dict_descarta_basura(self):
        self.assertIsNone(M.Recta.desde_dict({}))
        self.assertIsNone(M.Recta.desde_dict({"codigo_a": 1, "volt_a": 0, "codigo_b": 1, "volt_b": 1}))
        self.assertIsNone(M.Recta.desde_dict({"codigo_a": "x", "volt_a": 0, "codigo_b": 1, "volt_b": 1}))


class TestFormatoNumeros(unittest.TestCase):
    def test_leer_si(self):
        self.assertAlmostEqual(M.leer_si("2k"), 2000.0)
        self.assertAlmostEqual(M.leer_si("2,5 kHz"), 2500.0)
        self.assertAlmostEqual(M.leer_si("20 ms"), 0.02)
        self.assertAlmostEqual(M.leer_si("−5"), -5.0)

    def test_leer_si_rechaza_lo_invalido(self):
        for texto in ("", " V", "abc", "1e400", "nan"):
            with self.assertRaises(ValueError, msg=repr(texto)):
                M.leer_si(texto)

    def test_si(self):
        self.assertEqual(M.si(1500, "Hz"), "1,5 kHz")
        self.assertEqual(M.si(0.001, "V"), "1 mV")
        self.assertEqual(M.si(0, "V"), "0 V")
        self.assertEqual(M.si(None, "V"), "—")
        self.assertEqual(M.si(float("nan"), "V"), "—")


class TestMediciones(unittest.TestCase):
    FS = 100_000.0

    def _seno(self, f, n=2000, amp=1.0, offset=0.0):
        t = np.arange(n) / self.FS
        return offset + amp * np.sin(2 * np.pi * f * t)

    def test_seno(self):
        m = M.medir(self._seno(1000), self.FS)
        self.assertAlmostEqual(m["frec"], 1000.0, delta=5)
        self.assertAlmostEqual(m["vpp"], 2.0, delta=0.01)
        self.assertAlmostEqual(m["rms"], 1 / math.sqrt(2), delta=0.01)
        self.assertAlmostEqual(m["ciclo"], 50.0, delta=2)

    def test_offset(self):
        m = M.medir(self._seno(1000, offset=0.5), self.FS)
        self.assertAlmostEqual(m["media"], 0.5, delta=0.01)

    def test_cuadrada_ciclo_util(self):
        x = (np.arange(2000) % 100) / 100.0
        v = np.where(x < 0.25, 1.0, -1.0)
        m = M.medir(v, self.FS)
        self.assertAlmostEqual(m["ciclo"], 25.0, delta=2)
        self.assertAlmostEqual(m["frec"], 1000.0, delta=2)

    def test_senal_plana_no_da_frecuencia(self):
        m = M.medir(np.full(500, 1.0), self.FS)
        self.assertIsNone(m["frec"])
        self.assertAlmostEqual(m["vpp"], 0.0)

    def test_muy_pocas_muestras(self):
        self.assertEqual(M.medir(np.array([1.0, 2.0]), self.FS), {})

    def test_fs_cero_no_explota(self):
        m = M.medir(self._seno(1000), 0.0)
        self.assertIsNone(m["frec"])


class TestEspectro(unittest.TestCase):
    def test_pico_y_nivel(self):
        n, fs, f0 = 4096, 32768.0, 1024.0          # f0 cae justo en un bin
        v = np.sin(2 * np.pi * f0 * np.arange(n) / fs)
        f, db = M.espectro(v, fs)
        k = int(np.argmax(db[1:])) + 1
        self.assertAlmostEqual(float(f[k]), f0, delta=1e-6)
        self.assertAlmostEqual(float(db[k]), 20 * math.log10(1 / math.sqrt(2)), delta=0.1)


class TestSuavizar(unittest.TestCase):
    def test_conserva_la_longitud(self):
        v = np.arange(100, dtype=float)
        for w in (1, 2, 3, 4, 8, 16, 32):
            self.assertEqual(len(M.suavizar(v, w)), len(v), msg=f"ventana {w}")

    def test_los_bordes_no_caen_hacia_cero(self):
        v = np.full(64, 1.0)
        for w in (4, 8, 16, 32):
            s = M.suavizar(v, w)
            np.testing.assert_allclose(s, 1.0, atol=1e-12, err_msg=f"ventana {w}")

    def test_ventana_uno_o_senal_corta_no_cambia_nada(self):
        v = np.array([1.0, 5.0, 2.0])
        np.testing.assert_array_equal(M.suavizar(v, 1), v)
        np.testing.assert_array_equal(M.suavizar(v, 8), v)

    def test_promedia_de_verdad(self):
        v = np.array([0.0, 0.0, 4.0, 0.0, 0.0, 0.0, 0.0, 0.0])
        s = M.suavizar(v, 4)
        self.assertAlmostEqual(float(s.sum()), 4.0, places=9)   # un pulso solo se reparte


class TestTablaGenerador(unittest.TestCase):
    def setUp(self):
        self.cal = M.MODOS_SALIDA["PLACA"].diseno

    def test_seno_dentro_de_rango(self):
        t = M.armar_tabla(M.CanalGen(vpp=2.0, offset=0.0), self.cal)
        self.assertEqual(t.codigos.shape, (M.TABLA_N,))
        self.assertEqual(t.codigos.dtype, np.uint16)
        self.assertLessEqual(int(t.codigos.max()), M.DAC_MAX)
        self.assertFalse(t.recortada)

    def test_amplitud_excesiva_se_recorta_y_avisa(self):
        t = M.armar_tabla(M.CanalGen(vpp=30.0), self.cal)
        self.assertTrue(t.recortada)
        self.assertLessEqual(int(t.codigos.max()), M.DAC_MAX)
        self.assertGreaterEqual(int(t.codigos.min()), 0)

    def test_continua_es_constante(self):
        t = M.armar_tabla(M.CanalGen(forma="Continua", offset=1.0), self.cal)
        self.assertEqual(int(t.codigos.min()), int(t.codigos.max()))


class TestCsv(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self._tmp.cleanup()

    def _leer(self, texto):
        ruta = Path(self._tmp.name) / "forma.csv"
        ruta.write_text(texto, encoding="utf-8")
        return list(M.leer_csv_forma(str(ruta)))

    def test_coma_decimal_para_excel_en_espanol(self):
        self.assertEqual(M.num_csv(-0.0352058), "-0,0352058")
        self.assertEqual(M.num_csv(1.5e-7, ".9g"), "1,5e-07")

    def test_lee_lo_que_exporta_la_app(self):
        texto = "tiempo_s;ch1_V;ch2_V\n" + "".join(
            f"{M.num_csv(k * 1e-6, '.9g')};{M.num_csv(0.5)};{M.num_csv(-k / 4)}\n" for k in range(3))
        self.assertEqual(self._leer(texto), [0.0, -0.25, -0.5])

    def test_sigue_leyendo_csv_con_punto_decimal(self):
        self.assertEqual(self._leer("t;v\n0;1.5\n1;-2.25\n"), [1.5, -2.25])        # exportados antes
        self.assertEqual(self._leer("t,v\n0,1.5\n1,-2.25\n"), [1.5, -2.25])        # CSV en inglés
        self.assertEqual(self._leer("0\t1,5\n1\t-2,25\n"), [1.5, -2.25])           # tabulado
        self.assertEqual(self._leer("1.5\n-2.25\n"), [1.5, -2.25])                 # una columna


class TestConfig(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._appdata = os.environ.get("APPDATA")
        os.environ["APPDATA"] = self._tmp.name

    def tearDown(self):
        if self._appdata is None:
            os.environ.pop("APPDATA", None)
        else:
            os.environ["APPDATA"] = self._appdata
        self._tmp.cleanup()

    def test_sin_archivo_da_valores_por_defecto(self):
        self.assertEqual(M.Config.cargar(), M.Config())

    def test_guardar_y_cargar(self):
        c = M.Config(puerto="COM7")
        c.cal_salida["1:PLACA"] = {"codigo_a": 0, "volt_a": -5, "codigo_b": 4095, "volt_b": 5}
        c.guardar()
        self.assertEqual(M.Config.cargar().puerto, "COM7")
        self.assertEqual(M.Config.cargar().cal_salida, c.cal_salida)
        self.assertFalse(M.ruta_config().with_suffix(".json.tmp").exists())

    def test_archivo_corrupto_se_conserva(self):
        ruta = M.ruta_config()
        ruta.parent.mkdir(parents=True, exist_ok=True)
        ruta.write_text('{"puerto": "COM3", "cal_salida": {', encoding="utf-8")   # cortado a medias
        c = M.Config.cargar()
        self.assertEqual(c, M.Config())
        copia = ruta.with_suffix(".json.corrupto")
        self.assertTrue(copia.exists(), "debe quedar una copia del archivo dañado")
        self.assertIn("COM3", copia.read_text(encoding="utf-8"))

    def test_json_que_no_es_un_objeto(self):
        ruta = M.ruta_config()
        ruta.parent.mkdir(parents=True, exist_ok=True)
        ruta.write_text(json.dumps([1, 2, 3]), encoding="utf-8")
        self.assertEqual(M.Config.cargar(), M.Config())
        self.assertTrue(ruta.with_suffix(".json.corrupto").exists())


if __name__ == "__main__":
    unittest.main()
