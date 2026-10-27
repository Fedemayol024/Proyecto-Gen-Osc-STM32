"""Pestaña Placa: capacidades, límites, pines y conexiones de cada placa.

Los pines son los mismos en las dos Nucleo-144 (conectores ST Zio, manual
UM1974 de ST). Lo que cambia entre placas son las velocidades.
"""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (QComboBox, QHBoxLayout, QLabel, QScrollArea, QSizePolicy,
                               QTabWidget, QVBoxLayout, QWidget)

import modelo as M
import widgets as W

# ---------------------------------------------------------------------------
# Datos de cada placa
# ---------------------------------------------------------------------------
# (sección, parámetro, valor F767, valor F429). None = igual en ambas (se repite).
ESPEC = [
    ("Placa", "Micro", "STM32F767ZI · Cortex-M7 · 216 MHz", "STM32F429ZI · Cortex-M4 · 168 MHz"),
    ("Placa", "RAM", "512 KB", "256 KB (192 KB usables por DMA)"),
    ("Placa", "Conexión con la PC", "USB USER (CN13), Full Speed 12 Mbit/s", None),

    ("Generador", "Canales", "2, DAC de 12 bits (4096 niveles)", None),
    ("Generador", "Muestreo", "1 MS/s por canal", None),
    ("Generador", "Frecuencia", "0,01 Hz a 450 kHz (límite del firmware)", None),
    ("Generador", "Frecuencia útil", "hasta ~100 kHz con buena forma (≥ 10 puntos por ciclo)", None),
    ("Generador", "Resolución de frecuencia", "0,23 mHz (1 MS/s ÷ 2³²)", None),
    ("Generador", "Salida pin directo", "0,2 a 3,1 V · carga ≥ 5 kΩ", None),
    ("Generador", "Salida con la placa", "±5 V · pasos de ~3 mV", None),
    ("Generador", "Extras", "AM, FM, barrido lineal/log, forma arbitraria (CSV), fase entre canales", None),

    ("Osciloscopio", "Canales", "2 simultáneos (ADC1 + ADC2), 12 bits", None),
    ("Osciloscopio", "Muestreo máximo", "1,59 MS/s (ADC a 27 MHz)", "1,24 MS/s (ADC a 21 MHz)"),
    ("Osciloscopio", "Ancho de banda útil", "~200 kHz (≥ 8 muestras por ciclo)", "~150 kHz (≥ 8 muestras por ciclo)"),
    ("Osciloscopio", "Límite de Nyquist", "~790 kHz", "~620 kHz"),
    ("Osciloscopio", "Buffer de captura", "32 768 muestras por canal", "16 384 muestras por canal"),
    ("Osciloscopio", "Ventana en pantalla", "hasta 8192 puntos", None),
    ("Osciloscopio", "Base de tiempo", "2 µs/div a 1 s/div", None),
    ("Osciloscopio", "Entrada pin directo", "0 a 3,3 V — nunca más ni negativo", None),
    ("Osciloscopio", "Entrada con la placa", "±10 V o ±1 V (×10), 1 MΩ, acople AC/DC", None),

    ("Bode", "Rango", "~1 Hz a ~100 kHz (lo limita el generador)", None),
    ("Bode", "Rango dinámico", "~60 dB (ADC de 12 bits con ajuste senoidal)", None),

    ("Frecuencímetro", "Entrada", "D32 (PA0), señal lógica de 0 a 3,3 V", None),
    ("Frecuencímetro", "Rango", "fracciones de Hz a decenas de MHz", None),
    ("Frecuencímetro", "Resolución (recíproco)", "9,3 ns (timer a 108 MHz)", "11,9 ns (timer a 84 MHz)"),

    ("PWM", "Salidas", "D6 (PE9) y D42 (PE8, complementaria)", None),
    ("PWM", "Resolución de tiempo", "4,6 ns (timer a 216 MHz)", "6,0 ns (timer a 168 MHz)"),
    ("PWM", "Frecuencia máxima", "~54 MHz (con poco ajuste de ciclo útil)", "~42 MHz (con poco ajuste de ciclo útil)"),
    ("PWM", "Tiempo muerto", "0 a 4,7 µs", "0 a 6,0 µs"),
]

