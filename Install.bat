@echo off
title Instalador - Suite de Optimizacion PC
cd /d "%~dp0"

echo ============================================================
echo   INSTALADOR - Suite de Optimizacion PC v0.3.0
echo ============================================================
echo.

REM ----- 1) Detectar si hay internet -----
set "HAS_NET=0"
ping -n 1 -w 2000 8.8.8.8 >nul 2>nul
if not errorlevel 1 set "HAS_NET=1"

if "%HAS_NET%"=="1" (
    echo [OK] Conexion a internet detectada.
) else (
    echo [...] Sin conexion a internet detectada. Se usara pack offline.
)

REM ----- 2) Detectar si Python ya esta instalado -----
set "PYOK=0"
for /f "tokens=2 delims= " %%i in ('python --version 2^>^&1') do (
    echo %%i | findstr /R "^[0-9]\.[0-9]" >nul && set "PYOK=1"
)

if "%PYOK%"=="1" (
    echo [OK] Python ya esta instalado:
    python --version
    goto INSTALL_DEPS
)

REM ----- 3) Python no esta. Decidir online vs offline -----
echo.
echo Python NO esta instalado en este PC.
echo.

if "%HAS_NET%"=="1" (
    goto INSTALL_PYTHON_ONLINE
) else (
    goto INSTALL_PYTHON_OFFLINE
)

:INSTALL_PYTHON_ONLINE
echo ----- Instalando Python 3.12 con winget (online) -----
echo.
where winget >nul 2>nul
if errorlevel 1 (
    echo [WARN] winget no esta disponible. Buscando pack offline como fallback...
    goto INSTALL_PYTHON_OFFLINE
)
winget install Python.Python.3.12 --accept-source-agreements --accept-package-agreements
if errorlevel 1 (
    echo [WARN] winget fallo. Intentando con pack offline...
    goto INSTALL_PYTHON_OFFLINE
)
goto PYTHON_DONE

:INSTALL_PYTHON_OFFLINE
echo ----- Instalando Python desde pack offline -----
echo.
REM Buscar el primer python-*.exe en installers\
set "PY_INSTALLER="
for %%f in ("installers\python-*.exe") do (
    if not defined PY_INSTALLER set "PY_INSTALLER=%%f"
)
if not defined PY_INSTALLER (
    echo.
    echo ============================================================
    echo  [ERROR] NO HAY INTERNET NI PACK OFFLINE
    echo ============================================================
    echo.
    echo No se encontro el instalador de Python en:
    echo   installers\python-*.exe
    echo.
    echo Opciones:
    echo  1^) Conecta este PC a internet y vuelve a ejecutar Install.bat
    echo  2^) Prepara el pack offline en otro PC con internet:
    echo     - Ejecuta  installers\Download_Offline_Pack.bat
    echo     - Copia toda la carpeta del proyecto a este PC
    echo  3^) Instala Python manualmente desde:
    echo     https://www.python.org/downloads/
    echo     ^(IMPORTANTE: marca "Add Python to PATH"^)
    echo.
    pause
    exit /b 1
)

echo Ejecutando: %PY_INSTALLER% /quiet InstallAllUsers=0 PrependPath=1 Include_test=0
echo Esto puede tardar 1-2 minutos...
echo.
"%PY_INSTALLER%" /quiet InstallAllUsers=0 PrependPath=1 Include_test=0
if errorlevel 1 (
    echo.
    echo [ERROR] La instalacion silenciosa de Python fallo.
    echo Intenta ejecutar directamente: %PY_INSTALLER%
    echo y marca "Add Python to PATH" en la primera pantalla.
    pause
    exit /b 1
)

:PYTHON_DONE
echo.
echo [OK] Python instalado.
echo.
echo IMPORTANTE: como Python recien se acaba de instalar,
echo este script va a continuar con la instalacion de dependencias.
echo Si falla, cierra esta ventana, abre una NUEVA ventana del
echo Explorador y vuelve a ejecutar Install.bat
echo.

REM Re-detectar Python
set "PYOK=0"
for /f "tokens=2 delims= " %%i in ('python --version 2^>^&1') do (
    echo %%i | findstr /R "^[0-9]\.[0-9]" >nul && set "PYOK=1"
)
if "%PYOK%"=="0" (
    echo [WARN] Python no aparece en el PATH de esta sesion.
    echo Cierra esta ventana, abre una NUEVA ventana del Explorador,
    echo y vuelve a ejecutar Install.bat para instalar las dependencias.
    pause
    exit /b 0
)

:INSTALL_DEPS
echo.
echo ----- Instalando dependencias de Python -----
echo.

REM Si hay internet, instalar online (mas actualizado)
REM Si no, instalar desde wheels locales
if "%HAS_NET%"=="1" (
    echo Modo: ONLINE
    python -m pip install --upgrade pip
    python -m pip install -r requirements.txt
    set "DEPS_RC=%errorlevel%"
) else (
    if exist "installers\wheels\*.whl" (
        echo Modo: OFFLINE ^(desde installers\wheels\^)
        python -m pip install --no-index --find-links installers\wheels -r requirements.txt
        set "DEPS_RC=%errorlevel%"
    ) else (
        echo [ERROR] Sin internet y sin wheels en installers\wheels\
        echo Prepara el pack offline en un PC con internet.
        pause
        exit /b 1
    )
)

if not "%DEPS_RC%"=="0" (
    echo.
    echo [ERROR] No se pudieron instalar las dependencias.
    pause
    exit /b 1
)

echo.
echo ============================================================
echo   INSTALACION COMPLETA
echo ============================================================
echo.
echo Ya puedes ejecutar la suite con:
echo   - Doble clic en  Suite.bat
echo   - O el acceso directo en el escritorio
echo.
pause
exit /b 0
