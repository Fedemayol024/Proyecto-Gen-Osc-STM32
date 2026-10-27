"""Pestaña Generador (2 canales)."""
from __future__ import annotations

from dataclasses import asdict, fields

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QCheckBox, QFileDialog, QHBoxLayout, QLabel, QScrollArea,
                               QVBoxLayout, QWidget)

import modelo as M
import widgets as W

COLORES = {1: W.CH1, 2: W.CH2}


class PanelGenerador(QWidget):
    def __init__(self, tab, canal: int, datos: dict):
        super().__init__()
        self.tab, self.canal = tab, canal
        self.c = M.CanalGen(**{k: v for k, v in datos.items() if k in {f.name for f in fields(M.CanalGen)}})
        self.arbitraria = None
        self.tabla: M.TablaGen | None = None
        self.frec_real = None

        raiz = QVBoxLayout(self)
        raiz.setContentsMargins(0, 0, 0, 0)

        g, lay = W.grupo(f"Canal {canal}  ·  salida {'D24 (PA4)' if canal == 1 else 'D13 (PA5)'}")
        g.setStyleSheet(f"QGroupBox::title {{ color: {COLORES[canal]}; }}")
        raiz.addWidget(g)

        self.hab = W.boton("", self._alternar, chequeable=True)
        self.hab.setChecked(self.c.habilitado)
        W.tam(self.hab, "setMinimumHeight", 34)
        lay.addWidget(self.hab)

        self.salida = W.combo([m.nombre for m in M.MODOS_SALIDA.values()],
                              M.MODOS_SALIDA[self.c.modo_salida].nombre)
        self.forma = W.combo(M.FORMAS, self.c.forma)
        self.frec = W.EntradaSI("Hz", 0.01, 100e3, self.c.frecuencia, 7)
        self.periodo = W.EntradaSI("s", 1e-5, 100, 1 / self.c.frecuencia, 6)
        self.vpp = W.EntradaSI("V", 0, 11, self.c.vpp, 4)
        self.offset = W.EntradaSI("V", -6, 6, self.c.offset, 4)
        self.ciclo = W.EntradaSI("%", 0, 100, self.c.ciclo, 4)
        self.fase = W.EntradaSI("°", 0, 360, self.c.fase, 4)
        self.btn_csv = W.boton("Cargar CSV…", self._cargar_csv)

        lay.addWidget(W.fila("Salida", self.salida))
        lay.addWidget(W.fila("Forma", self.forma))
        lay.addWidget(W.fila("", self.btn_csv))
        lay.addWidget(W.fila("Frecuencia", self.frec))
        lay.addWidget(W.fila("Período", self.periodo))
        lay.addWidget(W.fila("Amplitud (pico a pico)", self.vpp))
        lay.addWidget(W.fila("Offset", self.offset))
        self.fila_ciclo = W.fila("Ciclo útil", self.ciclo)
        lay.addWidget(self.fila_ciclo)
        lay.addWidget(W.fila("Fase", self.fase, ayuda="Fase relativa entre canales (tocá «Sincronizar fases»)"))
        self.lbl_info = W.etiqueta_tenue("")
        lay.addWidget(self.lbl_info)

        g2, l2 = W.grupo("Modulación")
        self.mod = W.combo(["Ninguna", "AM", "FM"], self.c.modulacion)
        self.mod_frec = W.EntradaSI("Hz", 0.01, 10e3, self.c.mod_frec, 5)
        self.am_prof = W.EntradaSI("%", 0, 100, self.c.am_prof, 4)
        self.fm_desv = W.EntradaSI("Hz", 0, 50e3, self.c.fm_desvio, 5)
        l2.addWidget(W.fila("Tipo", self.mod))
        l2.addWidget(W.fila("Frecuencia moduladora", self.mod_frec))
        self.fila_am = W.fila("Profundidad AM", self.am_prof)
        self.fila_fm = W.fila("Desvío FM", self.fm_desv)
        l2.addWidget(self.fila_am)
        l2.addWidget(self.fila_fm)
        raiz.addWidget(g2)

        g3, l3 = W.grupo("Barrido de frecuencia")
        self.bar = W.combo(["No", "Lineal", "Logarítmico"], self.c.barrido)
        self.bar_f1 = W.EntradaSI("Hz", 0.01, 100e3, self.c.bar_f1, 5)
        self.bar_f2 = W.EntradaSI("Hz", 0.01, 100e3, self.c.bar_f2, 5)
        self.bar_t = W.EntradaSI("s", 0.01, 1000, self.c.bar_t, 4)
        l3.addWidget(W.fila("Modo", self.bar))
        l3.addWidget(W.fila("Desde", self.bar_f1))
        l3.addWidget(W.fila("Hasta", self.bar_f2))
        l3.addWidget(W.fila("Duración", self.bar_t))
        raiz.addWidget(g3)

        for c in (self.salida, self.forma, self.mod, self.bar):
            c.currentIndexChanged.connect(self._cambio)
        for e in (self.vpp, self.offset, self.ciclo, self.fase, self.mod_frec, self.am_prof,
                  self.fm_desv, self.bar_f1, self.bar_f2, self.bar_t):
            e.cambiado.connect(self._cambio)
        self.frec.cambiado.connect(lambda f: (self.periodo.set_valor(1 / f), self._cambio()))
        self.periodo.cambiado.connect(lambda t: (self.frec.set_valor(1 / t), self._cambio()))
        self._actualizar_visibles()

    # ------------------------------------------------------------------
    def _leer(self):
        c = self.c
        c.habilitado = self.hab.isChecked()
        c.modo_salida = next(k for k, m in M.MODOS_SALIDA.items() if m.nombre == self.salida.currentText())
        c.forma = self.forma.currentText()
        c.frecuencia = self.frec.valor()
        c.vpp, c.offset, c.ciclo, c.fase = self.vpp.valor(), self.offset.valor(), self.ciclo.valor(), self.fase.valor()
        c.modulacion = self.mod.currentText()
        c.mod_frec, c.am_prof, c.fm_desvio = self.mod_frec.valor(), self.am_prof.valor(), self.fm_desv.valor()
        c.barrido = self.bar.currentText()
        c.bar_f1, c.bar_f2, c.bar_t = self.bar_f1.valor(), self.bar_f2.valor(), self.bar_t.valor()

    def _actualizar_visibles(self):
        f = self.forma.currentText()
        self.fila_ciclo.setVisible(f in ("Cuadrada", "Triangular"))
        self.fila_ciclo.layout().itemAt(0).widget().setText("Simetría" if f == "Triangular" else "Ciclo útil")
        self.btn_csv.setVisible(f == "Arbitraria")
        es_dc = f == "Continua"
        for w in (self.frec, self.periodo, self.vpp, self.fase):
            w.setEnabled(not es_dc)
        m = self.mod.currentText()
        self.fila_am.setVisible(m == "AM")
        self.fila_fm.setVisible(m == "FM")
        self.mod_frec.setEnabled(m != "Ninguna")
        b = self.bar.currentText() != "No"
        for w in (self.bar_f1, self.bar_f2, self.bar_t):
            w.setEnabled(b)
        self.hab.setText(f"●  CH{self.canal} ACTIVADO" if self.hab.isChecked() else f"○  CH{self.canal} APAGADO (0 V)")
        modo = M.MODOS_SALIDA[self.c.modo_salida]
        lo, hi = M.limites_salida(modo, self.recta())
        self.offset.set_rango(lo, hi)
        self.vpp.set_rango(0, hi - lo)

    def recta(self) -> M.Recta:
        return self.tab.v.config.recta_salida(self.canal, self.c.modo_salida)

    def _alternar(self):
        self._cambio()

    def _cambio(self, *_):
        self._leer()
        self._actualizar_visibles()
        self.tabla = M.armar_tabla(self.c, self.recta(), self.arbitraria)
        lo, hi = self.tabla.lim
        txt = f"Rango de esta salida: {M.si(lo, 'V', 3)} a {M.si(hi, 'V', 3)}"
        if self.tabla.recortada:
            txt = f"<span style='color:{W.ALERTA}'>⚠ La señal se recorta.</span> " + txt
        if self.frec_real and self.c.forma != "Continua":
            txt += f"<br>Frecuencia confirmada: {M.si(self.frec_real, 'Hz', 8)}"
        self.lbl_info.setText(txt)
        self.tab.programar_envio(self.canal)
        self.tab.actualizar_vista()

    def _cargar_csv(self):
        ruta, _ = QFileDialog.getOpenFileName(self, "Forma de onda arbitraria", "",
                                              "Datos (*.csv *.txt);;Todos (*.*)")
        if not ruta:
            return
        try:
            self.arbitraria = M.leer_csv_forma(ruta)
            self.tab.v.estado(f"Forma cargada: {len(self.arbitraria)} puntos (se escala a la amplitud elegida).", W.OK)
        except (OSError, ValueError) as e:
            self.tab.v.estado(f"No se pudo leer el archivo: {e}", W.ERROR)
            return
        self._cambio()

    # ------------------------------------------------------------------
    def comandos(self) -> list:
        """Lista de comandos (texto o ('tabla', codigos)) para aplicar este canal."""
        c, t = self.c, self.tabla
        f = 0.0 if c.forma == "Continua" else c.frecuencia
        cmds = [("tabla", t.codigos),
                f"GSET {self.canal} {f:.6f} {c.fase:.3f} {1 if c.habilitado else 0} {t.reposo}"]
        if c.modulacion == "AM":
            cmds.append(f"GMOD {self.canal} AM {c.am_prof / 100:.4f} {c.mod_frec:.4f} {t.centro:.2f}")
        elif c.modulacion == "FM":
            cmds.append(f"GMOD {self.canal} FM {c.fm_desvio:.4f} {c.mod_frec:.4f} {t.centro:.2f}")
        else:
            cmds.append(f"GMOD {self.canal} NO 0 0 0")
        if c.barrido == "Lineal":
            cmds.append(f"GSWP {self.canal} LIN {c.bar_f1:.4f} {c.bar_f2:.4f} {c.bar_t:.4f}")
        elif c.barrido == "Logarítmico":
            cmds.append(f"GSWP {self.canal} LOG {c.bar_f1:.4f} {c.bar_f2:.4f} {c.bar_t:.4f}")
        else:
            cmds.append(f"GSWP {self.canal} NO")
        return cmds


