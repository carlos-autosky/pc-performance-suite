@echo off
title Battery Monitor PRO v3 (Administrador)
NET SESSION >nul 2>&1
if %errorLevel% NEQ 0 (
    echo Solicitando permisos de administrador...
    powershell -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)
cd /d "%~dp0\.."
where python >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Python no encontrado en PATH.
    pause
    exit /b 1
)
python -c "import psutil" >nul 2>nul
if errorlevel 1 (
    python -m pip install psutil
)
python battery_monitor\battery_monitor_v3.py
