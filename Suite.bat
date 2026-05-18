@echo off
title Suite de Optimizacion PC
cd /d "%~dp0"

REM Detectar Python real (no el stub de Microsoft Store)
set "PYOK=0"
for /f "tokens=2 delims= " %%i in ('python --version 2^>^&1') do (
    echo %%i | findstr /R "^[0-9]\.[0-9]" >nul && set "PYOK=1"
)

if "%PYOK%"=="0" (
    echo.
    echo ============================================================
    echo   PYTHON NO ESTA INSTALADO
    echo ============================================================
    echo.
    echo Esta suite necesita Python 3.9 o superior.
    echo.
    echo Opciones:
    echo   1^) Ejecuta  Install.bat  para instalarlo automaticamente
    echo      ^(usa winget, incluido en Windows 10/11^)
    echo.
    echo   2^) Instalar manualmente desde:
    echo      https://www.python.org/downloads/
    echo      ^(IMPORTANTE: marca "Add Python to PATH" en el instalador^)
    echo.
    echo ============================================================
    pause
    exit /b 1
)

REM Verificar dependencias
python -c "import psutil, customtkinter" >nul 2>nul
if errorlevel 1 (
    echo Instalando dependencias por primera vez...
    python -m pip install --upgrade pip
    python -m pip install -r requirements.txt
    if errorlevel 1 (
        echo.
        echo [ERROR] No se pudieron instalar las dependencias.
        echo Verifica conexion a internet o ejecuta como administrador.
        pause
        exit /b 1
    )
)

python Suite.py
