"""Informe en PDF de un barrido de Bode (A4, tema claro, para imprimir).

Se dibuja todo con Qt (QPdfWriter + QPainter): no hace falta ninguna librería extra y los
gráficos quedan vectoriales. Contenido:
  1. Datos del ensayo, resumen, tabla indexada de frecuencias características y H(s).
  2. Bode de ganancia y fase: medición (puntos) contra el modelo ajustado (punteado).
  3. Constelación de polos y ceros en el plano s y error del ajuste punto por punto.
  4. Anexo: todos los puntos medidos.
"""
from __future__ import annotations

import datetime as dt
import math

import numpy as np
from PySide6.QtCore import QMarginsF, QPointF, QRectF, Qt
from PySide6.QtGui import (QBrush, QColor, QFont, QPageLayout, QPageSize, QPainter, QPainterPath,
                           QPdfWriter, QPen)

import modelo as M

RES = 300                         # dpi del PDF
MM = RES / 25.4                   # píxeles por milímetro
ANCHO, ALTO = 210.0, 297.0        # A4 (mm)
MARGEN = 16.0

C_TEXTO = QColor("#111827")
C_TENUE = QColor("#6b7280")
C_GRILLA = QColor("#d1d5db")
C_GRILLA_FINA = QColor("#eef0f3")
C_GAN = QColor("#0e7490")
C_FASE = QColor("#7c3aed")
C_MOD = QColor("#ea580c")
C_ACENTO = QColor("#2563eb")
C_MALO = QColor("#dc2626")
C_POLO = QColor("#b91c1c")
C_CERO = QColor("#1d4ed8")
FUENTE = "Segoe UI"


def _num(x: float, dec: int = 2) -> str:
    t = f"{x:.{dec}f}"
    if float(t) == 0:
        t = t.lstrip("-")                            # sin "−0,0"
    return t.replace("-", "−").replace(".", ",")


def _entero(x: float) -> str:
    """−233 102 (separador de miles con espacio fino y signo menos tipográfico)."""
    t = f"{abs(x):,.0f}".replace(",", "\u2009")
    return ("−" if x < -0.5 else "") + t


def _hz(x: float, cifras: int = 4) -> str:
    return M.si(x, "Hz", cifras)