LIMITES = [
    "<b>Pines de entrada (A0, A1, D32): solo de 0 a 3,3 V.</b> Una tensión negativa o mayor "
    "puede dañar el micro. Para señales reales usá la etapa de entrada (Hoja 2 del hardware).",
    "<b>Las salidas del DAC (D24, D13) no manejan cargas bajas.</b> Con menos de ~5 kΩ la "
    "señal se deforma. Para manejar un circuito usá la etapa de salida (Hoja 1).",
    "<b>Arriba de ~100 kHz el generador tiene pocos puntos por ciclo</b>: el seno se ve escalonado "
    "y la cuadrada pierde flancos.",
    "<b>El osciloscopio no reemplaza a uno de laboratorio</b>: para ver más de ~200 kHz en tiempo "
    "real hace falta otro ADC o un osciloscopio comercial.",
    "<b>La masa de la placa es la de la PC</b> (por el USB). No midas nada conectado a 220 V ni "
    "circuitos con otra referencia de masa.",
    "<b>Hacen falta dos cables USB</b>: el del ST-LINK (CN1) para programar y alimentar, y el "
    "USB USER (CN13) para la app.",
]

# ---------------------------------------------------------------------------
# Conectores ST Zio (UM1974). Iguales en NUCLEO-F767ZI y NUCLEO-F429ZI.
# ---------------------------------------------------------------------------
CN8 = {1: "NC", 2: "D43", 3: "IOREF", 4: "D44", 5: "RESET", 6: "D45", 7: "+3V3", 8: "D46",
       9: "+5V", 10: "D47", 11: "GND", 12: "D48", 13: "GND", 14: "D49", 15: "VIN", 16: "D50"}
CN9 = {1: "A0", 2: "D51", 3: "A1", 4: "D52", 5: "A2", 6: "D53", 7: "A3", 8: "D54", 9: "A4",
       10: "D55", 11: "A5", 12: "GND", 13: "D72", 14: "D56", 15: "D71", 16: "D57", 17: "D70",
       18: "D58", 19: "D69", 20: "D59", 21: "D68", 22: "D60", 23: "GND", 24: "D61", 25: "D67",
       26: "D62", 27: "D66", 28: "D63", 29: "D65", 30: "D64"}
CN7 = {1: "D16", 2: "D15", 3: "D17", 4: "D14", 5: "D18", 6: "AREF", 7: "D19", 8: "GND",
       9: "D20", 10: "D13", 11: "D21", 12: "D12", 13: "D22", 14: "D11", 15: "D23", 16: "D10",
       17: "D24", 18: "D9", 19: "D25", 20: "D8"}
CN10 = {1: "AVDD", 2: "D7", 3: "AGND", 4: "D6", 5: "GND", 6: "D5", 7: "A6", 8: "D4", 9: "A7",
        10: "D3", 11: "A8", 12: "D2", 13: "D26", 14: "D1", 15: "D27", 16: "D0", 17: "GND",
        18: "D42", 19: "D28", 20: "D41", 21: "D29", 22: "GND", 23: "D30", 24: "D40", 25: "D31",
        26: "D39", 27: "GND", 28: "D38", 29: "D32", 30: "D37", 31: "D33", 32: "D36", 33: "D34",
        34: "D35"}

C_GEN = "#ff9e3d"
C_FREC = "#c58cff"
C_PWM = "#56d364"
C_GND = "#8b949e"
C_3V3 = "#f85149"

# (conector, pin) -> (rótulo, pin del micro, función, color)
USADOS = {
    ("CN9", 1): ("A0", "PA3", "Osciloscopio CH1", W.CH1),
    ("CN9", 3): ("A1", "PC0", "Osciloscopio CH2", W.CH2),
    ("CN7", 17): ("D24", "PA4", "Generador CH1", C_GEN),
    ("CN7", 10): ("D13", "PA5", "Generador CH2", C_GEN),
    ("CN10", 29): ("D32", "PA0", "Frecuencímetro", C_FREC),
    ("CN10", 4): ("D6", "PE9", "PWM", C_PWM),
    ("CN10", 18): ("D42", "PE8", "PWM complementario", C_PWM),
    ("CN8", 7): ("+3V3", "", "Referencia de las etapas", C_3V3),
    ("CN9", 12): ("GND", "", "Masa", C_GND),
}


