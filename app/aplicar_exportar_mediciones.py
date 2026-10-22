import re
from pathlib import Path

archivo = Path('tab_osciloscopio.py')
if not archivo.exists():
    print("❌ No se encontró 'tab_osciloscopio.py'")
    exit()

codigo = archivo.read_text(encoding='utf-8')

if 'QDialog' not in codigo:
    codigo = codigo.replace('from PySide6.QtWidgets import (', 'from PySide6.QtWidgets import (QDialog, ')

if 'from PySide6.QtGui import' not in codigo:
    codigo = 'from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPixmap\n' + codigo

dialogo_codigo = '''
class DialogoExportarImagen(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Opciones de exportación de imagen")
        self.resize(380, 300)
        
        layout = QVBoxLayout(self)
        
        g_ch, lay_ch = W.grupo("Canales a incluir")
        self.chk_ch1 = QCheckBox("Canal 1 (CH1)")
        self.chk_ch1.setChecked(True)
        self.chk_ch2 = QCheckBox("Canal 2 (CH2)")
        self.chk_ch2.setChecked(True)
        lay_ch.addWidget(self.chk_ch1)
        lay_ch.addWidget(self.chk_ch2)
        layout.addWidget(g_ch)
        
        g_med, lay_med = W.grupo("Mediciones a incluir")
        self.mediciones_opts = [
            ("frec", "Frecuencia", True),
            ("periodo", "Período", True),
            ("vpp", "Vpp", True),
            ("vmax", "V máx", False),
            ("vmin", "V mín", False),
            ("media", "V media", True),
            ("rms", "V rms", True),
            ("ciclo", "Ciclo útil", True),
        ]
        self.chks_med = {}
        grid = QGridLayout()
        for idx, (clave, nombre, defecto) in enumerate(self.mediciones_opts):
            chk = QCheckBox(nombre)
            chk.setChecked(defecto)
            self.chks_med[clave] = chk
            grid.addWidget(chk, idx // 2, idx % 2)
        lay_med.addLayout(grid)
        layout.addWidget(g_med)
        
        btns = QHBoxLayout()
        btn_ok = W.boton("Guardar imagen", self.accept, primario=True)
        btn_cancel = W.boton("Cancelar", self.reject)
        btns.addStretch(1)
        btns.addWidget(btn_cancel)
        btns.addWidget(btn_ok)
        layout.addLayout(btns)

    def opciones_seleccionadas(self):
        canales = []
        if self.chk_ch1.isChecked(): canales.append(1)
        if self.chk_ch2.isChecked(): canales.append(2)
        meds = [clave for clave, chk in self.chks_med.items() if chk.isChecked()]
        return canales, meds

'''

if 'class DialogoExportarImagen' not in codigo:
    codigo = re.sub(r'(class PanelCanal)', dialogo_codigo + r'\1', codigo)

nueva_exportar_png = '''    def _exportar_png(self):
        if not self.ultimo:
            return
        
        dlg = DialogoExportarImagen(self)
        if dlg.exec() != QDialog.Accepted:
            return
            
        canales_sel, meds_sel = dlg.opciones_seleccionadas()
        
        ruta, _ = QFileDialog.getSaveFileName(self, "Guardar imagen", "osciloscopio.png", "PNG (*.png)")
        if not ruta:
            return
            
        pix_plot = self.plot.grab()
        
        if not canales_sel or not meds_sel:
            pix_plot.save(ruta)
            self.v.estado(f"Guardado: {ruta}", W.OK)
            return
            
        nombres_med = {
            "frec": "Frecuencia", "periodo": "Período", "vpp": "Vpp",
            "vmax": "V máx", "vmin": "V mín", "media": "V media",
            "rms": "V rms", "ciclo": "Ciclo útil"
        }
        
        ancho = pix_plot.width()
        alto_plot = pix_plot.height()
        
        filas_canales = [c for c in canales_sel if self.canales[c].visible.isChecked()]
        if not filas_canales:
            filas_canales = canales_sel
            
        alto_banner = 35 + len(filas_canales) * 28 + 10
        alto_total = alto_plot + alto_banner
        
        imagen_final = QPixmap(ancho, alto_total)
        painter = QPainter(imagen_final)
        painter.setRenderHint(QPainter.Antialiasing)
        
        painter.fillRect(0, 0, ancho, alto_total, QColor(W.FONDO))
        painter.drawPixmap(0, 0, pix_plot)
        
        painter.setPen(QPen(QColor(W.BORDE), 2))
        painter.drawLine(0, alto_plot, ancho, alto_plot)
        
        font_header = QFont("Consolas", 10, QFont.Bold)
        font_data = QFont("Consolas", 10)
        
        cols = ["Canal"] + [nombres_med[k] for k in meds_sel]
        num_cols = len(cols)
        margen_x = 20
        ancho_col = (ancho - 2 * margen_x) / num_cols
        
        y_cursor = alto_plot + 25
        painter.setFont(font_header)
        painter.setPen(QColor(W.TENUE))
        for col_idx, col_name in enumerate(cols):
            x = margen_x + col_idx * ancho_col
            painter.drawText(int(x), int(y_cursor), col_name)
            
        for c in filas_canales:
            y_cursor += 28
            colores = {1: QColor(W.CH1), 2: QColor(W.CH2)}
            painter.setPen(colores.get(c, QColor(W.TEXTO)))
            
            painter.setFont(font_header)
            painter.drawText(int(margen_x), int(y_cursor), f"CH{c}")
            
            painter.setFont(font_data)
            for col_idx, k in enumerate(meds_sel, start=1):
                x = margen_x + col_idx * ancho_col
                txt = self.celdas[(c, k)].text() if (c, k) in self.celdas else "—"
                painter.drawText(int(x), int(y_cursor), txt)
                
        painter.end()
        imagen_final.save(ruta)
        self.v.estado(f"Guardado: {ruta}", W.OK)
'''

patron_exportar = r'    def _exportar_png\(self\):.*?(?=\n    def |\Z)'
codigo = re.sub(patron_exportar, nueva_exportar_png, codigo, flags=re.DOTALL)

archivo.write_text(codigo, encoding='utf-8')
print("🎉 ¡Menú de opciones y banner de mediciones agregados con éxito!")