class Documento:
    """Ayuda para escribir en milímetros sobre un QPdfWriter, con paginado y pie."""

    def __init__(self, ruta: str, titulo: str):
        self.w = QPdfWriter(ruta)
        self.w.setResolution(RES)
        self.w.setPageLayout(QPageLayout(QPageSize(QPageSize.A4), QPageLayout.Portrait,
                                         QMarginsF(0, 0, 0, 0)))
        self.w.setTitle(titulo)
        self.w.setCreator("Instrumento · Bode")
        self.p = QPainter()
        if not self.p.begin(self.w):          # Qt no avisa con una excepción si no puede escribir
            raise OSError("no se puede escribir el archivo (¿carpeta inexistente o PDF abierto en otro programa?)")
        self.p.setRenderHint(QPainter.Antialiasing)
        self.titulo = titulo
        self.pagina = 1
        self.y = MARGEN

    # --- básicos
    @staticmethod
    def r(x, y, w, h) -> QRectF:
        return QRectF(x * MM, y * MM, w * MM, h * MM)

    @staticmethod
    def pt(x, y) -> QPointF:
        return QPointF(x * MM, y * MM)

    def fuente(self, puntos=9.0, negrita=False, mono=False):
        f = QFont("Consolas" if mono else FUENTE)
        if mono:
            f.setStyleHint(QFont.Monospace)
        f.setPointSizeF(puntos)
        f.setBold(negrita)
        self.p.setFont(f)

    def texto(self, x, y, w, txt, puntos=9.0, negrita=False, color=C_TEXTO,
              alin=Qt.AlignLeft, mono=False) -> float:
        """Escribe (con salto de línea) y devuelve el alto usado en mm."""
        self.fuente(puntos, negrita, mono)
        self.p.setPen(color)
        flags = alin | Qt.AlignTop | Qt.TextWordWrap
        caja = self.p.boundingRect(self.r(x, y, w, 500), flags, txt)
        self.p.drawText(self.r(x, y, w, caja.height() / MM + 1), flags, txt)
        return caja.height() / MM

    def linea(self, x1, y1, x2, y2, color=C_GRILLA, ancho=0.25, estilo=Qt.SolidLine):
        self.p.setPen(QPen(color, ancho * MM, estilo))
        self.p.drawLine(self.pt(x1, y1), self.pt(x2, y2))

    def pie(self):
        y = ALTO - 10
        self.linea(MARGEN, y - 2, ANCHO - MARGEN, y - 2, C_GRILLA, 0.2)
        self.texto(MARGEN, y, 120, self.titulo, 7.5, color=C_TENUE)
        self.texto(ANCHO - MARGEN - 40, y, 40, f"Página {self.pagina}", 7.5, color=C_TENUE,
                   alin=Qt.AlignRight)

    def nueva_pagina(self):
        self.pie()
        self.w.newPage()
        self.pagina += 1
        self.y = MARGEN

    def espacio(self, mm_necesarios: float):
        if self.y + mm_necesarios > ALTO - 18:
            self.nueva_pagina()

    def seccion(self, titulo: str):
        self.espacio(14)
        self.y += 2
        self.texto(MARGEN, self.y, ANCHO - 2 * MARGEN, titulo, 12, True, C_ACENTO)
        self.y += 7
        self.linea(MARGEN, self.y, ANCHO - MARGEN, self.y, C_ACENTO, 0.35)
        self.y += 3

    def tabla(self, columnas: list[tuple[str, float]], filas: list[list[str]], puntos=8.0,
              alto_fila=5.2, colores: list | None = None):
        """columnas: [(encabezado, ancho mm)]. Pasa de página repitiendo el encabezado."""
        def encabezado():
            x = MARGEN
            self.p.fillRect(self.r(MARGEN, self.y, sum(c[1] for c in columnas), alto_fila + 0.6),
                            QColor("#f3f4f6"))
            for nombre, ancho in columnas:
                self.texto(x + 1.2, self.y + 1.0, ancho - 2, nombre, puntos, True)
                x += ancho
            self.y += alto_fila + 0.6
        encabezado()
        for i, fila in enumerate(filas):
            # alto de la fila según el texto más largo
            alto = alto_fila
            for (_, ancho), celda in zip(columnas, fila):
                self.fuente(puntos)
                caja = self.p.boundingRect(self.r(0, 0, ancho - 2.4, 500),
                                           Qt.AlignLeft | Qt.TextWordWrap, celda)
                alto = max(alto, caja.height() / MM + 1.6)
            if self.y + alto > ALTO - 18:
                self.nueva_pagina()
                encabezado()
            x = MARGEN
            color = colores[i] if colores and colores[i] is not None else C_TEXTO
            for (_, ancho), celda in zip(columnas, fila):
                self.texto(x + 1.2, self.y + 0.9, ancho - 2.4, celda, puntos, color=color)
                x += ancho
            self.y += alto
            self.linea(MARGEN, self.y, MARGEN + sum(c[1] for c in columnas), self.y,
                       C_GRILLA_FINA, 0.2)
        self.y += 2

    def terminar(self):
        self.pie()
        self.p.end()


# ---------------------------------------------------------------------------
# Gráficos
# ---------------------------------------------------------------------------
def _ticks(lo: float, hi: float, n: int = 6) -> list[float]:
    paso = (hi - lo) / max(n, 1)
    mag = 10 ** math.floor(math.log10(paso)) if paso > 0 else 1
    for m in (1, 2, 2.5, 5, 10):
        if m * mag >= paso:
            paso = m * mag
            break
    inicio = math.ceil(lo / paso) * paso
    return [inicio + i * paso for i in range(int((hi - inicio) / paso) + 1)]


