"""
NUCLEO-F767ZI (o F429ZI, con la variable de entorno SIM_PLACA=F429) simulado: implementa el protocolo del firmware sobre un
pseudo-terminal (Linux) para probar la app sin la placa.

Conexiones simuladas:
  OUT1 -> IN1 y OUT2 -> IN2   (modo "lazo", por defecto)
  OUT1 -> IN1 y OUT1 -> filtro RC (fc = 1 kHz) -> IN2   (modo "bode")
Las salidas usan la etapa "Placa ±5 V" y las entradas el rango ±10 V.
Uso: python nucleo_simulado.py [lazo|bode] [registro.txt]
"""
import math
import os
import sys
import time
import tty

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))
import modelo as M  # noqa: E402

MODO = sys.argv[1] if len(sys.argv) > 1 else "lazo"
REG = open(sys.argv[2], "w") if len(sys.argv) > 2 else None

maestro, esclavo = os.openpty()
tty.setraw(esclavo)
print(os.ttyname(esclavo), flush=True)

PLACA = os.environ.get("SIM_PLACA", "F767")
if PLACA == "F429":                     # 168 MHz, ADC a 21 MHz
    TCLK1, TCLK2, CPU = 84e6, 168e6, 168000000
    FSMAX = 21e6 / 17
else:                                   # 216 MHz, ADC a 27 MHz
    TCLK1, TCLK2, CPU = 108e6, 216e6, 216000000
    FSMAX = 27e6 / 17
FS_GEN = TCLK1 / round(TCLK1 / 1e6)
rng = np.random.default_rng(1)


class Canal:
    def __init__(self):
        self.tabla = np.full(4096, 2096, dtype=np.uint16)
        self.f = 0.0
        self.fase = 0.0
        self.hab = True
        self.reposo = 2096


gen = {1: Canal(), 2: Canal()}
pwm = {"f": 0.0, "hab": False}
dds = {"f": 0.0, "forma": 0, "hab": False, "amp": 0, "fase": 0.0, "mclk": 25e6, "mod": "NO"}
DDS_MCLK_REAL = 25.0004e6          # el cristal "verdadero" del módulo simulado (+16 ppm)
fcnt = {"ms": 0, "cont": False, "t": 0.0}


def tx(b: bytes):
    os.write(maestro, b)


def resp(t: str):
    tx((t + "\n").encode())


def vout(canal: Canal, t: np.ndarray) -> np.ndarray:
    if not canal.hab:
        cod = np.full(len(t), canal.reposo)
    else:
        ph = (canal.fase / 360.0 + canal.f * t) % 1.0
        cod = canal.tabla[(ph * 4096).astype(int) % 4096]
    return M.MODOS_SALIDA["PLACA"].diseno.volt(cod) + rng.normal(0, 0.002, len(t))


def adc(vin: np.ndarray) -> np.ndarray:
    vadc = M.BIAS_IN + M.K_IN * vin
    cod = np.rint(vadc / 3.3 * 4095 + rng.normal(0, 1.2, len(vin)))
    return np.clip(cod, 0, 4095).astype(np.uint32)


def rc(v: np.ndarray, fs: float, fc=1000.0) -> np.ndarray:
    a = 1 - math.exp(-2 * math.pi * fc / fs)
    y = np.empty_like(v)
    acc = v[0]
    for i in range(len(v)):
        acc += a * (v[i] - acc)
        y[i] = acc
    return y


def capturar(n, pre, fs, fuente, nivel, flanco, hist):
    fs = min(fs, FSMAX)
    psc = max(1, math.ceil(TCLK2 / fs / 65536))
    arr = max(2, round(TCLK2 / fs / psc))
    fs = TCLK2 / (psc * arr)
    total = n + (2 * n if fuente else 0)
    calent = 0
    if MODO == "bode":
        calent = int(min(200000, 8 * fs / (2 * math.pi * 1000.0))) + 10
    t0 = rng.uniform(0, 10)
    t = t0 + (np.arange(total + calent) - calent) / fs
    v1 = vout(gen[1], t)
    v2 = rc(v1, fs) if MODO == "bode" else vout(gen[2], t)
    c1, c2 = adc(v1[calent:]), adc(v2[calent:])
    disp = 2 if fuente == 0 else 0
    ini = 0
    if fuente:
        s = c1 if fuente == 1 else c2
        armado = False
        for i in range(total - (n - pre) + 1):
            x = int(s[i])
            if flanco == 0:
                if x <= nivel - hist:
                    armado = True
                elif armado and x >= nivel and i >= max(pre, 1):
                    ini, disp = i - pre, 1
                    break
            else:
                if x >= nivel + hist:
                    armado = True
                elif armado and x <= nivel and i >= max(pre, 1):
                    ini, disp = i - pre, 1
                    break
    pal = (c2[ini:ini + n] << 16) | c1[ini:ini + n]
    time.sleep(min(total / fs, 1.0) * 0.5)
    tx(f"DATA {n} {pre} {fs:.4f} {disp}\n".encode() + pal.astype("<u4").tobytes())


