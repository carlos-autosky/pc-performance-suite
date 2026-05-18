@echo off
title Preparar pack offline - Suite de Optimizacion PC
cd /d "%~dp0"

echo ============================================================
echo  PREPARAR PACK OFFLINE
echo ============================================================
echo.
echo Este script descarga el instalador de Python y las wheels
echo de las dependencias para que la suite pueda instalarse en
echo PCs sin internet.
echo.
echo Necesita conexion a internet en ESTE PC.
echo.
pause

REM Detectar Python (necesario para hacer pip download)
set "PYOK=0"
for /f "tokens=2 delims= " %%i in ('python --version 2^>^&1') do (
    echo %%i | findstr /R "^[0-9]\.[0-9]" >nul && set "PYOK=1"
)
if "%PYOK%"=="0" (
    echo [ERROR] Necesitas Python instalado en ESTE PC para preparar el pack.
    echo Instala Python desde https://www.python.org/downloads/ y vuelve a ejecutar.
    pause
    exit /b 1
)

echo.
echo ----- Descargando instalador de Python 3.12 -----
echo.

REM Version objetivo: Python 3.12.7 (la mas reciente estable de la serie 3.12)
set "PY_VERSION=3.12.7"
set "PY_FILE=python-%PY_VERSION%-amd64.exe"
set "PY_URL=https://www.python.org/ftp/python/%PY_VERSION%/%PY_FILE%"

if exist "%PY_FILE%" (
    echo [OK] Ya existe %PY_FILE% en esta carpeta. Omitiendo descarga.
) else (
    echo Descargando %PY_URL%
    curl -L -o "%PY_FILE%" "%PY_URL%"
    if errorlevel 1 (
        echo [ERROR] La descarga del instalador de Python fallo.
        echo Verifica conexion a internet.
        pause
        exit /b 1
    )
    echo [OK] Instalador de Python descargado.
)

echo.
echo ----- Descargando wheels de dependencias -----
echo.

REM pip download descarga las wheels SIN instalar.
REM --platform win_amd64 fuerza versiones para Windows 64-bit
REM --python-version 3.12 fuerza wheels compatibles con Python 3.12
REM --only-binary=:all: evita descargar source distributions
python -m pip download --dest wheels --platform win_amd64 --python-version 3.12 --only-binary=:all: psutil customtkinter darkdetect packaging
if errorlevel 1 (
    echo.
    echo [ATENCION] Algunas wheels no se pudieron descargar con --platform forzado.
    echo Reintentando sin restricciones...
    python -m pip download --dest wheels psutil customtkinter darkdetect packaging
)

echo.
echo ============================================================
echo  PACK OFFLINE LISTO
echo ============================================================
echo.
echo Contenido descargado en:
echo   %CD%
echo.
dir /b "%PY_FILE%" 2>nul
dir /b wheels\*.whl 2>nul
echo.
echo Para usarlo en otro PC:
echo  1) Copia toda la carpeta del proyecto (incluyendo installers/) al PC offline
echo  2) En el PC offline, doble clic en Install.bat
echo     - Si NO detecta internet, usa estos archivos locales
echo.
pause
