"""Genera los esquemáticos del hardware adicional para la NUCLEO-F767ZI."""
import schemdraw
import schemdraw.elements as elm

schemdraw.use("matplotlib")
schemdraw.config(fontsize=11, lw=1.3, font="DejaVu Sans")
GRIS = "#555555"


def nota(d, xy, texto, size=10):
    d.add(elm.Label().at(xy).label(texto, loc="right", fontsize=size, color=GRIS, halign="left"))


# ===========================================================================
# Hoja 1: salidas del generador
# ===========================================================================
def salida(d, y, nombre_pin, op, pines, refs, salida_txt):
    r_filtro, c_filtro, rf, rref, rgnd, rser = refs
    x0 = 0
    d.add(elm.Dot(open=True).at((x0, y)).label(nombre_pin, loc="left", fontsize=11))
    d.add(elm.Resistor().right(2.2).label(r_filtro, loc="top"))
    f = d.add(elm.Dot())
    d.add(elm.Capacitor().down(1.6).label(c_filtro, loc="bottom"))
    d.add(elm.Ground())
    d.add(elm.Line().at(f.center).right(1.2))
    o = d.add(elm.Opamp(leads=True, flip=True).right().anchor("in2").label(op, loc="center", fontsize=10))
    d.add(elm.Label().at(o.in2).label(pines[0], fontsize=8, ofst=(0.25, 0.25)))
    d.add(elm.Label().at(o.in1).label(pines[1], fontsize=8, ofst=(0.25, -0.3)))
    d.add(elm.Label().at(o.out).label(pines[2], fontsize=8, ofst=(-0.3, 0.3)))
    d.add(elm.Line().at(o.in1).left(0.6))
    d.add(elm.Line().down(1.3))
    nf = d.add(elm.Dot())
    d.add(elm.Resistor().right(o.out[0] + 0.8 - nf.center[0]).label(rf, loc="bottom"))
    d.add(elm.Line().toy(o.out[1]))
    d.add(elm.Dot())
    d.add(elm.Line().at(nf.center).down(1.0))
    nr = d.add(elm.Dot())
    d.add(elm.Resistor().at(nr.center).left(2.0).label(rref, loc="bottom"))
    d.add(elm.Vdd().label("3V3", fontsize=9))
    d.add(elm.Resistor().at(nr.center).down(2.0).label(rgnd, loc="bottom"))
    d.add(elm.Ground())
    d.add(elm.Line().at(o.out).right(0.8))
    d.add(elm.Resistor().right(2.2).label(rser, loc="top"))
    d.add(elm.Dot(open=True).label(salida_txt, loc="right", fontsize=12))


with schemdraw.Drawing(show=False) as d:
    d.config(unit=2.2)
    d.add(elm.Label().at((-1, 3.2)).label("Hoja 1 · Salidas del generador (±5 V)", loc="right", fontsize=15))
    salida(d, 0, "PA4 / D24\n(DAC1)", "U1A", ("3", "2", "1"),
           ("R1 330 Ω", "C1 1 nF", "R2 30 kΩ", "R3 15 kΩ", "R4 33 kΩ", "R5 47 Ω"), "OUT1  (BNC)")
    salida(d, -8, "PA5 / D13\n(DAC2)", "U1B", ("5", "6", "7"),
           ("R6 330 Ω", "C2 1 nF", "R7 30 kΩ", "R8 15 kΩ", "R9 33 kΩ", "R10 47 Ω"), "OUT2  (BNC)")
    nota(d, (-1, -15.4),
         "U1 = TL072 (o TL082 / NE5532) alimentado con ±12 V: pin 8 = +12 V, pin 4 = −12 V, 100 nF en cada pin a GND.\n"
         "Vout = Vdac · (1 + R2/R3 + R2/R4) − 3,3 V · R2/R3 = 3,909 · Vdac − 6,6 V  →  ±5 V con el DAC entre 0,41 V y 2,97 V\n"
         "(zona lineal del DAC del STM32). R1-C1: filtro de reconstrucción (~480 kHz). 3V3 = pin 3V3 del Nucleo (es la referencia del DAC).")
    d.save("hoja1_salidas.svg")
    d.save("hoja1_salidas.png", dpi=150)