buf = bytearray()
bin_pend = None
time.sleep(0.2)
while True:
    if fcnt["ms"] and time.monotonic() >= fcnt["t"]:
        f = pwm["f"] if pwm["hab"] else gen[1].f
        if dds["hab"] and dds["forma"] in (2, 3):     # cuadrada del AD9833 en D32
            reg = round(dds["f"] * 2**28 / dds["mclk"])
            f = reg * DDS_MCLK_REAL / 2**28 / (2 if dds["forma"] == 3 else 1)
        f = f * (1 + rng.normal(0, 2e-6)) if f else 0.0
        metodo = "R" if 0 < f < 5000 else "C"
        resp(f"FREQ {f:.6f} {metodo} {int(f * fcnt['ms'] / 1000)} {fcnt['ms']}")
        fcnt["t"] = time.monotonic() + fcnt["ms"] / 1000 if fcnt["cont"] else 0
        if not fcnt["cont"]:
            fcnt["ms"] = 0
    import select
    r, _, _ = select.select([maestro], [], [], 0.05)
    if not r:
        continue
    buf += os.read(maestro, 65536)
    while True:
        if bin_pend:
            c, n, suma = bin_pend
            if len(buf) < 2 * n:
                break
            datos = np.frombuffer(bytes(buf[:2 * n]), dtype="<u2").copy()
            del buf[:2 * n]
            bin_pend = None
            if int(datos.astype(np.uint64).sum()) & 0xFFFFFFFF == suma:
                gen[c].tabla = np.minimum(datos, 4095)
                resp(f"OK GTBL {c}")
            else:
                resp("ERR GTBL suma")
            continue
        i = buf.find(b"\n")
        if i < 0:
            break
        linea = bytes(buf[:i]).decode(errors="replace").strip()
        del buf[:i + 1]
        if not linea:
            continue
        if REG:
            REG.write(linea + "\n")
            REG.flush()
        p = linea.split()
        cmd = p[0]
        try:
            if cmd == "ID?":
                resp(f"INSTR-{PLACA} v0.8.19")
            elif cmd == "INFO?":
                resp(f"INFO gen_fs={FS_GEN:.3f} osc_fsmax={FSMAX:.3f} tabla=4096 ventana=8192 cpu={CPU} wdg_ms=2000 reinicio=energia dds_mclk={round(dds['mclk'])} dds_mod=1")
            elif cmd == "GTBL":
                bin_pend = (int(p[1]), int(p[2]), int(p[3]))
            elif cmd == "GSET":
                c = int(p[1])
                inc = round(float(p[2]) / FS_GEN * 2 ** 32)
                gen[c].f = inc * FS_GEN / 2 ** 32
                gen[c].fase, gen[c].hab, gen[c].reposo = float(p[3]), p[4] != "0", int(float(p[5]))
                resp(f"OK GSET {c} {gen[c].f:.6f}")
            elif cmd == "GMOD":
                resp(f"OK GMOD {p[1]} {float(p[4]):.6f}")
            elif cmd == "GSWP":
                resp(f"OK GSWP {p[1]}")
            elif cmd == "GSYNC":
                resp("OK GSYNC")
            elif cmd == "CAP":
                capturar(int(p[1]), int(p[2]), float(p[3]), int(p[4]), int(p[5]), int(p[6]), int(p[7]))
            elif cmd == "CAPX":
                resp("OK CAPX")
            elif cmd == "FCNT":
                ms = int(float(p[1]))
                fcnt.update(ms=ms, cont=p[2] != "0", t=time.monotonic() + ms / 1000)
                resp(f"OK FCNT {ms}")
            elif cmd == "PWM":
                f, ciclo, tm, hab = float(p[1]), float(p[2]), float(p[3]), p[4] != "0"
                psc = max(1, math.ceil(TCLK2 / f / 65536))
                per = max(4, round(TCLK2 / f / psc))
                pwm.update(f=TCLK2 / (psc * per), hab=hab)
                ccr = round(per * ciclo / 100)
                resp(f"OK PWM {pwm['f']:.4f} {100 * ccr / per:.3f} {round(tm / (1e9 / TCLK2)) * 1e9 / TCLK2:.2f}")
            elif cmd == "DDS":                 # módulo AD9833
                f, forma, hab = float(p[1]), int(float(p[2])), p[3] != "0"
                if not 0 <= forma <= 3:
                    raise ValueError("forma")
                mclk = dds["mclk"]
                reg = min(max(round(min(max(f, 0), mclk / 2) * 2**28 / mclk), 0), 2**28 - 1)
                dds.update(f=reg * mclk / 2**28, forma=forma, hab=hab)
                resp(f"OK DDS {dds['f']:.4f}")
            elif cmd == "DDSF":
                g = float(p[1]) % 360
                dds["fase"] = (round(g * 4096 / 360) % 4096) * 360 / 4096
                resp(f"OK DDSF {dds['fase']:.3f}")
            elif cmd == "DDSCLK":
                hz = float(p[1])
                if not 20e6 <= hz <= 30e6:
                    raise ValueError("reloj")
                dds["mclk"] = hz
                resp(f"OK DDSCLK {hz:.1f}")
            elif cmd == "DDSMOD":
                params = {"NO": 0, "LIN": 3, "LOG": 3, "FSK": 2, "PSK": 2, "RAF": 2, "AM": 2}
                if p[1] not in params or len(p) < 2 + params[p[1]]:
                    raise ValueError("tipo")
                [float(x) for x in p[2:2 + params[p[1]]]]
                dds["mod"] = p[1]
                resp(f"OK DDSMOD {p[1]}")
            elif cmd == "DDSA":
                n = round(float(p[1]))
                if not 0 <= n <= 255:
                    raise ValueError("paso")
                dds["amp"] = n
                resp(f"OK DDSA {n}")
            elif cmd == "STAT?":
                resp("STAT subejec=0 osc=0")
            else:
                resp(f"ERR comando desconocido: {cmd}")
        except (IndexError, ValueError) as e:
            resp(f"ERR {cmd}: {e}")
