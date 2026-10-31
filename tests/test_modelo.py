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


class TestAnalisisEspectro(unittest.TestCase):
    FS, N = 1e6, 8192

    def _senal(self, f0=12345.6, ruido=1e-3, semilla=1):
        t = np.arange(self.N) / self.FS
        r2 = math.sqrt(2)
        rng = np.random.default_rng(semilla)
        return (1.0 * r2 * np.sin(2 * np.pi * f0 * t) + 0.01 * r2 * np.sin(2 * np.pi * 2 * f0 * t)
                + 0.003 * r2 * np.sin(2 * np.pi * 3 * f0 * t) + rng.normal(0, ruido, self.N))

    def test_picos_frecuencia_y_nivel_con_todas_las_ventanas(self):
        v = self._senal()
        for ventana in ("Hann", "Hamming", "Blackman-Harris", "Flat-top"):
            f, p, enbw = M.espectro_potencia(v, self.FS, ventana)
            piso = M.piso_ruido(p)
            pk = M.buscar_picos(f, p, piso, -70, 10, 0, 3, enbw_bins=enbw)
            self.assertEqual(len(pk), 3, ventana)
            self.assertAlmostEqual(pk[0]["f"], 12345.6, delta=2, msg=ventana)
            self.assertAlmostEqual(pk[0]["db"], 0.0, delta=0.1, msg=ventana)       # 1 V eficaz = 0 dBV
            self.assertAlmostEqual(pk[1]["db"], -40.0, delta=0.3, msg=ventana)
            self.assertAlmostEqual(pk[2]["db"], 20 * math.log10(0.003), delta=0.5, msg=ventana)

    def test_umbrales(self):
        v = self._senal()
        f, p, enbw = M.espectro_potencia(v, self.FS, "Blackman-Harris")
        piso = M.piso_ruido(p)
        self.assertEqual(len(M.buscar_picos(f, p, piso, -45, 10, 0, 10, enbw_bins=enbw)), 2)
        self.assertEqual(len(M.buscar_picos(f, p, piso, -200, 10, 0, 1, enbw_bins=enbw)), 1)
        # con un umbral sobre el piso enorme no queda nada salvo lo muy grande
        self.assertEqual(len(M.buscar_picos(f, p, piso, -200, 80, 0, 10, enbw_bins=enbw)), 1)

    def test_thd_snr(self):
        v = self._senal()
        f, p, enbw = M.espectro_potencia(v, self.FS, "Blackman-Harris")
        a = M.analizar_armonicos(f, p, M.piso_ruido(p), enbw)
        self.assertAlmostEqual(a["f0"], 12345.6, delta=1)
        self.assertAlmostEqual(a["thd"], math.hypot(0.01, 0.003), delta=2e-4)
        self.assertAlmostEqual(a["snr"], 60.0, delta=1.0)            # 1 V contra 1 mV de ruido
        self.assertAlmostEqual(a["densidad"], 1e-3 / math.sqrt(self.FS / 2), delta=0.1e-6)
        self.assertTrue(a["resolucion_ok"])

    def test_pocos_periodos_avisa(self):
        v = self._senal(f0=600.0)
        f, p, enbw = M.espectro_potencia(v, self.FS, "Blackman-Harris")
        self.assertFalse(M.analizar_armonicos(f, p, M.piso_ruido(p), enbw)["resolucion_ok"])

    def test_quitar_piso_baja_el_ruido_y_respeta_las_componentes(self):
        v = self._senal()
        f, p, enbw = M.espectro_potencia(v, self.FS, "Blackman-Harris")
        piso = M.piso_ruido(p)
        q = M.quitar_piso(p, piso, 3.0)
        k = int(np.argmax(p))
        self.assertAlmostEqual(10 * math.log10(q[k]), 10 * math.log10(p[k]), delta=0.01)
        lejos = np.r_[200:1500]
        self.assertLess(np.median(M.a_db(q)[lejos]), np.median(M.a_db(p)[lejos]) - 30)

    def test_promediado_alisa_el_ruido(self):
        prom = M.PromedioEspectro()
        rng = np.random.default_rng(3)
        desvios = []
        for i in range(32):
            f, p, _ = M.espectro_potencia(rng.normal(0, 1e-3, 4096), 1e6)
            q = prom.agregar(("x",), p, 32)
            if i in (0, 31):
                desvios.append(float(np.std(M.a_db(q)[50:-50])))
        self.assertLess(desvios[1], desvios[0] / 3)
        q = prom.agregar(("otra",), p, 32)            # cambió la clave: arranca de nuevo
        self.assertEqual(prom.cuenta, 1)


