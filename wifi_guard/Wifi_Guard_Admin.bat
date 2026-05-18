@echo off
title Guardian Wi-Fi (Administrador)
NET SESSION >nul 2>&1
if %errorLevel% NEQ 0 (
    echo Solicitando permisos de administrador...
    powershell -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)
cd /d "%~dp0\.."

set "PYOK=0"
for /f "tokens=2 delims= " %%i in ('python --version 2^>^&1') do (
    echo %%i | findstr /R "^[0-9]\.[0-9]" >nul && set "PYOK=1"
)

if "%PYOK%"=="0" (
    echo Python no esta instalado. Ejecuta primero Install.bat en la raiz.
    pause
    exit /b 1
)

python -c "import psutil, customtkinter" >nul 2>nul
if errorlevel 1 (
    python -m pip install -r requirements.txt
)

python wifi_guard\wifi_guard.py