def grafico_frecuencia(doc: Documento, x, y, w, h, titulo, unidad, f, medida,
                       f_mod=None, modelo=None, usados=None, horizontales=(), verticales=(),
                       color=C_GAN):
    """Eje x logarítmico en frecuencia; medida en puntos, modelo punteado."""
    p = doc.p
    izq, abajo = 15.0, 9.0
    area = (x + izq, y + 6, w - izq - 3, h - abajo - 6)
    ax, ay, aw, ah = area
    doc.texto(x, y, w, f"{titulo} ({unidad})" if unidad else titulo, 9.5, True)
    f = np.asarray(f, dtype=float)
    medida = np.asarray(medida, dtype=float)
    todos = [medida]
    if modelo is not None:
        todos.append(np.asarray(modelo, dtype=float))
    vmin = min(float(np.nanmin(v)) for v in todos)
    vmax = max(float(np.nanmax(v)) for v in todos)
    for v in horizontales:
        vmin, vmax = min(vmin, v[0]), max(vmax, v[0])
    margen = max((vmax - vmin) * 0.08, 1.0)
    vmin, vmax = vmin - margen, vmax + margen
    lf0, lf1 = math.floor(math.log10(f.min())), math.ceil(math.log10(f.max()))
    if lf1 == lf0:
        lf1 += 1

    def px(fr, v):
        xx = ax + (math.log10(fr) - lf0) / (lf1 - lf0) * aw
        yy = ay + ah - (v - vmin) / (vmax - vmin) * ah
        return QPointF(xx * MM, yy * MM)

    p.setClipRect(doc.r(ax, ay, aw, ah))
    # grilla
    for d in range(lf0, lf1 + 1):
        for k in range(1, 10):
            fr = k * 10 ** d
            if 10 ** lf0 <= fr <= 10 ** lf1:
                xx = px(fr, vmin).x() / MM
                doc.linea(xx, ay, xx, ay + ah, C_GRILLA if k == 1 else C_GRILLA_FINA, 0.2)
    for v in _ticks(vmin, vmax):
        yy = px(10 ** lf0, v).y() / MM
        doc.linea(ax, yy, ax + aw, yy, C_GRILLA, 0.2)
    # referencias
    for v, etiqueta in horizontales:
        yy = px(10 ** lf0, v).y() / MM
        doc.linea(ax, yy, ax + aw, yy, C_TENUE, 0.3, Qt.DashLine)
        p.setClipping(False)
        doc.texto(ax + aw - 40, yy - 3.6, 40, etiqueta, 6.5, color=C_TENUE, alin=Qt.AlignRight)
        p.setClipRect(doc.r(ax, ay, aw, ah))
    for fr, etiqueta in verticales:
        if 10 ** lf0 <= fr <= 10 ** lf1:
            xx = px(fr, vmin).x() / MM
            doc.linea(xx, ay, xx, ay + ah, C_ACENTO, 0.3, Qt.DotLine)
            p.setClipping(False)
            doc.texto(xx + 0.6, ay + 0.5, 12, etiqueta, 6.5, True, C_ACENTO)
            p.setClipRect(doc.r(ax, ay, aw, ah))
    # medida: línea fina y puntos (los que el ajuste no usó, en rojo)
    camino = QPainterPath(px(f[0], medida[0]))
    for fr, v in zip(f[1:], medida[1:]):
        camino.lineTo(px(fr, v))
    color_l = QColor(color)
    color_l.setAlpha(120)
    p.setPen(QPen(color_l, 0.25 * MM))
    p.setBrush(Qt.NoBrush)
    p.drawPath(camino)
    p.setPen(Qt.NoPen)
    for i, (fr, v) in enumerate(zip(f, medida)):
        malo = usados is not None and not usados[i]
        p.setBrush(QBrush(C_MALO if malo else color))
        rr = (0.75 if malo else 0.55) * MM
        p.drawEllipse(px(fr, v), rr, rr)
    # modelo punteado
    if f_mod is not None and modelo is not None:
        camino = QPainterPath(px(f_mod[0], modelo[0]))
        for fr, v in zip(f_mod[1:], modelo[1:]):
            camino.lineTo(px(fr, v))
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(C_MOD, 0.45 * MM, Qt.DashLine))
        p.drawPath(camino)
    p.setClipping(False)
    # marco y etiquetas de ejes
    p.setPen(QPen(C_TENUE, 0.25 * MM))
    p.setBrush(Qt.NoBrush)
    p.drawRect(doc.r(ax, ay, aw, ah))
    for d in range(lf0, lf1 + 1):
        xx = px(10 ** d, vmin).x() / MM
        doc.texto(xx - 10, ay + ah + 1, 20, _hz(10 ** d, 3), 6.5, color=C_TENUE, alin=Qt.AlignHCenter)
    for v in _ticks(vmin, vmax):
        yy = px(10 ** lf0, v).y() / MM
        doc.texto(x, yy - 1.6, izq - 1.5, f"{v:g}".replace(".", ","), 6.5, color=C_TENUE,
                  alin=Qt.AlignRight)


