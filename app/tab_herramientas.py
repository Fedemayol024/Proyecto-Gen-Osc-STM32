"""Pestaña Herramientas: frecuencímetro y salida PWM."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

import modelo as M
import widgets as W


class TabHerramientas(QWidget):
    def __init__(self, ventana):
        super().__init__()
        self.v = ventana
        cfg = ventana.config.herramientas
        raiz = QHBoxLayout(self)
        raiz.setContentsMargins(8, 8, 8, 8)

        # ---------------------------------------------- frecuencímetro
        g, lay = W.grupo("Frecuencímetro  ·  D32 (PA0) por la entrada protegida (Hoja 3)")
        self.lbl_f = QLabel("— Hz")
        self.lbl_f.setObjectName("grande")
        self.lbl_f.setAlignment(Qt.AlignCenter)
        self.lbl_t = QLabel("Período: —")
        self.lbl_t.setAlignment(Qt.AlignCenter)
        self.lbl_m = W.etiqueta_tenue("")
        self.lbl_m.setAlignment(Qt.AlignCenter)
        lay.addWidget(self.lbl_f)
        lay.addWidget(self.lbl_t)
        lay.addWidget(self.lbl_m)
        self.compuerta = W.combo(["10 ms", "100 ms", "1 s", "10 s"], cfg.get("compuerta", "1 s"))
        lay.addWidget(W.fila("Tiempo de compuerta", self.compuerta,
                             ayuda="Más tiempo = más resolución en el método por conteo"))
        fila = QHBoxLayout()
        self.btn_f = W.boton("Medir", self._alternar_f, primario=True, chequeable=True)
        fila.addWidget(self.btn_f)
        lay.addLayout(fila)
        lay.addWidget(W.etiqueta_tenue(
            "Frecuencias altas: cuenta flancos durante la compuerta (hasta decenas de MHz).\n"
            "Frecuencias bajas: mide el tiempo entre flancos con resolución de ~9 ns, así que "
            "da muchas cifras aun con compuertas cortas. La señal entra siempre por la entrada "
            "protegida FREC (Hoja 3), nunca directo a D32."))
        lay.addStretch(1)
        self.compuerta.currentIndexChanged.connect(self._reiniciar_f)
        raiz.addWidget(g, 1)

        # ---------------------------------------------- PWM
        g, lay = W.grupo("PWM complementario  ·  D6 (PE9) y D42 (PE8)")
        self.pwm_f = W.EntradaSI("Hz", 1, 50e6, cfg.get("pwm_f", 20e3), 6)
        self.pwm_c = W.EntradaSI("%", 0, 100, cfg.get("pwm_c", 50.0), 4)
        self.pwm_tm = W.EntradaSI("s", 0, 4.6e-6, cfg.get("pwm_tm", 200e-9), 4)
        lay.addWidget(W.fila("Frecuencia", self.pwm_f))
        lay.addWidget(W.fila("Ciclo útil", self.pwm_c))
        lay.addWidget(W.fila("Tiempo muerto", self.pwm_tm,
                             ayuda="Retardo entre que se apaga una salida y se enciende la otra"))
        self.btn_pwm = W.boton("Activar PWM", self._enviar_pwm, primario=True, chequeable=True)
        lay.addWidget(self.btn_pwm)
        self.lbl_pwm = W.etiqueta_tenue("")
        lay.addWidget(self.lbl_pwm)
        lay.addWidget(W.etiqueta_tenue(
            "PE9 = salida principal, PE8 = complementaria (invertida, con tiempo muerto).\n"
            "Señales de 3,3 V: para manejar MOSFET usá un driver de compuertas (IR2110, "
            "UCC27211, etc.). También sirve como generador de pulsos rápido o para "
            "compensar las puntas del osciloscopio (1 kHz, 50 %)."))
        lay.addStretch(1)
        for e in (self.pwm_f, self.pwm_c, self.pwm_tm):
            e.cambiado.connect(lambda *_: self.btn_pwm.isChecked() and self._enviar_pwm())
        raiz.addWidget(g, 1)

    def estado_config(self) -> dict:
        return {"compuerta": self.compuerta.currentText(), "pwm_f": self.pwm_f.valor(),
                "pwm_c": self.pwm_c.valor(), "pwm_tm": self.pwm_tm.valor()}

    def _ms(self) -> int:
        return {"10 ms": 10, "100 ms": 100, "1 s": 1000, "10 s": 10000}[self.compuerta.currentText()]

    def _alternar_f(self):
        if not self.v.disp.esta_conectado:
            self.btn_f.setChecked(False)
            return
        if self.btn_f.isChecked():
            self.v.disp.enviar(f"FCNT {self._ms()} 1")
            self.btn_f.setText("Detener")
            self.lbl_m.setText("Midiendo…")
        else:
            self.v.disp.enviar("FCNT 0 0")
            self.btn_f.setText("Medir")
        self.v.guardar_config_pronto()

    def _reiniciar_f(self):
        if self.btn_f.isChecked() and self.v.disp.esta_conectado:
            self.v.disp.enviar(f"FCNT {self._ms()} 1")
        self.v.guardar_config_pronto()

    def _enviar_pwm(self):
        if not self.v.disp.esta_conectado:
            self.btn_pwm.setChecked(False)
            return
        hab = 1 if self.btn_pwm.isChecked() else 0
        self.btn_pwm.setText("Desactivar PWM" if hab else "Activar PWM")
        self.v.disp.enviar(f"PWM {self.pwm_f.valor():.4f} {self.pwm_c.valor():.3f} "
                           f"{self.pwm_tm.valor() * 1e9:.1f} {hab}")
        self.v.guardar_config_pronto()

    def al_linea(self, linea: str):
        p = linea.split()
        if p[0] == "FREQ" and len(p) >= 5:
            try:
                f, metodo, flancos, ms = float(p[1]), p[2], int(p[3]), int(p[4])
            except ValueError:
                return
            if f <= 0:
                self.lbl_f.setText("— Hz")
                self.lbl_t.setText("Sin señal (o muy lenta para esta compuerta)")
            else:
                cifras = 9 if metodo == "R" else max(3, min(9, len(str(flancos)) + 1))
                self.lbl_f.setText(M.si(f, "Hz", cifras))
                self.lbl_t.setText(f"Período: {M.si(1 / f, 's', min(cifras, 7))}")
            nombre = "recíproco" if metodo == "R" else "conteo"
            self.lbl_m.setText(f"Método: {nombre} · {flancos} flancos en {M.si(ms / 1000, 's')}")
        elif p[0] == "OK" and len(p) >= 5 and p[1] == "PWM":
            try:
                f, c, tm = float(p[2]), float(p[3]), float(p[4])
            except ValueError:
                return
            self.lbl_pwm.setText(f"Real: {M.si(f, 'Hz', 6)} · {c:.2f} % · tiempo muerto {M.si(tm * 1e-9, 's', 3)}"
                                 .replace(".", ",", 1))

    def al_desconectar(self):
        self.btn_f.setChecked(False)
        self.btn_f.setText("Medir")
        self.btn_pwm.setChecked(False)
        self.btn_pwm.setText("Activar PWM")