# ===========================================================================
# Hoja 2: entradas del osciloscopio
# ===========================================================================
def entrada(d, y, nombre_in, refs, op, pines, pin_mcu):
    (sw_ac, c_ac, r1, ctrim, r2, r3, cx, dclamp, rf, rg, sw_x10, rs, cs) = refs
    d.add(elm.Dot(open=True).at((0, y)).label(nombre_in, loc="left", fontsize=12))
    d.add(elm.Line().right(0.6))
    a = d.add(elm.Dot())
    d.add(elm.Capacitor().right(2.0).label(c_ac, loc="bottom"))
    b = d.add(elm.Dot())
    d.add(elm.Line().at(a.center).up(1.0))
    d.add(elm.Switch().right(2.0).label(sw_ac, loc="top"))
    d.add(elm.Line().down(1.0))
    d.add(elm.Line().at(b.center).right(0.5))
    c = d.add(elm.Dot())
    d.add(elm.Resistor().right(2.6).label(r1, loc="bottom"))
    x = d.add(elm.Dot())
    d.add(elm.Line().at(c.center).up(1.2))
    d.add(elm.Capacitor(polar=False).right(2.6).label(ctrim, loc="top"))
    d.add(elm.Line().down(1.2))
    # red de polarización en el nodo X
    d.add(elm.Line().at(x.center).down(0.8))
    xb = d.add(elm.Dot())
    d.add(elm.Resistor().at(xb.center).down(2.0).label(r3, loc="bottom"))
    d.add(elm.Ground())
    d.add(elm.Line().at(xb.center).right(2.6))
    xc = d.add(elm.Dot())
    d.add(elm.Capacitor().at(xc.center).down(2.0).label(cx, loc="bottom"))
    d.add(elm.Ground())
    d.add(elm.Line().at(xc.center).right(2.4))
    xd = d.add(elm.Dot())
    d.add(elm.Diode().at(xd.center).down(2.0).reverse().label(dclamp + "\n(a GND)", loc="bottom", fontsize=9, ofst=0.15))
    d.add(elm.Ground())
    d.add(elm.Line().at(x.center).up(3.2))
    xu = d.add(elm.Dot())
    d.add(elm.Resistor().at(xu.center).left(2.4).label(r2, loc="top"))
    d.add(elm.Vdd().label("3V3", fontsize=9))
    d.add(elm.Diode().at(xu.center).right(2.4).label(dclamp + "\n(a 3V3)", loc="bottom", fontsize=9))
    d.add(elm.Vdd().label("3V3", fontsize=9))
    # amplificador
    d.add(elm.Line().at(x.center).right(7.0))
    o = d.add(elm.Opamp(leads=True, flip=True).right().anchor("in2").label(op, loc="center", fontsize=10))
    d.add(elm.Label().at(o.in2).label(pines[0], fontsize=8, ofst=(0.25, 0.25)))
    d.add(elm.Label().at(o.in1).label(pines[1], fontsize=8, ofst=(0.25, -0.3)))
    d.add(elm.Label().at(o.out).label(pines[2], fontsize=8, ofst=(-0.3, 0.3)))
    d.add(elm.Line().at(o.in1).left(0.6))
    d.add(elm.Line().down(1.3))
    nf = d.add(elm.Dot())
    d.add(elm.Resistor().right(o.out[0] + 0.8 - nf.center[0]).label(rf, loc="bottom"))
    d.add(elm.Line().toy(o.out[1]))
    d.add(elm.Dot())
    d.add(elm.Line().at(nf.center).down(0.8))
    d.add(elm.Resistor().down(1.8).label(rg, loc="bottom"))
    d.add(elm.Switch().down(1.6).label(sw_x10, loc="bottom"))
    d.add(elm.Line().down(0.4))
    d.add(elm.Dot(open=True).label("VREF 1,65 V", loc="bottom", fontsize=9))
    d.add(elm.Line().at(o.out).right(0.8))
    d.add(elm.Resistor().right(2.0).label(rs, loc="top"))
    s = d.add(elm.Dot())
    d.add(elm.Capacitor().at(s.center).down(1.6).label(cs, loc="bottom"))
    d.add(elm.Ground())
    d.add(elm.Line().at(s.center).right(1.0))
    d.add(elm.Dot(open=True).label(pin_mcu, loc="right", fontsize=12))


