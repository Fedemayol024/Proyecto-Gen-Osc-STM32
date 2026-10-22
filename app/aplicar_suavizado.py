import re
from pathlib import Path

archivo = Path("tab_osciloscopio.py")
if not archivo.exists():
    print("❌ No encontré 'tab_osciloscopio.py'. Asegúrate de ejecutar esto dentro de la carpeta 'app'.")
    exit()

codigo = archivo.read_text(encoding="utf-8")

# 1. Inyectar el control en la interfaz
if "self.suavizado =" not in codigo:
    codigo = re.sub(
        r'(pl\.addLayout\(filab\)\n\n\s*)(g, lay = W\.grupo\("Horizontal"\))',
        r'\1g, lay = W.grupo("Suavizado")\n        self.suavizado = W.combo(["Desactivado", "x4", "x8", "x16", "x32"])\n        self.suavizado.setCurrentIndex(cfg.get("suavizado", 0))\n        self.suavizado.currentIndexChanged.connect(self._cambio)\n        lay.addWidget(W.fila("Promedio (Average)", self.suavizado))\n        pl.addWidget(g)\n\n        \2',
        codigo
    )
    print("✅ Panel de suavizado agregado.")

# 2. Guardar el estado en la configuración
if '"suavizado": self.suavizado.currentIndex()' not in codigo:
    codigo = re.sub(
        r'("nivel": self\.nivel\.valor\(\),\s*\n\s*)("ch1": self\.canales\[1\]\.estado\(\))',
        r'\1"suavizado": self.suavizado.currentIndex(),\n                \2',
        codigo
    )
    print("✅ Guardado de configuración actualizado.")

# 3. Modificar la función que procesa los voltajes
if 'np.convolve' not in codigo:
    patron = r'(    def _a_volts\(self, d: dict\) -> dict:\n)(.*?\n)(?=    def |\Z)'
    nueva_funcion = """        r = {"fs": d["fs"], "pre": d["pre"], "n": d["n"], "disparado": d["disparado"]}
        
        # Tamaño de la ventana de suavizado ("Desactivado"=0, "x4"=1, "x8"=2...)
        ventana = [1, 4, 8, 16, 32][self.suavizado.currentIndex()]
        
        for c in (1, 2):
            v = self.recta(c).volt(d[f"ch{c}"]) * self.canales[c].factor
            
            # Aplicar filtro de Promedio Móvil si está activado
            if ventana > 1 and len(v) >= ventana:
                v = np.convolve(v, np.ones(ventana)/ventana, mode='same')
            
            if self.canales[c].acople.currentText() == "AC":
                v = v - v.mean()
            r[c] = v
        return r
"""
    codigo = re.sub(patron, r'\g<1>' + nueva_funcion, codigo, flags=re.DOTALL)
    print("✅ Filtro de Promedio Móvil inyectado con éxito.")

archivo.write_text(codigo, encoding="utf-8")
print("🎉 ¡Todo listo! Ya puedes abrir tu aplicación y probar el suavizado.")