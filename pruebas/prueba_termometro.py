"""Prueba de la pestaña Termómetro NTC contra el Nucleo simulado en modo "ntc".
Uso: python nucleo_simulado.py ntc   (en otra terminal; imprime el pty)
     python prueba_termometro.py <pty> <carpeta_capturas>"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["APPDATA"] = "/tmp/claude_instr_termo"
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))

import serial  # noqa: E402
serial.Serial._update_dtr_state = lambda self: None
serial.Serial._update_rts_state = lambda self: None

import main as A  # noqa: E402
import tab_termometro as TT  # noqa: E402
import widgets as W  # noqa: E402
from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication, QInputDialog  # noqa: E402

PTY, CAPS = sys.argv[1], sys.argv[2]
A.listar_puertos = lambda: [(PTY, f"{PTY} · Instrumento (USB del Nucleo)")]
# el multímetro "marca" 25,0 °C
QInputDialog.getDouble = staticmethod(lambda *a, **k: (25.0, True))

app = QApplication(sys.argv)
app.setStyleSheet(W.estilo())
v = A.Ventana(os.environ.get("SIM_PLACA", "F767"))
v.resize(1400, 880)
v.show()
t = v.tab_termo
pasos, res = [], []


def paso(ms, fn):
    pasos.append((ms, fn))


def ok(c, txt):
    res.append(("OK    " if c else "FALLA ") + txt)


def cap(nombre):
    app.processEvents()
    v.grab().save(os.path.join(CAPS, nombre))


def temp_c():
    return t.tk[-1] - 273.15 if t.tk else float("nan")


paso(300, lambda: v.alternar_conexion())
paso(2500, lambda: ok(v.disp.esta_conectado, "conecta"))
paso(100, lambda: (v.tabs.setCurrentWidget(t), t.e_int.set_valor(2.0)))
paso(1500, lambda: ok(not v.tab_osc.corriendo, "al entrar, el osciloscopio queda en pausa"))
paso(3500, lambda: ok(t.cal is not None and abs(t.cal["t_k"] - 298.15) < 1e-6,
                      f"calibrado: {t.lbl_cal.text()!r}"))
paso(1000, lambda: ok(abs(temp_c() - 25) < 0.3, f"en reposo lee {temp_c():.2f} °C (esperado 25)"))
paso(100, lambda: t._alternar_registro())
paso(100, lambda: cap("termo_1_reposo.png"))
paso(14000, lambda: ok(30 < temp_c() < 33.5, f"agarrando la NTC lee {temp_c():.2f} °C (esperado ~32)"))
paso(100, lambda: t.unidad.setCurrentText("K"))
paso(800, lambda: ok(t.lbl_temp.text().endswith("K"), f"en kelvin: {t.lbl_temp.text()}"))
paso(100, lambda: t.unidad.setCurrentText("°C"))
paso(800, lambda: cap("termo_2_calentando.png"))


def exportar():
    ruta = os.path.join(CAPS, "registro.csv")
    t.exportar_csv(ruta, "°F")
    filas = open(ruta, encoding="utf-8-sig").read().splitlines()
    ok(len(t.registro) >= 5, f"puntos registrados: {len(t.registro)}")
    ok(filas[0] == "Fecha;Hora;Temperatura [°F];Tensión CH1 [V]", f"encabezado CSV: {filas[0]}")
    ok(len(filas) == len(t.registro) + 1, f"filas CSV: {len(filas)}")
    print("\n".join(filas[:4]))


paso(100, exportar)
paso(8000, lambda: cap("termo_3_enfriando.png"))
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
