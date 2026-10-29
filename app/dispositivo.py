"""
Comunicación con la placa (NUCLEO-F767ZI o NUCLEO-F429ZI) por el puerto USB virtual.

Un hilo lee continuamente: separa las líneas de texto y, cuando llega
"DATA n pre fs disparado", lee los 4·n bytes binarios que siguen y los
entrega ya separados en dos canales (códigos del ADC).
Todo se informa con señales de Qt (seguras entre hilos).
"""
from __future__ import annotations

import threading
import time

import numpy as np
import serial
import serial.tools.list_ports
from PySide6.QtCore import QObject, Signal

ID_PREFIJO = "INSTR-"      # "INSTR-F767 v0.8.19" o "INSTR-F429 v0.8.19"
VID_ST, PID_CDC = 0x0483, 0x5740


def listar_puertos() -> list[tuple[str, str]]:
    """[(dispositivo, etiqueta)], primero el USB nativo del Nucleo."""
    salida = []
    for p in serial.tools.list_ports.comports():
        desc = p.description if p.description and p.description != "n/a" else "Puerto serie"
        es_nucleo = p.vid == VID_ST and p.pid == PID_CDC
        es_stlink = p.vid == VID_ST and not es_nucleo
        if es_nucleo:
            etiqueta = f"{p.device} · Instrumento (USB del Nucleo)"
        elif es_stlink:
            etiqueta = f"{p.device} · ST-LINK (no es este)"
        else:
            etiqueta = f"{p.device} · {desc}"
        salida.append((0 if es_nucleo else (2 if es_stlink else 1), p.device, etiqueta))
    salida.sort()
    return [(d, e) for _, d, e in salida]


class Dispositivo(QObject):
    conectado = Signal(str)            # versión
    desconectado = Signal(str)         # motivo
    error = Signal(str)
    linea = Signal(str)
    datos = Signal(object)             # dict: n, pre, fs, disparado, ch1, ch2 (códigos)

    def __init__(self):
        super().__init__()
        self._ser: serial.Serial | None = None
        self._activo = False
        self._lock = threading.Lock()
        self.puerto: str | None = None
        self.version: str | None = None
        self.placa: str | None = None      # placa que respondió ("F767", "F429")
        self.info: dict = {}

    # ------------------------------------------------------------------
    @property
    def esta_conectado(self) -> bool:
        return self._activo and self._ser is not None

    def abrir(self, puerto: str):
        self.cerrar()
        threading.Thread(target=self._conectar, args=(puerto,), daemon=True).start()

    def cerrar(self):
        self._activo = False
        ser, self._ser = self._ser, None
        if ser:
            try:
                ser.close()
            except Exception:
                pass

    def enviar(self, texto: str) -> bool:
        return self._escribir((texto.strip() + "\n").encode("ascii"))

    def enviar_tabla(self, canal: int, codigos: np.ndarray) -> bool:
        cod = np.asarray(codigos, dtype="<u2")
        suma = int(cod.astype(np.uint64).sum()) & 0xFFFFFFFF
        cab = f"GTBL {canal} {len(cod)} {suma}\n".encode("ascii")
        return self._escribir(cab + cod.tobytes())

    def _escribir(self, datos: bytes) -> bool:
        ser = self._ser
        if not ser or not self._activo:
            return False
        try:
            with self._lock:
                ser.write(datos)
            return True
        except Exception as e:  # noqa: BLE001
            self._perdida(f"Error al escribir: {e}")
            return False

    # ------------------------------------------------------------------
    def _conectar(self, puerto: str):
        try:
            ser = serial.Serial(puerto, 115200, timeout=0.05, write_timeout=2)
        except serial.SerialException as e:
            m = str(e)
            if "PermissionError" in m or "Access is denied" in m or "denegado" in m:
                m = f"{puerto} está ocupado por otro programa."
            self.error.emit(m)
            return
        buf = b""
        version = None
        placa = None
        info = {}
        t0 = time.monotonic()
        ultimo = 0.0
        try:
            ser.reset_input_buffer()
            ser.write(b"\nCAPX\n")
            while time.monotonic() - t0 < 4.0 and not (version and info):
                if time.monotonic() - ultimo > 0.4:
                    ser.write(b"ID?\nINFO?\n")
                    ultimo = time.monotonic()
                buf += ser.read(ser.in_waiting or 1)
                while b"\n" in buf:
                    l, buf = buf.split(b"\n", 1)
                    s = l.decode("ascii", "replace").strip()
                    if s.startswith(ID_PREFIJO):
                        partes = s.split()
                        placa = partes[0][len(ID_PREFIJO):]
                        version = partes[1].lstrip("v") if len(partes) > 1 else "?"
                    elif s.startswith("INFO"):
                        for p in s.split()[1:]:
                            if "=" in p:
                                k, v = p.split("=", 1)
                                try:
                                    info[k] = float(v)
                                except ValueError:
                                    info[k] = v          # texto (p. ej. reinicio=watchdog)
        except Exception as e:  # noqa: BLE001
            ser.close()
            self.error.emit(f"Error de comunicación: {e}")
            return
        if not version:
            ser.close()
            self.error.emit(f"La placa en {puerto} no respondió. Revisá: 1) el cable en el USB USER "
                            "(CN13); 2) que el LED azul LD2 parpadee (si no, falta instrumento_iniciar() "
                            "e instrumento_lazo() en main.c); 3) que CDC_Receive_FS de usbd_cdc_if.c "
                            "llame a instrumento_usb_rx(Buf, *Len).")
            return
        self._ser, self._activo = ser, True
        self.puerto, self.version, self.info, self.placa = puerto, version, info, placa
        self.conectado.emit(version)
        threading.Thread(target=self._lector, args=(ser,), daemon=True).start()

    def _lector(self, ser: serial.Serial):
        buf = bytearray()
        esperando: dict | None = None
        while self._activo and self._ser is ser:
            try:
                d = ser.read(ser.in_waiting or 1)
            except Exception as e:  # noqa: BLE001
                if self._ser is ser:
                    self._perdida(f"Se perdió la conexión ({e.__class__.__name__}).")
                return
            if not d:
                continue
            buf += d
            while True:
                if esperando is not None:
                    need = esperando["n"] * 4
                    if len(buf) < need:
                        break
                    crudo = np.frombuffer(bytes(buf[:need]), dtype="<u4")
                    del buf[:need]
                    esperando["ch1"] = (crudo & 0xFFFF).astype(np.uint16)
                    esperando["ch2"] = (crudo >> 16).astype(np.uint16)
                    self.datos.emit(esperando)
                    esperando = None
                    continue
                i = buf.find(b"\n")
                if i < 0:
                    if len(buf) > 65536:
                        buf.clear()
                    break
                linea = bytes(buf[:i]).decode("ascii", "replace").strip()
                del buf[:i + 1]
                if linea.startswith("DATA "):
                    p = linea.split()
                    try:
                        esperando = {"n": int(p[1]), "pre": int(p[2]), "fs": float(p[3]),
                                     "disparado": int(p[4])}
                    except (IndexError, ValueError):
                        esperando = None
                    if esperando is not None and not 0 < esperando["n"] <= int(self.info.get("ventana", 8192)):
                        esperando = None   # encabezado dañado: no esperar bytes que nunca van a llegar
                elif linea:
                    self.linea.emit(linea)

    def _perdida(self, motivo: str):
        if self._activo:
            self.cerrar()
            self.desconectado.emit(motivo)