with schemdraw.Drawing(show=False) as d:
    d.config(unit=2.2)
    d.add(elm.Label().at((-1.5, 6.6)).label("Hoja 2 · Entradas del osciloscopio (±10 V / ±1 V, 1 MΩ)",
                                          loc="right", fontsize=15))
    entrada(d, 0, "IN1\n(BNC)",
            ("S1 DC", "C11 100 nF\n250 V", "R11 1 MΩ", "CT1 2–10 pF\n(trimmer)", "R12 300 kΩ",
             "R13 430 kΩ", "C12 22 pF", "D11 BAV99", "R14 9,1 kΩ", "R15 1 kΩ", "S2 ×10", "R16 100 Ω",
             "C13 470 pF"), "U2A", ("3", "2", "1"), "PA3 / A0\n(ADC1 IN3)")
    entrada(d, -12, "IN2\n(BNC)",
            ("S3 DC", "C21 100 nF\n250 V", "R21 1 MΩ", "CT2 2–10 pF\n(trimmer)", "R22 300 kΩ",
             "R23 430 kΩ", "C22 22 pF", "D21 BAV99", "R24 9,1 kΩ", "R25 1 kΩ", "S4 ×10", "R26 100 Ω",
             "C23 470 pF"), "U2B", ("5", "6", "7"), "PC0 / A1\n(ADC2 IN10)")

    # referencia 1,65 V
    yr = -22.5
    d.add(elm.Label().at((-1.5, yr + 1.6)).label("Referencia VREF = 1,65 V", loc="right", fontsize=12))
    d.add(elm.Vdd().at((0, yr)).label("3V3", fontsize=9))
    d.add(elm.Resistor().down(2.0).label("R30 10 kΩ", loc="bottom"))
    m = d.add(elm.Dot())
    d.add(elm.Resistor().down(2.0).label("R31 10 kΩ", loc="bottom"))
    d.add(elm.Ground())
    d.add(elm.Line().at(m.center).left(3.0))
    d.add(elm.Capacitor().down(2.0).label("C30 1 µF", loc="top"))
    d.add(elm.Ground())
    d.add(elm.Line().at(m.center).right(1.5))
    o = d.add(elm.Opamp(leads=True, flip=True).right().anchor("in2").label("U2C", loc="center", fontsize=10))
    d.add(elm.Label().at(o.in2).label("10", fontsize=8, ofst=(0.25, 0.25)))
    d.add(elm.Label().at(o.in1).label("9", fontsize=8, ofst=(0.25, -0.3)))
    d.add(elm.Label().at(o.out).label("8", fontsize=8, ofst=(-0.3, 0.3)))
    d.add(elm.Line().at(o.in1).left(0.5))
    d.add(elm.Line().down(1.2))
    d.add(elm.Line().right(o.out[0] + 0.6 - (o.in1[0] - 0.5)))
    d.add(elm.Line().toy(o.out[1]))
    d.add(elm.Line().at(o.out).right(1.5))
    d.add(elm.Dot(open=True).label("VREF 1,65 V", loc="right", fontsize=11))

    nota(d, (14, yr + 0.5),
         "U2 = MCP6024 (4 operacionales rail-to-rail, 10 MHz) alimentado con 3,3 V del Nucleo:\n"
         "pin 4 = 3V3, pin 11 = GND, 100 nF entre ambos. U2D sin usar: + a VREF, − a su salida.\n"
         "Como U2 se alimenta con 3,3 V, nunca entrega más de 3,3 V al ADC: protege al STM32.\n\n"
         "Nodo X: X = 1,65 V + 0,150 · Vin  (rango ±10 V con S2 abierta).\n"
         "S2 cerrada (×10): ganancia 10,1 alrededor de 1,65 V → rango ±1 V.\n"
         "S1 abierta = acople AC (C11); cerrada = DC. Impedancia de entrada ≈ 1,18 MΩ.\n"
         "CT1: ajustalo con una cuadrada de 1 kHz (PWM) hasta que los flancos queden rectos\n"
         "(igual que compensar una punta de osciloscopio). D11 = BAV99 (doble diodo: un\n"
         "diodo del nodo X a 3V3 y otro de GND al nodo X).", 10)
    d.save("hoja2_entradas.svg")
    d.save("hoja2_entradas.png", dpi=150)


