import os
from pathlib import Path

archivo = Path('tab_osciloscopio.py')
codigo = archivo.read_text(encoding='utf-8')

nueva_func = '''    def _exportar_png(self):
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
        cursores_activos = self.chk_cur.isChecked()
        texto_cursores = self.lbl_cursores.text() if cursores_activos else ""
        
        if (not canales_sel or not meds_sel) and not cursores_activos:
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
        if not filas_canales and canales_sel:
            filas_canales = canales_sel
            
        alto_banner = 15
        if canales_sel and meds_sel:
            alto_banner += 35 + len(filas_canales) * 28
        if cursores_activos:
            alto_banner += 35 if (canales_sel and meds_sel) else 40
            
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
        
        y_cursor = alto_plot
        margen_x = 20
        
        if canales_sel and meds_sel:
            y_cursor += 25
            cols = ["Canal"] + [nombres_med[k] for k in meds_sel]
            num_cols = len(cols)
            ancho_col = (ancho - 2 * margen_x) / max(1, num_cols)
            
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
        
        if cursores_activos:
            y_cursor += 30 if (canales_sel and meds_sel) else 25
            painter.setFont(font_header)
            painter.setPen(QColor("#d2a8ff"))
            painter.drawText(int(margen_x), int(y_cursor), f"Cursores: {texto_cursores}")
                
        painter.end()
        imagen_final.save(ruta)
        self.v.estado(f"Guardado: {ruta}", W.OK)
'''

# Reemplazo seguro cortando desde donde empieza la funcion
idx = codigo.find('    def _exportar_png(self):')
if idx != -1:
    codigo = codigo[:idx] + nueva_func
    archivo.write_text(codigo, encoding='utf-8')
    print("✅ Actualizado correctamente.")
else:
    print("❌ Error: No se encontro la funcion en el archivo.")
