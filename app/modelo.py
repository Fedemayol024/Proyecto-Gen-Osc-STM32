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


def leer_csv_forma(ruta: str) -> np.ndarray:
    """Lee una columna de números (la última de cada fila) de un CSV o TXT."""
    valores = []
    with open(ruta, encoding="utf-8", errors="replace") as f:
        for linea in f:
            partes = [p for p in linea.replace(";", ",").replace("\t", ",").split(",") if p.strip()]
            if not partes:
                continue
            try:
                valores.append(float(partes[-1].strip().replace(" ", "")))
            except ValueError:
                try:
                    valores.append(float(partes[-1].strip().replace(",", ".")))
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


def ajuste_seno(v: np.ndarray, fs: float, f: float) -> tuple[float, float, float]:
    """Ajuste por mínimos cuadrados a A·sen(2πft + φ) + C. Devuelve (A, φ en rad, C)."""
    t = np.arange(len(v)) / fs
    w = 2 * np.pi * f * t
    m = np.column_stack([np.sin(w), np.cos(w), np.ones_like(w)])
    (a, b, c), *_ = np.linalg.lstsq(m, v, rcond=None)
    return float(math.hypot(a, b)), float(math.atan2(b, a)), float(c)


def espectro(v: np.ndarray, fs: float) -> tuple[np.ndarray, np.ndarray]:
    """Espectro en dBV (valor eficaz de cada componente), ventana de Hann."""
    n = len(v)
    w = np.hanning(n)
    x = np.fft.rfft((v - v.mean()) * w)
    amp = np.abs(x) * 2 / w.sum() / math.sqrt(2)
    amp[0] = abs(v.mean())
    f = np.fft.rfftfreq(n, 1 / fs)
    return f, 20 * np.log10(np.maximum(amp, 1e-7))


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
def ruta_config() -> Path:
    base = os.environ.get("APPDATA")
    carpeta = Path(base) / "InstrumentoF767" if base else Path.home() / ".instrumento_f767"
    return carpeta / "config.json"


@dataclass
class Config:
    puerto: str | None = None
    cal_salida: dict = field(default_factory=dict)     # "1:PLACA" -> Recta dict
    cal_entrada: dict = field(default_factory=dict)    # "1:ALTO"  -> Recta dict
    gen: dict = field(default_factory=dict)
    osc: dict = field(default_factory=dict)
    herramientas: dict = field(default_factory=dict)

    def recta_salida(self, canal: int, modo: str) -> Recta:
        r = Recta.desde_dict(self.cal_salida.get(f"{canal}:{modo}", {}))
        return r or MODOS_SALIDA[modo].diseno

    def recta_entrada(self, canal: int, modo: str) -> Recta:
        r = Recta.desde_dict(self.cal_entrada.get(f"{canal}:{modo}", {}))
        return r or MODOS_ENTRADA[modo].diseno

    @staticmethod
    def cargar() -> "Config":
        ruta = ruta_config()
        try:
            d = json.loads(ruta.read_text(encoding="utf-8"))
            if not isinstance(d, dict):
                raise ValueError("config.json no es un objeto JSON")
            c = Config()
            for k in asdict(c):
                if k in d:
                    setattr(c, k, d[k])
            return c
        except FileNotFoundError:
            return Config()
        except (OSError, ValueError, TypeError):
            # Archivo ilegible o cortado: se conserva una copia antes de que el
            # próximo guardado lo pise con los valores por defecto (las
            # calibraciones se hacen con multímetro y no conviene perderlas).
            try:
                ruta.replace(ruta.with_suffix(".json.corrupto"))
            except OSError:
                pass
            return Config()

    def guardar(self):
        try:
            r = ruta_config()
            r.parent.mkdir(parents=True, exist_ok=True)
            tmp = r.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(asdict(self), indent=2, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, r)      # atómico: nunca queda un config.json a medias
        except OSError:
            pass