def leyenda(doc: Documento, x, y, color):
    p = doc.p
    p.setPen(Qt.NoPen)
    p.setBrush(QBrush(color))
    p.drawEllipse(doc.pt(x + 1, y + 1.6), 0.55 * MM, 0.55 * MM)
    doc.texto(x + 3, y, 30, "medición", 7, color=C_TENUE)
    doc.linea(x + 20, y + 1.6, x + 27, y + 1.6, C_MOD, 0.45, Qt.DashLine)
    doc.texto(x + 28.5, y, 35, "modelo ajustado", 7, color=C_TENUE)
    p.setPen(Qt.NoPen)
    p.setBrush(QBrush(C_MALO))
    p.drawEllipse(doc.pt(x + 56, y + 1.6), 0.75 * MM, 0.75 * MM)
    doc.texto(x + 58, y, 70, "punto que el ajuste no usó", 7, color=C_TENUE)


def plano_s(doc: Documento, x, y, lado, sing: list[dict], fmin_med: float, fmax_med: float,
            numeros: list[str] | None = None):
    """Plano s con escala radial logarítmica: ángulo = el de la raíz, radio ∝ log10(|s|/2π).
    Así entran en el mismo dibujo raíces de Hz y de MHz."""
    p = doc.p
    cx, cy, R = x + lado / 2, y + lado / 2, lado / 2 - 7
    fs = [s["f"] for s in sing if s["f"] > 0] + [fmin_med, fmax_med]
    l0 = math.floor(math.log10(max(min(fs), fmin_med / 100)))
    l1 = math.ceil(math.log10(min(max(fs), fmax_med * 1000)))
    if l1 - l0 < 2:
        l1 = l0 + 2

    def radio(fr):
        if fr <= 10 ** l0:
            return 0.0
        return min(1.0, (math.log10(fr) - l0) / (l1 - l0)) * R

    # semiplano izquierdo (estable) sombreado y rango medido
    p.setPen(Qt.NoPen)
    p.setBrush(QBrush(QColor("#f0fdf4")))
    p.drawPie(doc.r(cx - R, cy - R, 2 * R, 2 * R), 90 * 16, 180 * 16)
    r0, r1 = radio(fmin_med), radio(fmax_med)
    anillo = QPainterPath()
    anillo.addEllipse(doc.pt(cx, cy), r1 * MM, r1 * MM)
    anillo.addEllipse(doc.pt(cx, cy), r0 * MM, r0 * MM)
    p.setBrush(QBrush(QColor(37, 99, 235, 22)))
    p.drawPath(anillo)
    # décadas
    for d in range(l0 + 1, l1 + 1):
        rr = radio(10 ** d)
        p.setPen(QPen(C_GRILLA, 0.2 * MM, Qt.DashLine if d % 1 else Qt.SolidLine))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(doc.pt(cx, cy), rr * MM, rr * MM)
        doc.texto(cx + rr * 0.707 + 0.5, cy - rr * 0.707 - 3.2, 18, _hz(10 ** d, 3), 6, color=C_TENUE)
    doc.linea(cx - R - 3, cy, cx + R + 3, cy, C_TENUE, 0.3)
    doc.linea(cx, cy - R - 3, cx, cy + R + 3, C_TENUE, 0.3)
    doc.texto(cx + R + 0.5, cy + 0.6, 10, "σ", 8, color=C_TENUE)
    doc.texto(cx + 1, cy - R - 6, 10, "jω", 8, color=C_TENUE)
    doc.texto(cx - R, cy + R + 1.5, 40, "estable (σ < 0)", 6.5, color=QColor("#15803d"))
    # raíces
    for i, sg in enumerate(sing, 1):
        i = numeros[i - 1] if numeros else i         # mismo número que en la tabla
        s = sg["s"]
        ang = math.atan2(s.imag, s.real)
        rr = radio(sg["f"])
        for signo in ((1, -1) if sg["par"] else (1,)):
            px = cx + rr * math.cos(ang)
            py = cy - signo * rr * math.sin(ang)
            if sg["clase"] == "polo":
                p.setPen(QPen(C_POLO, 0.45 * MM))
                t = 1.6
                p.drawLine(doc.pt(px - t, py - t), doc.pt(px + t, py + t))
                p.drawLine(doc.pt(px - t, py + t), doc.pt(px + t, py - t))
                col = C_POLO
            else:
                p.setPen(QPen(C_CERO, 0.45 * MM))
                p.setBrush(Qt.NoBrush)
                p.drawEllipse(doc.pt(px, py), 1.7 * MM, 1.7 * MM)
                col = C_CERO
            if signo == 1:
                doc.texto(px + 1.8, py - 4.6, 8, str(i), 7, True, col)
    doc.texto(x, y + lado + 4, lado, "Escala radial logarítmica: el radio es la frecuencia |s|/2π y "
              "el ángulo es el de la raíz. Sombreado azul: rango medido. × polo · ○ cero; los números "
              "son los de la tabla.", 6.8, color=C_TENUE)


