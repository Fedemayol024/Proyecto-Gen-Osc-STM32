"""
Instrumento NUCLEO-F767ZI / NUCLEO-F429ZI - Osciloscopio + Generador + Bode + Herramientas
=========================================================================================
Al abrir se elige la placa (se puede recordar la elección y cambiarla después).
Ejecutar:   python main.py
Crear .exe: build_exe.bat
"""
from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (QApplication, QButtonGroup, QCheckBox, QComboBox, QDialog,
                               QHBoxLayout, QLabel, QMainWindow, QMessageBox, QPushButton,
                               QStatusBar, QTabWidget, QVBoxLayout, QWidget)

import modelo as M
import widgets as W
from dispositivo import Dispositivo, listar_puertos
from tab_bode import TabBode
from tab_calibracion import TabCalibracion
from tab_generador import TabGenerador
from tab_herramientas import TabHerramientas
from tab_osciloscopio import TabOsciloscopio
from tab_placa import TabPlaca

VERSION = "1.0"


def recurso(nombre: str) -> str:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).parent))
    return str(base / nombre)


class DialogoPlaca(QDialog):
    """Menú inicial: elegir con qué placa se va a trabajar."""

    def __init__(self, actual: str = M.PLACA_POR_DEFECTO, recordar: bool = False, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Elegí la placa")
        self.setMinimumWidth(520)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 20, 22, 18)
        lay.setSpacing(12)
        t = QLabel("¿Con qué placa vas a trabajar?")
        t.setStyleSheet(f"font-size: 15pt; font-weight: 700; color: {W.TEXTO};")
        lay.addWidget(t)
        lay.addWidget(W.etiqueta_tenue("Cada placa tiene su propio firmware y guarda su propia "
                                       "calibración. Podés cambiarla después desde la barra de arriba."))
        self.grupo = QButtonGroup(self)
        self.grupo.setExclusive(True)
        self.botones = {}
        for clave, info in M.PLACAS.items():
            b = QPushButton(f"{info['nombre']}\n{info['detalle']}")
            b.setCheckable(True)
            b.setMinimumHeight(64)
            b.setStyleSheet("QPushButton { text-align: left; padding: 10px 14px; font-size: 11pt; }")
            b.setChecked(clave == actual)
            b.clicked.connect(lambda _=False, c=clave: self._elegida(c))
            b.setProperty("clave", clave)
            self.grupo.addButton(b)
            self.botones[clave] = b
            lay.addWidget(b)
        self.recordar = QCheckBox("Recordar mi elección y no volver a preguntar")
        self.recordar.setChecked(recordar)
        lay.addWidget(self.recordar)
        fila = QHBoxLayout()
        fila.addStretch(1)
        fila.addWidget(W.boton("Cancelar", self.reject))
        self.btn_ok = W.boton("Continuar", self.accept, primario=True)
        fila.addWidget(self.btn_ok)
        lay.addLayout(fila)
        self._placa = actual if actual in M.PLACAS else M.PLACA_POR_DEFECTO
        self.botones[self._placa].setChecked(True)

    def _elegida(self, clave: str):
        self._placa = clave

    @property
    def placa(self) -> str:
        return self._placa


def elegir_placa(parent=None, forzar: bool = False) -> str | None:
    """Devuelve la placa elegida (y guarda la preferencia) o None si se canceló."""
    pref = M.cargar_preferencias()
    if not forzar and not pref["preguntar"]:
        return pref["placa"]
    dlg = DialogoPlaca(pref["placa"], recordar=not pref["preguntar"], parent=parent)
    if dlg.exec() != QDialog.Accepted:
        return None
    M.guardar_preferencias({"placa": dlg.placa, "preguntar": not dlg.recordar.isChecked()})
    return dlg.placa