class TabGenerador(QWidget):
    def __init__(self, ventana):
        super().__init__()
        self.v = ventana
        cfg = ventana.config.gen
        self._pendientes = set()
        self._ultimo_enviado = {1: None, 2: None}
        self._fases_enviadas = None

        raiz = QVBoxLayout(self)
        raiz.setContentsMargins(8, 8, 8, 8)

        arriba = QHBoxLayout()
        arriba.addWidget(W.boton("Sincronizar fases", self.sincronizar))
        arriba.addWidget(W.etiqueta_tenue(
            "Los dos canales comparten la misma base de tiempo: con la misma frecuencia, la fase "
            "relativa se mantiene exacta. Frecuencia de muestreo ≈ 1 MS/s (hasta ~100 kHz útiles)."))
        raiz.addLayout(arriba)

        cuerpo = QHBoxLayout()
        raiz.addLayout(cuerpo, 1)
        self.paneles = {}
        for c in (1, 2):
            sc = QScrollArea()
            sc.setWidgetResizable(True)
            sc.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            p = PanelGenerador(self, c, cfg.get(f"ch{c}", {}) or
                               ({"habilitado": True} if c == 1 else {"habilitado": False, "forma": "Cuadrada"}))
            sc.setWidget(p)
            cuerpo.addWidget(sc, 1)
            self.paneles[c] = p

        # vista previa de un período
        self.prev = pg.PlotWidget(background=W.FONDO)
        self.prev.setMenuEnabled(False)
        self.prev.setMouseEnabled(False, False)
        self.prev.showGrid(x=True, y=True, alpha=0.25)
        self.prev.setLabel("left", "V")
        self.prev.setLabel("bottom", "Un período (1 = período del CH1)")
        W.tam(self.prev, "setMinimumWidth", 360)
        self.curvas = {c: self.prev.plot(pen=pg.mkPen(COLORES[c], width=2)) for c in (1, 2)}
        cuerpo.addWidget(self.prev, 1)

        self.temporizador = QTimer(self)
        self.temporizador.setSingleShot(True)
        self.temporizador.timeout.connect(self._enviar)
        for p in self.paneles.values():
            p._cambio()

    def estado_config(self) -> dict:
        return {f"ch{c}": asdict(p.c) for c, p in self.paneles.items()}

    def actualizar_vista(self):
        if not hasattr(self, "curvas"):
            return
        p1 = self.paneles.get(1)
        f1 = p1.c.frecuencia if p1 and p1.c.forma != "Continua" else 1.0
        for c, p in self.paneles.items():
            if p.tabla is None:
                continue
            visible = p.c.habilitado
            self.curvas[c].setVisible(visible)
            if not visible:
                continue
            f = p.c.frecuencia if p.c.forma != "Continua" else f1
            ciclos = f / f1
            n = M.TABLA_N
            puntos = min(4000, max(400, int(n * ciclos)))
            x = np.linspace(0, 1, puntos, endpoint=False)
            fase = p.c.fase / 360
            idx = (((x * ciclos + fase) % 1.0) * n).astype(int) % n
            self.curvas[c].setData(x, p.tabla.volts[idx])

    def programar_envio(self, canal: int):
        self._pendientes.add(canal)
        self.temporizador.start(80)
        self.v.guardar_config_pronto()

    def reenviar_todo(self):
        self._ultimo_enviado = {1: None, 2: None}
        self._fases_enviadas = None
        self._pendientes = {1, 2}
        self._enviar()

    def _enviar(self):
        if not self.v.disp.esta_conectado:
            return
        for c in sorted(self._pendientes):
            p = self.paneles[c]
            cmds = p.comandos()
            ultimo = self._ultimo_enviado[c]
            tabla_igual = ultimo is not None and np.array_equal(ultimo[0], p.tabla.codigos)
            for cmd in cmds:
                if isinstance(cmd, tuple):
                    if not tabla_igual:
                        self.v.disp.enviar_tabla(c, cmd[1])
                elif ultimo is None or cmd not in ultimo[1]:
                    self.v.disp.enviar(cmd)
            self._ultimo_enviado[c] = (p.tabla.codigos.copy(), [x for x in cmds if isinstance(x, str)])
        self._pendientes.clear()
        fases = tuple(self.paneles[c].c.fase for c in (1, 2))
        if fases != self._fases_enviadas:
            self._fases_enviadas = fases
            self.v.disp.enviar("GSYNC")

    def sincronizar(self):
        if self.v.disp.esta_conectado:
            self.v.disp.enviar("GSYNC")
            self.v.estado("Fases sincronizadas.", W.OK)

    def al_linea(self, linea: str):
        p = linea.split()
        if linea.startswith("OK GSET") and len(p) >= 4:
            try:
                c, f = int(p[2]), float(p[3])
            except ValueError:
                return
            if c in self.paneles:
                self.paneles[c].frec_real = f
                pan = self.paneles[c]
                lo, hi = pan.tabla.lim
                txt = f"Rango de esta salida: {M.si(lo, 'V', 3)} a {M.si(hi, 'V', 3)}"
                if pan.tabla.recortada:
                    txt = f"<span style='color:{W.ALERTA}'>⚠ La señal se recorta.</span> " + txt
                if pan.c.forma != "Continua":
                    txt += f"<br>Frecuencia confirmada: {M.si(f, 'Hz', 8)}"
                pan.lbl_info.setText(txt)
        elif linea.startswith("ERR GTBL"):
            self.v.estado("Error al enviar la tabla; se reintenta.", W.ALERTA)
            self.reenviar_todo()
