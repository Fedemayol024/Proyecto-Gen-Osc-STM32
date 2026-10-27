"""
Modelo del instrumento: calibraciones, conversión tensión <-> código y
armado de las tablas de forma de onda. No depende de la interfaz.
"""
from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass, asdict, field
from pathlib import Path

import numpy as np

TABLA_N = 4096           # puntos por período en el generador
DAC_MAX = 4095
ADC_MAX = 4095
VREF = 3.3


# ---------------------------------------------------------------------------
# Recta código <-> tensión (sirve para el DAC y para el ADC)
# ---------------------------------------------------------------------------
@dataclass
class Recta:
    codigo_a: float
    volt_a: float
    codigo_b: float
    volt_b: float

    @property
    def pendiente(self) -> float:
        return (self.volt_b - self.volt_a) / (self.codigo_b - self.codigo_a)

    def volt(self, codigo):
        return self.volt_a + (np.asarray(codigo, dtype=float) - self.codigo_a) * self.pendiente

    def codigo(self, volt):
        return self.codigo_a + (np.asarray(volt, dtype=float) - self.volt_a) / self.pendiente

    def valida(self) -> bool:
        try:
            return (self.codigo_a != self.codigo_b and abs(self.pendiente) > 1e-9
                    and all(math.isfinite(v) for v in asdict(self).values()))
        except (ZeroDivisionError, TypeError):
            return False

    @staticmethod
    def desde_dict(d) -> "Recta | None":
        try:
            r = Recta(float(d["codigo_a"]), float(d["volt_a"]), float(d["codigo_b"]), float(d["volt_b"]))
            return r if r.valida() else None
        except (KeyError, TypeError, ValueError):
            return None


def _recta_lineal(f, c0=0.0, c1=4095.0) -> Recta:
    return Recta(c0, float(f(c0)), c1, float(f(c1)))


# ---------------------------------------------------------------------------
# Salidas del generador
# ---------------------------------------------------------------------------
# Etapa de salida de la placa (igual topología que el proyecto ESP32):
#   Vout = Vdac (1 + Rf/Rref + Rf/Rgnd) - 3,3 V · Rf/Rref
RF_OUT, RREF_OUT, RGND_OUT = 30e3, 15e3, 33e3
G_OUT = 1 + RF_OUT / RREF_OUT + RF_OUT / RGND_OUT
OFF_OUT = VREF * RF_OUT / RREF_OUT

# Zona lineal del DAC del STM32 con el buffer de salida activado
DAC_V_MIN, DAC_V_MAX = 0.2, 3.1


@dataclass(frozen=True)
class ModoSalida:
    clave: str
    nombre: str
    vmin: float
    vmax: float
    diseno: Recta


def _vdac(c):
    return VREF * np.asarray(c, dtype=float) / DAC_MAX


MODOS_SALIDA = {
    "PLACA": ModoSalida("PLACA", "Placa ±5 V", -5.0, 5.0,
                        _recta_lineal(lambda c: G_OUT * _vdac(c) - OFF_OUT)),
    "DIRECTO": ModoSalida("DIRECTO", "Pin directo (0,2–3,1 V)", DAC_V_MIN, DAC_V_MAX,
                          _recta_lineal(_vdac)),
}

# ---------------------------------------------------------------------------
# Entradas del osciloscopio
# ---------------------------------------------------------------------------
# Atenuador de entrada: X = 1,65 V + K·Vin   (R1 = 1 MΩ, R2 = 300 kΩ a 3,3 V,
# R3 = 430 kΩ a GND) y luego ganancia 1 o 10,1 alrededor de 1,65 V.
R1_IN, R2_IN, R3_IN = 1e6, 300e3, 430e3
_G = 1 / R1_IN + 1 / R2_IN + 1 / R3_IN
K_IN = (1 / R1_IN) / _G
BIAS_IN = (VREF / R2_IN) / _G
G_ALTA = 1 + 9.1e3 / 1e3
VMED = 1.65


def _vadc(c):
    return VREF * np.asarray(c, dtype=float) / ADC_MAX


@dataclass(frozen=True)
class ModoEntrada:
    clave: str
    nombre: str
    rango: float          # ± tensión de entrada aproximada (para la interfaz)
    diseno: Recta


def _vin_rango(ganancia):
    # Vadc = VMED + g·(BIAS_IN + K·Vin - VMED)  ->  Vin
    return lambda c: ((_vadc(c) - VMED) / ganancia + VMED - BIAS_IN) / K_IN


