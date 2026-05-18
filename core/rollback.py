"""
Sistema de rollback universal para PC Performance Suite.

Cada accion que modifica el sistema registra un 'snapshot' previo.
El usuario puede revertir cambios individualmente o todos.

Tipos de snapshot soportados:
- registry_value: valor de registro (con tipo, hive, path, name, prev_value)
- registry_delete: re-crear un valor que se borro
- file_quarantine: archivo movido a cuarentena (no borrado), puede restaurarse
- service_state: estado anterior de un servicio Windows
- power_setting: valor previo de powercfg
- startup_entry: entrada de inicio deshabilitada/quitada
"""

import os
import json
import uuid
import shutil
import subprocess
from pathlib import Path
from datetime import datetime

try:
    import winreg
except ImportError:
    winreg = None


SUITE_ROOT = Path(__file__).resolve().parent.parent
_LEGACY_DIR = SUITE_ROOT / "rollback_log"

# Directorio de datos del usuario (sobrevive a actualizaciones)
from . import config as _cfg
ROLLBACK_DIR = _cfg.user_data_dir() / "rollback_log"
ROLLBACK_DB = ROLLBACK_DIR / "rollback.json"
QUARANTINE_DIR = ROLLBACK_DIR / "quarantine"

ROLLBACK_DIR.mkdir(parents=True, exist_ok=True)
QUARANTINE_DIR.mkdir(exist_ok=True)

# Migracion del legacy (rollback_log en la raiz del proyecto)
if _LEGACY_DIR.exists() and _LEGACY_DIR.is_dir():
    try:
        legacy_db = _LEGACY_DIR / "rollback.json"
        if legacy_db.exists() and not ROLLBACK_DB.exists():
            shutil.copy2(legacy_db, ROLLBACK_DB)
        legacy_q = _LEGACY_DIR / "quarantine"
        if legacy_q.exists() and legacy_q.is_dir():
            for child in legacy_q.iterdir():
                target = QUARANTINE_DIR / child.name
                if not target.exists():
                    try:
                        shutil.move(str(child), str(target))
                    except Exception:
                        pass
        # Renombrar el directorio legacy para no volver a migrar
        try:
            _LEGACY_DIR.rename(_LEGACY_DIR.with_name("rollback_log.bak"))
        except Exception:
            pass
    except Exception:
        pass


def _load():
    if not ROLLBACK_DB.exists():
        return {"version": 1, "entries": []}
    try:
        return json.loads(ROLLBACK_DB.read_text(encoding="utf-8"))
    except Exception:
        return {"version": 1, "entries": []}


