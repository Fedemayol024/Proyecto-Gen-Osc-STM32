"""Cálculos de la pestaña Termómetro NTC."""
import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))
import tab_termometro as T  # noqa: E402

G = 1 + 49.4 / 47
RS, VREF, VEXC, B = 5100.0, 1.65, 3.3, 3950.0


def circuito(tc):
    """Tensiones que da el circuito real con la NTC a tc °C."""
    r = 5000 * math.exp(B * (1 / (tc + 273.15) - 1 / 298.15))
    va = VEXC * RS / (RS + r)
    return VREF + G * (va - VREF), va, r


def test_ida_y_vuelta_resistencia():
    for tc in (10, 25, 33, 45):
        vo, va, r = circuito(tc)
        assert abs(T.tension_nodo(vo, G, VREF) - va) < 1e-12
        assert abs(T.resistencia_ntc(va, RS, VEXC) - r) / r < 1e-12


def test_calibracion_de_un_punto_recupera_la_temperatura():
    # calibrando a 24 °C, cualquier otra temperatura se recupera exacta con el mismo B
    vo_cal, _, _ = circuito(24.0)
    r_cal = T.resistencia_ntc(T.tension_nodo(vo_cal, G, VREF), RS, VEXC)
    for tc in (15, 24, 30, 33, 40):
        vo, _, _ = circuito(tc)
        r = T.resistencia_ntc(T.tension_nodo(vo, G, VREF), RS, VEXC)
        tk = T.temperatura_k(r, r_cal, 24 + 273.15, B)
        assert abs(tk - 273.15 - tc) < 1e-9


def test_calibracion_corrige_tolerancia_de_la_ntc():
    # una NTC que en realidad vale 5,4 kΩ a 25 °C (8 % arriba): sin calibrar se equivoca,
    # calibrada a la temperatura ambiente lee bien
    def vo_real(tc):
        r = 5400 * math.exp(B * (1 / (tc + 273.15) - 1 / 298.15))
        va = VEXC * RS / (RS + r)
        return VREF + G * (va - VREF)
    r = T.resistencia_ntc(T.tension_nodo(vo_real(32), G, VREF), RS, VEXC)
    sin_cal = T.temperatura_k(r, 5000, 298.15, B) - 273.15
    r_cal = T.resistencia_ntc(T.tension_nodo(vo_real(25), G, VREF), RS, VEXC)
    con_cal = T.temperatura_k(r, r_cal, 298.15, B) - 273.15
    assert abs(sin_cal - 32) > 1.0
    assert abs(con_cal - 32) < 1e-9


def test_unidades():
    assert abs(T.a_unidad(298.15, "°C") - 25) < 1e-12
    assert abs(T.a_unidad(298.15, "K") - 298.15) < 1e-12
    assert abs(T.a_unidad(298.15, "°F") - 77) < 1e-9


def test_fuera_de_rango():
    assert math.isnan(T.resistencia_ntc(0.0, RS, VEXC))
    assert math.isnan(T.resistencia_ntc(3.3, RS, VEXC))
    assert math.isnan(T.temperatura_k(float("nan"), 5000, 298.15, B))
    assert T.formato(float("nan")) == "—"
    assert T.formato(-1.5, 1) == "−1,5"