class TestFosforo(unittest.TestCase):
    def test_trazo_continuo_sin_huecos(self):
        x = np.linspace(0, 10, 300)                # menos muestras que columnas
        img = M.rasterizar_trazo(x, np.zeros_like(x), 1000, 640, 10, -4, 4)
        self.assertTrue(img[:, 320].all())
        self.assertEqual(int(img.sum()), 1000)

    def test_flanco_vertical_marca_toda_la_columna(self):
        x = np.array([4.999, 5.0005, 10.0])
        y = np.array([-3.0, 3.0, 3.0])
        img = M.rasterizar_trazo(x, y, 1000, 640, 10, -4, 4)
        col = img[499]
        self.assertTrue(col[int((-3 + 4) / 8 * 640):int((3 + 4) / 8 * 640)].all())

    def test_fuera_de_pantalla_no_marca(self):
        x = np.linspace(0, 10, 4000)
        img = M.rasterizar_trazo(x, np.full_like(x, 6.0), 1000, 640, 10, -4, 4)
        self.assertFalse(img.any())


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

    def test_cada_placa_tiene_su_configuracion(self):
        M.Config(puerto="COM3").guardar()                       # F767 por defecto
        M.Config(puerto="COM9", placa="F429").guardar()
        self.assertEqual(M.Config.cargar().puerto, "COM3")
        self.assertEqual(M.Config.cargar("F429").puerto, "COM9")
        self.assertEqual(M.Config.cargar("F429").placa, "F429")
        self.assertEqual(M.ruta_config().name, "config.json")   # compatibilidad con lo anterior
        self.assertEqual(M.ruta_config("F429").name, "config_F429.json")

    def test_ad9833_frecuencia_y_comandos(self):
        self.assertAlmostEqual(M.dds_frecuencia_real(1000), 999.961, places=3)   # registro 10737
        self.assertEqual(M.dds_frecuencia_real(20e6), 12.5e6)                # tope (Nyquist)
        self.assertEqual(M.dds_paso_amplitud(100), 255)
        self.assertEqual(M.dds_paso_amplitud(-5), 0)
        c = M.ConfigDDS.desde_dict({"habilitado": True, "forma": "Triangular", "frecuencia": 2e6,
                                    "amplitud": 50})
        self.assertEqual(M.dds_comandos(c, extendido=False), ["DDSA 128", "DDS 2000000.0000 1 1"])
        self.assertEqual(M.dds_comandos(c), ["DDSCLK 25000000.0", "DDSA 128", "DDSF 0.000",
                                             "DDS 2000000.0000 1 1", "DDSMOD NO"])
        c.forma = "Cuadrada f/2"
        self.assertEqual(M.dds_comandos(c, extendido=False)[1], "DDS 2000000.0000 2 1")  # firmware viejo
        c = M.ConfigDDS.desde_dict({"forma": "Rara", "frecuencia": 1e9, "amplitud": "x", "mclk": 5})
        self.assertEqual((c.forma, c.habilitado, c.mclk), ("Seno", False, 25e6))
        self.assertEqual((c.frecuencia, c.amplitud), (12.5e6, 50.0))       # recortada / por defecto

    def test_ad9833_modulaciones(self):
        c = M.ConfigDDS.desde_dict({"modulacion": "Barrido", "bar_log": False, "bar_f1": 10,
                                    "bar_f2": 2e6, "bar_t": 3})
        self.assertEqual(M.dds_texto_modulacion(c), "DDSMOD LIN 10.0000 2000000.0000 3.0000")
        for mod, esperado in [("FSK", "DDSMOD FSK 2000.0000 100.0000"),
                              ("PSK", "DDSMOD PSK 180.000 100.0000"),
                              ("Ráfaga", "DDSMOD RAF 10 0.010000"),
                              ("AM", "DDSMOD AM 0.5000 10.0000"),
                              ("Ninguna", "DDSMOD NO")]:
            c.modulacion = mod
            self.assertEqual(M.dds_texto_modulacion(c), esperado)
        c = M.ConfigDDS.desde_dict({"fsk_tasa": 1e6, "am_frec": 1e4, "raf_ciclos": 2.6})
        self.assertEqual((c.fsk_tasa, c.am_frec, c.raf_ciclos), (M.DDS_TASA_MAX, M.DDS_AM_FMAX, 3.0))
        self.assertAlmostEqual(M.dds_fase_real(90), 90.0)
        self.assertAlmostEqual(M.dds_fase_real(370), 10.0195, places=3)   # 114/4096 · 360

    def test_ad9833_calibracion_de_amplitud(self):
        self.assertIsNone(M.dds_vpp([], 50))
        uno = M.limpiar_cal_dds([[80, 1.48, 2.02], ["x", 1], [150, 1]])  # solo la medición válida
        self.assertEqual(uno, [[80.0, 1.48, 2.02]])
        self.assertAlmostEqual(M.dds_vpp(uno, 40), 0.74)                 # proporcional
        self.assertAlmostEqual(M.dds_vmedia(uno, 40), 2.02)
        self.assertAlmostEqual(M.dds_porcentaje_para_vpp(uno, 0.74), 40)
        cal = M.limpiar_cal_dds([[100, 2.0, 2.1], [0, 0.0, 1.9], [50, 0.9, None]])
        self.assertEqual([p[0] for p in cal], [0.0, 50.0, 100.0])        # ordenada
        self.assertAlmostEqual(M.dds_vpp(cal, 75), 1.45)
        self.assertAlmostEqual(M.dds_vmedia(cal, 50), 2.0)               # sin el punto sin media
        self.assertAlmostEqual(M.dds_porcentaje_para_vpp(cal, 1.45), 75)

    def test_ad9833_correccion_de_reloj(self):
        # el módulo tiene un cristal de 25,0004 MHz (+16 ppm): a 1 MHz pedido sale 16 Hz de más
        f_sal = M.dds_frecuencia_real(1e6) * 25.0004e6 / 25e6
        nuevo = M.dds_mclk_corregido(25e6, 1e6, f_sal)
        self.assertAlmostEqual(nuevo, 25.0004e6, delta=1)
        self.assertAlmostEqual(M.dds_frecuencia_real(1e6, nuevo) * 25.0004e6 / nuevo, 1e6, delta=0.1)
        self.assertIsNone(M.dds_mclk_corregido(25e6, 1e6, 0))           # sin señal
        self.assertIsNone(M.dds_mclk_corregido(25e6, 1e6, 1.2e6))       # otra señal

    def test_escala_segun_resolucion(self):
        pant = (1920, 1080)
        self.assertEqual(M.escala_para(None, pant), 1.0)                  # automática
        self.assertEqual(M.escala_para((1920, 1080), pant), 1.0)
        self.assertEqual(M.escala_para((1280, 720), pant), 1.5)           # más chica: todo más grande
        self.assertEqual(M.escala_para((3840, 2160), pant), 0.5)          # más grande: entra más
        self.assertAlmostEqual(M.escala_para((1366, 768), pant), 1.406, places=3)
        self.assertEqual(M.escala_para((640, 360), (3840, 2160)), M.ESCALA_MAX)
        self.assertEqual(M.leer_resolucion("1920×1080"), (1920, 1080))
        self.assertIsNone(M.leer_resolucion("auto"))

    def test_preferencias_de_placa(self):
        auto = {"placa": "F767", "preguntar": True, "resolucion": "auto"}
        self.assertEqual(M.cargar_preferencias(), auto)
        M.guardar_preferencias({"placa": "F429", "preguntar": False})
        self.assertEqual(M.cargar_preferencias(), {"placa": "F429", "preguntar": False, "resolucion": "auto"})
        M.guardar_resolucion((1366, 768))
        self.assertEqual(M.resolucion_guardada(), (1366, 768))
        self.assertEqual(M.cargar_preferencias()["placa"], "F429")         # no pisa lo demás
        M.guardar_resolucion(None)
        self.assertIsNone(M.resolucion_guardada())
        M.ruta_preferencias().write_text('{"resolucion": "gigante", "zoom": 1.4}', encoding="utf-8")
        self.assertIsNone(M.resolucion_guardada())                        # valor absurdo / viejo
        M.ruta_preferencias().write_text('{"placa": "F999"}', encoding="utf-8")
        self.assertEqual(M.cargar_preferencias()["placa"], "F767")   # placa desconocida

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