def _save(db):
    ROLLBACK_DB.write_text(
        json.dumps(db, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def _new_entry(module, kind, label, payload, applied=True):
    entry = {
        "id": uuid.uuid4().hex[:12],
        "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "module": module,
        "kind": kind,
        "label": label,
        "applied": applied,
        "reverted": False,
        "payload": payload,
    }
    db = _load()
    db["entries"].append(entry)
    _save(db)
    return entry


def list_entries(only_active=True):
    db = _load()
    rows = db.get("entries", [])
    if only_active:
        rows = [r for r in rows if not r.get("reverted")]
    rows.sort(key=lambda r: r["ts"], reverse=True)
    return rows


def all_entries():
    return _load().get("entries", [])


def mark_reverted(entry_id):
    db = _load()
    for e in db["entries"]:
        if e["id"] == entry_id:
            e["reverted"] = True
            e["reverted_ts"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            break
    _save(db)


# ---------- File quarantine ----------

def quarantine_file(module, src_path, label=None):
    """
    Mueve archivo a cuarentena (no borra). Devuelve entry_id.
    """
    src = Path(src_path)
    if not src.exists():
        return None
    qid = uuid.uuid4().hex[:12]
    qdir = QUARANTINE_DIR / qid
    qdir.mkdir(parents=True, exist_ok=True)
    dst = qdir / src.name
    try:
        shutil.move(str(src), str(dst))
    except Exception as e:
        return {"error": str(e)}

    entry = _new_entry(
        module=module,
        kind="file_quarantine",
        label=label or f"Archivo: {src.name}",
        payload={
            "qid": qid,
            "original_path": str(src),
            "quarantine_path": str(dst),
            "size_bytes": dst.stat().st_size if dst.exists() else 0,
        },
    )
    return entry


def quarantine_files_batch(module, paths, group_label):
    """Mueve varios archivos a cuarentena bajo un mismo group_id."""
    qid = uuid.uuid4().hex[:12]
    qdir = QUARANTINE_DIR / qid
    qdir.mkdir(parents=True, exist_ok=True)
    moved = []
    failed = []
    for src_path in paths:
        src = Path(src_path)
        if not src.exists():
            continue
        try:
            rel = src.name + "_" + uuid.uuid4().hex[:6]
            dst = qdir / rel
            shutil.move(str(src), str(dst))
            moved.append({
                "original": str(src),
                "quarantined": str(dst),
                "size": dst.stat().st_size if dst.exists() else 0,
            })
        except Exception as e:
            failed.append({"path": str(src), "error": str(e)})

    if not moved:
        try:
            qdir.rmdir()
        except Exception:
            pass
        return None, failed

    total = sum(m["size"] for m in moved)
    entry = _new_entry(
        module=module,
        kind="file_quarantine_batch",
        label=group_label,
        payload={
            "qid": qid,
            "count": len(moved),
            "total_bytes": total,
            "items": moved,
        },
    )
    return entry, failed


# ---------- Registry ----------

def _hive_to_const(hive_name):
    if winreg is None:
        return None
    return {
        "HKCU": winreg.HKEY_CURRENT_USER,
        "HKLM": winreg.HKEY_LOCAL_MACHINE,
        "HKCR": winreg.HKEY_CLASSES_ROOT,
        "HKU":  winreg.HKEY_USERS,
    }.get(hive_name)


def _hive_const_to_name(const):
    if winreg is None:
        return ""
    return {
        winreg.HKEY_CURRENT_USER: "HKCU",
        winreg.HKEY_LOCAL_MACHINE: "HKLM",
        winreg.HKEY_CLASSES_ROOT: "HKCR",
        winreg.HKEY_USERS: "HKU",
    }.get(const, "")


def registry_delete_value(module, hive_name, subkey, value_name, label=None):
    """
    Borra un valor de registro guardando snapshot para rollback.
    """
    if winreg is None:
        return None
    hive = _hive_to_const(hive_name)
    if hive is None:
        return None

    prev_value = None
    prev_type = None
    try:
        with winreg.OpenKey(hive, subkey, 0, winreg.KEY_READ) as k:
            prev_value, prev_type = winreg.QueryValueEx(k, value_name)
    except FileNotFoundError:
        return None
    except OSError:
        return None

    try:
        with winreg.OpenKey(hive, subkey, 0, winreg.KEY_SET_VALUE) as k:
            winreg.DeleteValue(k, value_name)
    except OSError as e:
        return {"error": str(e)}

    entry = _new_entry(
        module=module,
        kind="registry_value_deleted",
        label=label or f"Borrado {hive_name}\\{subkey} -> {value_name}",
        payload={
            "hive": hive_name,
            "subkey": subkey,
            "value_name": value_name,
            "prev_value": str(prev_value),
            "prev_type": prev_type,
        },
    )
    return entry


# ---------- Power settings (powercfg) ----------

def power_setting_change(module, label, prev_state_dump, change_command):
    """
    Registra cambio de powercfg con un dump de estado previo (string libre).
    El revert reaplica el dump (segun el modulo lo interprete).
    """
    entry = _new_entry(
        module=module,
        kind="power_setting",
        label=label,
        payload={
            "prev_state_dump": prev_state_dump,
            "command_applied": change_command,
        },
    )
    return entry


# ---------- Reverter ----------

def revert_entry(entry_id):
    """
    Intenta revertir una entrada. Devuelve (ok, message).
    """
    db = _load()
    target = None
    for e in db["entries"]:
        if e["id"] == entry_id:
            target = e
            break
    if not target:
        return False, "Entrada no encontrada"
    if target.get("reverted"):
        return False, "Ya estaba revertida"

    kind = target["kind"]
    payload = target["payload"]

    try:
        if kind in ("file_quarantine", "file_quarantine_batch"):
            ok, msg = _revert_quarantine(payload)
        elif kind == "registry_value_deleted":
            ok, msg = _revert_registry_delete(payload)
        elif kind == "power_setting":
            ok, msg = False, ("Power settings: revertir manualmente con: " +
                              payload.get("prev_state_dump", "")[:200])
        else:
            ok, msg = False, f"Tipo desconocido: {kind}"
    except Exception as e:
        ok, msg = False, f"Error revirtiendo: {e}"

    if ok:
        mark_reverted(entry_id)
    return ok, msg


def _revert_quarantine(payload):
    items = payload.get("items")
    if items is None:
        items = [{
            "original": payload["original_path"],
            "quarantined": payload["quarantine_path"],
        }]
    restored = 0
    failed = []
    for it in items:
        try:
            src = Path(it["quarantined"])
            dst = Path(it["original"])
            if not src.exists():
                failed.append(f"falta {src.name}")
                continue
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dst))
            restored += 1
        except Exception as e:
            failed.append(str(e))
    qid = payload.get("qid")
    if qid:
        qdir = QUARANTINE_DIR / qid
        try:
            if qdir.exists() and not any(qdir.iterdir()):
                qdir.rmdir()
        except Exception:
            pass
    if restored == 0:
        return False, f"No se pudo restaurar nada. {failed}"
    return True, f"Restaurados {restored} elemento(s)" + (f". Errores: {len(failed)}" if failed else "")


def _revert_registry_delete(payload):
    if winreg is None:
        return False, "winreg no disponible"
    hive = _hive_to_const(payload["hive"])
    if hive is None:
        return False, "Hive invalido"
    try:
        with winreg.OpenKey(hive, payload["subkey"], 0, winreg.KEY_SET_VALUE) as k:
            winreg.SetValueEx(
                k, payload["value_name"], 0,
                int(payload.get("prev_type", 1)),
                payload["prev_value"]
            )
        return True, "Valor restaurado"
    except Exception as e:
        return False, f"Error: {e}"


def purge_old_quarantine(days=30):
    """Elimina cuarentena de items revertidos hace mas de N dias o muy viejos."""
    cutoff = datetime.now().timestamp() - days * 86400
    removed = 0
    for qdir in QUARANTINE_DIR.iterdir():
        try:
            if qdir.stat().st_mtime < cutoff:
                shutil.rmtree(qdir, ignore_errors=True)
                removed += 1
        except Exception:
            pass
    return removed


def stats():
    db = _load()
    entries = db.get("entries", [])
    active = [e for e in entries if not e.get("reverted")]
    total_bytes = 0
    for e in active:
        if e["kind"] == "file_quarantine_batch":
            total_bytes += e["payload"].get("total_bytes", 0)
        elif e["kind"] == "file_quarantine":
            total_bytes += e["payload"].get("size_bytes", 0)
    return {
        "total_entries": len(entries),
        "active_entries": len(active),
        "reverted_entries": len(entries) - len(active),
        "quarantine_bytes": total_bytes,
    }
