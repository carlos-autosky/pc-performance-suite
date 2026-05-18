"""
Persistencia ligera de preferencias (tema, API keys, etc.).

Los datos del usuario viven en %APPDATA%\\PC Performance Suite\\
para que las actualizaciones de la app NO los borren.
"""

import os
import json
import shutil
from pathlib import Path

APP_NAME = "PC Performance Suite"
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# --- Directorio de datos del usuario (sobrevive a actualizaciones) ---

def _appdata_dir():
    """%APPDATA%\\PC Performance Suite\\ — creado si no existe."""
    base = os.environ.get("APPDATA")
    if not base:
        base = str(Path.home() / "AppData" / "Roaming")
    p = Path(base) / APP_NAME
    p.mkdir(parents=True, exist_ok=True)
    return p


USER_DATA_DIR = _appdata_dir()
CONFIG_PATH = USER_DATA_DIR / "config.json"

# --- Migracion automatica del legacy (config en raiz del proyecto) ---

_LEGACY_CONFIG = PROJECT_ROOT / "config.json"
if _LEGACY_CONFIG.exists() and not CONFIG_PATH.exists():
    try:
        shutil.copy2(_LEGACY_CONFIG, CONFIG_PATH)
        # Renombramos el legacy a .bak para no volver a migrar
        try:
            _LEGACY_CONFIG.rename(_LEGACY_CONFIG.with_suffix(".json.bak"))
        except Exception:
            pass
    except Exception:
        pass


DEFAULTS = {
    "theme": "dark",
    "vt_api_key": "",
    "mb_auth_key": "",
}


def load():
    if not CONFIG_PATH.exists():
        return dict(DEFAULTS)
    try:
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        out = dict(DEFAULTS)
        out.update(data)
        return out
    except Exception:
        return dict(DEFAULTS)


def save(cfg):
    try:
        CONFIG_PATH.write_text(
            json.dumps(cfg, indent=2, ensure_ascii=False),
            encoding="utf-8"
        )
    except Exception:
        pass


def get(key, default=None):
    return load().get(key, default if default is not None else DEFAULTS.get(key))


def set_value(key, value):
    cfg = load()
    cfg[key] = value
    save(cfg)


def user_data_dir():
    """Devuelve el path raiz de datos del usuario (otros modulos lo usan)."""
    return USER_DATA_DIR
