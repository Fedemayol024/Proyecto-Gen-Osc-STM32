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
    import panel_dds  # noqa: E402

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

    # --------------------------------------------------------------- opciones gráficas
    def test_resolucion_agranda_y_vuelve_a_automatica(self):
        scroll = self.osc.findChild(TO.QScrollArea)
        ancho = scroll.width()
        self.v.resolucion_pantalla = lambda: (1920, 1080)
        self.v.elegir_resolucion((1280, 720))                     # más chica que la pantalla
        self.assertAlmostEqual(W.ESCALA, 1.5)
        self.assertEqual(scroll.width(), W.px(340))
        self.assertIn(f"{W.pt(10)}pt", _app.styleSheet())
        self.assertEqual(M.resolucion_guardada(), (1280, 720))
        self.v.elegir_resolucion(None)                            # automática
        self.assertEqual(W.ESCALA, 1.0)
        self.assertEqual(scroll.width(), ancho)
        self.assertIsNone(M.resolucion_guardada())

    def test_menu_de_opciones_graficas(self):
        self.v.resolucion_pantalla = lambda: (1920, 1080)
        self.v._armar_menu_opciones()
        textos = [a.text() for a in self.v.menu_opciones.actions() if a.text()]
        self.assertTrue(textos[1].startswith("Automática · la de la pantalla (1920×1080)"))
        marcadas = [a.text() for a in self.v.menu_opciones.actions() if a.isChecked()]
        self.assertEqual(len(marcadas), 1)
        self.assertTrue(marcadas[0].startswith("Automática"))      # por defecto: la del sistema
        self.assertTrue(any(t.startswith("1366×768") and "más grande" in t for t in textos))
        self.assertTrue(any(t.startswith("1920×1080") and "igual a la pantalla" in t for t in textos))
        self.assertTrue(any(t.startswith("3840×2160") and "entra más" in t for t in textos))

    def test_agrandar_no_saca_la_ventana_de_la_pantalla(self):
        from PySide6.QtCore import QRect

        class Pantalla:
            def availableGeometry(self): return QRect(0, 0, 1920, 1032)
            def geometry(self): return QRect(0, 0, 1920, 1080)
            def devicePixelRatio(self): return 1.0
        self.v.screen = lambda: Pantalla()
        self.v.resize(1000, 650)
        self.v.move(880, 300)                                     # cerca del borde derecho
        self.v.show()
        for res in [(1600, 900), (1366, 768), (1280, 720)]:
            self.v.elegir_resolucion(res)
            _app.processEvents()
            g = self.v.frameGeometry()
            self.assertLessEqual(g.right(), 1919, res)
            self.assertGreaterEqual(g.x(), 0, res)
            self.assertLessEqual(g.bottom(), 1031, res)

    def test_la_ventana_entra_en_una_notebook(self):
        self.v.lbl_con.setText("● Conectado · COM7 · NUCLEO-F767ZI · firmware v0.8.19 · generador "
                               "1 MS/s · osciloscopio hasta 1,59 MS/s")      # texto largo
        minimo = self.v.minimumSizeHint()
        self.assertLessEqual(minimo.width(), 1280)
        self.assertLessEqual(minimo.height(), 680)

    # --------------------------------------------------------------- Single / Autoset
    def _conectado(self):
        enviados = []
        self.v.disp.enviar = lambda t: enviados.append(t) or True
        p = mock.patch.object(type(self.v.disp), "esta_conectado", new_callable=mock.PropertyMock,
                              return_value=True)
        p.start()
        self.addCleanup(p.stop)
        self.v.disp.info = {"osc_fsmax": 1.59e6}
        return enviados

    def _llega(self, enviados):
        """La placa contesta la última CAP enviada con un cuadro de ese tamaño."""
        cap = [e for e in enviados if e.startswith("CAP ")][-1].split()
        n, pre, fs = int(cap[1]), int(cap[2]), float(cap[3])
        t = np.arange(n) / fs
        ch = np.rint(2048 + 1000 * np.sin(2 * np.pi * 1000 * t)).astype(np.uint16)
        self.v._al_datos({"n": n, "pre": pre, "fs": fs, "disparado": 1, "ch1": ch, "ch2": ch})

    def test_single_y_autoset_no_encimar_capturas(self):
        """Con una captura en camino, Single/Autoset no mandan otra CAP (el firmware viejo
        abortaba la captura a la mitad y el ADC quedaba trabado hasta reconectar)."""
        enviados = self._conectado()
        self.osc._alternar_run()                                   # RUN: una captura en camino
        self.assertEqual(sum(e.startswith("CAP ") for e in enviados), 1)
        for boton in (self.osc._unico, self.osc._autoset):
            self.assertTrue(self.osc.esperando)
            antes = sum(e.startswith("CAP ") for e in enviados)
            boton()
            self.assertEqual(sum(e.startswith("CAP ") for e in enviados), antes)   # nada encimado
            self._llega(enviados)                                  # llega la de antes del botón…
            self.assertEqual(sum(e.startswith("CAP ") for e in enviados), antes + 1)  # …y recién ahí
            self._llega(enviados)
            if boton == self.osc._unico:
                self.assertFalse(self.osc.corriendo)               # Single terminó
                self.assertIn("Single", self.v.statusBar().currentMessage())
                self.osc._alternar_run()
            else:
                while self.osc.autoset_estado:
                    self._llega(enviados)
                self.assertIn("Autoset listo", self.v.statusBar().currentMessage())
                self.assertTrue(self.osc.corriendo)               # sigue adquiriendo

    def test_stop_cancela_un_single_pendiente(self):
        enviados = self._conectado()
        self.osc._alternar_run()
        self.osc._unico()
        self.osc._alternar_run()                                   # STOP
        self.assertIsNone(self.osc.accion_pendiente)
        self.assertFalse(self.osc.corriendo)
        antes = len(enviados)
        self._llega(enviados)
        self.assertEqual(len(enviados), antes)                     # no pide más

    # --------------------------------------------------------------- pestaña Placa
    def test_resaltar_rotulo_y_pin_con_el_mouse(self):
        from PySide6.QtCore import QPoint
        from PySide6.QtTest import QTest
        self.v.resize(1366, 860)
        self.v.show()
        self.v.tabs.setCurrentWidget(self.v.tab_placa)
        d = self.v.tab_placa.dib_placa
        d.grab()                                          # dibuja y arma las zonas
        zonas = {}
        for r, k in d._zonas:
            zonas.setdefault(k, []).append(r)
        self.assertIn("CN8-12", zonas)                    # FSY del AD9833
        for r in zonas["CN8-12"]:                         # el rótulo y el pin
            QTest.mouseMove(d, QPoint(int(r.center().x() * W.ESCALA), int(r.center().y() * W.ESCALA)))
            self.assertEqual(d.resaltado, "CN8-12")
            QTest.mouseMove(d, QPoint(int(d.width() / 2), 5))   # fuera de todo
            self.assertIsNone(d.resaltado)

    # --------------------------------------------------------------- AD9833
    def test_ad9833_envia_comandos_solo_con_firmware_que_lo_soporta(self):
        enviados = []
        self.v.disp.enviar = lambda t: enviados.append(t) or True
        self.v.disp.enviar_tabla = lambda *a: True
        gen = self.v.tab_gen
        with mock.patch.object(type(self.v.disp), "esta_conectado", new_callable=mock.PropertyMock,
                               return_value=True):
            self.v.disp.info = {}                                   # firmware viejo
            gen.reenviar_todo()
            self.assertFalse(any(e.startswith("DDS") for e in enviados))
            self.assertIn("firmware", gen.dds.lbl_info.text())
            self.v.disp.info = {"dds_mclk": 25e6}                   # firmware nuevo
            gen.reenviar_todo()
            self.assertIn("DDS 100000.0000 0 0", enviados)
            self.assertIn("DDSA 128", enviados)
            enviados.clear()
            gen.dds.frec.set_valor(1e6)
            gen.dds.forma.setCurrentText("Cuadrada")
            gen.dds.hab.setChecked(True)
            gen.dds._cambio()
            gen._enviar()
            self.assertEqual(enviados, ["DDS 1000000.0000 2 1"])     # la amplitud no cambió
            gen.al_linea("OK DDS 999999.9776")
            self.assertIn("confirmada", gen.dds.lbl_info.text())
        self.assertEqual(gen.estado_config()["dds"]["forma"], "Cuadrada")

    def _dds_conectado(self, info):
        enviados = []
        self.v.disp.enviar = lambda t: enviados.append(t) or True
        self.v.disp.enviar_tabla = lambda *a: True
        p = mock.patch.object(type(self.v.disp), "esta_conectado", new_callable=mock.PropertyMock,
                              return_value=True)
        p.start()
        self.addCleanup(p.stop)
        self.v.disp.info = info
        return enviados

    def test_ad9833_firmware_nuevo_manda_fase_modulacion_y_reloj(self):
        enviados = self._dds_conectado({"dds_mclk": 25e6, "dds_mod": 1})
        gen, d = self.v.tab_gen, self.v.tab_gen.dds
        gen.reenviar_todo()
        for cmd in ("DDSCLK 25000000.0", "DDSF 0.000", "DDSMOD NO"):
            self.assertIn(cmd, enviados)
        # modulación: solo se ven los campos del tipo elegido, y se manda solo lo que cambió
        enviados.clear()
        d.mod.setCurrentText("FSK")
        gen._enviar()
        self.assertEqual(enviados, ["DDSMOD FSK 2000.0000 100.0000"])
        self.assertTrue(d.filas_mod["FSK"][0].isVisibleTo(d))
        self.assertFalse(d.filas_mod["Barrido"][0].isVisibleTo(d))
        enviados.clear()
        d.fase.set_valor(90)
        d._cambio()
        gen._enviar()
        self.assertEqual(enviados, ["DDSF 90.000"])
        # otro reloj: cambian todos los registros, se manda todo de nuevo
        enviados.clear()
        d.c.mclk = 25.0004e6
        gen.programar_envio_dds()
        gen._enviar()
        self.assertEqual(enviados[0], "DDSCLK 25000400.0")
        self.assertEqual(len(enviados), 5)
        # ráfaga más larga que el período: avisa
        d.mod.setCurrentText("Ráfaga")
        d.raf_ciclos.setValue(1000)
        self.assertIn("continua", d.lbl_mod.text())

    def test_ad9833_firmware_basico_no_recibe_comandos_nuevos(self):
        enviados = self._dds_conectado({"dds_mclk": 25e6})
        self.v.tab_gen.dds.mod.setCurrentText("AM")
        self.v.tab_gen.reenviar_todo()
        self.assertFalse(any(e.startswith(("DDSF", "DDSMOD", "DDSCLK")) for e in enviados))
        self.assertIn("firmware", self.v.tab_gen.dds.lbl_info.text())

    def test_ad9833_amplitud_en_volts_con_calibracion(self):
        d = self.v.tab_gen.dds
        d.show()
        self.assertTrue(d.fila_amp.isVisibleTo(d))              # sin calibrar: en %
        self.assertFalse(d.fila_vpp.isVisibleTo(d))
        # calibrada: el 0 % midió 12 mV de resto, pero el selector arranca en 0 V
        d.c.cal = [[0.0, 0.012, 2.0], [100.0, 1.85, 2.0]]
        d._mostrar()
        self.assertFalse(d.fila_amp.isVisibleTo(d))             # ahora se elige en Vpp
        self.assertTrue(d.fila_vpp.isVisibleTo(d))
        self.assertEqual((d.vpp.vmin, d.vpp.vmax), (0.0, 1.85))  # de 0 V a lo medido a 100 %
        self.assertAlmostEqual(d.vpp.valor(), 1.85 * 128 / 255, places=3)   # 50 % → paso 128
        self.assertIn("de continua", d.lbl_info.text())
        d._vpp_editado(1.48)                                     # escribir Vpp mueve el potenciómetro
        self.assertAlmostEqual(d.amp.valor(), 80.0, places=1)
        self.assertEqual(M.dds_paso_amplitud(d.c.amplitud), 204)
        d._vpp_editado(0.0)
        self.assertEqual(M.dds_paso_amplitud(d.c.amplitud), 0)   # 0 V → 0 % (no el resto medido)
        self.assertEqual(d.c.cal[0], [0.0, 0.012, 2.0])          # la tabla conserva lo medido
        d.c.cal = [[0.0, 0.0, 2.6], [100.0, 1.85, 2.6]]          # se pasaría de 3,3 V
        d.amp.set_valor(100)
        d._cambio()
        self.assertIn("pines directos", d.lbl_info.text())

    def test_ad9833_fase_solo_en_psk_y_rafaga(self):
        d = self.v.tab_gen.dds
        d.show()
        self.assertFalse(d.fila_fase.isVisibleTo(d))            # sola no se nota
        d.mod.setCurrentText("PSK")
        self.assertTrue(d.fila_fase.isVisibleTo(d))
        self.assertEqual(d.fila_fase.layout().itemAt(0).widget().text(), "Fase 1")
        d.mod.setCurrentText("Ráfaga")
        self.assertEqual(d.fila_fase.layout().itemAt(0).widget().text(), "Fase de arranque")
        d.fase.set_valor(90)
        d._cambio()
        self.assertIn("arranca en 90,0°", d.lbl_mod.text())

    def test_ad9833_lee_tensiones_como_las_muestra_el_osciloscopio(self):
        from panel_dds import leer_tension
        for texto, v in [("906,25mV", 0.90625), ("625,00 mV", 0.625), ("1,48 V", 1.48), ("1.48", 1.48),
                         ("2,02", 2.02), ("906,25 mVpp", 0.90625), ("500 µV", 0.0005), ("0", 0.0)]:
            self.assertAlmostEqual(leer_tension(texto), v, msg=texto)
        for texto in ("", "abc", ",", "m"):
            self.assertIsNone(leer_tension(texto), texto)

    def test_ad9833_calibracion_paso_a_paso(self):
        from panel_dds import DialogoCalDDS
        d = self.v.tab_gen.dds
        d.c.cal = [[80.0, 1.48, 2.02]]                      # medición anterior fuera de la lista
        d.frec.set_valor(5e6)
        d.mod.setCurrentText("FSK")                          # lo que había antes de calibrar
        dlg = DialogoCalDDS(d)
        # paso 1: la salida queda en seno de 1 kHz al 0 %, sin modulación
        self.assertIn("Paso 1 de 5", dlg.lbl_paso.text())
        self.assertEqual((d.c.frecuencia, d.c.amplitud, d.c.modulacion), (1000.0, 0.0, "Ninguna"))
        self.assertFalse(dlg.btn_sig.isEnabled())            # falta el Vpp
        dlg.e_vpp.setText("0 mV")
        dlg.e_vmed.setText("2,0 V")
        dlg._continuar()
        # paso 2: 25 %
        self.assertIn("Paso 2 de 5", dlg.lbl_paso.text())
        self.assertEqual(d.c.amplitud, 25.0)
        dlg.e_vpp.setText("algo")
        self.assertFalse(dlg.btn_sig.isEnabled())            # no se entiende: no avanza
        self.assertIn("No entiendo", dlg.lbl_lectura.text())
        dlg.e_vpp.setText("453,13mV")
        dlg.e_vmed.setText("")                               # la media es opcional
        dlg._continuar()
        dlg.e_vpp.setText("906,25 mV")                        # 50 %
        dlg._continuar()
        dlg._saltar()                                        # 75 %: no se midió
        dlg.e_vpp.setText("1,85 V")
        dlg.e_vmed.setText("2,03")
        dlg._continuar()                                     # 100 % → resumen
        self.assertEqual(dlg.pila.currentIndex(), 1)
        self.assertEqual(dlg.btn_sig.text(), "Guardar")
        self.assertEqual(dlg.puntos(), [[0.0, 0.0, 2.0], [25.0, 0.45313, None], [50.0, 0.90625, None],
                                        [80.0, 1.48, 2.02], [100.0, 1.85, 2.03]])
        dlg._anterior()                                      # se puede volver a corregir
        self.assertIn("Paso 5 de 5", dlg.lbl_paso.text())
        dlg.reject()
        # al cerrar, el AD9833 vuelve a como estaba
        self.assertEqual((d.c.frecuencia, d.c.modulacion), (5e6, "FSK"))
        self.assertEqual(d.c.cal, [[80.0, 1.48, 2.02]])      # cancelado: no cambia la calibración

    def test_ad9833_calibracion_automatica_con_ch1(self):
        from PySide6.QtTest import QTest
        from panel_dds import DialogoCalDDS
        enviados = self._dds_conectado({"dds_mclk": 25e6, "dds_mod": 1})
        osc = self.v.tab_osc
        osc.canales[1].entrada.setCurrentText(M.MODOS_ENTRADA["DIRECTO"].nombre)
        osc.canales[1].punta.setCurrentText("×1")
        pedidos = []
        self.v.pedir_captura = lambda dueno, n, pre, fs, *a: pedidos.append((dueno, n, fs))
        d = self.v.tab_gen.dds
        modulo = {0: (0.0, 2.0), 25: (0.46, 2.01), 50: (0.92, 2.02), 75: (1.38, 2.02), 100: (1.84, 2.03)}

        def captura(pct):
            vpp, vmed = modulo[pct]
            t = np.arange(8192) / 200e3
            volts = vmed + vpp / 2 * np.sin(2 * np.pi * 999.961 * t)
            cod = np.clip(np.rint(osc.recta(1).codigo(volts)), 0, 4095).astype(np.uint16)
            return {"n": 8192, "pre": 0, "fs": 200e3, "disparado": 2, "ch1": cod, "ch2": cod}

        dlg = DialogoCalDDS(d)
        d._dlg_cal = dlg
        with mock.patch("panel_dds.QMessageBox.question", return_value=panel_dds.QMessageBox.Yes):
            dlg._alternar_auto()
        self.assertTrue(dlg.auto)
        self.assertFalse(osc.corriendo)                      # el osciloscopio queda en pausa
        self.assertIn("CAPX", enviados)
        for pct in (0, 25, 50, 75, 100):
            self.assertEqual(d.c.amplitud, float(pct))       # la app puso la salida
            QTest.qWait(500)                                 # espera a que se asiente y captura
            self.assertEqual(pedidos[-1], ("dds", 8192, 200e3))
            self.v._al_datos  # (la captura llega por main._al_datos con dueño "dds")
            d.al_captura(captura(pct))
            QTest.qWait(300)
        self.assertFalse(dlg.auto)
        self.assertEqual(dlg.pila.currentIndex(), 1)         # resumen
        pts = dlg.puntos()
        self.assertEqual([p[0] for p in pts], [0.0, 25.0, 50.0, 75.0, 100.0])
        for p in pts:
            vpp, vmed = modulo[int(p[0])]
            self.assertAlmostEqual(p[1], vpp, delta=0.01)    # cuantización del ADC
            self.assertAlmostEqual(p[2], vmed, delta=0.005)
        self.assertIn("lista", self.v.statusBar().currentMessage())
        osc.corriendo = False
        dlg.osc_corria = True
        dlg.reject()
        self.assertTrue(osc.corriendo)                       # el osciloscopio vuelve a RUN

    def test_ad9833_calibracion_automatica_avisa_si_recorta(self):
        from PySide6.QtTest import QTest
        from panel_dds import DialogoCalDDS
        self._dds_conectado({"dds_mclk": 25e6, "dds_mod": 1})
        self.v.pedir_captura = lambda *a: None
        d = self.v.tab_gen.dds
        dlg = DialogoCalDDS(d)
        d._dlg_cal = dlg
        with mock.patch("panel_dds.QMessageBox.question", return_value=panel_dds.QMessageBox.Yes):
            dlg._alternar_auto()
        saturada = np.r_[np.zeros(4096), np.full(4096, 4095)].astype(np.uint16)
        for _ in range(5):
            QTest.qWait(500)
            d.al_captura({"n": 8192, "pre": 0, "fs": 200e3, "disparado": 2, "ch1": saturada, "ch2": saturada})
            QTest.qWait(300)
        self.assertIn("se recortó", self.v.statusBar().currentMessage())
        dlg.reject()

    def test_ad9833_medir_reloj_con_el_frecuencimetro(self):
        enviados = self._dds_conectado({"dds_mclk": 25e6, "dds_mod": 1})
        d = self.v.tab_gen.dds
        d.mod.setCurrentText("PSK")
        self.v.tab_gen.reenviar_todo()
        enviados.clear()
        with mock.patch("panel_dds.QMessageBox.question", return_value=panel_dds.QMessageBox.Yes):
            d.medir_reloj()
        self.assertEqual(enviados[-2:], ["DDS 1000000.0000 2 1", "FCNT 1000 0"])
        self.assertIn("DDSMOD NO", enviados)
        self.assertFalse(d.btn_reloj.isEnabled())
        enviados.clear()
        f_med = M.dds_frecuencia_real(1e6) * 25.0004e6 / 25e6     # cristal real +16 ppm
        self.v._al_linea(f"FREQ {f_med:.6f} C {int(f_med)} 1000")
        self.assertAlmostEqual(d.c.mclk, 25.0004e6, delta=1)
        self.assertIn("ppm", self.v.statusBar().currentMessage())
        self.assertTrue(d.btn_reloj.isEnabled())
        self.v.tab_gen._enviar()                                  # vuelve a lo que estaba, con el reloj nuevo
        self.assertEqual(enviados[0], "DDSCLK 25000400.0")
        self.assertIn("DDSMOD PSK 180.000 100.0000", enviados)
        # una medición sin sentido no cambia el reloj
        with mock.patch("panel_dds.QMessageBox.question", return_value=panel_dds.QMessageBox.Yes):
            d.medir_reloj()
        self.v._al_linea("FREQ 0.000000 R 0 1000")
        self.assertAlmostEqual(d.c.mclk, 25.0004e6, delta=1)
        self.assertIn("revisá la conexión", self.v.statusBar().currentMessage())

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