# ---------------------------------------------------------------------------
# Informe
# ---------------------------------------------------------------------------
def generar(ruta: str, resultados: list, modelo: "M.ModeloBode | None", analisis: dict | None,
            meta: dict, titulo: str = "", notas: str = "") -> int:
    """Escribe el PDF. resultados: [(f, g_dB, fase°, vpp_entrada, vpp_salida)]. Devuelve
    la cantidad de páginas."""
    arr = np.array(resultados, dtype=float)
    f, g, fase = arr[:, 0], arr[:, 1], arr[:, 2]
    titulo_doc = titulo.strip() or "Respuesta en frecuencia"
    doc = Documento(ruta, f"Informe de Bode · {titulo_doc}")
    W = ANCHO - 2 * MARGEN

    # ------------------------------------------------------------- página 1
    doc.y += doc.texto(MARGEN, doc.y, W, "Informe de respuesta en frecuencia", 17, True)
    doc.y += doc.texto(MARGEN, doc.y + 1, W, titulo_doc, 12, False, C_ACENTO) + 3
    if notas.strip():
        doc.y += doc.texto(MARGEN, doc.y, W, notas.strip(), 9, color=C_TENUE) + 2

    doc.seccion("Datos del ensayo")
    filas = [[k, v] for k, v in meta.items() if v not in (None, "")]
    doc.tabla([("Dato", 52), ("Valor", W - 52)], filas, 8.5)

    sing = M.singularidades_bode(modelo, f, analisis) if modelo is not None else []
    doc.seccion("Resumen")
    if analisis:
        doc.y += doc.texto(MARGEN, doc.y, W, analisis["tipo"], 12, True) + 1
        if analisis["f3db"]:
            ref = "del pico" if "Pasabanda" in analisis["tipo"] else "de la meseta"
            doc.y += doc.texto(MARGEN, doc.y, W, f"Frecuencia de corte (−3 dB {ref}): "
                               + ", ".join(_hz(x) for x in analisis["f3db"]), 10, True, C_ACENTO) + 1
        for d in analisis["detalles"]:
            doc.y += doc.texto(MARGEN + 3, doc.y, W - 3, "• " + d, 9) + 0.6
        usados = int(modelo.usados.sum())
        doc.y += doc.texto(MARGEN, doc.y + 1, W,
                           f"Ajuste: {len(sing)} singularidades (orden {modelo.orden[0]}/{modelo.orden[1]}), "
                           f"error eficaz {_num(analisis['error_db'])} dB y {_num(analisis['error_fase'], 1)}° "
                           f"en {usados} de {len(f)} puntos.", 8.5, color=C_TENUE) + 2
    else:
        gmax = float(g.max())
        doc.y += doc.texto(MARGEN, doc.y, W, f"Ganancia máxima: {_num(gmax)} dB a {_hz(f[g.argmax()])}. "
                           "No se pudo ajustar un modelo (hacen falta al menos 6 puntos).", 9.5) + 2

    # tabla indexada de frecuencias características
    doc.seccion("Frecuencias características")
    filas, colores = [], []
    idx = 1
    for x in (analisis or {}).get("f3db", []):
        filas.append([str(idx), "Corte (−3 dB)", _hz(x), "", "", "medido sobre el modelo"])
        colores.append(C_ACENTO)
        idx += 1
    numero_sing = {}
    for sg in sing:
        numero_sing[id(sg)] = idx
        tipo = ("Par de polos" if sg["par"] else "Polo") if sg["clase"] == "polo" else \
            ("Par de ceros" if sg["par"] else "Cero")
        s = sg["s"]
        s_txt = (f"{_entero(s.real)} ± j{_entero(s.imag)}" if sg["par"] else _entero(s.real))
        nota = sg["region"]
        if sg["piso"]:
            nota = "piso de acople entre CH1 y CH2 (no es del circuito)"
        elif sg["par"] and sg["clase"] == "cero":
            nota += " · rechazo / autorresonancia"
        q = f"{_num(sg['q'], 2)}  (ζ = {_num(1 / (2 * sg['q']), 3)})" if sg["q"] else "—"
        filas.append([str(idx), tipo, _hz(sg["f"]), q, s_txt, nota])
        colores.append(C_POLO if sg["clase"] == "polo" else C_CERO)
        idx += 1
    if filas:
        doc.tabla([("#", 8), ("Elemento", 26), ("Frecuencia", 24), ("Q", 32),
                   ("s (rad/s)", 34), ("Comentario", W - 124)], filas, 8, colores=colores)
    else:
        doc.y += doc.texto(MARGEN, doc.y, W, "Sin modelo ajustado.", 9, color=C_TENUE) + 2

    if modelo is not None:
        doc.seccion("Función de transferencia ajustada")
        k = M.ganancia_continua_bode(modelo)
        kdb = 20 * math.log10(max(abs(k), 1e-15))
        polos = [s for s in sing if s["clase"] == "polo"]
        ceros = [s for s in sing if s["clase"] == "cero"]

        def factores(lista):
            out = []
            for s in lista:
                if s["par"]:
                    out.append(f"(1 + s/({_num(s['q'], 2)}·ω{numero_sing[id(s)]}) + s²/ω{numero_sing[id(s)]}²)")
                else:
                    out.append(f"(1 + s/ω{numero_sing[id(s)]})")
            if len(out) > 1:
                return "[" + " · ".join(out) + "]"
            return out[0] if out else "1"
        doc.y += doc.texto(MARGEN, doc.y, W, f"H(s) = K · {factores(ceros)} / {factores(polos)}",
                           9.5, mono=True) + 1.5
        doc.y += doc.texto(MARGEN, doc.y, W,
                           f"K = H(0) = {_num(k.real, 5)}  ({_num(kdb, 2)} dB) · ωᵢ = 2π·fᵢ con las "
                           "frecuencias de la tabla (para un cero en el semiplano derecho el signo "
                           "del término lineal cambia).", 8.5, color=C_TENUE) + 2

    # ------------------------------------------------------------- página 2: Bode
    doc.nueva_pagina()
    doc.seccion("Diagrama de Bode: medición contra modelo")
    leyenda(doc, MARGEN, doc.y, C_GAN)
    doc.y += 6
    fm = gm = fasem = None
    usados = modelo.usados if modelo is not None else None
    verticales = []
    if analisis:
        verticales = [(x, str(i)) for i, x in enumerate(analisis["f3db"], 1)]
    for sg in sing:
        if sg["region"] == "en el rango" and not sg["piso"]:
            verticales.append((sg["f"], str(numero_sing[id(sg)])))
    if modelo is not None:
        fm = np.logspace(math.log10(f.min()), math.log10(f.max()), 700)
        hm = modelo.h(fm)
        gm = 20 * np.log10(np.maximum(np.abs(hm), 1e-15))
        fasem = np.degrees(np.unwrap(np.angle(hm)))
        d = fase[0] - np.degrees(np.angle(modelo.h([f[0]])[0]))
        fasem = fasem + 360 * round(d / 360)
    horiz = []
    if analisis and analisis.get("ref_db") is not None:
        horiz = [(analisis["ref_db"] - 3, "−3 dB")]
    alto = (ALTO - doc.y - 26) / 2
    grafico_frecuencia(doc, MARGEN, doc.y, W, alto, "Ganancia", "dB", f, g, fm, gm, usados,
                       horiz, verticales, C_GAN)
    doc.y += alto + 3
    grafico_frecuencia(doc, MARGEN, doc.y, W, alto, "Fase", "°", f, fase, fm, fasem, usados,
                       (), verticales, C_FASE)
    doc.y += alto

    # ------------------------------------------------------------- página 3: plano s y error
    if modelo is not None:
        doc.nueva_pagina()
        doc.seccion("Constelación de polos y ceros (plano s)")
        lado = 112
        plano_s(doc, MARGEN + (W - lado) / 2, doc.y, lado, sing, float(f.min()), float(f.max()),
                [str(numero_sing[id(sg)]) for sg in sing])
        doc.y += lado + 14
        doc.seccion("Error del ajuste punto por punto")
        hmed = 10 ** (g / 20) * np.exp(1j * np.radians(fase))
        hmod = modelo.h(f)
        edb = 20 * np.log10(np.abs(hmod / hmed))
        efa = np.degrees(np.angle(hmod / hmed))
        alto = (ALTO - doc.y - 24) / 2
        grafico_frecuencia(doc, MARGEN, doc.y, W, alto, "Modelo − medición (ganancia)", "dB",
                           f, edb, usados=usados, horizontales=[(0.0, "")], color=C_GAN)
        doc.y += alto + 2
        grafico_frecuencia(doc, MARGEN, doc.y, W, alto, "Modelo − medición (fase)", "°",
                           f, efa, usados=usados, horizontales=[(0.0, "")], color=C_FASE)
        doc.y += alto

    # ------------------------------------------------------------- anexo
    doc.nueva_pagina()
    doc.seccion("Anexo: puntos medidos")
    filas, colores = [], []
    hmod = modelo.h(f) if modelo is not None else None
    for i, r in enumerate(arr):
        fila = [str(i + 1), _hz(r[0], 5), _num(r[1], 2), _num(r[2], 1)]
        if hmod is not None:
            gmi = 20 * math.log10(max(abs(hmod[i]), 1e-15))
            fmi = math.degrees(math.atan2(hmod[i].imag, hmod[i].real))
            dfa = (fmi - r[2] + 180) % 360 - 180
            fila += [_num(gmi, 2), _num(gmi - r[1], 2), _num(dfa, 1)]
        else:
            fila += ["", "", ""]
        fila += [M.si(r[3], "V", 3), M.si(r[4], "V", 3)]
        filas.append(fila)
        colores.append(C_MALO if usados is not None and not usados[i] else None)
    doc.tabla([("#", 9), ("Frecuencia", 24), ("Gan. (dB)", 18), ("Fase (°)", 17),
               ("Modelo (dB)", 20), ("Δ dB", 15), ("Δ fase", 15), ("Vpp entrada", 30),
               ("Vpp salida", W - 148)], filas, 7, 4.4, colores)
    if usados is not None and (~usados).any():
        doc.texto(MARGEN, doc.y, W, "En rojo: puntos que el ajuste robusto no tuvo en cuenta "
                  "(no encajan con el resto: autorresonancia, acople, un punto suelto).", 7.5,
                  color=C_TENUE)
    paginas = doc.pagina
    doc.terminar()
    return paginas


def meta_por_defecto() -> dict:
    return {"Fecha": dt.datetime.now().strftime("%d/%m/%Y %H:%M")}