MODOS_ENTRADA = {
    "ALTO": ModoEntrada("ALTO", "Placa ±10 V", 10.0, _recta_lineal(_vin_rango(1.0))),
    "BAJO": ModoEntrada("BAJO", "Placa ±1 V (×10)", 1.0, _recta_lineal(_vin_rango(G_ALTA))),
    "DIRECTO": ModoEntrada("DIRECTO", "Pin directo (0–3,3 V)", 3.3, _recta_lineal(_vadc)),
}

# ---------------------------------------------------------------------------
# Formas de onda
# ---------------------------------------------------------------------------
FORMAS = ["Senoidal", "Cuadrada", "Triangular", "Diente de sierra", "Continua", "Ruido", "Arbitraria"]


def forma_normalizada(forma: str, ciclo: float, arbitraria: np.ndarray | None = None) -> np.ndarray:
    """Un período de la forma, valores entre -1 y 1 (Continua devuelve 0)."""
    x = np.arange(TABLA_N) / TABLA_N
    d = min(max(ciclo / 100.0, 0.0), 1.0)
    if forma == "Senoidal":
        return np.sin(2 * np.pi * x)
    if forma == "Cuadrada":
        return np.where(x < d, 1.0, -1.0)
    if forma == "Triangular":
        if d <= 0:
            y = 1 - x
        elif d >= 1:
            y = x
        else:
            y = np.where(x < d, x / d, (1 - x) / (1 - d))
        return 2 * y - 1
    if forma == "Diente de sierra":
        return 2 * x - 1
    if forma == "Ruido":
        rng = np.random.default_rng(12345)
        r = rng.standard_normal(TABLA_N)
        return np.clip(r / 3.0, -1, 1)          # ±3 sigma ocupan la amplitud
    if forma == "Arbitraria" and arbitraria is not None and len(arbitraria) >= 2:
        a = np.asarray(arbitraria, dtype=float)
        xp = np.arange(len(a)) / len(a)
        y = np.interp(x, xp, a, period=1.0)
        lo, hi = y.min(), y.max()
        return (2 * (y - lo) / (hi - lo) - 1) if hi > lo else np.zeros(TABLA_N)
    return np.zeros(TABLA_N)


def num_csv(x: float, fmt: str = ".6g") -> str:
    """Número para un CSV separado por ';' con coma decimal, como lo abre Excel en español."""
    return format(x, fmt).replace(".", ",")


def leer_csv_forma(ruta: str) -> np.ndarray:
    """Lee una columna de números (la última de cada fila) de un CSV o TXT.
    Acepta ';' o tabulador con coma o punto decimal, y ',' con punto decimal."""
    valores = []
    with open(ruta, encoding="utf-8", errors="replace") as f:
        for linea in f:
            sep = ";" if ";" in linea else "\t" if "\t" in linea else ","
            partes = [p for p in linea.split(sep) if p.strip()]
            if not partes:
                continue
            try:
                valores.append(float(partes[-1].strip().replace(" ", "").replace(",", ".")))
            except ValueError:
                continue
    if len(valores) < 2:
        raise ValueError("El archivo no tiene al menos 2 valores numéricos.")
    return np.array(valores)


@dataclass
class CanalGen:
    habilitado: bool = True
    forma: str = "Senoidal"
    frecuencia: float = 1000.0
    vpp: float = 2.0
    offset: float = 0.0
    ciclo: float = 50.0
    fase: float = 0.0
    modulacion: str = "Ninguna"        # Ninguna / AM / FM
    mod_frec: float = 10.0
    am_prof: float = 50.0              # %
    fm_desvio: float = 100.0           # Hz
    barrido: str = "No"                # No / Lineal / Logarítmico
    bar_f1: float = 100.0
    bar_f2: float = 10_000.0
    bar_t: float = 1.0
    modo_salida: str = "PLACA"


@dataclass
class TablaGen:
    codigos: np.ndarray          # uint16, TABLA_N
    volts: np.ndarray            # lo que sale de verdad (simulado)
    recortada: bool
    lim: tuple[float, float]
    reposo: int                  # código para 0 V (o el mínimo)
    centro: float                # código del offset (para AM)