def _pin_color(nombre: str):
    if nombre in ("GND", "AGND"):
        return C_GND
    if nombre in ("+3V3", "+5V", "VIN", "AVDD", "IOREF"):
        return "#a1585a"
    return None


# ---------------------------------------------------------------------------
# Dibujo de la placa
# ---------------------------------------------------------------------------
class DibujoPlaca(QWidget):
    """Vista superior esquemática (no a escala) de una Nucleo-144, con el ST-LINK arriba."""

    MARGEN = 250          # lugar para los rótulos a cada lado (px)
    ANCHO_ROT = 215
    ALTO_ROT = 38

    def __init__(self):
        super().__init__()
        self.placa = M.PLACA_POR_DEFECTO
        self.setMinimumSize(900, 700)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def set_placa(self, placa):
        self.placa = placa
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor(W.FONDO))
        w, h = self.width(), self.height()
        alto = h - 50
        ancho = alto * 70 / 133
        if ancho > w - 2 * self.MARGEN:
            ancho = w - 2 * self.MARGEN
            alto = ancho * 133 / 70
        x0, y0 = (w - ancho) / 2, (h - alto) / 2
        mm = ancho / 70.0
        self._mm, self._x0, self._ancho = mm, x0, ancho
        chica = QFont("Segoe UI", 8)

        # cuerpo de la placa
        p.setPen(QPen(QColor("#2f3a2f"), 2))
        p.setBrush(QColor("#e9ecef"))
        p.drawRoundedRect(QRectF(x0, y0, ancho, alto), 3 * mm, 3 * mm)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#dde2e7"))
        p.drawRect(QRectF(x0 + 1, y0 + 1, ancho - 2, 21 * mm))
        p.setPen(QPen(QColor("#9aa4ae"), 1, Qt.DashLine))
        p.drawLine(QPointF(x0, y0 + 22 * mm), QPointF(x0 + ancho, y0 + 22 * mm))

        # USB del ST-LINK (arriba) y textos
        self._caja(p, QRectF(x0 + 28 * mm, y0 - 2 * mm, 14 * mm, 7 * mm))
        p.setFont(chica)
        p.setPen(QColor("#374151"))
        p.drawText(QRectF(x0, y0 + 6 * mm, ancho, 5 * mm), Qt.AlignCenter, "CN1 · USB ST-LINK")
        p.drawText(QRectF(x0, y0 + 11 * mm, ancho, 5 * mm), Qt.AlignCenter,
                   "programar y alimentar")
        # nombre
        p.setPen(QColor("#1f2937"))
        p.setFont(QFont("Segoe UI", 12, QFont.Bold))
        p.drawText(QRectF(x0, y0 + 24 * mm, ancho, 7 * mm), Qt.AlignCenter, M.nombre_placa(self.placa))
        # micro
        cx, cy = x0 + 35 * mm, y0 + 82 * mm
        p.setBrush(QColor("#22272e"))
        p.setPen(Qt.NoPen)
        p.drawRect(QRectF(cx - 9 * mm, cy - 9 * mm, 18 * mm, 18 * mm))
        p.setPen(QColor("#d0d7de"))
        p.setFont(chica)
        p.drawText(QRectF(cx - 9 * mm, cy - 9 * mm, 18 * mm, 18 * mm), Qt.AlignCenter,
                   M.nombre_placa(self.placa).replace("NUCLEO-", "STM32\n"))
        # abajo: Ethernet, USB USER, LED azul
        eth = QRectF(x0 + 12 * mm, y0 + alto - 10 * mm, 16 * mm, 11 * mm)
        usb = QRectF(x0 + 40 * mm, y0 + alto - 5 * mm, 12 * mm, 6 * mm)
        self._caja(p, eth)
        self._caja(p, usb)
        p.setPen(QColor("#374151"))
        p.setFont(chica)
        p.drawText(QRectF(eth.left() - 6 * mm, eth.top() - 5 * mm, eth.width() + 12 * mm, 4.5 * mm),
                   Qt.AlignCenter, "Ethernet")
        p.drawText(QRectF(usb.left() - 10 * mm, usb.top() - 5 * mm, usb.width() + 20 * mm, 4.5 * mm),
                   Qt.AlignCenter, "CN13 · USB USER (app)")
        p.setBrush(QColor("#3b82f6"))
        p.setPen(Qt.NoPen)
        led = QPointF(x0 + 58 * mm, y0 + alto - 16 * mm)
        p.drawEllipse(led, 1.3 * mm, 1.3 * mm)
        p.setPen(QColor("#374151"))
        p.drawText(QPointF(led.x() + 2.5 * mm, led.y() + 1.2 * mm), "LD2")

        # conectores
        paso = 2.54 * mm
        rot_izq, rot_der = [], []
        self._conector(p, "CN8", CN8, x0 + 5 * mm, y0 + 36 * mm, paso, rot_izq)
        self._conector(p, "CN9", CN9, x0 + 5 * mm, y0 + 62 * mm, paso, rot_izq)
        self._conector(p, "CN7", CN7, x0 + ancho - 5 * mm - 2 * paso, y0 + 34 * mm, paso, rot_der)
        self._conector(p, "CN10", CN10, x0 + ancho - 5 * mm - 2 * paso, y0 + 66 * mm, paso, rot_der)
        self._rotulos(p, rot_izq, izquierda=True)
        self._rotulos(p, rot_der, izquierda=False)
        p.end()

    def _caja(self, p, r):
        p.setBrush(QColor("#b9c0c7"))
        p.setPen(QPen(QColor("#6b7280"), 1))
        p.drawRect(r)

    def _conector(self, p, nombre, pines, x, y, paso, rotulos):
        filas = len(pines) // 2
        p.setBrush(QColor("#111827"))
        p.setPen(Qt.NoPen)
        p.drawRect(QRectF(x, y, 2 * paso, filas * paso))
        p.setPen(QColor("#374151"))
        p.setFont(QFont("Segoe UI", 9, QFont.Bold))
        p.drawText(QRectF(x - 20, y - 18, 2 * paso + 40, 16), Qt.AlignCenter, nombre)
        for fila in range(filas):
            for col in range(2):                       # impar a la izquierda, par a la derecha
                num = 2 * fila + 1 + col
                c = QPointF(x + paso * (0.5 + col), y + paso * (0.5 + fila))
                usado = USADOS.get((nombre, num))
                color = usado[3] if usado else _pin_color(pines[num])
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(color) if color else QColor("#c9a227"))
                r = paso * (0.38 if usado else 0.22)
                p.drawEllipse(c, r, r)
                if usado:
                    rotulos.append((c, usado, f"{nombre}-{num}"))
        p.setPen(QPen(QColor("#e5e7eb"), 1))         # marca del pin 1
        p.setBrush(Qt.NoBrush)
        p.drawRect(QRectF(x + 0.08 * paso, y + 0.08 * paso, 0.84 * paso, 0.84 * paso))

    def _rotulos(self, p, rotulos, izquierda):
        """Ubica los rótulos al costado de la placa sin que se pisen."""
        rotulos.sort(key=lambda r: r[0].y())
        y_libre = -1e9
        for c, (rot, pin, funcion, color), cn in rotulos:
            y = max(c.y() - self.ALTO_ROT / 2, y_libre)
            y_libre = y + self.ALTO_ROT + 6
            if izquierda:
                caja = QRectF(self._x0 - 24 - self.ANCHO_ROT, y, self.ANCHO_ROT, self.ALTO_ROT)
                ancla = QPointF(caja.right(), caja.center().y())
                codo = QPointF(self._x0 - 10, caja.center().y())
            else:
                caja = QRectF(self._x0 + self._ancho + 24, y, self.ANCHO_ROT, self.ALTO_ROT)
                ancla = QPointF(caja.left(), caja.center().y())
                codo = QPointF(self._x0 + self._ancho + 10, caja.center().y())
            path = QPainterPath(c)
            path.lineTo(QPointF(codo.x(), c.y()))
            path.lineTo(codo)
            path.lineTo(ancla)
            p.setPen(QPen(QColor(color), 1.6))
            p.setBrush(Qt.NoBrush)
            p.drawPath(path)
            p.setBrush(QColor(W.PANEL))
            p.drawRoundedRect(caja, 6, 6)
            p.setPen(QColor(color))
            p.setFont(QFont("Segoe UI", 9, QFont.Bold))
            p.drawText(caja.adjusted(8, 3, -6, -18), Qt.AlignLeft | Qt.AlignVCenter, f"{rot}  ·  {funcion}")
            p.setPen(QColor(W.TENUE))
            p.setFont(QFont("Segoe UI", 8))
            sub = f"{pin}  ·  {cn}" if pin else cn
            p.drawText(caja.adjusted(8, 19, -6, -2), Qt.AlignLeft | Qt.AlignVCenter, sub)


