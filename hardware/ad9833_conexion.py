import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch
BG="#0d1117"; PANEL="#161b22"; TX="#e6edf3"; TN="#8b949e"
fig,ax=plt.subplots(figsize=(13,7.2),dpi=150); fig.patch.set_facecolor(BG); ax.set_facecolor(BG)
ax.set_xlim(0,130); ax.set_ylim(0,72); ax.axis("off")
def caja(x,y,w,h,t,sub,col):
    ax.add_patch(FancyBboxPatch((x,y),w,h,boxstyle="round,pad=0.4,rounding_size=2",fc=PANEL,ec=col,lw=2))
    ax.text(x+w/2,y+h-3,t,ha="center",va="top",color=TX,fontsize=13,weight="bold")
    if sub: ax.text(x+w/2,y+h-7.2,sub,ha="center",va="top",color=TN,fontsize=9)
ax.text(2,69,"Conexión del módulo AD9833 a la Nucleo (F767ZI y F429ZI, mismos pines)",color=TX,fontsize=15,weight="bold",va="top")
caja(4,10,30,52,"Nucleo","conector CN8 (lado izquierdo,\nzona de abajo)","#30363d")
caja(70,12,26,50,"Módulo AD9833","AD9833 + MCP41010 + AD8051\n(el SMA se reemplaza por la BNC)","#3fb950")
filas=[("3V3","CN8-7","VCC","#f85149","alimentación"),
       ("GND","CN8-11","GND","#8b949e","masa"),
       ("PC10 · D45","CN8-6","CLK","#58a6ff","reloj SPI"),
       ("PC12 · D47","CN8-10","DAT","#d29922","datos SPI"),
       ("PD2 · D48","CN8-12","FSY","#bc8cff","selección AD9833"),
       ("PG2 · D49","CN8-14","CS","#ff7b72","selección pote digital")]
y0=46
for i,(pin,cn,mod,c,fn) in enumerate(filas):
    y=y0-i*6
    ax.plot([34.4,69.6],[y,y],color=c,lw=2.6,solid_capstyle="round")
    ax.plot(34.4,y,"o",color=c,ms=7); ax.plot(69.6,y,"o",color=c,ms=7)
    ax.text(32.8,y,pin,ha="right",va="center",color=TX,fontsize=10.5)
    ax.text(6,y,cn,ha="left",va="center",color=TN,fontsize=9)
    ax.text(71.6,y,mod,ha="left",va="center",color=TX,fontsize=10.5,weight="bold")
    ax.text(52,y+1.3,fn,ha="center",va="bottom",color=c,fontsize=8.5)
# salida
ax.plot([96.4,104],[22,22],color="#3fb950",lw=2.6); ax.plot([96.4,104],[18,18],color="#8b949e",lw=2.6)
ax.text(94.6,22,"PGA",ha="right",va="center",color=TX,fontsize=10)
ax.text(94.6,18,"GND",ha="right",va="center",color=TX,fontsize=10)
caja(104,14,22,12,"BNC","sonda en ×1","#d29922")
ax.text(115,10.5,"→ circuito a medir\n(y también a A0 / IN1)",ha="center",va="top",color=TN,fontsize=9.5)
notas=("• Alimentar el módulo con 3V3: el MCP41010 (potenciómetro de amplitud) a 5 V necesita 3,5 V\n"
       "  para un «1» y la Nucleo da 3,3 V. Salidas: VOUT = directa (~0,6 Vpp), PGA = amplificada.\n"
       "• Ningún pin del módulo le manda tensión a la Nucleo: solo recibe órdenes. Cables cortos (< 15 cm).\n"
       "• Son 6 Dupont, todos del mismo conector CN8. No choca con nada del proyecto actual.")
ax.text(4,7,notas,color=TN,fontsize=9.3,va="top",family="DejaVu Sans")
import os; os.chdir(os.path.dirname(os.path.abspath(__file__))); fig.savefig("ad9833_conexion.png",facecolor=BG,bbox_inches="tight")