def limites_salida(modo: ModoSalida, cal: Recta) -> tuple[float, float]:
    """Rango utilizable: zona lineal del DAC ∩ límites de la salida."""
    c_lo = DAC_V_MIN / VREF * DAC_MAX
    c_hi = DAC_V_MAX / VREF * DAC_MAX
    v1, v2 = float(cal.volt(c_lo)), float(cal.volt(c_hi))
    lo, hi = min(v1, v2), max(v1, v2)
    return max(lo, modo.vmin), min(hi, modo.vmax)


def armar_tabla(c: CanalGen, cal: Recta, arbitraria: np.ndarray | None = None) -> TablaGen:
    modo = MODOS_SALIDA[c.modo_salida]
    lo, hi = limites_salida(modo, cal)
    norm = forma_normalizada(c.forma, c.ciclo, arbitraria)
    if c.forma == "Continua":
        v = np.full(TABLA_N, c.offset)
    else:
        v = c.offset + norm * c.vpp / 2.0
    paso = abs(cal.pendiente)
    recortada = bool(v.min() < lo - paso or v.max() > hi + paso)
    v = np.clip(v, lo, hi)
    cod = np.clip(np.rint(cal.codigo(v)), 0, DAC_MAX).astype(np.uint16)
    v_real = cal.volt(cod)
    cero = min(max(0.0, lo), hi)
    reposo = int(np.clip(np.rint(cal.codigo(cero)), 0, DAC_MAX))
    centro = float(np.clip(cal.codigo(min(max(c.offset, lo), hi)), 0, DAC_MAX))
    return TablaGen(cod, v_real, recortada, (lo, hi), reposo, centro)


# ---------------------------------------------------------------------------
# Mediciones sobre una señal muestreada
# ---------------------------------------------------------------------------
def medir(v: np.ndarray, fs: float) -> dict:
    if v is None or len(v) < 4:
        return {}
    vmax, vmin = float(v.max()), float(v.min())
    media = float(v.mean())
    rms = float(np.sqrt(np.mean(v * v)))
    vpp = vmax - vmin
    r = {"vmax": vmax, "vmin": vmin, "vpp": vpp, "media": media, "rms": rms,
         "frec": None, "periodo": None, "ciclo": None}
    if vpp <= 0:
        return r
    h = 0.1 * vpp
    alto = media + h / 2
    bajo = media - h / 2
    estado = v[0] > media
    subidas = []
    for i in range(1, len(v)):
        if not estado and v[i] > alto:
            estado = True
            # interpolación lineal del cruce por la media
            j = i
            while j > 0 and v[j - 1] > media:
                j -= 1
            if j > 0 and v[j] != v[j - 1]:
                subidas.append(j - 1 + (media - v[j - 1]) / (v[j] - v[j - 1]))
            else:
                subidas.append(float(j))
        elif estado and v[i] < bajo:
            estado = False
    if len(subidas) >= 2 and fs > 0:
        periodo_m = (subidas[-1] - subidas[0]) / (len(subidas) - 1)
        if periodo_m > 0:
            r["periodo"] = periodo_m / fs
            r["frec"] = fs / periodo_m
            a, b = int(subidas[0]), int(subidas[-1])
            if b > a:
                r["ciclo"] = 100.0 * float(np.mean(v[a:b] > media))
    return r


def suavizar(v: np.ndarray, ventana: int) -> np.ndarray:
    """Promedio móvil centrado de 'ventana' puntos. Los bordes se rellenan
    repitiendo el primer y el último valor: con ceros (np.convolve 'same'), los
    extremos de la captura caían hacia 0 V."""
    if ventana <= 1 or len(v) < ventana:
        return v
    izq = ventana // 2
    relleno = np.pad(v, (izq, ventana - 1 - izq), mode="edge")
    return np.convolve(relleno, np.ones(ventana) / ventana, mode="valid")


def fasor_seno(v: np.ndarray, fs: float, f: float) -> tuple[complex, float]:
    """Ajuste por mínimos cuadrados a A·sen(2πft + φ) + C.
    Devuelve (A·e^jφ, residuo eficaz del ajuste)."""
    t = np.arange(len(v)) / fs
    w = 2 * np.pi * f * t
    m = np.column_stack([np.sin(w), np.cos(w), np.ones_like(w)])
    coef, *_ = np.linalg.lstsq(m, v, rcond=None)
    residuo = float(np.sqrt(np.mean((v - m @ coef) ** 2)))
    return complex(coef[0], coef[1]), residuo


