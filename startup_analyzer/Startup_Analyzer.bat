@echo off
title Startup Analyzer - PC Performance Suite
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

python startup_analyzer\startup_analyzer.py