# ---------------------------------------------------------------------------
# Diagramas de conexión
# ---------------------------------------------------------------------------
ESQUEMAS = {
    "Prueba rápida: generador → osciloscopio": [
        ("nucleo", "D24 · Gen CH1", "A0 · Osc CH1", None, W.CH1),
        ("nucleo", "D13 · Gen CH2", "A1 · Osc CH2", None, W.CH2),
    ],
    "Bode de un circuito": [
        ("bode",),
    ],
    "Medir una señal externa": [
        ("externa",),
    ],
    "Frecuencímetro y PWM": [
        ("frecpwm",),
    ],
}


class DibujoConexiones(QWidget):
    def __init__(self):
        super().__init__()
        self.esquema = next(iter(ESQUEMAS))
        self.setMinimumSize(760, 420)

    def set_esquema(self, nombre):
        self.esquema = nombre
        self.update()

    # --- utilidades
    def _bloque(self, p, r: QRectF, titulo, sub="", color="#30363d"):
        p.setPen(QPen(QColor(color), 2))
        p.setBrush(QColor(W.PANEL))
        p.drawRoundedRect(r, 10, 10)
        p.setPen(QColor(W.TEXTO))
        p.setFont(QFont("Segoe UI", 11, QFont.Bold))
        p.drawText(r.adjusted(8, 8, -8, -8), Qt.AlignHCenter | Qt.AlignTop, titulo)
        if sub:
            p.setPen(QColor(W.TENUE))
            p.setFont(QFont("Segoe UI", 9))
            p.drawText(r.adjusted(8, 30, -8, -8), Qt.AlignHCenter | Qt.AlignTop | Qt.TextWordWrap, sub)

    def _pin(self, p, pt: QPointF, texto, color, derecha=True):
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(color))
        p.drawEllipse(pt, 5, 5)
        p.setPen(QColor(W.TEXTO))
        p.setFont(QFont("Segoe UI", 9))
        if derecha:
            p.drawText(QRectF(pt.x() + 9, pt.y() - 10, 170, 20), Qt.AlignVCenter | Qt.AlignLeft, texto)
        else:
            p.drawText(QRectF(pt.x() - 179, pt.y() - 10, 170, 20), Qt.AlignVCenter | Qt.AlignRight, texto)

    def _cable(self, p, puntos, color, etiqueta=""):
        p.setPen(QPen(QColor(color), 2.4))
        p.setBrush(Qt.NoBrush)
        path = QPainterPath(puntos[0])
        for q in puntos[1:]:
            path.lineTo(q)
        p.drawPath(path)
        if etiqueta:
            m = puntos[len(puntos) // 2]
            p.setPen(QColor(color))
            p.setFont(QFont("Segoe UI", 9))
            p.drawText(QRectF(m.x() - 90, m.y() - 22, 180, 18), Qt.AlignCenter, etiqueta)

    def _nucleo(self, p, r: QRectF):
        self._bloque(p, r, "Nucleo", "")
        # USB USER hacia la PC
        pc = QRectF(r.left() + r.width() / 2 - 60, r.top() - 95, 120, 50)
        self._bloque(p, pc, "PC · app")
        self._cable(p, [QPointF(pc.center().x(), pc.bottom()), QPointF(r.center().x(), r.top())],
                    "#6e7681")
        p.setPen(QColor(W.TENUE))
        p.setFont(QFont("Segoe UI", 9))
        p.drawText(QRectF(r.center().x() + 6, pc.bottom() + 6, 200, 18), Qt.AlignLeft,
                   "USB USER (CN13)")

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor(W.FONDO))
        w, h = self.width(), self.height()
        tipo = ESQUEMAS[self.esquema][0][0]
        nuc = QRectF(40, 130, 220, max(220, h - 200))
        self._nucleo(p, nuc)
        x_pin = nuc.right()

        def pin_n(i, n=4):
            return QPointF(x_pin, nuc.top() + 50 + i * (nuc.height() - 70) / max(1, n - 1))

        if tipo == "nucleo":
            pins = [(pin_n(0), "D24 · Gen CH1", C_GEN), (pin_n(1), "D13 · Gen CH2", C_GEN),
                    (pin_n(2), "A0 · Osc CH1", W.CH1), (pin_n(3), "A1 · Osc CH2", W.CH2)]
            for pt, t, c in pins:
                self._pin(p, pt, t, c, derecha=False)
            xr = x_pin + 140
            self._cable(p, [pins[0][0], QPointF(xr, pins[0][0].y()), QPointF(xr, pins[2][0].y()),
                            pins[2][0]], W.CH1, "")
            self._cable(p, [pins[1][0], QPointF(xr + 60, pins[1][0].y()), QPointF(xr + 60, pins[3][0].y()),
                            pins[3][0]], W.CH2, "")
            self._nota(p, QRectF(xr + 110, nuc.top(), w - xr - 130, nuc.height()),
                       "Un cable de D24 a A0 y otro de D13 a A1. No hace falta masa: es la misma placa.\n\n"
                       "En la app: Generador y Osciloscopio en «Pin directo». Generador con offset ≥ "
                       "la mitad de la amplitud (por ejemplo 2 Vpp con 1,65 V), porque los pines solo van "
                       "de 0 a 3,3 V.")
        elif tipo == "bode":
            pins = [(pin_n(0), "D24 · Gen CH1", C_GEN), (pin_n(1), "A0 · Osc CH1 (entrada)", W.CH1),
                    (pin_n(2), "A1 · Osc CH2 (salida)", W.CH2), (pin_n(3), "GND", C_GND)]
            for pt, t, c in pins:
                self._pin(p, pt, t, c, derecha=False)
            dut = QRectF(x_pin + 230, nuc.top() + 20, 200, nuc.height() - 40)
            self._bloque(p, dut, "Circuito a medir", "filtro, amplificador…", "#d29922")
            ent = QPointF(dut.left(), dut.top() + dut.height() * 0.25)
            sal = QPointF(dut.left(), dut.top() + dut.height() * 0.6)
            gnd = QPointF(dut.left(), dut.bottom() - 20)
            xb = x_pin + 120
            ys = [pins[0][0].y(), ent.y(), pins[1][0].y()]
            self._cable(p, [pins[0][0], QPointF(xb, pins[0][0].y())], C_GEN)
            self._cable(p, [QPointF(xb, min(ys)), QPointF(xb, max(ys))], C_GEN)
            self._cable(p, [QPointF(xb, ent.y()), ent], C_GEN)
            self._cable(p, [pins[1][0], QPointF(xb, pins[1][0].y())], W.CH1)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(C_GEN))
            for y in ys[1:]:
                p.drawEllipse(QPointF(xb, y), 4.5, 4.5)       # empalmes
            self._cable(p, [pins[2][0], QPointF(xb + 50, pins[2][0].y()), QPointF(xb + 50, sal.y()),
                            QPointF(dut.left() - 0, sal.y())], W.CH2)
            self._cable(p, [pins[3][0], QPointF(xb + 80, pins[3][0].y()), QPointF(xb + 80, gnd.y()), gnd], C_GND)
            p.setPen(QColor(W.TEXTO)); p.setFont(QFont("Segoe UI", 9))
            p.drawText(QPointF(dut.left() + 6, ent.y() + 4), "entrada")
            p.drawText(QPointF(dut.left() + 6, sal.y() + 4), "salida")
            p.drawText(QPointF(dut.left() + 6, gnd.y() + 4), "masa")
            self._nota(p, QRectF(dut.right() + 20, nuc.top(), w - dut.right() - 40, nuc.height()),
                       "D24 alimenta el circuito y también va a A0, que mide lo que realmente entra. "
                       "A1 mide la salida. Masa común.\n\n"
                       "Sin placa de entrada, las dos señales tienen que quedar entre 0 y 3,3 V: "
                       "generador en «Pin directo» con offset de 1,65 V. Con la placa (±10 V) se "
                       "puede medir con señales centradas en 0 V.")
        elif tipo == "externa":
            pins = [(pin_n(0, 3), "A0 · Osc CH1", W.CH1), (pin_n(1, 3), "A1 · Osc CH2", W.CH2),
                    (pin_n(2, 3), "GND", C_GND)]
            for pt, t, c in pins:
                self._pin(p, pt, t, c, derecha=False)
            et = QRectF(x_pin + 90, nuc.top() + 10, 160, nuc.height() - 20)
            self._bloque(p, et, "Etapa de entrada", "Hoja 2: ±10 V / ±1 V, 1 MΩ, protección", "#3fb950")
            src = QRectF(et.right() + 80, nuc.top() + 10, 140, nuc.height() - 20)
            self._bloque(p, src, "Señal externa", "", "#d29922")
            for i, (pt, _, c) in enumerate(pins):
                q = QPointF(et.left(), pt.y())
                self._cable(p, [pt, q], c)
                self._cable(p, [QPointF(et.right(), pt.y()), QPointF(src.left(), pt.y())], c)
            self._nota(p, QRectF(src.right() + 20, nuc.top(), w - src.right() - 40, nuc.height()),
                       "Directo a los pines solo se puede medir entre 0 y 3,3 V. Para señales "
                       "reales (negativas o más grandes) pasá por la etapa de entrada y elegí "
                       "en la app la «Entrada» que coincida con la llave de rango.")
        else:  # frecuencímetro y PWM
            pins = [(pin_n(0), "D32 · Frecuencímetro", C_FREC), (pin_n(1), "D6 · PWM", C_PWM),
                    (pin_n(2), "D42 · PWM complementario", C_PWM), (pin_n(3), "GND", C_GND)]
            for pt, t, c in pins:
                self._pin(p, pt, t, c, derecha=False)
            ent = QRectF(x_pin + 200, pins[0][0].y() - 30, 200, 60)
            self._bloque(p, ent, "Señal lógica 0–3,3 V")
            self._cable(p, [pins[0][0], QPointF(ent.left(), pins[0][0].y())], C_FREC)
            drv = QRectF(x_pin + 200, pins[1][0].y() - 10, 200, pins[3][0].y() - pins[1][0].y() + 30)
            self._bloque(p, drv, "Driver de compuertas", "IR2110, UCC27211… → MOSFET / puente H", "#3fb950")
            for pt, _, c in pins[1:]:
                self._cable(p, [pt, QPointF(drv.left(), pt.y())], c)
            self._nota(p, QRectF(drv.right() + 20, nuc.top(), w - drv.right() - 40, nuc.height()),
                       "El frecuencímetro espera una señal lógica (0 a 3,3 V). Las salidas PWM son de "
                       "3,3 V y poca corriente: para manejar transistores de potencia usá un driver.")
        p.end()

    def _nota(self, p, r: QRectF, texto):
        if r.width() < 120:
            return
        p.setPen(QColor(W.TENUE))
        p.setFont(QFont("Segoe UI", 10))
        p.drawText(r, Qt.AlignLeft | Qt.AlignVCenter | Qt.TextWordWrap, texto)