# ---------------------------------------------------------------------------
# Bode: largo de cada captura y promedio de las que hagan falta
# ---------------------------------------------------------------------------
# El ruido de la amplitud y la fase ajustadas baja con la raíz del número de muestras, así
# que conviene la captura más larga posible sin que el barrido se haga eterno.
BODE_T_CAPTURA = 0.2       # s de captura buscados por punto (al menos 8 períodos)
BODE_T_PUNTO = 2.0         # s máximos por punto sumando las repeticiones
BODE_FASE_OBJ = math.radians(1.0)
BODE_REP_MAX = 16


def captura_bode(f: float, fs_max: float, ventana: int = 8192,
                 t_obj: float = BODE_T_CAPTURA) -> tuple[int, float]:
    """(n, fs) de la captura para un punto del barrido: al menos 50 muestras por período
    y 8 períodos, y la ventana completa siempre que no tarde más de 't_obj'."""
    t = max(8.0 / f, t_obj)
    fs = min(fs_max, max(50.0 * f, ventana / t))
    n = int(min(ventana, max(400, round(t * fs))))
    return n, fs


def repeticiones_bode(amp: float, residuo: float, n: int, t_captura: float,
                      fase_obj: float = BODE_FASE_OBJ, maximo: int = BODE_REP_MAX,
                      t_punto: float = BODE_T_PUNTO) -> int:
    """Capturas a promediar para que la incertidumbre de la fase quede en 'fase_obj'.
    Con ruido blanco de valor eficaz 'residuo', la del ajuste es residuo·√(2/n)/amp."""
    incert = residuo * math.sqrt(2.0 / max(n, 1)) / max(amp, 1e-12)
    k = math.ceil((incert / fase_obj) ** 2)
    tope = max(1, int(t_punto // max(t_captura, 1e-9)))
    return int(min(maximo, tope, max(1, k)))


# ---------------------------------------------------------------------------
# Espectro (FFT): ventanas, promediado, piso de ruido y picos
# ---------------------------------------------------------------------------
VENTANAS = ["Hann", "Hamming", "Blackman-Harris", "Flat-top", "Rectangular"]
DB_MIN = -160.0          # piso de la escala en dB (nada se dibuja más abajo)


def ventana_fft(nombre: str, n: int) -> np.ndarray:
    k = np.arange(n) / max(n - 1, 1) * 2 * np.pi
    if nombre == "Hamming":
        return 0.54 - 0.46 * np.cos(k)
    if nombre == "Blackman-Harris":
        return 0.35875 - 0.48829 * np.cos(k) + 0.14128 * np.cos(2 * k) - 0.01168 * np.cos(3 * k)
    if nombre == "Flat-top":
        return (0.21557895 - 0.41663158 * np.cos(k) + 0.277263158 * np.cos(2 * k)
                - 0.083578947 * np.cos(3 * k) + 0.006947368 * np.cos(4 * k))
    if nombre == "Rectangular":
        return np.ones(n)
    return np.hanning(n)


def enbw(w: np.ndarray) -> float:
    """Ancho de banda equivalente de ruido de la ventana, en bins."""
    return float(len(w) * np.sum(w ** 2) / np.sum(w) ** 2)


def espectro_potencia(v: np.ndarray, fs: float, ventana: str = "Hann") -> tuple[np.ndarray, np.ndarray, float]:
    """Frecuencias, potencia de cada bin (V² eficaces de una senoidal centrada en ese bin)
    y ENBW de la ventana (bins). Una senoidal de A V eficaces da A² en su bin."""
    v = np.asarray(v, dtype=float)
    n = len(v)
    w = ventana_fft(ventana, n)
    x = np.fft.rfft((v - v.mean()) * w)
    p = 2 * np.abs(x) ** 2 / np.sum(w) ** 2
    p[0] = v.mean() ** 2
    return np.fft.rfftfreq(n, 1 / fs), p, enbw(w)


def a_db(p: np.ndarray) -> np.ndarray:
    return 10 * np.log10(np.maximum(p, 10 ** (DB_MIN / 10)))


def espectro(v: np.ndarray, fs: float, ventana: str = "Hann") -> tuple[np.ndarray, np.ndarray]:
    """Espectro en dBV (valor eficaz de cada componente)."""
    f, p, _ = espectro_potencia(v, fs, ventana)
    return f, a_db(p)


def piso_ruido(p: np.ndarray, promedios: int = 1, ancho: int | None = None) -> np.ndarray:
    """Estimación del piso de ruido (potencia media por bin) con una mediana móvil, que no
    se deja llevar por los picos. La mediana del ruido blanco queda por debajo de su media
    (ln 2 sin promediar, casi 1 con muchos promedios) y se corrige."""
    p = np.asarray(p, dtype=float)
    n = len(p)
    if n < 8:
        return np.full(n, float(np.median(p)) if n else 0.0)
    if ancho is None:
        ancho = int(np.clip(n // 48, 9, 151))
    ancho |= 1
    m = ancho // 2
    ext = np.concatenate([p[1:m + 1][::-1], p, p[-m - 1:-1][::-1]])
    med = np.median(np.lib.stride_tricks.sliding_window_view(ext, ancho), axis=1)
    k = max(1, int(promedios))
    corr = math.log(2) if k == 1 else max(math.log(2), 1 - 1 / (3 * k))
    return med / corr


def quitar_piso(p: np.ndarray, piso: np.ndarray, fuerza: float = 2.0, resto: float = 1e-4) -> np.ndarray:
    """Sustracción espectral: resta el piso de ruido (con un factor de sobre-resta) y deja
    un resto muy chico donde solo había ruido. Las componentes reales casi no cambian."""
    return np.maximum(p - fuerza * piso, resto * piso)


def _interp_parabolica(db: np.ndarray, i: int) -> tuple[float, float]:
    """Corrección de posición (en bins) y nivel del pico por ajuste de una parábola."""
    if i <= 0 or i >= len(db) - 1:
        return 0.0, float(db[i])
    a, b, c = db[i - 1], db[i], db[i + 1]
    den = a - 2 * b + c
    if den >= 0:
        return 0.0, float(b)
    d = 0.5 * (a - c) / den
    d = float(np.clip(d, -0.5, 0.5))
    return d, float(b - 0.25 * (a - c) * d)


def _centroide(p: np.ndarray, k: int, medio: int) -> float:
    """Corrección (en bins) de la frecuencia de un pico por el centro de masa de su lóbulo.
    Funciona con cualquier ventana, también con la flat-top (que tiene el pico plano)."""
    a, b = max(0, k - medio), min(len(p), k + medio + 1)
    w = p[a:b]
    s = float(np.sum(w))
    if s <= 0:
        return 0.0
    return float(np.sum(w * np.arange(a, b)) / s) - k


def medio_lobulo(enbw_bins: float) -> int:
    """Medio ancho (bins) del lóbulo principal, aproximado a partir del ENBW."""
    return max(1, int(round(1.6 * enbw_bins)))


def buscar_picos(f: np.ndarray, p: np.ndarray, piso: np.ndarray, umbral_db: float = -80.0,
                 sobre_piso_db: float = 10.0, sep_hz: float = 0.0, max_picos: int = 10,
                 ignorar_dc: bool = True, enbw_bins: float = 1.5) -> list[dict]:
    """Picos del espectro (potencia p) que superan el umbral absoluto y quedan al menos
    `sobre_piso_db` por encima del piso de ruido. Ordenados de mayor a menor nivel."""
    db = a_db(p)
    db_piso = a_db(piso)
    n = len(db)
    if n < 3:
        return []
    df = float(f[1] - f[0]) if n > 1 else 1.0
    i = np.arange(1, n - 1)
    loc = (db[i] > db[i - 1]) & (db[i] >= db[i + 1])
    cand = i[loc]
    if ignorar_dc:
        cand = cand[cand >= 3]
    cand = cand[(db[cand] >= umbral_db) & (db[cand] - db_piso[cand] >= sobre_piso_db)]
    cand = cand[np.argsort(db[cand])[::-1]]
    medio = medio_lobulo(enbw_bins)
    sep = max(sep_hz, (medio + 1) * df)
    elegidos: list[dict] = []
    for k in cand:
        a, b = max(0, k - medio), min(n, k + medio + 1)
        pot = float(np.sum(p[a:b] - piso[a:b])) / enbw_bins      # Parseval: no depende del bin
        nivel = 10 * math.log10(pot) if pot > p[k] * 0.5 else float(db[k])
        fk = float(f[k] + _centroide(p, int(k), medio) * df)
        if any(abs(fk - e["f"]) < sep for e in elegidos):
            continue
        elegidos.append({"f": fk, "db": nivel, "bin": int(k), "sobre_piso": float(db[k] - db_piso[k])})
        if len(elegidos) >= max_picos:
            break
    return elegidos


def _zona(p: np.ndarray, piso: np.ndarray, k: int, medio: int, tope: int | None = None) -> tuple[int, int]:
    """Bins que ocupa una componente: su lóbulo principal más las «polleras» de la ventana
    mientras sigan claramente por encima del piso de ruido."""
    n = len(p)
    tope = max(medio, n // 16 if tope is None else tope)
    a, b = max(0, k - medio), min(n, k + medio + 1)
    while a > 0 and k - a < tope and p[a - 1] > 2 * piso[a - 1]:
        a -= 1
    while b < n and b - k < tope and p[b] > 2 * piso[b]:
        b += 1
    return a, b


def analizar_armonicos(f: np.ndarray, p: np.ndarray, piso: np.ndarray, enbw_bins: float,
                       f0: float | None = None, n_arm: int = 10) -> dict | None:
    """Fundamental, armónicos, THD, SNR, SINAD y ENOB a partir de la potencia por bin.
    La potencia de una componente es la suma de su zona dividida por el ENBW (menos el ruido
    que cae en esa zona). El ruido es todo lo demás, y bajo las zonas se estima con el piso."""
    n = len(p)
    if n < 16:
        return None
    df = float(f[1] - f[0])
    medio = medio_lobulo(enbw_bins) + 1
    if f0 is None:
        k0 = int(np.argmax(p[3:])) + 3
    else:
        k0 = int(round(f0 / df))
        if not 3 <= k0 < n:
            return None
        a, b = max(3, k0 - 2), min(n, k0 + 3)
        k0 = a + int(np.argmax(p[a:b]))
    f_fund = float(f[k0] + _centroide(p, k0, medio - 1) * df)
    tope = max(medio, int(0.45 * f_fund / df))           # una zona no invade la del armónico vecino
    usados = np.zeros(n, bool)
    a, b = _zona(p, piso, 0, medio, tope)
    usados[:b] = True                                           # continua

    def potencia(a, b):
        return max(float(np.sum(p[a:b]) - np.sum(piso[a:b])) / enbw_bins, 0.0)

    a, b = _zona(p, piso, k0, medio, tope)
    p_fund = potencia(a, b)
    usados[a:b] = True
    armonicos = []
    for h in range(2, n_arm + 1):
        kh = int(round(h * f_fund / df))
        if kh >= n - 1:
            break
        a, b = max(0, kh - 2), min(n, kh + 3)
        kh = a + int(np.argmax(p[a:b]))
        a, b = _zona(p, piso, kh, medio, tope)
        armonicos.append({"n": h, "f": float(f[kh]), "p": potencia(a, b)})
        usados[a:b] = True
    p_arm = sum(x["p"] for x in armonicos)
    p_ruido = float(np.sum(p[~usados]) + np.sum(piso[usados])) / enbw_bins
    if p_fund <= 0:
        return None
    thd = math.sqrt(p_arm / p_fund)
    snr = 10 * math.log10(p_fund / max(p_ruido, 1e-30))
    sinad = 10 * math.log10(p_fund / max(p_ruido + p_arm, 1e-30))
    piso_med = float(np.median(piso[3:]))
    return {"f0": f_fund, "a0": math.sqrt(p_fund), "thd": thd,
            "thd_db": 20 * math.log10(max(thd, 1e-12)), "snr": snr, "sinad": sinad,
            "enob": (sinad - 1.76) / 6.02, "armonicos": armonicos,
            "piso_db": 10 * math.log10(max(piso_med, 1e-30)),
            "densidad": math.sqrt(max(piso_med, 0.0) / (enbw_bins * df)),
            "rbw": enbw_bins * df,
            # con pocos períodos en pantalla los armónicos caen dentro del lóbulo del fundamental
            "resolucion_ok": f_fund / df >= 3 * medio}


class PromedioEspectro:
    """Promedio de potencias de los últimos N cuadros (promedio exponencial equivalente).
    Promediar potencias no baja el piso, pero lo vuelve parejo: desaparecen los
    «micropicos» del ruido blanco y las componentes reales quedan quietas."""

    def __init__(self):
        self.clave = None
        self.p = None
        self.cuenta = 0

    def reiniciar(self):
        self.clave, self.p, self.cuenta = None, None, 0

    def agregar(self, clave, p: np.ndarray, n: int) -> np.ndarray:
        if n <= 1:
            self.reiniciar()
            return p
        if clave != self.clave or self.p is None or len(self.p) != len(p):
            self.clave, self.p, self.cuenta = clave, p.copy(), 1
            return self.p
        self.cuenta += 1
        a = 1.0 / min(self.cuenta, n)
        self.p = self.p + a * (p - self.p)
        return self.p

    @property
    def efectivos(self) -> int:
        return max(1, self.cuenta)


# ---------------------------------------------------------------------------
# Persistencia (fósforo): un trazo pasado a una grilla de puntos de pantalla
# ---------------------------------------------------------------------------
def rasterizar_trazo(x: np.ndarray, y: np.ndarray, cols: int, filas: int,
                     x_max: float, y_min: float, y_max: float) -> np.ndarray:
    """Marca en una grilla (cols × filas, índice [col, fila], fila 0 abajo) los puntos por
    donde pasa el trazo, uniendo cada muestra con la siguiente para que los flancos y los
    picos angostos queden marcados aunque caigan entre dos muestras."""
    img = np.zeros((cols, filas), dtype=bool)
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    if len(x) < 2:
        return img
    if len(x) < 2 * cols:                          # pocas muestras: interpolar para no dejar huecos
        xs = np.linspace(x[0], x[-1], 2 * cols)
        y = np.interp(xs, x, y)
        x = xs
    cx = np.floor(x / x_max * cols).astype(np.int64)
    fy = (y - y_min) / (y_max - y_min) * filas
    a, b = fy[:-1], fy[1:]
    cx = cx[:-1]
    ok = (cx >= 0) & (cx < cols) & ~((a < 0) & (b < 0)) & ~((a >= filas) & (b >= filas))
    lo = np.clip(np.floor(np.minimum(a, b)), 0, filas - 1).astype(np.int64)[ok]
    hi = np.clip(np.floor(np.maximum(a, b)), 0, filas - 1).astype(np.int64)[ok]
    cx = cx[ok]
    if not len(cx):
        return img
    largo = hi - lo + 1
    total = int(largo.sum())
    inicio = np.repeat(np.cumsum(largo) - largo, largo)
    filas_idx = np.repeat(lo, largo) + (np.arange(total) - inicio)
    img[np.repeat(cx, largo), filas_idx] = True
    return img


# ---------------------------------------------------------------------------
# Formato de números (coma decimal)
# ---------------------------------------------------------------------------
_PREF = [(1e9, "G"), (1e6, "M"), (1e3, "k"), (1.0, ""), (1e-3, "m"), (1e-6, "µ"), (1e-9, "n")]
_SUF = {"G": 1e9, "M": 1e6, "k": 1e3, "K": 1e3, "m": 1e-3, "u": 1e-6, "µ": 1e-6, "n": 1e-9}


def si(valor, unidad: str = "", cifras: int = 4) -> str:
    if valor is None or not math.isfinite(valor):
        return "—"
    if valor == 0:
        return f"0 {unidad}".strip()
    a = abs(valor)
    for fac, p in _PREF:
        if a >= fac * (1 - 1e-12):
            break
    num = valor / fac
    dec = max(0, cifras - 1 - int(math.floor(math.log10(abs(num)))))
    t = f"{num:.{dec}f}"
    if "." in t:
        t = t.rstrip("0").rstrip(".")
    return f"{t.replace('.', ',').replace('-', '−')} {p}{unidad}".strip()


def leer_si(texto: str) -> float:
    t = texto.strip().replace(" ", "").replace(",", ".").replace("−", "-")
    for u in ("Hz", "hz", "V", "v", "s", "%", "°", "dB"):
        if t.endswith(u) and len(t) > len(u):
            t = t[: -len(u)]
            break
    mult = 1.0
    if t and t[-1] in _SUF:
        mult = _SUF[t[-1]]
        t = t[:-1]
    v = float(t) * mult
    if not math.isfinite(v):
        raise ValueError
    return v


# ---------------------------------------------------------------------------
# Configuración persistente
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Placas soportadas
# ---------------------------------------------------------------------------
# Clave = lo que responde el firmware a "ID?" ("INSTR-F767 v0.8.18" -> "F767").
PLACAS = {
    "F767": {"nombre": "NUCLEO-F767ZI",
             "detalle": "Cortex-M7 · 216 MHz · osciloscopio hasta ~1,6 MS/s"},
    "F429": {"nombre": "NUCLEO-F429ZI",
             "detalle": "Cortex-M4 · 168 MHz · osciloscopio hasta ~1,2 MS/s"},
}
PLACA_POR_DEFECTO = "F767"


def nombre_placa(placa: str) -> str:
    return PLACAS.get(placa, {}).get("nombre", f"placa {placa}")


def carpeta_config() -> Path:
    base = os.environ.get("APPDATA")
    # Se mantiene el nombre de carpeta original para no perder calibraciones.
    return Path(base) / "InstrumentoF767" if base else Path.home() / ".instrumento_f767"


def ruta_config(placa: str = PLACA_POR_DEFECTO) -> Path:
    """Cada placa tiene su propia configuración (las calibraciones dependen del
    DAC y del ADC de cada micro). La F767 conserva el nombre original."""
    nombre = "config.json" if placa == PLACA_POR_DEFECTO else f"config_{placa}.json"
    return carpeta_config() / nombre


def ruta_preferencias() -> Path:
    return carpeta_config() / "preferencias.json"


def cargar_preferencias() -> dict:
    """{"placa": "F767", "preguntar": True, "zoom": 1.0}"""
    pref = {"placa": PLACA_POR_DEFECTO, "preguntar": True, "zoom": 1.0}
    try:
        d = json.loads(ruta_preferencias().read_text(encoding="utf-8"))
        if isinstance(d, dict):
            if d.get("placa") in PLACAS:
                pref["placa"] = d["placa"]
            pref["preguntar"] = bool(d.get("preguntar", True))
            z = d.get("zoom", 1.0)
            if isinstance(z, (int, float)) and 0.5 <= z <= 3:
                pref["zoom"] = float(z)
    except (OSError, ValueError, TypeError):
        pass
    return pref


def zoom_guardado() -> float:
    return cargar_preferencias()["zoom"]


def guardar_zoom(zoom: float):
    pref = cargar_preferencias()
    pref["zoom"] = round(float(zoom), 2)
    guardar_preferencias(pref)


def guardar_preferencias(pref: dict):
    try:
        r = ruta_preferencias()
        r.parent.mkdir(parents=True, exist_ok=True)
        tmp = r.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(pref, indent=2), encoding="utf-8")
        os.replace(tmp, r)
    except OSError:
        pass


@dataclass
class Config:
    puerto: str | None = None
    cal_salida: dict = field(default_factory=dict)     # "1:PLACA" -> Recta dict
    cal_entrada: dict = field(default_factory=dict)    # "1:ALTO"  -> Recta dict
    gen: dict = field(default_factory=dict)
    osc: dict = field(default_factory=dict)
    herramientas: dict = field(default_factory=dict)
    placa: str = PLACA_POR_DEFECTO      # a qué placa pertenece esta configuración

    def recta_salida(self, canal: int, modo: str) -> Recta:
        r = Recta.desde_dict(self.cal_salida.get(f"{canal}:{modo}", {}))
        return r or MODOS_SALIDA[modo].diseno

    def recta_entrada(self, canal: int, modo: str) -> Recta:
        r = Recta.desde_dict(self.cal_entrada.get(f"{canal}:{modo}", {}))
        return r or MODOS_ENTRADA[modo].diseno

    @staticmethod
    def cargar(placa: str = PLACA_POR_DEFECTO) -> "Config":
        ruta = ruta_config(placa)
        try:
            d = json.loads(ruta.read_text(encoding="utf-8"))
            if not isinstance(d, dict):
                raise ValueError("config.json no es un objeto JSON")
            c = Config(placa=placa)
            for k in asdict(c):
                if k in d and k != "placa":
                    setattr(c, k, d[k])
            return c
        except FileNotFoundError:
            return Config(placa=placa)
        except (OSError, ValueError, TypeError):
            # Archivo ilegible o cortado: se conserva una copia antes de que el
            # próximo guardado lo pise con los valores por defecto (las
            # calibraciones se hacen con multímetro y no conviene perderlas).
            try:
                ruta.replace(ruta.with_suffix(".json.corrupto"))
            except OSError:
                pass
            return Config(placa=placa)

    def guardar(self):
        try:
            r = ruta_config(self.placa)
            r.parent.mkdir(parents=True, exist_ok=True)
            tmp = r.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(asdict(self), indent=2, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, r)      # atómico: nunca queda un config.json a medias
        except OSError:
            pass
