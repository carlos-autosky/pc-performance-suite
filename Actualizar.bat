@echo off
title Actualizando PC Performance Suite...
cd /d "%~dp0"
echo.
echo  Descargando ultimas actualizaciones...
echo.
git pull
echo.
if %errorlevel%==0 (
    echo  Actualizado correctamente.
) else (
    echo  Error al actualizar. Verifica tu conexion a internet.
)
echo.
pause