# ---------------------------------------------------------------------------
# Pestaña
# ---------------------------------------------------------------------------
class TabPlaca(QWidget):
    def __init__(self, ventana):
        super().__init__()
        self.v = ventana
        raiz = QHBoxLayout(self)
        raiz.setContentsMargins(8, 8, 8, 8)

        # izquierda: capacidades y límites
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setFixedWidth(560)
        sc.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        cont = QWidget()
        lay = QVBoxLayout(cont)
        lay.setContentsMargins(0, 0, 8, 0)
        sc.setWidget(cont)
        raiz.addWidget(sc)

        self.lbl_titulo = QLabel()
        self.lbl_titulo.setStyleSheet(f"font-size: 15pt; font-weight: 700; color: {W.TEXTO};")
        lay.addWidget(self.lbl_titulo)
        self.lbl_vivo = W.etiqueta_tenue("")
        lay.addWidget(self.lbl_vivo)

        g, gl = W.grupo("Capacidades")
        self.lbl_espec = QLabel()
        self.lbl_espec.setTextFormat(Qt.RichText)
        self.lbl_espec.setWordWrap(True)
        gl.addWidget(self.lbl_espec)
        lay.addWidget(g)

        g, gl = W.grupo("Limitaciones y cuidados")
        lim = QLabel("<ul style='margin-left:-20px'>" +
                     "".join(f"<li style='margin-bottom:6px'>{t}</li>" for t in LIMITES) + "</ul>")
        lim.setTextFormat(Qt.RichText)
        lim.setWordWrap(True)
        gl.addWidget(lim)
        lay.addWidget(g)
        lay.addStretch(1)

        # derecha: pines y conexiones
        self.sub = QTabWidget()
        raiz.addWidget(self.sub, 1)
        pag = QWidget()
        pl = QVBoxLayout(pag)
        pl.setContentsMargins(6, 6, 6, 6)
        pl.addWidget(W.etiqueta_tenue(
            "Vista de arriba, con el ST-LINK arriba (esquema, no a escala). Los pines usados están "
            "marcados en color; el cuadradito indica el pin 1 de cada conector. Al lado de cada pin, "
            "la placa tiene impreso su rótulo (A0, D13…): usalo para confirmar."))
        self.dib_placa = DibujoPlaca()
        sp = QScrollArea()
        sp.setWidgetResizable(True)
        sp.setWidget(self.dib_placa)
        pl.addWidget(sp, 1)
        self.sub.addTab(pag, "Pines")

        pag = QWidget()
        pl = QVBoxLayout(pag)
        pl.setContentsMargins(6, 6, 6, 6)
        fila = QHBoxLayout()
        fila.addWidget(QLabel("Uso:"))
        self.combo = QComboBox()
        self.combo.addItems(list(ESQUEMAS))
        fila.addWidget(self.combo)
        fila.addStretch(1)
        pl.addLayout(fila)
        self.dib_con = DibujoConexiones()
        pl.addWidget(self.dib_con, 1)
        self.combo.currentTextChanged.connect(self.dib_con.set_esquema)
        self.sub.addTab(pag, "Conexiones")

        self.actualizar()

    def actualizar(self):
        placa = self.v.placa
        self.lbl_titulo.setText(M.nombre_placa(placa))
        self.dib_placa.set_placa(placa)
        otra = "F429" if placa == "F767" else "F767"
        filas, seccion = [], None
        for sec, par, v767, v429 in ESPEC:
            vals = {"F767": v767, "F429": v429 if v429 is not None else v767}
            if sec != seccion:
                filas.append(f"<tr><td colspan='2' style='padding-top:10px;color:{W.ACENTO};"
                             f"font-weight:700'>{sec}</td></tr>")
                seccion = sec
            dif = v429 is not None
            marca = (f"<br><span style='color:{W.TENUE};font-size:9pt'>"
                     f"{M.nombre_placa(otra)}: {vals[otra]}</span>") if dif else ""
            filas.append(f"<tr><td style='color:{W.TENUE};padding-right:12px' width='38%'>{par}</td>"
                         f"<td>{vals[placa]}{marca}</td></tr>")
        self.lbl_espec.setText("<table width='100%' cellspacing='0' cellpadding='3'>" +
                               "".join(filas) + "</table>")
        self._actualizar_vivo()

    def _actualizar_vivo(self):
        d = self.v.disp
        if d.esta_conectado and d.info:
            i = d.info
            self.lbl_vivo.setText(
                f"<span style='color:{W.OK}'>● Medido en la placa conectada:</span> generador "
                f"{M.si(i.get('gen_fs', 0), 'S/s', 4)} · osciloscopio hasta "
                f"{M.si(i.get('osc_fsmax', 0), 'S/s', 4)} · ventana {int(i.get('ventana', 0))} puntos · "
                f"CPU {M.si(i.get('cpu', 0), 'Hz', 3)}")
        else:
            self.lbl_vivo.setText("Valores de referencia. Al conectar la placa se muestran los "
                                  "medidos en ella.")

    def al_conectar(self):
        self._actualizar_vivo()

    def al_desconectar(self):
        self._actualizar_vivo()