# ===========================================================================
# Hoja 3: frecuencímetro, PWM y alimentación
# ===========================================================================
with schemdraw.Drawing(show=False) as d:
    d.config(unit=2.2)
    d.add(elm.Label().at((-1.5, 4.4)).label("Hoja 3 · Frecuencímetro, PWM y alimentación", loc="right", fontsize=15))

    # Frecuencímetro
    d.add(elm.Label().at((-1.5, 2.9)).label("Entrada del frecuencímetro", loc="right", fontsize=12))
    d.add(elm.Dot(open=True).at((0, 0)).label("FREC\n(BNC)", loc="left", fontsize=11))
    d.add(elm.Resistor().right(2.4).label("R40 1 kΩ", loc="top"))
    n = d.add(elm.Dot())
    d.add(elm.Line().right(2.4))
    n2 = d.add(elm.Dot())
    d.add(elm.Line().right(1.0))
    d.add(elm.Dot(open=True).label("PA0 / D32\n(TIM2)", loc="right", fontsize=11))
    d.add(elm.Diode().at(n.center).up(1.6).label("D40\nBAV99", loc="bottom", fontsize=9))
    d.add(elm.Vdd().label("3V3", fontsize=9))
    d.add(elm.Diode().at(n.center).down(1.6).reverse())
    d.add(elm.Ground())
    d.add(elm.Resistor().at(n2.center).down(2.0).label("R41 100 kΩ", loc="bottom"))
    d.add(elm.Ground())
    nota(d, (12, 0.6), "Señales lógicas de 0 a 3,3 V (o 5 V: los diodos y R40 limitan).\n"
                       "Para medir señales analógicas chicas, agregar un comparador\n"
                       "rápido con histéresis (p. ej. TLV3501) antes de R40.")

    # PWM
    y = -6
    d.add(elm.Label().at((-1.5, y + 1.8)).label("Salidas PWM complementarias", loc="right", fontsize=12))
    d.add(elm.Dot(open=True).at((0, y)).label("PE9 / D6\n(TIM1_CH1)", loc="left", fontsize=11))
    d.add(elm.Resistor().right(2.4).label("R50 100 Ω", loc="top"))
    d.add(elm.Dot(open=True).label("PWM_H", loc="right", fontsize=11))
    d.add(elm.Dot(open=True).at((0, y - 2.4)).label("PE8 / D42\n(TIM1_CH1N)", loc="left", fontsize=11))
    d.add(elm.Resistor().right(2.4).label("R51 100 Ω", loc="top"))
    d.add(elm.Dot(open=True).label("PWM_L", loc="right", fontsize=11))
    nota(d, (12, y - 0.6), "3,3 V, hasta decenas de MHz. Para manejar MOSFET/IGBT usar un\n"
                           "driver de compuertas (IR2110, UCC27211…), nunca el pin directo.")

    # Alimentación
    y = -15
    d.add(elm.Label().at((-1.5, y + 4.4)).label("Alimentación ±12 V para U1", loc="right", fontsize=12))
    d.add(elm.Dot(open=True).at((0, y)).label("5V del Nucleo\n(CN8)", loc="left", fontsize=11))
    d.add(elm.Line().right(1.5))
    p5 = d.add(elm.Dot())
    d.add(elm.Capacitor().down(1.8).label("C60\n10 µF", loc="bottom", fontsize=9))
    d.add(elm.Ground())
    d.add(elm.Line().at(p5.center).right(1.5))
    ic = d.add(elm.Ic(pins=[elm.IcPin(name="0V", side="left"), elm.IcPin(name="Vin", side="left"),
                            elm.IcPin(name="−Vo", side="right"), elm.IcPin(name="COM", side="right"),
                            elm.IcPin(name="+Vo", side="right")],
                      size=(3.6, 4.2)).anchor("Vin"))
    d.add(elm.Label().at((ic.center[0], ic.center[1] + 2.8)).label("DC-DC A0512S-1W  (5 V → ±12 V)", fontsize=10))
    d.add(elm.Line().at(ic["0V"]).left(0.6))
    d.add(elm.Ground())
    d.add(elm.Line().at(ic["+Vo"]).right(2.0))
    pp = d.add(elm.Dot())
    d.add(elm.Line().right(1.6))
    d.add(elm.Dot(open=True).label("+12 V  (U1 pin 8)", loc="right", fontsize=11))
    d.add(elm.Capacitor().at(pp.center).down(1.1).label("C61 10 µF", loc="bottom", fontsize=9, ofst=(0.9, 0)))
    d.add(elm.Ground())
    d.add(elm.Line().at(ic["COM"]).right(0.8))
    d.add(elm.Ground())
    d.add(elm.Line().at(ic["−Vo"]).right(2.0))
    pn = d.add(elm.Dot())
    d.add(elm.Line().right(1.6))
    d.add(elm.Dot(open=True).label("−12 V  (U1 pin 4)", loc="right", fontsize=11))
    d.add(elm.Capacitor().at(pn.center).down(1.1).label("C62 10 µF", loc="bottom", fontsize=9, ofst=(0.9, 0)))
    d.add(elm.Ground())
    nota(d, (-1.5, y - 7.2),
         "COM del módulo = GND del Nucleo (masa común con todo el circuito).\n"
         "Alternativas: fuente partida de laboratorio ±12 V, o dos baterías de 9 V (±9 V también sirve para U1).\n"
         "U2 (MCP6024) y las referencias usan el 3V3 del Nucleo. Consumo total < 100 mA del USB.")
    d.save("hoja3_frecuencimetro_pwm_alimentacion.svg")
    d.save("hoja3_frecuencimetro_pwm_alimentacion.png", dpi=150)
print("ok")