class Ventana(QMainWindow):
    def __init__(self, placa: str = M.PLACA_POR_DEFECTO, auto_puerto: str | None = None):
        super().__init__()
        self.placa = placa if placa in M.PLACAS else M.PLACA_POR_DEFECTO
        nombre = M.nombre_placa(self.placa)
        self.setWindowTitle(f"Instrumento {nombre} · Osciloscopio y generador")
        self.resize(1360, 860)
        self.config = M.Config.cargar(self.placa)
        self.disp = Dispositivo()
        self.dueno_captura = None          # quién pidió la última captura
        self._esperado = None              # (n, pre) de la captura pedida
        self._mapa_puertos = {}

        central = QWidget()
        self.setCentralWidget(central)
        raiz = QVBoxLayout(central)
        raiz.setContentsMargins(8, 8, 8, 4)

        # barra de conexión
        barra = QHBoxLayout()
        titulo = QLabel("◉  Instrumento")
        titulo.setStyleSheet(f"font-size: 14pt; font-weight: 700; color: {W.TEXTO};")
        barra.addWidget(titulo)
        self.btn_placa = W.boton(f"{nombre}  ▾", self._menu_placa)
        self.btn_placa.setToolTip("Cambiar de placa")
        barra.addWidget(self.btn_placa)
        barra.addSpacing(16)
        self.combo_puertos = QComboBox()
        self.combo_puertos.setMinimumWidth(320)
        barra.addWidget(self.combo_puertos)
        barra.addWidget(W.boton("↻", self.actualizar_puertos))
        self.btn_con = W.boton("Conectar", self.alternar_conexion, primario=True)
        barra.addWidget(self.btn_con)
        self.lbl_con = QLabel("● Desconectado")
        self.lbl_con.setStyleSheet(f"color: {W.TENUE};")
        barra.addWidget(self.lbl_con)
        barra.addStretch(1)
        raiz.addLayout(barra)

        self._t_guardar = QTimer(self)
        self._t_guardar.setSingleShot(True)
        self._t_guardar.timeout.connect(self.guardar_config)

        self.tabs = QTabWidget()
        raiz.addWidget(self.tabs, 1)
        self.tab_gen = TabGenerador(self)
        self.tab_osc = TabOsciloscopio(self)
        self.tab_bode = TabBode(self)
        self.tab_herr = TabHerramientas(self)
        self.tab_cal = TabCalibracion(self)
        self.tab_placa = TabPlaca(self)
        self.tabs.addTab(self.tab_osc, "Osciloscopio")
        self.tabs.addTab(self.tab_gen, "Generador")
        self.tabs.addTab(self.tab_bode, "Bode")
        self.tabs.addTab(self.tab_herr, "Frecuencímetro y PWM")
        self.tabs.addTab(self.tab_cal, "Calibración")
        self.tabs.addTab(self.tab_placa, "Placa")

        self.setStatusBar(QStatusBar())
        self.estado(f"Versión {VERSION}. Conectá el USB USER (CN13) del Nucleo y tocá Conectar.")

        self.disp.conectado.connect(self._al_conectar)
        self.disp.desconectado.connect(lambda m: self._al_desconectar(m, W.ERROR))
        self.disp.error.connect(lambda m: self._al_desconectar(m, W.ERROR))
        self.disp.linea.connect(self._al_linea)
        self.disp.datos.connect(self._al_datos)

        self.actualizar_puertos()
        if auto_puerto:
            for et, dev in self._mapa_puertos.items():
                if dev == auto_puerto:
                    self.combo_puertos.setCurrentText(et)
                    QTimer.singleShot(400, self.alternar_conexion)
                    break

    # -------------------------------------------------------------- placa
    def _menu_placa(self):
        nueva = elegir_placa(self, forzar=True)
        if nueva and nueva != self.placa:
            self.cambiar_placa(nueva)

    def cambiar_placa(self, placa: str, puerto: str | None = None):
        """Reabre la ventana con la configuración y calibración de otra placa."""
        pref = M.cargar_preferencias()
        pref["placa"] = placa
        M.guardar_preferencias(pref)
        if self.disp.esta_conectado:
            self.disp.enviar("CAPX")
            self.disp.cerrar()
        nueva = Ventana(placa, auto_puerto=puerto)
        nueva.resize(self.size())
        nueva.move(self.pos())
        app = QApplication.instance()
        app._ventana = nueva
        nueva.show()
        self.close()

    # -------------------------------------------------------------- estado
    def estado(self, texto: str, color: str = W.TENUE):
        self.statusBar().setStyleSheet(f"color: {color};")
        self.statusBar().showMessage(texto)

    def guardar_config_pronto(self):
        self._t_guardar.start(1500)

    def guardar_config(self):
        if not hasattr(self, "tab_cal"):
            return
        self.config.gen = self.tab_gen.estado_config()
        self.config.osc = self.tab_osc.estado_config()
        h = self.tab_herr.estado_config()
        h["bode"] = self.tab_bode.estado_config()
        self.config.herramientas = h
        self.config.guardar()

    # -------------------------------------------------------------- conexión
    def actualizar_puertos(self):
        puertos = listar_puertos()
        self._mapa_puertos = {et: dev for dev, et in puertos}
        self.combo_puertos.clear()
        if not puertos:
            self.combo_puertos.addItem("No hay puertos")
            return
        self.combo_puertos.addItems([et for _, et in puertos])
        for dev, et in puertos:
            if dev == self.config.puerto:
                self.combo_puertos.setCurrentText(et)
                break

    def alternar_conexion(self):
        if self.disp.esta_conectado:
            self.disp.cerrar()
            self._al_desconectar("Desconectado.", W.TENUE)
            return
        puerto = self._mapa_puertos.get(self.combo_puertos.currentText())
        if not puerto:
            self.estado("Elegí un puerto (conectá el USB USER del Nucleo y tocá ↻).", W.ALERTA)
            return
        self.btn_con.setEnabled(False)
        self.btn_con.setText("Conectando…")
        self.lbl_con.setText(f"● Buscando el instrumento en {puerto}…")
        self.lbl_con.setStyleSheet(f"color: {W.ALERTA};")
        self.disp.abrir(puerto)

    def _al_conectar(self, version: str):
        detectada = self.disp.placa
        if detectada and detectada != self.placa:
            puerto = self.disp.puerto
            self.disp.cerrar()
            self._al_desconectar(f"La placa conectada es {M.nombre_placa(detectada)}, no "
                                 f"{M.nombre_placa(self.placa)}.", W.ALERTA)
            if detectada in M.PLACAS:
                r = QMessageBox.question(
                    self, "Otra placa",
                    f"La placa conectada es una {M.nombre_placa(detectada)}, pero la app está "
                    f"configurada para {M.nombre_placa(self.placa)}.\n\n"
                    f"¿Cambiar a {M.nombre_placa(detectada)} y conectar?")
                if r == QMessageBox.Yes:
                    self.cambiar_placa(detectada, puerto)
            return
        self.config.puerto = self.disp.puerto
        self.btn_con.setEnabled(True)
        self.btn_con.setText("Desconectar")
        info = self.disp.info
        self.lbl_con.setText(f"● Conectado · {self.disp.puerto} · {M.nombre_placa(self.placa)} · v{version} · "
                             f"generador {M.si(info.get('gen_fs', 0), 'S/s', 3)} · "
                             f"osciloscopio hasta {M.si(info.get('osc_fsmax', 0), 'S/s', 3)}")
        self.lbl_con.setStyleSheet(f"color: {W.OK};")
        self.estado("Instrumento conectado.", W.OK)
        self.tab_gen.reenviar_todo()
        self.tab_osc.al_conectar()
        self.tab_placa.al_conectar()
        self.guardar_config_pronto()

    def _al_desconectar(self, motivo: str, color: str):
        self.btn_con.setEnabled(True)
        self.btn_con.setText("Conectar")
        self.lbl_con.setText("● Desconectado")
        self.lbl_con.setStyleSheet(f"color: {W.TENUE};")
        self.tab_osc.al_desconectar()
        self.tab_herr.al_desconectar()
        self.tab_placa.al_desconectar()
        if self.tab_bode.activo:
            self.tab_bode.activo = False
            self.tab_bode.btn.setText("Iniciar barrido")
        self.estado(motivo, color)

    def _al_linea(self, linea: str):
        if linea.startswith("ERR") and not linea.startswith("ERR GTBL"):
            self.estado(f"La placa respondió: {linea}", W.ERROR)
        self.tab_gen.al_linea(linea)
        self.tab_herr.al_linea(linea)

    def pedir_captura(self, dueno: str, n: int, pre: int, fs: float, fuente: int = 0,
                      nivel: int = 2048, flanco: int = 0, hist: int = 20):
        """Pide una captura y recuerda quién la pidió (los datos que no
        coinciden con el último pedido se descartan)."""
        self.dueno_captura = dueno
        self._esperado = (int(n), int(pre))
        self.disp.enviar(f"CAP {int(n)} {int(pre)} {fs:.4f} {fuente} {nivel} {flanco} {hist}")

    def cancelar_captura(self):
        self._esperado = None
        if self.disp.esta_conectado:
            self.disp.enviar("CAPX")

    def _al_datos(self, d: dict):
        if self._esperado is None or (d["n"], d["pre"]) != self._esperado:
            return
        self._esperado = None
        dueno = self.dueno_captura
        if dueno == "bode":
            self.tab_bode.al_recibir(d)
        elif dueno == "cal":
            self.tab_cal.al_recibir(d)
        else:
            self.tab_osc.al_recibir(d)

    def closeEvent(self, e):
        self.guardar_config()
        if self.disp.esta_conectado:
            self.disp.enviar("CAPX")
        self.disp.cerrar()
        super().closeEvent(e)


def main():
    app = QApplication(sys.argv)
    app.setStyleSheet(W.ESTILO)
    ico = recurso("icono.ico")
    if Path(ico).exists():
        app.setWindowIcon(QIcon(ico))
    placa = elegir_placa()
    if placa is None:
        return
    app._ventana = Ventana(placa)
    app._ventana.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
