@echo off
REM ==========================================================
REM  Crea Instrumento.exe (un solo archivo, sin consola)
REM  Requisito: Python 3.10 o superior (python.org) con la
REM  opcion "Add python.exe to PATH" tildada.
REM ==========================================================
cd /d "%~dp0"
echo Instalando dependencias...
python -m pip install --upgrade pip
python -m pip install -r requirements.txt pyinstaller
if errorlevel 1 goto error

echo Generando el ejecutable (tarda un par de minutos)...
python -m PyInstaller --noconfirm --clean --onefile --windowed ^
  --name Instrumento ^
  --icon icono.ico ^
  --add-data "icono.ico;." ^
  main.py
if errorlevel 1 goto error

echo.
echo Listo: dist\Instrumento.exe
pause
exit /b 0

:error
echo.
echo Hubo un error. Revisa los mensajes de arriba.
pause
exit /b 1
