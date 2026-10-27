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
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))

import numpy as np  # noqa: E402

try:
    from PySide6.QtCore import QEvent
    from PySide6.QtWidgets import QApplication, QFileDialog
    HAY_QT = True
except ImportError:      # pragma: no cover
    HAY_QT = False

if HAY_QT:
    import main as A  # noqa: E402
    import modelo as M  # noqa: E402
    import tab_osciloscopio as TO  # noqa: E402
    import widgets as W  # noqa: E402

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
        W.aplicar_escala(_app, 1.0)
        self.v.close()
        self.v.deleteLater()
        QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
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
    # --------------------------------------------------------------- persistencia
    def _cuadro_con_glitch(self, glitch: bool):
        d = self._cuadro()
        d["ch2"] = np.full(d["n"], 2048, np.uint16)
        if glitch:
            i = d["pre"] + 300                                  # 0,3 div después del disparo
            d["ch1"] = d["ch1"].copy()
            d["ch1"][i:i + 3] = 4000
        return d

    def _filas_glitch(self):
        """Columnas y filas de la imagen donde cae el pico del transitorio (CH1 a ~+7 div, recortado)."""
        f = self.osc.fosforo
        col = int((5 + 0.3 * 0.5) / TO.DIV_X * f.COLS)          # 1 ms/div, 200 kS/s: 300 muestras = 1,5 ms
        return f.buf[1][col - 3:col + 12, int(0.97 * f.FILAS):]

    def test_persistencia_retiene_un_transitorio_y_lo_apaga(self):
        self.osc.persistencia.setCurrentIndex(TO.PERSISTENCIAS.index("1 s"))
        self.osc._mostrar(self._cuadro_con_glitch(True))
        for _ in range(5):
            self.osc._mostrar(self._cuadro_con_glitch(False))
        self.assertGreater(float(self._filas_glitch().max()), 0.3)         # sigue marcado
        self.osc.fosforo._tic()
        self.assertIsNotNone(self.osc.fosforo.img.image)
        self.osc.fosforo._t -= 2.0                                           # pasaron 2 s
        self.osc.fosforo._tic()
        self.assertEqual(float(self._filas_glitch().max()), 0.0)            # ya se apagó

    def test_persistencia_infinita_no_se_apaga_y_se_borra_al_cambiar_escala(self):
        self.osc.persistencia.setCurrentIndex(TO.PERSISTENCIAS.index("Infinita"))
        self.osc._mostrar(self._cuadro_con_glitch(True))
        self.osc.fosforo._t -= 60.0
        self.osc.fosforo._tic()
        self.assertGreater(float(self._filas_glitch().max()), 0.3)
        self.osc.canales[1].vdiv.setCurrentIndex(self.osc.canales[1].vdiv.currentIndex() + 1)
        self.assertFalse(self.osc.fosforo.buf[1].any())

    def test_persistencia_desactivada_no_acumula(self):
        self.osc.persistencia.setCurrentIndex(0)
        self.osc._mostrar(self._cuadro_con_glitch(True))
        self.assertFalse(self.osc.fosforo.buf[1].any())

    # --------------------------------------------------------------- FFT
    def test_analisis_fft_detecta_picos_y_umbral(self):
        self.osc.tdiv.setCurrentIndex(TO.TDIVS.index(10e-3))         # 20 kS/s, 2000 puntos
        n, pre, fs, *_ = self.osc.parametros_captura()
        t = np.arange(n) / fs
        v = 2048 + 1200 * np.sin(2 * np.pi * 1000 * t) + 40 * np.sin(2 * np.pi * 3000 * t)
        v += np.random.default_rng(2).normal(0, 1.5, n)
        d = {"n": n, "pre": pre, "fs": fs, "disparado": 1, "ch1": np.rint(v).astype(np.uint16),
             "ch2": np.full(n, 2048, np.uint16)}
        self.osc.canales[2].visible.setChecked(False)
        self.osc.abrir_analisis_fft()
        dlg = self.osc.dlg_fft
        self.assertTrue(self.osc.chk_fft.isChecked())
        self.osc._t_dlg_fft = 0
        self.osc._mostrar(d)
        self.assertGreaterEqual(len(dlg.picos), 2)
        self.assertAlmostEqual(dlg.picos[0]["f"], 1000, delta=1)
        self.assertEqual(dlg.picos[0]["armonico"], 1)
        self.assertEqual(dlg.picos[1]["armonico"], 3)
        self.assertEqual(dlg.tabla.rowCount(), len(dlg.picos))
        self.assertAlmostEqual(dlg.analisis["thd"], 40 / 1200, delta=0.003)
        # subir el umbral por encima del 3er armónico deja solo el fundamental
        nivel_3 = dlg.picos[1]["db"]
        dlg.umbral.setValue(nivel_3 + 3)
        self.osc._t_dlg_fft = 0
        self.osc._mostrar(d)
        self.assertEqual(len(dlg.picos), 1)
        self.assertAlmostEqual(self.osc.linea_umbral.value(), nivel_3 + 3, delta=0.05)
        # eliminar el piso de ruido no mueve los picos
        x, y = self.osc.curvas_fft[1].getData()
        mediana_antes = float(np.median(y))
        dlg.ruido.setCurrentIndex(2)
        dlg.promedio.setCurrentIndex(2)
        for _ in range(8):
            self.osc._mostrar(d)
        x, y = self.osc.curvas_fft[1].getData()
        self.assertLess(float(np.median(y)), mediana_antes - 30)  # el piso bajó más de 30 dB
        self.assertGreater(float(np.max(y)), -10)                  # el fundamental sigue ahí
        self.assertEqual(self.osc.estado_config()["fft"]["ruido"], 2)

    # --------------------------------------------------------------- zoom
    def test_zoom_agranda_y_vuelve(self):
        scroll = self.osc.findChild(TO.QScrollArea)
        ancho = scroll.width()
        self.v.cambiar_zoom(+1)
        self.v.aplicar_zoom()
        self.assertAlmostEqual(W.ESCALA, 1.1)
        self.assertEqual(scroll.width(), W.px(340))
        self.assertEqual(self.v.btn_zoom.text(), "110 %")
        self.assertIn(f"{W.pt(10)}pt", _app.styleSheet())
        self.assertEqual(M.zoom_guardado(), 1.1)
        self.v.cambiar_zoom(+1)
        self.v.cambiar_zoom(+1)                                   # dos pasos seguidos: 125 % → 140 %
        self.assertEqual(self.v.btn_zoom.text(), "140 %")
        self.v.cambiar_zoom(0)
        self.v.aplicar_zoom()
        self.assertEqual(scroll.width(), ancho)
        self.assertEqual(M.zoom_guardado(), 1.0)

    # --------------------------------------------------------------- reconexión / watchdog
    def test_reconexion_automatica_tras_un_reinicio(self):
        abiertos = []
        self.v.disp.abrir = lambda puerto: abiertos.append(puerto)
        self.v.config.puerto = "COM7"
        A.listar_puertos = lambda: []                       # la placa se está reiniciando
        self.v._perdida_conexion("Se perdió la conexión.")
        self.assertEqual(self.v.btn_con.text(), "Cancelar")
        self.v._intentar_reconexion()
        self.assertEqual(abiertos, [])                      # el puerto todavía no volvió
        A.listar_puertos = lambda: [("COM7", "Instrumento (USB del Nucleo)")]
        self.v._intentar_reconexion()
        self.assertEqual(abiertos, ["COM7"])
        self.v._error_conexion("no respondió")             # un intento fallido no corta la reconexión
        self.assertIsNotNone(self.v._reconexion)
        # vuelve: la placa avisa que se reinició por el watchdog
        self.v.disp.info = {"gen_fs": 1e6, "osc_fsmax": 1.59e6, "wdg_ms": 2000.0, "reinicio": "watchdog"}
        self.v.disp.placa, self.v.disp.puerto = "F767", "COM7"
        enviados = []
        self.v.disp.enviar = lambda t: enviados.append(t) or True
        self.v.disp.enviar_tabla = lambda *a: True
        with mock.patch.object(type(self.v.disp), "esta_conectado", new_callable=mock.PropertyMock,
                               return_value=True):
            self.v._al_conectar(A.VERSION)
        self.assertIsNone(self.v._reconexion)
        self.assertIn("watchdog", self.v.statusBar().currentMessage())
        self.assertTrue(any(e.startswith("GSET") for e in enviados))   # se reenvió el generador
        self.assertIn("watchdog", self.v.tab_placa.lbl_vivo.text())

    def test_aviso_de_firmware_de_otra_version(self):
        self.assertTrue(A.misma_serie("0.8.18", "0.8.25"))
        self.assertFalse(A.misma_serie("0.7.3", "0.8.18"))
        self.assertIn(A.VERSION, self.v.windowTitle())
        self.v.disp.info, self.v.disp.placa, self.v.disp.puerto = {}, "F767", "COM7"
        self.v.disp.enviar = lambda t: True
        self.v.disp.enviar_tabla = lambda *a: True
        with mock.patch.object(type(self.v.disp), "esta_conectado", new_callable=mock.PropertyMock,
                               return_value=True):
            self.v._al_conectar("0.7.3")
        self.assertIn("cargá el firmware", self.v.statusBar().currentMessage())

    def test_reconexion_se_rinde_y_se_puede_cancelar(self):
        self.v.disp.abrir = lambda puerto: None
        self.v.config.puerto = "COM7"
        A.listar_puertos = lambda: []
        self.v._perdida_conexion("Se perdió la conexión.")
        self.v.alternar_conexion()                          # «Cancelar»
        self.assertIsNone(self.v._reconexion)
        self.assertEqual(self.v.btn_con.text(), "Conectar")
        self.v._perdida_conexion("Se perdió la conexión.")
        self.v._reconexion["hasta"] = 0
        self.v._intentar_reconexion()
        self.assertIsNone(self.v._reconexion)
        self.assertIn("No se pudo reconectar", self.v.statusBar().currentMessage())

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
