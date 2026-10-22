"""Pestaña Calibración: salidas con multímetro y entradas con el generador."""
from __future__ import annotations

import time

import numpy as np
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QVBoxLayout, QWidget

import modelo as M
import widgets as W

COD_A, COD_B = 600, 3500          # zona lineal del DAC


class TabCalibracion(QWidget):
    def __init__(self, ventana):
        super().__init__()
        self.v = ventana
        self.auto = None          # estado de la autocalibración
        self.cero = False
        raiz = QHBoxLayout(self)
        raiz.setContentsMargins(8, 8, 8, 8)

        # ------------------------------------------------ salidas
        g, lay = W.grupo("1 · Salidas del generador (con multímetro)")
        lay.addWidget(W.etiqueta_tenue(
            "Medí con un multímetro en V DC entre la salida y GND. Se ponen dos niveles fijos "
            "y escribís lo que marca. Hacelo primero: la calibración de las entradas usa las salidas."))
        self.s_canal = W.combo(["CH1", "CH2"])
        self.s_modo = W.combo([m.nombre for m in M.MODOS_SALIDA.values()])
        lay.addWidget(W.fila("Canal", self.s_canal))
        lay.addWidget(W.fila("Salida", self.s_modo))
        self.medidas = []
        for i, cod in enumerate((COD_A, COD_B), 1):
            f = QHBoxLayout()
            b = W.boton(f"Poner punto {i}", lambda _=False, c=cod: self._poner(c))
            e = QLineEdit()
            e.setPlaceholderText("V medidos")
            e.setFixedWidth(110)
            f.addWidget(b)
            f.addWidget(QLabel(f"código {cod}"))
            f.addStretch(1)
            f.addWidget(e)
            lay.addLayout(f)
            self.medidas.append((cod, e))
        f = QHBoxLayout()
        f.addWidget(W.boton("Guardar", self._guardar_salida, primario=True))
        f.addWidget(W.boton("Valores de diseño", self._diseno_salida))
        lay.addLayout(f)
        self.lbl_s = W.etiqueta_tenue("")
        lay.addWidget(self.lbl_s)
        lay.addStretch(1)
        raiz.addWidget(g, 1)

        # ------------------------------------------------ entradas
        g, lay = W.grupo("2 · Entradas del osciloscopio (automática)")
        lay.addWidget(W.etiqueta_tenue(
            "Conectá OUT1 → IN1 y OUT2 → IN2 (salidas en modo «Placa ±5 V», ya calibradas). "
            "Se calibra el rango de entrada elegido en la pestaña Osciloscopio para cada canal "
            "(poné la llave de la placa en ese mismo rango). El generador pone dos tensiones "
            "conocidas y se ajusta la recta de cada entrada."))
        self.btn_auto = W.boton("Autocalibrar entradas", self._autocal, primario=True)
        lay.addWidget(self.btn_auto)
        lay.addWidget(W.boton("Cero: entradas a GND", self._cero))
        lay.addWidget(W.etiqueta_tenue("«Cero» corrige solo el desplazamiento: uní cada entrada a GND y tocá el botón."))
        lay.addWidget(W.boton("Entradas: valores de diseño", self._diseno_entrada))
        self.lbl_e = W.etiqueta_tenue("")
        lay.addWidget(self.lbl_e)
        lay.addStretch(1)
        raiz.addWidget(g, 1)

        self.t = QTimer(self)
        self.t.setSingleShot(True)
        self.t.timeout.connect(self._auto_capturar)

    # ------------------------------------------------ salidas
    def _canal_modo(self):
        c = 1 if self.s_canal.currentText() == "CH1" else 2
        m = next(k for k, x in M.MODOS_SALIDA.items() if x.nombre == self.s_modo.currentText())
        return c, m

    def _poner(self, cod):
        if not self.v.disp.esta_conectado:
            self.v.estado("Conectá la placa primero.", W.ALERTA)
            return
        c, _ = self._canal_modo()
        self.v.disp.enviar_tabla(c, np.full(M.TABLA_N, cod, dtype=np.uint16))
        self.v.disp.enviar(f"GSET {c} 0 0 1 {cod}")
        self.v.disp.enviar(f"GMOD {c} NO 0 0 0")
        self.v.disp.enviar(f"GSWP {c} NO")
        self.lbl_s.setText(f"Salida CH{c} en código {cod}. Medí y escribí el valor.")

    def _guardar_salida(self):
        c, m = self._canal_modo()
        try:
            (ca, ea), (cb, eb) = self.medidas
            r = M.Recta(ca, M.leer_si(ea.text()), cb, M.leer_si(eb.text()))
        except ValueError:
            self.lbl_s.setText("Escribí las dos tensiones medidas.")
            return
        d = M.MODOS_SALIDA[m].diseno
        if not r.valida() or abs(r.pendiente / d.pendiente - 1) > 0.35:
            self.lbl_s.setText("Los valores están muy lejos de lo esperado; revisá la medición y el modo de salida.")
            return
        self.v.config.cal_salida[f"{c}:{m}"] = r.__dict__
        self.v.config.guardar()
        self.lbl_s.setText(f"Guardado. {abs(r.pendiente) * 1000:.3f} mV por paso.".replace(".", ","))
        self.v.tab_gen.paneles[c]._cambio()
        self.v.tab_gen.reenviar_todo()

    def _diseno_salida(self):
        c, m = self._canal_modo()
        self.v.config.cal_salida.pop(f"{c}:{m}", None)
        self.v.config.guardar()
        self.lbl_s.setText("Se volvió a los valores de diseño.")
        self.v.tab_gen.paneles[c]._cambio()
        self.v.tab_gen.reenviar_todo()

    # ------------------------------------------------ entradas
    def _niveles(self, canal):
        rango = M.MODOS_ENTRADA[self.v.tab_osc.canales[canal].clave_entrada].rango
        a = min(4.0, 0.7 * rango)
        return -a, a

    def _autocal(self):
        if not self.v.disp.esta_conectado:
            self.v.estado("Conectá la placa primero.", W.ALERTA)
            return
        self.v.tab_osc._set_run(False)
        self.v.cancelar_captura()
        self.auto = {"paso": 0, "lect": {1: [], 2: []}, "volts": {1: [], 2: []}}
        self.btn_auto.setEnabled(False)
        self._auto_poner()

    def _auto_poner(self):
        paso = self.auto["paso"]
        for c in (1, 2):
            niveles = self._niveles(c)
            if self.v.tab_osc.canales[c].clave_entrada == "DIRECTO":
                niveles = (0.5, 2.8)
            v = niveles[paso]
            modo = "PLACA" if self.v.tab_osc.canales[c].clave_entrada != "DIRECTO" else "DIRECTO"
            r = self.v.config.recta_salida(c, modo)
            cod = int(np.clip(np.rint(r.codigo(v)), 0, 4095))
            self.auto["volts"][c].append(float(r.volt(cod)))
            self.v.disp.enviar_tabla(c, np.full(M.TABLA_N, cod, dtype=np.uint16))
            self.v.disp.enviar(f"GSET {c} 0 0 1 {cod}")
            self.v.disp.enviar(f"GMOD {c} NO 0 0 0")
            self.v.disp.enviar(f"GSWP {c} NO")
        self.lbl_e.setText(f"Midiendo nivel {paso + 1} de 2…")
        self.t.start(300)

    def _auto_capturar(self):
        self.v.pedir_captura("cal", 2000, 0, 100000)

    def al_recibir(self, d):
        if not self.auto and not self.cero:
            return
        if self.cero:
            self.cero = False
            for c in (1, 2):
                clave = self.v.tab_osc.canales[c].clave_entrada
                r = self.v.config.recta_entrada(c, clave)
                cod0 = float(np.mean(d[f"ch{c}"]))
                desplaz = float(r.volt(cod0))
                nueva = M.Recta(r.codigo_a, r.volt_a - desplaz, r.codigo_b, r.volt_b - desplaz)
                self.v.config.cal_entrada[f"{c}:{clave}"] = nueva.__dict__
            self.v.config.guardar()
            self.lbl_e.setText("Cero corregido en las dos entradas.")
            self.v.dueno_captura = None
            return
        for c in (1, 2):
            self.auto["lect"][c].append(float(np.mean(d[f"ch{c}"])))
        self.auto["paso"] += 1
        if self.auto["paso"] < 2:
            self._auto_poner()
            return
        txt = []
        for c in (1, 2):
            (ca, cb), (va, vb) = self.auto["lect"][c], self.auto["volts"][c]
            clave = self.v.tab_osc.canales[c].clave_entrada
            r = M.Recta(ca, va, cb, vb)
            d = M.MODOS_ENTRADA[clave].diseno
            if r.valida() and abs(r.pendiente / d.pendiente - 1) < 0.35:
                self.v.config.cal_entrada[f"{c}:{clave}"] = r.__dict__
                txt.append(f"IN{c} ({M.MODOS_ENTRADA[clave].nombre}): {abs(r.pendiente) * 1000:.3f} mV/código")
            else:
                txt.append(f"IN{c}: lectura fuera de lo esperado (¿está conectada OUT{c} → IN{c}?)")
        self.v.config.guardar()
        self.lbl_e.setText("\n".join(txt).replace(".", ","))
        self.auto = None
        self.btn_auto.setEnabled(True)
        self.v.dueno_captura = None
        self.v.tab_gen.reenviar_todo()

    def _cero(self):
        if not self.v.disp.esta_conectado:
            return
        self.v.tab_osc._set_run(False)
        self.cero = True
        self.v.pedir_captura("cal", 2000, 0, 100000)

    def _diseno_entrada(self):
        for c in (1, 2):
            self.v.config.cal_entrada.pop(f"{c}:{self.v.tab_osc.canales[c].clave_entrada}", None)
        self.v.config.guardar()
        self.lbl_e.setText("Entradas con valores de diseño.")
