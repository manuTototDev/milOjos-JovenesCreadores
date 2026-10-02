@echo off
REM ===============================================================
REM  MilOjos - lanzador del calibrador de brazos
REM  Doble click para calibrar, o desde consola:
REM     calibrar.bat --brazo 2
REM     calibrar.bat --solo-zonas
REM     calibrar.bat --simular
REM  Cualquier argumento se pasa tal cual a calibrar_brazos.py
REM ===============================================================

chcp 65001 >nul
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"

set "PY=%~dp0venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"

echo.
echo   Cierra el Monitor Serie del IDE de Arduino antes de seguir.
echo.

"%PY%" calibrar_brazos.py %*

echo.
pause
