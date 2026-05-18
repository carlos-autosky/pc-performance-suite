============================================================
 Suite de Optimizacion PC v0.3.0
 Optimiza, limpia y revierte cualquier cambio con un clic.
 Compatible con Windows 10 y 11. Standalone.
 Copyright (c) KrlosEdu / 2026
============================================================

============================================================
 INSTALACION (PC NUEVO) - SOPORTE ONLINE Y OFFLINE
============================================================

Doble clic en  Install.bat

El instalador es DUAL:

  - SI HAY INTERNET   -> instala las ultimas versiones online
                         (winget para Python + pip para deps)

  - SI NO HAY INTERNET -> usa el pack offline incluido en
                          installers/ (Python 3.12.7 + wheels)

  - Si Python ya esta instalado, salta a las dependencias

============================================================
 PREPARAR PACK OFFLINE (en PC con internet)
============================================================

Si quieres llevar la suite a un PC sin internet:

  1) En un PC con internet, ejecuta:
     installers\Download_Offline_Pack.bat

     Esto descarga (~26 MB total):
     - python-3.12.X-amd64.exe       (instalador de Python)
     - wheels\psutil-*.whl
     - wheels\customtkinter-*.whl
     - wheels\darkdetect-*.whl
     - wheels\packaging-*.whl

  2) Copia toda la carpeta del proyecto al PC offline
     (incluye installers/ con su contenido)

  3) En el PC offline: doble clic en Install.bat
     Detecta automaticamente que no hay internet y usa el pack.

============================================================
 INSTALACION MANUAL (si winget no funciona y no hay pack)
============================================================

1) Descarga Python 3.9+ desde:
   https://www.python.org/downloads/

2) IMPORTANTE: durante la instalacion, MARCA la casilla
   "Add Python to PATH"

3) Ejecuta Suite.bat - instala automaticamente las dependencias
   la primera vez

============================================================
 DEPENDENCIAS
============================================================

- Python 3.9 o superior
- psutil (>=5.9.0)
- customtkinter (>=5.2.0)

Las dos ultimas se instalan automaticamente al ejecutar
Suite.bat por primera vez.

============================================================
 USO
============================================================

- Doble clic en  Suite.bat  para abrir el lanzador
- O en el acceso directo del escritorio (si ya lo creaste)

Desde el lanzador puedes abrir cualquiera de las 8 herramientas:

1) Monitor de Bateria PRO
2) Limpiador de Disco y Temporales (con explorador multi-disco)
3) Detector de Conflictos
4) Analizador de Inicio
5) Centro de Seguridad
6) Desinstalador Profundo
7) Monitor de CPU y Temperatura
8) Optimizador de Memoria

============================================================
 DATOS DEL USUARIO (no se borran al actualizar)
============================================================

La configuracion del usuario (tema, API keys, historial de
rollback, archivos en cuarentena) viven en:

  %APPDATA%\PC Performance Suite\

Esta carpeta sobrevive a actualizaciones de la app.

============================================================
 ROLLBACK / REVERSION
============================================================

Cada cambio que afecta el sistema se registra y puede
revertirse desde el lanzador, boton "Historial / Revertir".

Los archivos eliminados van a una "cuarentena" reversible
(no se borran inmediatamente). Solo el "Borrado Permanente"
en el explorador NO se puede revertir.

============================================================
 ALGUNAS HERRAMIENTAS REQUIEREN ADMINISTRADOR
============================================================

Para aplicar cambios de registro de Windows o servicios
del sistema (Battery Monitor optimizaciones, Cleaner Temp
de Windows), ejecuta como administrador:

  battery_monitor/Battery_Monitor_Admin.bat

O clic derecho en Suite.bat > Ejecutar como administrador.

============================================================
