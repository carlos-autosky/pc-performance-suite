"""
Recoleccion ligera de info de sistema en vivo.
Usado por el lanzador para los KPIs del header.
"""

import platform
import subprocess
import time
import psutil


def os_label():
    rel = platform.release()
    ver = platform.version()
    try:
        build = int(ver.split(".")[-1]) if ver.count(".") >= 2 else 0
    except Exception:
        build = 0
    if rel == "11" or (rel == "10" and build >= 22000):
        return f"Windows 11 (build {build})"
    if rel == "10":
        return f"Windows 10 (build {build})"
    return f"{platform.system()} {rel}"


def fmt_bytes(n):
    n = float(n or 0)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PB"


def hardware_summary():
    """Datos estaticos del equipo (se llama una sola vez al iniciar)."""
    info = {}

    # Nombre del equipo
    info["hostname"] = platform.node()

    # Sistema operativo
    info["os"] = os_label()

    # Procesador
    cpu_name = platform.processor()
    try:
        out = subprocess.check_output(
            ["wmic", "cpu", "get", "Name"],
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            text=True, timeout=5,
        )
        lines = [l.strip() for l in out.strip().splitlines() if l.strip()]
        if len(lines) >= 2:
            cpu_name = lines[1]
    except Exception:
        pass
    cores = psutil.cpu_count(logical=False) or "?"
    threads = psutil.cpu_count(logical=True) or "?"
    info["cpu"] = f"{cpu_name}  ({cores}C / {threads}T)"

    # RAM total
    info["ram"] = fmt_bytes(psutil.virtual_memory().total)

    # Discos
    disks = []
    for p in psutil.disk_partitions(all=False):
        try:
            u = psutil.disk_usage(p.mountpoint)
            disks.append(f"{p.device} {fmt_bytes(u.total)}")
        except Exception:
            pass
    info["disks"] = disks if disks else ["N/D"]

    # GPU (via wmic)
    info["gpu"] = "N/D"
    try:
        out = subprocess.check_output(
            ["wmic", "path", "win32_VideoController", "get", "Name"],
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            text=True, timeout=5,
        )
        lines = [l.strip() for l in out.strip().splitlines() if l.strip()]
        if len(lines) >= 2:
            info["gpu"] = " / ".join(lines[1:])
    except Exception:
        pass

    return info


_CPU_PRIMED = False


def _prime_cpu():
    global _CPU_PRIMED
    if not _CPU_PRIMED:
        psutil.cpu_percent(interval=None)
        _CPU_PRIMED = True


def cpu_snapshot():
    _prime_cpu()
    pct = psutil.cpu_percent(interval=None)
    freq = psutil.cpu_freq()
    cores = psutil.cpu_count(logical=False) or 0
    threads = psutil.cpu_count(logical=True) or 0
    return {
        "percent": round(pct, 1),
        "freq_mhz": round(freq.current, 0) if freq else None,
        "cores": cores,
        "threads": threads,
    }


def ram_snapshot():
    vm = psutil.virtual_memory()
    return {
        "percent": round(vm.percent, 1),
        "used": vm.used,
        "total": vm.total,
        "available": vm.available,
        "used_text": fmt_bytes(vm.used),
        "total_text": fmt_bytes(vm.total),
    }


def disk_snapshot(path="C:\\"):
    try:
        d = psutil.disk_usage(path)
        return {
            "percent": round(d.percent, 1),
            "used": d.used,
            "total": d.total,
            "free": d.free,
            "used_text": fmt_bytes(d.used),
            "total_text": fmt_bytes(d.total),
            "free_text": fmt_bytes(d.free),
            "path": path,
        }
    except Exception:
        return {"percent": 0, "used": 0, "total": 0, "free": 0,
                "used_text": "N/D", "total_text": "N/D", "free_text": "N/D",
                "path": path}


def battery_snapshot():
    try:
        b = psutil.sensors_battery()
        if not b:
            return {"has_battery": False}
        return {
            "has_battery": True,
            "percent": round(float(b.percent), 1) if b.percent is not None else None,
            "plugged": bool(b.power_plugged),
        }
    except Exception:
        return {"has_battery": False}


def all_snapshots():
    return {
        "ts": time.time(),
        "cpu": cpu_snapshot(),
        "ram": ram_snapshot(),
        "disk": disk_snapshot(),
        "battery": battery_snapshot(),
    }
