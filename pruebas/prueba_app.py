"""Prueba de la app contra el Nucleo simulado (Linux, sin pantalla).
Uso: python prueba_app.py <pty> <carpeta_capturas> <lazo|bode>"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["APPDATA"] = "/tmp/claude_instr_test"
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))

import serial  # noqa: E402
serial.Serial._update_dtr_state = lambda self: None
serial.Serial._update_rts_state = lambda self: None

import main as A  # noqa: E402
import widgets as W  # noqa: E402
from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

PTY, CAPS, MODO = sys.argv[1], sys.argv[2], sys.argv[3]
A.listar_puertos = lambda: [(PTY, f"{PTY} · Instrumento (USB del Nucleo)")]

app = QApplication(sys.argv)
app.setStyleSheet(W.ESTILO)
v = A.Ventana(os.environ.get("SIM_PLACA", "F767"))
v.resize(1400, 880)
v.show()
pasos, res = [], []


def paso(ms, fn):
    pasos.append((ms, fn))


def ok(c, t):
    res.append(("OK    " if c else "FALLA ") + t)


def cap(nombre, tab=None):
    if tab is not None:
        v.tabs.setCurrentIndex(tab)
    app.processEvents()
    v.grab().save(os.path.join(CAPS, nombre))


def gen(c, **kw):
    p = v.tab_gen.paneles[c]
    for k, val in kw.items():
        if k == "forma":
            p.forma.setCurrentText(val)
        elif k == "hab":
            p.hab.setChecked(val)
        else:
            getattr(p, k).set_valor(val)
    p._cambio()


paso(300, lambda: v.alternar_conexion())
paso(2500, lambda: ok(v.disp.esta_conectado, f"conecta: {v.lbl_con.text()}"))

if MODO == "lazo":
    paso(100, lambda: gen(1, forma="Senoidal", hab=True, frec=1000, vpp=4.0, offset=0.5))
    paso(100, lambda: gen(2, forma="Cuadrada", hab=True, frec=3000, vpp=2.0, offset=-1.0, ciclo=25))
    paso(1200, lambda: ok(v.tab_gen.paneles[1].frec_real is not None, "generador confirma frecuencia"))
    paso(100, lambda: v.tab_osc._autoset())
    paso(4000, lambda: ok(v.tab_osc.corriendo and v.tab_osc.ultimo is not None, "autoset y captura corriendo"))
    paso(1500, lambda: ok(v.tab_osc.ultimo["disparado"] == 1, "cuadro disparado"))
    def medir():
        import modelo as M
        u = v.tab_osc.ultimo
        m1, m2 = M.medir(u[1], u["fs"]), M.medir(u[2], u["fs"])
        ok(abs(m1["frec"] - 1000) < 5, f"CH1 frecuencia medida {m1['frec']:.2f} Hz")
        ok(abs(m1["vpp"] - 4.0) < 0.15, f"CH1 Vpp medido {m1['vpp']:.3f} V")
        ok(abs(m1["media"] - 0.5) < 0.05, f"CH1 media {m1['media']:.3f} V")
        ok(abs(m2["ciclo"] - 25) < 2, f"CH2 ciclo útil {m2['ciclo']:.1f} %")
    paso(100, medir)
    paso(100, lambda: cap("1_osciloscopio.png", 0))
    paso(100, lambda: (v.tab_osc.chk_fft.setChecked(True), v.tab_osc.chk_cur.setChecked(True)))
    paso(1500, lambda: cap("2_osciloscopio_fft_cursores.png", 0))
    paso(100, lambda: (v.tab_osc.chk_fft.setChecked(False), v.tab_osc.chk_cur.setChecked(False),
                       v.tab_osc.modo_xy.setChecked(True), gen(2, forma="Senoidal", frec=1000, fase=90, vpp=4, offset=0),
                       v.tab_osc.canales[2].vdiv.setCurrentIndex(9), v.tab_osc.canales[2].pos.set_valor(0, True),
                       v.tab_osc.canales[1].pos.set_valor(0, True)))
    paso(2000, lambda: cap("3_xy.png", 0))
    paso(100, lambda: v.tab_osc.modo_xy.setChecked(False))
    paso(100, lambda: cap("4_generador.png", 1))
    paso(100, lambda: (v.tabs.setCurrentIndex(3), v.tab_herr.btn_f.setChecked(True), v.tab_herr._alternar_f(),
                       v.tab_herr.btn_pwm.setChecked(True), v.tab_herr._enviar_pwm()))
    paso(2500, lambda: ok("Hz" in v.tab_herr.lbl_f.text() and "—" not in v.tab_herr.lbl_f.text(),
                          f"frecuencímetro: {v.tab_herr.lbl_f.text()}"))
    paso(100, lambda: ok("Real" in v.tab_herr.lbl_pwm.text(), f"PWM: {v.tab_herr.lbl_pwm.text()}"))
    paso(100, lambda: cap("5_herramientas.png", 3))
    paso(100, lambda: (v.tabs.setCurrentIndex(4), v.tab_cal._autocal()))
    paso(4000, lambda: ok("mV/código" in v.tab_cal.lbl_e.text(), f"autocalibración: {v.tab_cal.lbl_e.text()!r}"))
    paso(100, lambda: cap("6_calibracion.png", 4))
else:
    paso(100, lambda: (v.tabs.setCurrentIndex(2), v.tab_bode.f1.set_valor(50), v.tab_bode.f2.set_valor(50e3),
                       v.tab_bode.ppd.setCurrentText("10"), v.tab_bode.amp.set_valor(4.0)))
    paso(100, lambda: v.tab_bode._alternar())
    def esperar_bode(intentos=[0]):
        if v.tab_bode.activo and intentos[0] < 120:
            intentos[0] += 1
            QTimer.singleShot(500, esperar_bode)
            return
        import numpy as np
        arr = np.array(v.tab_bode.resultados)
        ok(len(arr) >= 25, f"puntos de Bode: {len(arr)}")
        i = np.argmin(abs(arr[:, 0] - 1000))
        ok(abs(arr[i, 1] + 3.0) < 0.8, f"ganancia en {arr[i,0]:.0f} Hz: {arr[i,1]:.2f} dB (esperado ≈ −3)")
        ok(abs(arr[i, 2] + 45) < 6, f"fase en {arr[i,0]:.0f} Hz: {arr[i,2]:.1f}° (esperado ≈ −45)")
        ok(abs(arr[-1, 2] + 90) < 15, f"fase a {arr[-1,0]:.0f} Hz: {arr[-1,2]:.1f}° (esperado → −90)")
        ok("corte" in v.tab_bode.lbl_res.text(), v.tab_bode.lbl_res.text().replace("\n", " | "))
        cap("7_bode.png", 2)
        v.close()
    paso(500, esperar_bode)

if MODO == "lazo":
    paso(200, lambda: v.close())


def correr(i=0):
    if i >= len(pasos):
        return
    ms, fn = pasos[i]
    def f():
        try:
            fn()
        except Exception as e:  # noqa: BLE001
            import traceback
            traceback.print_exc()
            res.append(f"FALLA excepción en paso {i}: {e}")
        correr(i + 1)
    QTimer.singleShot(ms, f)


correr()
app.exec()
print("\n".join(res))
