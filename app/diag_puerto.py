"""Diagnóstico del puerto del instrumento.
Uso:  python diag_puerto.py COM11
Abre el puerto, manda ID? e INFO? y muestra TODO lo que llega durante 4 s."""
import sys
import time

import serial

puerto = sys.argv[1] if len(sys.argv) > 1 else "COM11"
print(f"Abriendo {puerto}...")
s = serial.Serial(puerto, 115200, timeout=0.1)
s.dtr = True
time.sleep(0.3)
for cmd in (b"ID?\n", b"INFO?\n", b"STAT?\n"):
    print(">>", cmd)
    s.write(cmd)
    t0 = time.time()
    while time.time() - t0 < 1.3:
        d = s.read(256)
        if d:
            print("<<", d)
s.close()
print("Listo. Si no apareció ninguna línea '<<', la placa no está respondiendo.")
