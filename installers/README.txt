============================================================
 Pack offline de instalacion
============================================================

Este directorio contiene los instaladores para PCs SIN INTERNET.

PARA PREPARAR EL PACK (en un PC con internet):
  1) Doble clic en  Download_Offline_Pack.bat
     - Descarga el instalador de Python 3.12 a esta carpeta
     - Descarga las wheels de psutil + customtkinter a wheels/
  2) Copia toda la carpeta del proyecto al PC offline
     (incluyendo este directorio installers/)

PARA INSTALAR EN PC OFFLINE:
  1) Doble clic en  Install.bat  (en la raiz del proyecto)
     El instalador detecta automaticamente:
     - SI HAY internet  -> instala las ultimas versiones online
     - SI NO HAY        -> instala desde estos archivos locales

CONTENIDO ESPERADO:
  installers\python-3.12.X-amd64.exe   (~28 MB, Python instalador)
  installers\wheels\*.whl              (psutil, customtkinter, darkdetect, packaging)

NOTAS:
  - Si esta carpeta esta vacia y no hay internet, Install.bat
    mostrara un error claro indicando que necesita el pack.
  - Las wheels deben coincidir con la version de Python.
    Download_Offline_Pack.bat descarga las correctas para Python 3.12.

============================================================
