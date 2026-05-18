"""
Battery Monitor PRO v3 - PC Performance Suite
Standalone - compatible con Windows 10 y 11 (todas las versiones).
Sin integracion a redes externas. Todo se almacena local.
"""

import re
import sys
import time
import json
import csv
import ctypes
import platform
import threading
import subprocess
import tkinter as tk
from pathlib import Path
from datetime import datetime
from tkinter import Tk, StringVar, BooleanVar, IntVar, messagebox, filedialog
from tkinter import ttk

# Acceso a core/ del padre
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core import style as _style_mod
_style_mod.apply_saved_theme()
from core.style import COLORS, FONTS, configure_ttk, color_for_value, COPYRIGHT
from core.ui_kit import KpiCard, SectionCard, StatusPill, ScrollableFrame
from core.ctk_kit import init_ctk, Btn, Check
from core.scale import setup_scaling, s
from core.progress import ProgressOverlay
init_ctk()

try:
    import psutil
except ImportError:
    print("ERROR: falta el paquete 'psutil'. Instala con: pip install -r requirements.txt")
    sys.exit(1)

try:
    import winreg
except ImportError:
    winreg = None


APP_TITLE = "Monitor de Bateria PRO v3"
APP_VERSION = "3.1.2"
SUITE_NAME = "Suite de Optimizacion PC"

BASE_DIR = Path(__file__).resolve().parent

# Datos del usuario en %APPDATA% (sobreviven a actualizaciones)
from core import config as _cfg
REPORT_DIR = _cfg.user_data_dir() / "reportes_bateria"
HISTORY_CSV = REPORT_DIR / "historial_bateria.csv"
REPORT_DIR.mkdir(parents=True, exist_ok=True)

# Migracion del legacy (reportes_bateria dentro de battery_monitor/)
_LEGACY_REPORT_DIR = BASE_DIR / "reportes_bateria"
if _LEGACY_REPORT_DIR.exists() and _LEGACY_REPORT_DIR.is_dir():
    try:
        for child in _LEGACY_REPORT_DIR.iterdir():
            target = REPORT_DIR / child.name
            if not target.exists():
                try:
                    import shutil as _sh
                    _sh.move(str(child), str(target))
                except Exception:
                    pass
        # Renombrar carpeta legacy para no volver a migrar
        try:
            _LEGACY_REPORT_DIR.rename(_LEGACY_REPORT_DIR.with_name("reportes_bateria.bak"))
        except Exception:
            pass
    except Exception:
        pass


# =====================================================
# Utilidades de sistema
# =====================================================

def is_admin():
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def detect_os_info():
    """Detecta Windows 10 / 11 y si el equipo es Mac con Boot Camp."""
    info = {
        "system": platform.system(),
        "release": platform.release(),
        "version": platform.version(),
        "machine": platform.machine(),
        "is_windows_10": False,
        "is_windows_11": False,
        "is_mac_bootcamp": False,
        "manufacturer": "",
        "model": "",
    }

    try:
        ver = platform.version()
        build = int(ver.split(".")[-1]) if ver.count(".") >= 2 else 0
        info["build"] = build
        rel = platform.release()
        if rel == "11" or (rel == "10" and build >= 22000):
            info["is_windows_11"] = True
        elif rel == "10":
            info["is_windows_10"] = True
    except Exception:
        info["build"] = 0

    cmd = (
        'powershell -NoProfile -Command '
        '"Get-CimInstance Win32_ComputerSystem | '
        'Select-Object Manufacturer,Model | ConvertTo-Json -Compress"'
    )
    code, out, _ = run_cmd(cmd, shell=True)
    if code == 0 and out:
        try:
            data = json.loads(out)
            info["manufacturer"] = (data.get("Manufacturer") or "").strip()
            info["model"] = (data.get("Model") or "").strip()
            mfr = info["manufacturer"].lower()
            mdl = info["model"].lower()
            if "apple" in mfr or "macbook" in mdl or "mac" in mdl:
                info["is_mac_bootcamp"] = True
        except Exception:
            pass

    return info


def run_cmd(cmd, timeout=120, shell=False):
    try:
        cp = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            shell=shell,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return cp.returncode, (cp.stdout or "").strip(), (cp.stderr or "").strip()
    except subprocess.TimeoutExpired:
        return 1, "", f"Timeout despues de {timeout}s"
    except Exception as e:
        return 1, "", str(e)


def read_text(path):
    p = Path(path)
    if not p.exists():
        return ""
    for enc in ("utf-8", "utf-16", "latin-1"):
        try:
            return p.read_text(encoding=enc, errors="ignore")
        except Exception:
            pass
    return ""


def safe_pct(a, b):
    try:
        if a is None or b is None or b == 0:
            return None
        return round((a / b) * 100, 1)
    except Exception:
        return None


def health_status(health):
    if health is None:
        return "N/D"
    if health >= 90:
        return "Excelente"
    if health >= 80:
        return "Buena"
    if health >= 70:
        return "Media"
    return "Baja"


def score_status(score):
    if score is None:
        return "N/D"
    if score >= 85:
        return "Optimo"
    if score >= 70:
        return "Bueno"
    if score >= 50:
        return "Mejorable"
    return "Critico"


# =====================================================
# Lectura de bateria
# =====================================================

def get_battery_psutil():
    try:
        batt = psutil.sensors_battery()
        if not batt:
            return {"has_battery": False}
        secs = batt.secsleft
        if secs in (psutil.POWER_TIME_UNLIMITED, psutil.POWER_TIME_UNKNOWN) or secs < 0:
            t = "No disponible"
        else:
            h = secs // 3600
            m = (secs % 3600) // 60
            t = f"{h}h {m}m"
        return {
            "has_battery": True,
            "percent": round(float(batt.percent), 1) if batt.percent is not None else None,
            "plugged": bool(batt.power_plugged),
            "time_left_text": t,
        }
    except Exception:
        return {"has_battery": False}


def get_win32_battery():
    cmd = (
        'powershell -NoProfile -Command '
        '"Get-CimInstance Win32_Battery | '
        'Select-Object Name,BatteryStatus,EstimatedChargeRemaining,EstimatedRunTime,Chemistry,DesignVoltage | '
        'ConvertTo-Json -Compress"'
    )
    code, out, _ = run_cmd(cmd, shell=True)
    if code != 0 or not out:
        return {}
    try:
        data = json.loads(out)
        if isinstance(data, list):
            data = data[0] if data else {}
        return data or {}
    except Exception:
        return {}


def generate_battery_report():
    f = REPORT_DIR / "battery_report.html"
    run_cmd(["powercfg", "/batteryreport", "/output", str(f)], timeout=120)
    return {"battery_report": f}


def generate_energy_report(duration_sec=15):
    """
    Analiza el consumo de energia en tiempo real.
    duration_sec: cuanto tiempo monitorear (Windows hace medicion real
    durante este tiempo + un analisis posterior).
    Default 15 seg (buen balance entre calidad y tiempo).
    """
    f = REPORT_DIR / "energy_report.html"
    run_cmd(["powercfg", "/energy", "/output", str(f),
             "/duration", str(duration_sec)],
            timeout=duration_sec + 60)
    return {"energy_report": f}


def generate_sleepstudy_report():
    f = REPORT_DIR / "sleepstudy_report.html"
    run_cmd(["powercfg", "/sleepstudy", "/output", str(f)], timeout=120)
    return {"sleepstudy_report": f}


def generate_reports():
    """Compatibilidad - genera todos los reportes secuencial."""
    out = {}
    out.update(generate_battery_report())
    out.update(generate_energy_report())
    out.update(generate_sleepstudy_report())
    return out


def parse_battery_report(path):
    text = read_text(path)
    if not text:
        return {}

    def get_num(*labels):
        for label in labels:
            m = re.search(rf"{re.escape(label)}.*?>([\d,\.]+)\s*mWh", text, re.I | re.S)
            if m:
                return int(re.sub(r"[^\d]", "", m.group(1)))
        return None

    design = get_num(
        "DESIGN CAPACITY",
        "CAPACIDAD DE DISENO",
        "CAPACIDAD DE DISEÑO",
        "CAPACIDAD DE DISEÑO",
    )
    full = get_num(
        "FULL CHARGE CAPACITY",
        "CAPACIDAD DE CARGA COMPLETA",
        "CAPACIDAD DE LA CARGA COMPLETA",
    )
    cyc = re.search(
        r"(?:CYCLE COUNT|RECUENTO DE CICLOS|NÚMERO DE CICLOS).*?>([\d,\.]+)",
        text, re.I | re.S
    )
    cycles = int(re.sub(r"[^\d]", "", cyc.group(1))) if cyc else None
    return {
        "design_capacity_mWh": design,
        "full_charge_capacity_mWh": full,
        "health_pct": safe_pct(full, design),
        "cycle_count": cycles,
    }


def get_powercfg_text(args):
    code, out, err = run_cmd(["powercfg"] + args, timeout=60)
    return out if out else err


def get_fast_startup():
    cmd = (
        'powershell -NoProfile -Command '
        '"(Get-ItemProperty -Path \'HKLM:\\SYSTEM\\CurrentControlSet\\Control\\Session Manager\\Power\' '
        '-Name HiberbootEnabled -ErrorAction SilentlyContinue).HiberbootEnabled"'
    )
    code, out, _ = run_cmd(cmd, shell=True)
    val = (out or "").strip()
    if val == "1":
        return "Activo"
    if val == "0":
        return "Desactivado"
    return "No disponible"


def get_startup_apps():
    if winreg is None:
        return []
    result = []
    keys = [
        (winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run", "HKCU"),
        (winreg.HKEY_LOCAL_MACHINE, r"Software\Microsoft\Windows\CurrentVersion\Run", "HKLM"),
    ]
    for hive, path, pref in keys:
        try:
            k = winreg.OpenKey(hive, path)
            i = 0
            while True:
                try:
                    name, value, _ = winreg.EnumValue(k, i)
                    result.append((pref, name, str(value)))
                    i += 1
                except OSError:
                    break
            winreg.CloseKey(k)
        except OSError:
            pass
    return result


def process_snapshot(top_n=20):
    rows = []
    for p in psutil.process_iter(["pid", "name", "username", "cpu_percent", "memory_percent"]):
        try:
            p.cpu_percent(None)
        except Exception:
            pass
    time.sleep(1.0)
    for p in psutil.process_iter(["pid", "name", "username", "cpu_percent", "memory_percent"]):
        try:
            info = p.info
            rows.append({
                "pid": info.get("pid"),
                "name": info.get("name") or "",
                "cpu": round(info.get("cpu_percent") or 0.0, 2),
                "mem": round(info.get("memory_percent") or 0.0, 2),
                "user": info.get("username") or "",
            })
        except Exception:
            pass
    rows.sort(key=lambda x: (x["cpu"], x["mem"]), reverse=True)
    return rows[:top_n]


def parse_energy_warnings(path):
    text = read_text(path)
    findings = []
    checks = [
        ("Wi-Fi en maximo rendimiento con bateria",
         r"(802\.11.*?M[aá]ximo rendimiento|Wireless.*Maximum Performance)"),
        ("USB sin suspension selectiva",
         r"(USB.*no entra en suspensi|USB.*not entering Selective Suspend)"),
        ("Uso alto de CPU",
         r"(Uso.*alto.*procesador|Processor utilization is high)"),
        ("Bluetooth con problema de driver",
         r"Bluetooth"),
        ("Temporizadores de despertador detectados",
         r"(Wake Timer|Temporizador de activaci)"),
        ("ASPM PCIe deshabilitado",
         r"(ASPM.*deshabilitad|ASPM.*disabled)"),
        ("Brillo de pantalla alto en bateria",
         r"(brillo.*alto|Display brightness)"),
        ("Plan de energia con alto rendimiento",
         r"(Plan de energ.*Alto rendimiento|Power plan.*High performance)"),
    ]
    for label, pat in checks:
        if re.search(pat, text, re.I | re.S):
            findings.append(label)
    return findings


def compute_score(m):
    score = 100
    health = m.get("health_pct")
    if health is not None:
        if health < 70:
            score -= 30
        elif health < 80:
            score -= 18
        elif health < 90:
            score -= 8

    if m.get("fast_startup") == "Activo":
        score -= 8
    if m.get("wake_timers_active"):
        score -= 8
    if m.get("wifi_max_perf"):
        score -= 10
    if m.get("wsearch_active"):
        score -= 8
    if m.get("usb_issues"):
        score -= 10
    if m.get("bluetooth_issue"):
        score -= 6
    high_cpu = m.get("high_cpu_process_count", 0)
    if high_cpu >= 3:
        score -= 10
    elif high_cpu >= 1:
        score -= 5
    startup_n = m.get("startup_count", 0)
    if startup_n >= 8:
        score -= 10
    elif startup_n >= 5:
        score -= 6
    elif startup_n >= 3:
        score -= 3

    return max(0, min(100, score))


def build_recommendations(m, os_info):
    recs = []
    if not m.get("has_battery", True):
        recs.append(("Sin bateria detectada",
                     "Este equipo no reporta bateria. Las recomendaciones se enfocan en consumo general."))

    health = m.get("health_pct")
    if health is not None:
        recs.append(("Salud de bateria", f"{health_status(health)} ({health}%)."))

    cycles = m.get("cycle_count")
    if cycles is not None and cycles > 500:
        recs.append(("Ciclos de carga",
                     f"Bateria con {cycles} ciclos. Considera evaluar reemplazo si la salud baja del 70%."))

    if m.get("fast_startup") == "Activo":
        recs.append(("Inicio Rapido",
                     "Desactivarlo reduce consumo residual y estados hibridos no deseados."))
    if m.get("wake_timers_active"):
        recs.append(("Wake timers",
                     "Desactivarlos evita despertares ocultos durante la suspension."))
    if m.get("wifi_max_perf"):
        recs.append(("Wi-Fi",
                     "Cambiar el adaptador inalambrico a 'Ahorro maximo' cuando esta en bateria."))
    if m.get("wsearch_active"):
        recs.append(("Indexacion",
                     "Windows Search puede consumir CPU/disco. Evaluar limitar carpetas indexadas."))
    if m.get("onedrive_startup"):
        recs.append(("OneDrive",
                     "Pausarlo en bateria o quitarlo del inicio reduce consumo."))
    if m.get("edge_autolaunch"):
        recs.append(("Edge",
                     "Quitar el autoarranque evita procesos en segundo plano."))
    if m.get("usb_issues"):
        recs.append(("USB",
                     "Hay dispositivos sin suspension selectiva."))
    if m.get("bluetooth_issue"):
        recs.append(("Bluetooth",
                     "Revisar driver o desactivar Bluetooth si no se usa."))
    if not m.get("s3_available") and m.get("has_battery", True):
        recs.append(("Suspension",
                     "El equipo no reporta S3 (Modern Standby probablemente activo). Verificar firmware."))

    if os_info.get("is_mac_bootcamp"):
        recs.append(("Mac con Boot Camp",
                     "En MacBooks con Windows algunos drivers Apple no optimizan ahorro. "
                     "Considerar usar Power Manager de Boot Camp y mantener drivers actualizados."))

    if os_info.get("is_windows_10"):
        recs.append(("Windows 10",
                     "Considera actualizar a Windows 11 si el hardware lo soporta para mejor gestion energetica."))

    return recs


def save_history(m):
    exists = HISTORY_CSV.exists()
    row = {
        "fecha": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "salud_pct": m.get("health_pct"),
        "carga_actual_pct": m.get("percent"),
        "conectado": "Si" if m.get("plugged") else "No",
        "ciclos": m.get("cycle_count"),
        "fast_startup": m.get("fast_startup"),
        "wake_timers": "Si" if m.get("wake_timers_active") else "No",
        "wifi_max_perf": "Si" if m.get("wifi_max_perf") else "No",
        "wsearch_activo": "Si" if m.get("wsearch_active") else "No",
        "startup_count": m.get("startup_count"),
        "score": m.get("score"),
        "estado": m.get("score_status"),
    }
    with open(HISTORY_CSV, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(row.keys()))
        if not exists:
            writer.writeheader()
        writer.writerow(row)


def load_history(limit=200):
    if not HISTORY_CSV.exists():
        return []
    rows = []
    with open(HISTORY_CSV, "r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)
    return rows[-limit:]


def export_summary(metrics, os_info):
    path = REPORT_DIR / "resumen_pro_v3.txt"
    lines = [
        "===== BATTERY MONITOR PRO V3 =====",
        f"Suite: {SUITE_NAME}",
        f"Fecha: {datetime.now():%Y-%m-%d %H:%M:%S}",
        "",
        "----- Sistema -----",
        f"OS: {os_info.get('system')} {os_info.get('release')} (build {os_info.get('build', 'N/D')})",
        f"Fabricante: {os_info.get('manufacturer', 'N/D')}",
        f"Modelo: {os_info.get('model', 'N/D')}",
        f"Mac con Boot Camp: {'Si' if os_info.get('is_mac_bootcamp') else 'No'}",
        "",
        "----- Resumen -----",
        f"Puntuacion global: {metrics.get('score')} / 100",
        f"Estado: {metrics.get('score_status')}",
        f"Salud bateria: {metrics.get('health_pct', 'N/D')}% ({metrics.get('health_status', 'N/D')})",
        f"Carga actual: {metrics.get('percent', 'N/D')}%",
        f"Conectado a corriente: {'Si' if metrics.get('plugged') else 'No'}",
        f"Tiempo restante: {metrics.get('time_left_text', 'N/D')}",
        f"Ciclos de carga: {metrics.get('cycle_count', 'N/D')}",
        f"Fast Startup: {metrics.get('fast_startup', 'N/D')}",
        "",
        "----- Hallazgos -----",
    ]
    findings = metrics.get("energy_findings", [])
    if findings:
        for x in findings:
            lines.append(f"- {x}")
    else:
        lines.append("Sin hallazgos relevantes.")
    lines += ["", "----- Recomendaciones -----"]
    for title, desc in metrics.get("recommendations", []):
        lines.append(f"- {title}: {desc}")
    lines += ["", "----- Top procesos -----"]
    for p in metrics.get("processes", [])[:10]:
        lines.append(f"- {p['name']} | CPU {p['cpu']}% | MEM {p['mem']}%")
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def apply_safe_optimizations(selected):
    """
    Devuelve (actions, failures, results)
    actions: lista de strings con cambios OK
    failures: lista de strings con problemas
    results: dict {key: "ok"|"fail"|"skipped"} para cada opcion seleccionada
    """
    actions, failures = [], []
    results = {}

    def do_shell(cmd, label):
        code, out, err = run_cmd(cmd, shell=True, timeout=120)
        if code == 0:
            actions.append(label)
            return True
        else:
            failures.append(f"{label}: {err or out or 'Error'}")
            return False

    if selected.get("fast_startup"):
        ok = do_shell(
            'reg add "HKLM\\SYSTEM\\CurrentControlSet\\Control\\Session Manager\\Power" '
            '/v HiberbootEnabled /t REG_DWORD /d 0 /f',
            "Fast Startup desactivado"
        )
        results["fast_startup"] = "ok" if ok else "fail"
    if selected.get("wake_timers"):
        ok1 = do_shell('powercfg -setacvalueindex scheme_current SUB_SLEEP RTCWAKE 0',
                       "Wake timers AC desactivados")
        ok2 = do_shell('powercfg -setdcvalueindex scheme_current SUB_SLEEP RTCWAKE 0',
                       "Wake timers bateria desactivados")
        do_shell('powercfg -setactive scheme_current', "Plan actualizado")
        results["wake_timers"] = "ok" if (ok1 and ok2) else "fail"
    if selected.get("wifi_saving"):
        # GUIDs correctos para "Wireless Adapter Settings -> Power Saving Mode"
        # subgrupo: 19cbb8fa-5279-450e-9fac-8a3d5fedd0c1 (Wireless Adapter Settings)
        # setting:  12bbebe6-58d6-4636-95bb-3217ef867c1a (Power Saving Mode)
        # valores: 0=Maximo rendimiento, 1=Ahorro bajo, 2=Ahorro medio, 3=Ahorro maximo
        # AC: rendimiento maximo (0). DC: ahorro maximo (3).
        wifi_sub = "19cbb8fa-5279-450e-9fac-8a3d5fedd0c1"
        wifi_set = "12bbebe6-58d6-4636-95bb-3217ef867c1a"
        ok1 = do_shell(
            f'powercfg -setacvalueindex scheme_current {wifi_sub} {wifi_set} 0',
            "Wi-Fi en rendimiento maximo conectado a corriente"
        )
        ok2 = do_shell(
            f'powercfg -setdcvalueindex scheme_current {wifi_sub} {wifi_set} 3',
            "Wi-Fi en ahorro maximo en bateria"
        )
        do_shell('powercfg -setactive scheme_current', "Plan actualizado")
        results["wifi_saving"] = "ok" if (ok1 and ok2) else "fail"
    if selected.get("wsearch"):
        ok1 = do_shell('sc stop "WSearch"', "Windows Search detenido")
        ok2 = do_shell('sc config "WSearch" start=disabled', "Windows Search deshabilitado")
        results["wsearch"] = "ok" if ok2 else "fail"
    if selected.get("power_saver"):
        ok = do_shell('powercfg -setactive SCHEME_MIN', "Plan ahorro activado")
        results["power_saver"] = "ok" if ok else "fail"
    if selected.get("disable_wake_devices"):
        txt = get_powercfg_text(["/devicequery", "wake_armed"])
        any_ok = False
        any_fail = False
        for line in (txt or "").splitlines():
            line = line.strip()
            if line and "NONE" not in line.upper():
                code, out, err = run_cmd(["powercfg", "/devicedisablewake", line], timeout=60)
                if code == 0:
                    actions.append(f"Wake deshabilitado: {line}")
                    any_ok = True
                else:
                    failures.append(f"No se pudo: {line}")
                    any_fail = True
        if any_ok and not any_fail:
            results["disable_wake_devices"] = "ok"
        elif any_ok:
            results["disable_wake_devices"] = "fail"
        else:
            results["disable_wake_devices"] = "skipped"
    if selected.get("startup_cleanup"):
        if winreg is not None:
            try:
                key = winreg.OpenKey(
                    winreg.HKEY_CURRENT_USER,
                    r"Software\Microsoft\Windows\CurrentVersion\Run",
                    0, winreg.KEY_SET_VALUE
                )
                for name in ["OneDrive", "Claude"]:
                    try:
                        winreg.DeleteValue(key, name)
                        actions.append(f"Inicio deshabilitado: {name}")
                    except OSError:
                        pass
                winreg.CloseKey(key)
            except Exception as e:
                failures.append(f"HKCU Run: {e}")
        ps = (
            'powershell -NoProfile -Command '
            '"$p=\'HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Run\'; '
            '(Get-Item $p).Property | Where-Object {$_ -like \'MicrosoftEdgeAutoLaunch*\'} | '
            'ForEach-Object { Remove-ItemProperty -Path $p -Name $_ -Force }"'
        )
        do_shell(ps, "Inicio deshabilitado: Edge auto-launch")
        results["startup_cleanup"] = "ok"
    return actions, failures, results


def collect_metrics(os_info, on_progress=None):
    """
    Recopila metricas del sistema. on_progress(msg:str) opcional,
    se llama entre cada fase para informar al usuario que esta pasando.
    """
    def progress(msg):
        if on_progress:
            try:
                on_progress(msg)
            except Exception:
                pass

    reports = {}
    progress("Generando informe de bateria... (5-10 segundos)")
    reports.update(generate_battery_report())

    progress("Analizando consumo de energia... (Windows monitorea ~15 seg + analisis)")
    reports.update(generate_energy_report(duration_sec=15))

    progress("Generando informe de hibernacion... (5-10 segundos)")
    reports.update(generate_sleepstudy_report())

    progress("Leyendo informe de bateria...")
    battery_html = parse_battery_report(reports["battery_report"])

    progress("Consultando estado de bateria en vivo...")
    batt_live = get_battery_psutil()
    batt_wmi = get_win32_battery()

    progress("Consultando temporizadores de despertador...")
    wake_timers = get_powercfg_text(["/waketimers"])
    wake_armed = get_powercfg_text(["/devicequery", "wake_armed"])
    sleep_states = get_powercfg_text(["/a"])

    progress("Procesando hallazgos de consumo de energia...")
    energy_findings = parse_energy_warnings(reports["energy_report"])

    progress("Listando apps de inicio...")
    startup = get_startup_apps()

    progress("Tomando snapshot de procesos en ejecucion...")
    procs = process_snapshot()

    progress("Calculando puntuacion y recomendaciones...")

    startup_join = " | ".join([f"{a[1]} {a[2]}" for a in startup]).lower()
    high_cpu_count = len([p for p in procs if p["cpu"] >= 1.0])
    no_wake_text = ("No hay temporizadores de activaci" in (wake_timers or "")
                    or "There are no active wake timers" in (wake_timers or ""))

    m = {
        **battery_html,
        **batt_live,
        "battery_name": batt_wmi.get("Name"),
        "fast_startup": get_fast_startup(),
        "wake_timers_text": wake_timers,
        "wake_timers_active": not no_wake_text and bool((wake_timers or "").strip()),
        "wake_armed_text": wake_armed,
        "sleep_states_text": sleep_states,
        "s3_available": "S3" in (sleep_states or ""),
        "modern_standby": "S0" in (sleep_states or "") and "Standby" in (sleep_states or ""),
        "energy_findings": energy_findings,
        "processes": procs,
        "startup_apps": startup,
        "startup_count": len(startup),
        "high_cpu_process_count": high_cpu_count,
        "onedrive_startup": "onedrive" in startup_join,
        "edge_autolaunch": "edge" in startup_join,
        "claude_startup": "claude" in startup_join,
        "wifi_max_perf": any("Wi-Fi en maximo rendimiento" in x for x in energy_findings),
        "wsearch_active": any(
            "searchindexer" in (p["name"] or "").lower() and p["cpu"] > 0
            for p in procs
        ),
        "usb_issues": any("USB sin suspension selectiva" in x for x in energy_findings),
        "bluetooth_issue": any("Bluetooth" in x for x in energy_findings),
    }
    m["health_status"] = health_status(m.get("health_pct"))
    m["score"] = compute_score(m)
    m["score_status"] = score_status(m["score"])
    m["recommendations"] = build_recommendations(m, os_info)
    save_history(m)
    return m


# =====================================================
# UI
# =====================================================

class App:
    def __init__(self, root):
        self.root = root
        self.root.title(f"{APP_TITLE} - {SUITE_NAME}")
        # Geometry conservadora para que quepa en 1080p con DPI 125%
        self.root.geometry(f"{s(1100)}x{s(720)}")
        self.root.minsize(s(960), s(640))
        self.root.configure(bg=COLORS["bg"])
        configure_ttk(self.root)

        self.os_info = detect_os_info()
        self.metrics = {}

        self.status_var = StringVar(value="Listo")
        self.admin_var = StringVar(value="Si" if is_admin() else "No")

        self.opt_fast = BooleanVar(value=True)
        self.opt_wake = BooleanVar(value=True)
        self.opt_wifi = BooleanVar(value=True)
        self.opt_search = BooleanVar(value=False)
        self.opt_power = BooleanVar(value=False)
        self.opt_devwake = BooleanVar(value=False)
        self.opt_startup = BooleanVar(value=False)

        self.auto_refresh = BooleanVar(value=False)
        self.auto_interval_min = IntVar(value=15)
        self._auto_job = None

        self.kpi_cards = {}

        self.build_ui()
        # Diferir 400ms para que la ventana este completamente renderizada
        # antes de mostrar el overlay de progreso (sino aparece detras o se cierra solo)
        self.root.after(400, self.refresh_async)

    def _os_label(self):
        if self.os_info.get("is_windows_11"):
            base = "Windows 11"
        elif self.os_info.get("is_windows_10"):
            base = "Windows 10"
        else:
            base = f"{self.os_info.get('system')} {self.os_info.get('release')}"
        if self.os_info.get("is_mac_bootcamp"):
            base += " (Mac Boot Camp)"
        return base

    def make_text(self, parent):
        box = tk.Frame(parent, bg=COLORS["bg_card"])
        box.pack(fill="both", expand=True)
        txt = tk.Text(box, wrap="word", font=FONTS["mono"],
                      bg=COLORS["bg_card"], fg=COLORS["text"],
                      relief="flat", borderwidth=0,
                      padx=12, pady=10,
                      selectbackground=COLORS["info_bg"])
        scr = ttk.Scrollbar(box, orient="vertical", command=txt.yview)
        txt.configure(yscrollcommand=scr.set)
        txt.pack(side="left", fill="both", expand=True)
        scr.pack(side="right", fill="y")
        return txt

    def set_text(self, widget, text):
        widget.delete("1.0", "end")
        widget.insert("1.0", text)

    def _make_tree(self, parent, cols, headings, widths, anchors,
                   show="headings", height=20, tree_col_width=200):
        """Crea Treeview + scrollbar y devuelve el tree."""
        wrap = tk.Frame(parent, bg=COLORS["bg_card"])
        wrap.pack(fill="both", expand=True)
        tree = ttk.Treeview(wrap, columns=cols, show=show, height=height)
        if "tree" in show:
            tree.heading("#0", text="SECCION")
            tree.column("#0", width=tree_col_width, anchor="w")
        for c in cols:
            tree.heading(c, text=headings[c])
            tree.column(c, width=widths[c], anchor=anchors[c])
        sb = ttk.Scrollbar(wrap, orient="vertical", command=tree.yview)
        sb.pack(side="right", fill="y")
        tree.configure(yscrollcommand=sb.set)
        tree.pack(side="left", fill="both", expand=True)
        return tree

    def build_ui(self):
        # ------- Header -------
        head = tk.Frame(self.root, bg=COLORS["bg"])
        head.pack(fill="x", padx=20, pady=(16, 6))

        left = tk.Frame(head, bg=COLORS["bg"])
        left.pack(side="left")
        tk.Label(left, text=APP_TITLE, bg=COLORS["bg"], fg=COLORS["text"],
                 font=FONTS["title"]).pack(anchor="w")
        meta = tk.Frame(left, bg=COLORS["bg"])
        meta.pack(anchor="w", pady=(2, 0))
        tk.Label(meta, text=f"v{APP_VERSION}",
                 bg=COLORS["bg"], fg=COLORS["text_muted"],
                 font=FONTS["label"]).pack(side="left")
        tk.Label(meta, text="  -  ", bg=COLORS["bg"],
                 fg=COLORS["text_soft"], font=FONTS["label"]).pack(side="left")
        tk.Label(meta, text=self._os_label(),
                 bg=COLORS["bg"], fg=COLORS["text_muted"],
                 font=FONTS["label"]).pack(side="left")
        tk.Label(meta, text="  -  ", bg=COLORS["bg"],
                 fg=COLORS["text_soft"], font=FONTS["label"]).pack(side="left")
        admin_label = "Administrador" if is_admin() else "Sin elevacion"
        admin_kind = "ok" if is_admin() else "warn"
        admin_pill = StatusPill(meta, text=admin_label, kind=admin_kind, width=130)
        admin_pill.pack(side="left", padx=(4, 0))

        right = tk.Frame(head, bg=COLORS["bg"])
        right.pack(side="right")
        Btn(right, text="Actualizar",
            command=self.refresh_async,
            kind="accent", width=110).pack(side="right")
        Btn(right, text="Exportar resumen",
            command=self.export_summary_ui,
            kind="ghost", width=160).pack(side="right", padx=(0, 8))
        Check(right, text="Auto-actualizar",
              variable=self.auto_refresh,
              command=self.toggle_auto_refresh).pack(side="right", padx=(0, 12))

        # ------- KPIs -------
        kpi_band = tk.Frame(self.root, bg=COLORS["bg"])
        kpi_band.pack(fill="x", padx=20, pady=(10, 6))

        kpi_defs = [
            ("score",  "PUNTUACION GLOBAL",   COLORS["accent"]),
            ("status", "ESTADO",         COLORS["info"]),
            ("health", "SALUD BATERIA",  COLORS["ok"]),
            ("charge", "CARGA",          COLORS["accent_dark"]),
        ]
        for i, (key, title, color) in enumerate(kpi_defs):
            card = KpiCard(kpi_band, title=title, value="-",
                           subtitle="-", accent=color,
                           show_bar=(key in ("score", "health", "charge")),
                           bar_invert=False, height=s(95))
            card.grid(row=0, column=i, sticky="nsew", padx=s(6), pady=s(4))
            kpi_band.columnconfigure(i, weight=1)
            self.kpi_cards[key] = card

        kpi_band2 = tk.Frame(self.root, bg=COLORS["bg"])
        kpi_band2.pack(fill="x", padx=s(20), pady=(0, s(8)))

        kpi_defs2 = [
            ("power",  "ALIMENTACION",   COLORS["info"]),
            ("time",   "TIEMPO RESTANTE",COLORS["info"]),
            ("cycles", "CICLOS",         COLORS["warn"]),
            ("fast",   "INICIO RAPIDO",  COLORS["info"]),
        ]
        for i, (key, title, color) in enumerate(kpi_defs2):
            card = KpiCard(kpi_band2, title=title, value="-",
                           subtitle="-", accent=color,
                           width=240, height=110)
            card.grid(row=0, column=i, sticky="nsew", padx=6, pady=4)
            kpi_band2.columnconfigure(i, weight=1)
            self.kpi_cards[key] = card

        # ------- Tabs (envueltos en un container para overlay inline) -------
        import customtkinter as ctk
        self._tabs_container = tk.Frame(self.root, bg=COLORS["bg"])
        self._tabs_container.pack(fill="both", expand=True, padx=s(20), pady=(s(4), s(10)))

        nb = ctk.CTkTabview(
            self._tabs_container,
            corner_radius=10,
            fg_color=COLORS["bg_card"],
            border_color=COLORS["border"],
            border_width=1,
            segmented_button_fg_color=COLORS["bg_card_alt"],
            segmented_button_selected_color=COLORS["accent"],
            segmented_button_selected_hover_color=COLORS["accent_dark"],
            segmented_button_unselected_color=COLORS["bg_card_alt"],
            segmented_button_unselected_hover_color=COLORS["bg_card"],
            text_color=COLORS["text"],
        )
        nb.pack(fill="both", expand=True)
        self._nb = nb

        # Banner de carga inline (oculto por default)
        # Se va a place() encima del notebook cuando hay trabajo en curso
        self._loading_banner = tk.Frame(
            self._tabs_container,
            bg=COLORS["bg_card"],
            highlightbackground=COLORS["accent"],
            highlightthickness=2,
        )
        loading_inner = tk.Frame(self._loading_banner, bg=COLORS["bg_card"])
        loading_inner.place(relx=0.5, rely=0.5, anchor="center")
        tk.Label(loading_inner, text="PROCESANDO",
                 bg=COLORS["bg_card"], fg=COLORS["text_muted"],
                 font=FONTS["small"]).pack()
        self._loading_msg_var = tk.StringVar(value="Trabajando...")
        tk.Label(loading_inner, textvariable=self._loading_msg_var,
                 bg=COLORS["bg_card"], fg=COLORS["text"],
                 font=FONTS["h1"], wraplength=s(700),
                 justify="center").pack(pady=(s(8), s(14)))
        self._loading_bar = ctk.CTkProgressBar(
            loading_inner, mode="indeterminate",
            progress_color=COLORS["accent"],
            fg_color=COLORS["bg_card_alt"],
            border_color=COLORS["border"],
            width=s(420), height=s(14),
        )
        self._loading_bar.pack(pady=(0, s(10)))
        tk.Label(loading_inner,
                 text="No cierres la ventana. Esto puede tardar 1-3 minutos en la primera carga.",
                 bg=COLORS["bg_card"], fg=COLORS["text_muted"],
                 font=FONTS["label"], wraplength=s(700),
                 justify="center").pack()

        for tab_name in ["Resumen", "Recomendaciones", "Procesos",
                         "Grafica", "Historial", "Optimizacion", "Detalles"]:
            nb.add(tab_name)

        self.tab_dash = nb.tab("Resumen")
        self.tab_reco = nb.tab("Recomendaciones")
        self.tab_proc = nb.tab("Procesos")
        self.tab_chart = nb.tab("Grafica")
        self.tab_hist = nb.tab("Historial")
        self.tab_opt = nb.tab("Optimizacion")
        self.tab_logs = nb.tab("Detalles")

        # Resumen - tabla con secciones expandibles
        sec = SectionCard(self.tab_dash, title="Detalle del equipo y bateria")
        sec.pack(fill="both", expand=True, padx=10, pady=10)
        self.summary_tree = self._make_tree(
            sec.body(),
            cols=("campo", "valor"),
            headings={"campo": "CAMPO", "valor": "VALOR"},
            widths={"campo": 280, "valor": 700},
            anchors={"campo": "w", "valor": "w"},
            show="tree headings",
            tree_col_width=240,
        )

        # Procesos
        proc_wrap = SectionCard(self.tab_proc,
                                title="Top procesos por consumo")
        proc_wrap.pack(fill="both", expand=True, padx=10, pady=10)
        cols = ("pid", "name", "cpu", "mem", "user")
        self.proc_tree = ttk.Treeview(proc_wrap.body(), columns=cols,
                                      show="headings", height=22)
        widths = {"pid": 80, "name": 360, "cpu": 100, "mem": 100, "user": 220}
        for c in cols:
            self.proc_tree.heading(c, text=c.upper())
            self.proc_tree.column(c, width=widths[c], anchor="w")
        self.proc_tree.pack(fill="both", expand=True)

        # Recomendaciones - tabla
        sec2 = SectionCard(self.tab_reco,
                           title="Recomendaciones para mejorar autonomia")
        sec2.pack(fill="both", expand=True, padx=10, pady=10)
        self.reco_tree = self._make_tree(
            sec2.body(),
            cols=("num", "titulo", "descripcion"),
            headings={"num": "#", "titulo": "RECOMENDACION",
                      "descripcion": "DETALLE"},
            widths={"num": 50, "titulo": 240, "descripcion": 700},
            anchors={"num": "center", "titulo": "w", "descripcion": "w"},
        )

        # Historial
        hist_card = SectionCard(self.tab_hist, title="Historial de mediciones")
        hist_card.pack(fill="both", expand=True, padx=10, pady=10)
        hist_top = tk.Frame(hist_card.body(), bg=COLORS["bg_card"])
        hist_top.pack(fill="x", pady=(0, 8))
        Btn(hist_top, text="Exportar CSV",
            command=self.export_history_ui,
            kind="ghost", width=130).pack(side="left")
        Btn(hist_top, text="Recargar",
            command=self.populate_history,
            kind="ghost", width=110).pack(side="left", padx=8)
        Btn(hist_top, text="Borrar historial",
            command=self.clear_history_ui,
            kind="danger", width=150).pack(side="left", padx=8)
        hist_cols = ("fecha", "salud_pct", "carga_actual_pct", "ciclos",
                     "score", "estado", "fast_startup", "wake_timers", "startup_count")
        self.hist_tree = ttk.Treeview(hist_card.body(), columns=hist_cols,
                                      show="headings", height=18)
        for c in hist_cols:
            self.hist_tree.heading(c, text=c.upper())
            self.hist_tree.column(c, width=110, anchor="w")
        self.hist_tree.pack(fill="both", expand=True)

        # Grafica
        self.build_chart_tab()

        # Optimizacion
        self.build_opt_tab()

        # Detalles - tabla con secciones expandibles
        sec3 = SectionCard(self.tab_logs, title="Detalles tecnicos del sistema")
        sec3.pack(fill="both", expand=True, padx=10, pady=10)
        self.log_tree = self._make_tree(
            sec3.body(),
            cols=("dato",),
            headings={"dato": "INFORMACION"},
            widths={"dato": 900},
            anchors={"dato": "w"},
            show="tree headings",
            tree_col_width=320,
        )

        # ------- Status bar -------
        statusbar = tk.Frame(self.root, bg=COLORS["bg"])
        statusbar.pack(fill="x", padx=20, pady=(0, 12))
        tk.Label(statusbar, textvariable=self.status_var,
                 bg=COLORS["bg"], fg=COLORS["text_muted"],
                 font=FONTS["small"]).pack(side="left")
        tk.Label(statusbar,
                 text=f"{APP_TITLE} v{APP_VERSION}  -  {COPYRIGHT}",
                 bg=COLORS["bg"], fg=COLORS["text_soft"],
                 font=FONTS["small"]).pack(side="right")

    def build_opt_tab(self):
        # Footer fijo abajo con el boton EJECUTAR (siempre visible)
        footer = tk.Frame(self.tab_opt, bg=COLORS["bg"], height=64)
        footer.pack(side="bottom", fill="x", padx=10, pady=(8, 12))
        footer.pack_propagate(False)
        Btn(footer, text="EJECUTAR: aplicar optimizacion",
            command=self.apply_optimizations_ui,
            kind="accent", width=280, height=42).pack(side="left", pady=8)
        tk.Label(footer,
                 text="  Cada cambio queda registrado y se puede revertir desde Historial.",
                 bg=COLORS["bg"], fg=COLORS["text_muted"],
                 font=FONTS["label"]).pack(side="left", padx=14)

        # Contenido envuelto en ScrollableFrame para permitir scroll vertical
        # cuando la ventana sea chica o haya muchos checkboxes.
        scroll = ScrollableFrame(self.tab_opt)
        scroll.pack(fill="both", expand=True, padx=10, pady=10)
        scroll_body = scroll.body()

        wrap = SectionCard(scroll_body,
                           title="Perfil seguro de optimizacion energetica")
        wrap.pack(fill="x", padx=4, pady=4)

        info = tk.Label(wrap.body(),
                        text=("Cada cambio se aplica con un registro reversible. "
                              "Puedes revertirlo desde el lanzador en 'Historial / Rollback'."),
                        bg=COLORS["bg_card"], fg=COLORS["text_muted"],
                        font=FONTS["body"], justify="left", wraplength=900)
        info.pack(anchor="w", pady=(0, 12))

        opts = [
            ("fast_startup", self.opt_fast,
             "Desactivar Inicio Rapido (Fast Startup)",
             "Reduce consumo residual y conflictos de hibernacion."),
            ("wake_timers", self.opt_wake,
             "Desactivar temporizadores de despertador",
             "Evita que el equipo despierte sin intervencion."),
            ("wifi_saving", self.opt_wifi,
             "Wi-Fi en ahorro maximo con bateria",
             "Reduce el consumo del adaptador inalambrico."),
            ("wsearch", self.opt_search,
             "Deshabilitar Windows Search (indexador)",
             "Solo recomendado en equipos lentos. Afecta busquedas."),
            ("power_saver", self.opt_power,
             "Activar plan de Ahorro de energia",
             "Cambia el plan activo a 'Ahorro'."),
            ("disable_wake_devices", self.opt_devwake,
             "Quitar permiso de despertar a dispositivos",
             "Aplica devicedisablewake a todos los dispositivos armados."),
            ("startup_cleanup", self.opt_startup,
             "Limpiar autoarranque comun (OneDrive/Edge/Claude)",
             "Quita entradas comunes del registro de inicio."),
        ]
        self.opt_status_pills = {}
        for key, var, label, desc in opts:
            row = tk.Frame(wrap.body(), bg=COLORS["bg_card"])
            row.pack(fill="x", pady=4)
            Check(row, text=label, variable=var).pack(side="left")
            tk.Label(row, text=f"   {desc}",
                     bg=COLORS["bg_card"], fg=COLORS["text_muted"],
                     font=FONTS["label"]).pack(side="left")
            pill = StatusPill(row, text="PENDIENTE", kind="muted",
                              width=110, height=22)
            pill.pack(side="right", padx=8)
            self.opt_status_pills[key] = pill

        if not is_admin():
            warn = tk.Frame(wrap.body(), bg=COLORS["warn_bg"])
            warn.pack(fill="x", pady=(12, 0))
            tk.Label(warn,
                     text=" Para aplicar cambios reinicia con 'Battery_Monitor_Admin.bat'",
                     bg=COLORS["warn_bg"], fg=COLORS["warn"],
                     font=FONTS["label_b"]).pack(anchor="w", padx=10, pady=8)

        result_card = SectionCard(scroll_body, title="Resultado de la ultima ejecucion")
        result_card.pack(fill="x", padx=4, pady=(8, 4))
        self.opt_result = self.make_text(result_card.body())
        # Forzar altura minima para que el text widget se vea aunque este vacio
        try:
            self.opt_result.configure(height=10)
        except Exception:
            pass

    def build_chart_tab(self):
        wrap = SectionCard(self.tab_chart,
                           title="Evolucion historica - Puntuacion y Salud")
        wrap.pack(fill="both", expand=True, padx=10, pady=10)
        top = tk.Frame(wrap.body(), bg=COLORS["bg_card"])
        top.pack(fill="x")
        Btn(top, text="Refrescar grafica",
            command=self.draw_chart,
            kind="ghost", width=160).pack(side="right")
        self.chart_canvas = tk.Canvas(wrap.body(), bg=COLORS["bg_card"],
                                       height=420, highlightthickness=0)
        self.chart_canvas.pack(fill="both", expand=True, pady=(8, 0))
        self.chart_canvas.bind("<Configure>", lambda e: self.draw_chart())

    def draw_chart(self):
        c = self.chart_canvas
        c.delete("all")
        rows = load_history(limit=120)
        w = c.winfo_width()
        h = c.winfo_height()
        if w < 50 or h < 50:
            return

        margin_l, margin_r, margin_t, margin_b = 60, 30, 30, 50
        plot_w = w - margin_l - margin_r
        plot_h = h - margin_t - margin_b

        for i in range(0, 11):
            y = margin_t + plot_h * (1 - i / 10)
            c.create_line(margin_l, y, margin_l + plot_w, y,
                          fill=COLORS["border_soft"])
            c.create_text(margin_l - 10, y, text=str(i * 10), anchor="e",
                          font=FONTS["small"], fill=COLORS["text_muted"])

        c.create_line(margin_l, margin_t,
                      margin_l, margin_t + plot_h,
                      fill=COLORS["border"])
        c.create_line(margin_l, margin_t + plot_h,
                      margin_l + plot_w, margin_t + plot_h,
                      fill=COLORS["border"])

        if not rows:
            c.create_text(w / 2, h / 2,
                          text="Sin historial todavia. Pulsa 'Actualizar' algunas veces.",
                          fill=COLORS["text_muted"], font=FONTS["body"])
            return

        n = len(rows)

        def _to_float(v):
            try:
                return float(v) if v not in (None, "", "None") else None
            except Exception:
                return None

        scores = [_to_float(r.get("score")) for r in rows]
        healths = [_to_float(r.get("salud_pct")) for r in rows]

        def points(values, color):
            xs = []
            for i, v in enumerate(values):
                if v is None:
                    continue
                x = margin_l + (plot_w * (i / max(1, n - 1)))
                y = margin_t + plot_h * (1 - max(0, min(100, v)) / 100)
                xs.append((x, y))
            if len(xs) >= 2:
                flat = [coord for pt in xs for coord in pt]
                c.create_line(*flat, fill=color, width=2, smooth=False)
            for x, y in xs:
                c.create_oval(x - 3, y - 3, x + 3, y + 3,
                              fill=color, outline=color)

        points(scores, COLORS["accent"])
        points(healths, COLORS["ok"])

        legend_x = margin_l + plot_w - 140
        legend_y = margin_t + 6
        c.create_rectangle(legend_x, legend_y,
                           legend_x + 134, legend_y + 50,
                           fill=COLORS["bg_card"],
                           outline=COLORS["border"])
        c.create_line(legend_x + 10, legend_y + 18,
                      legend_x + 36, legend_y + 18,
                      fill=COLORS["accent"], width=2)
        c.create_text(legend_x + 44, legend_y + 18, text="Puntuacion",
                      anchor="w", font=FONTS["label"],
                      fill=COLORS["text"])
        c.create_line(legend_x + 10, legend_y + 38,
                      legend_x + 36, legend_y + 38,
                      fill=COLORS["ok"], width=2)
        c.create_text(legend_x + 44, legend_y + 38, text="Salud %",
                      anchor="w", font=FONTS["label"],
                      fill=COLORS["text"])

        if n > 0:
            f0 = rows[0].get("fecha", "")
            fN = rows[-1].get("fecha", "")
            c.create_text(margin_l, margin_t + plot_h + 18,
                          text=f0, anchor="w", font=FONTS["small"],
                          fill=COLORS["text_muted"])
            c.create_text(margin_l + plot_w, margin_t + plot_h + 18,
                          text=fN, anchor="e", font=FONTS["small"],
                          fill=COLORS["text_muted"])

    def toggle_auto_refresh(self):
        if self.auto_refresh.get():
            self._schedule_auto()
            self.status_var.set(f"Auto-actualizacion activa cada {self.auto_interval_min.get()} min")
        else:
            if self._auto_job:
                self.root.after_cancel(self._auto_job)
                self._auto_job = None
            self.status_var.set("Auto-actualizacion desactivada")

    def _schedule_auto(self):
        ms = max(1, self.auto_interval_min.get()) * 60 * 1000
        self._auto_job = self.root.after(ms, self._auto_tick)

    def _auto_tick(self):
        if self.auto_refresh.get():
            self.refresh_async()
            self._schedule_auto()

    def _show_loading_banner(self, msg):
        try:
            self._loading_msg_var.set(msg)
            # place() encima del notebook, ocupando todo el container
            self._loading_banner.place(relx=0, rely=0,
                                        relwidth=1, relheight=1)
            self._loading_banner.lift()
            self._loading_bar.start()
        except Exception:
            pass

    def _hide_loading_banner(self):
        try:
            self._loading_bar.stop()
        except Exception:
            pass
        try:
            self._loading_banner.place_forget()
        except Exception:
            pass

    def refresh_async(self):
        self.status_var.set("Actualizando metricas...")
        # Solo banner inline (cubre el notebook). No usar Toplevel
        # porque se duplica con el banner.
        self._show_loading_banner("Iniciando recopilacion de metricas...")
        threading.Thread(target=self.refresh_worker, daemon=True).start()

    def refresh_worker(self):
        def on_progress(msg):
            self.root.after(0, lambda m=msg: self._loading_msg_var.set(m))
            self.root.after(0, lambda m=msg: self.status_var.set(m))

        try:
            self.metrics = collect_metrics(self.os_info, on_progress=on_progress)
            self.root.after(0, self.populate_ui)
            self.root.after(0, lambda: self.status_var.set(
                f"Metricas actualizadas - {datetime.now():%H:%M:%S}"
            ))
        except Exception as e:
            self.root.after(0, lambda: self.status_var.set(f"Error: {e}"))
        finally:
            self.root.after(0, self._hide_loading_banner)

    def populate_ui(self):
        m = self.metrics
        score = m.get("score")
        score_color = (color_for_value(score, (50, 80), invert=False)
                       if score is not None else COLORS["text_muted"])
        self.kpi_cards["score"].update_data(
            value=f"{score}" if score is not None else "N/D",
            subtitle=f"{m.get('score_status', 'N/D')}  -  de 100",
            accent=score_color,
            bar_value=score or 0, bar_max=100,
        )

        status = m.get("score_status", "N/D")
        status_color = (COLORS["ok"] if status == "Optimo"
                        else COLORS["info"] if status == "Bueno"
                        else COLORS["warn"] if status == "Mejorable"
                        else COLORS["bad"] if status == "Critico"
                        else COLORS["text_muted"])
        self.kpi_cards["status"].update_data(
            value=status, subtitle=f"Puntuacion: {score}/100",
            accent=status_color,
        )

        health = m.get("health_pct")
        h_color = (color_for_value(health, (70, 85), invert=False)
                   if health is not None else COLORS["text_muted"])
        self.kpi_cards["health"].update_data(
            value=f"{health}%" if health is not None else "N/D",
            subtitle=m.get("health_status", "N/D"),
            accent=h_color,
            bar_value=health or 0, bar_max=100,
        )

        pct = m.get("percent")
        c_color = (color_for_value(pct, (20, 50), invert=False)
                   if pct is not None else COLORS["text_muted"])
        self.kpi_cards["charge"].update_data(
            value=f"{pct}%" if pct is not None else "N/D",
            subtitle=("Cargando" if m.get("plugged")
                      else "En bateria" if m.get("has_battery", True)
                      else "Sin bateria"),
            accent=c_color,
            bar_value=pct or 0, bar_max=100,
        )

        if not m.get("has_battery", True):
            power_text, power_kind = "Sin bateria", COLORS["text_muted"]
        elif m.get("plugged"):
            power_text, power_kind = "Cargando", COLORS["ok"]
        else:
            power_text, power_kind = "En bateria", COLORS["info"]
        self.kpi_cards["power"].update_data(
            value=power_text, subtitle=m.get("battery_name", "") or "-",
            accent=power_kind,
        )

        self.kpi_cards["time"].update_data(
            value=m.get("time_left_text", "N/D"),
            subtitle="Estimado segun uso actual",
            accent=COLORS["info"],
        )

        cyc = m.get("cycle_count")
        cyc_color = (COLORS["ok"] if cyc and cyc < 300
                     else COLORS["warn"] if cyc and cyc < 500
                     else COLORS["bad"] if cyc and cyc >= 500
                     else COLORS["text_muted"])
        self.kpi_cards["cycles"].update_data(
            value=str(cyc) if cyc is not None else "N/D",
            subtitle="Reemplazo recomendado >500" if cyc else "-",
            accent=cyc_color,
        )

        fast_val = m.get("fast_startup", "N/D")
        fast_color = (COLORS["ok"] if fast_val == "Desactivado"
                      else COLORS["warn"] if fast_val == "Activo"
                      else COLORS["text_muted"])
        sleep_sub = ("Modern Standby (S0)" if m.get("modern_standby")
                     else "S3 disponible" if m.get("s3_available")
                     else "S3 no disponible")
        self.kpi_cards["fast"].update_data(
            value=fast_val, subtitle=sleep_sub, accent=fast_color,
        )

        # Tabla Resumen (con secciones expandibles)
        for it in self.summary_tree.get_children():
            self.summary_tree.delete(it)

        node_eq = self.summary_tree.insert(
            "", "end", text="Equipo", open=True
        )
        self.summary_tree.insert(node_eq, "end", values=(
            "Fabricante", self.os_info.get('manufacturer', 'N/D')))
        self.summary_tree.insert(node_eq, "end", values=(
            "Modelo", self.os_info.get('model', 'N/D')))
        self.summary_tree.insert(node_eq, "end", values=(
            "Sistema operativo", self._os_label()))

        node_bt = self.summary_tree.insert(
            "", "end", text="Bateria", open=True
        )
        self.summary_tree.insert(node_bt, "end", values=(
            "Nombre", m.get('battery_name', 'N/D') or "N/D"))
        self.summary_tree.insert(node_bt, "end", values=(
            "Capacidad de diseno", f"{m.get('design_capacity_mWh', 'N/D')} mWh"))
        self.summary_tree.insert(node_bt, "end", values=(
            "Carga completa actual", f"{m.get('full_charge_capacity_mWh', 'N/D')} mWh"))
        self.summary_tree.insert(node_bt, "end", values=(
            "Ciclos de carga", str(m.get('cycle_count', 'N/D'))))
        self.summary_tree.insert(node_bt, "end", values=(
            "Salud", f"{m.get('health_pct', 'N/D')}% ({m.get('health_status', 'N/D')})"))

        node_ct = self.summary_tree.insert(
            "", "end", text="Carga actual", open=True
        )
        self.summary_tree.insert(node_ct, "end", values=(
            "Porcentaje", f"{m.get('percent', 'N/D')}%"))
        self.summary_tree.insert(node_ct, "end", values=(
            "Conectado a corriente", "Si" if m.get("plugged") else "No"))
        self.summary_tree.insert(node_ct, "end", values=(
            "Tiempo restante", m.get("time_left_text", "N/D")))

        node_sw = self.summary_tree.insert(
            "", "end", text="Software / energia", open=True
        )
        self.summary_tree.insert(node_sw, "end", values=(
            "Inicio rapido (Fast Startup)", m.get("fast_startup", "N/D")))
        self.summary_tree.insert(node_sw, "end", values=(
            "Suspension S3 disponible", "Si" if m.get("s3_available") else "No"))
        self.summary_tree.insert(node_sw, "end", values=(
            "Modern Standby (S0)", "Si" if m.get("modern_standby") else "No"))
        self.summary_tree.insert(node_sw, "end", values=(
            "Apps de inicio", str(m.get('startup_count', 0))))
        self.summary_tree.insert(node_sw, "end", values=(
            "Procesos con CPU >=1%", str(m.get('high_cpu_process_count', 0))))

        findings = m.get("energy_findings", [])
        node_fi = self.summary_tree.insert(
            "", "end",
            text=f"Hallazgos del informe ({len(findings)})",
            open=True
        )
        if findings:
            for i, x in enumerate(findings, 1):
                self.summary_tree.insert(node_fi, "end",
                                          values=(f"#{i}", x))
        else:
            self.summary_tree.insert(node_fi, "end",
                                      values=("-", "Sin hallazgos"))

        startup_apps = m.get("startup_apps", [])
        node_st = self.summary_tree.insert(
            "", "end",
            text=f"Apps de inicio detectadas ({len(startup_apps)})",
            open=False
        )
        if startup_apps:
            for prefix, name, val in startup_apps:
                self.summary_tree.insert(node_st, "end",
                                          values=(f"{prefix} - {name}", val))
        else:
            self.summary_tree.insert(node_st, "end",
                                      values=("-", "Sin apps de inicio"))

        # Procesos
        for item in self.proc_tree.get_children():
            self.proc_tree.delete(item)
        for p in m.get("processes", []):
            self.proc_tree.insert("", "end", values=(p["pid"], p["name"], p["cpu"], p["mem"], p["user"]))

        # Recomendaciones (tabla)
        for it in self.reco_tree.get_children():
            self.reco_tree.delete(it)
        recs = m.get("recommendations", [])
        if recs:
            for i, (title, desc) in enumerate(recs, 1):
                self.reco_tree.insert("", "end", values=(i, title, desc))
        else:
            self.reco_tree.insert("", "end",
                                   values=("-", "Sin recomendaciones",
                                           "El equipo esta optimizado."))

        # Detalles tecnicos (tree con secciones expandibles)
        for it in self.log_tree.get_children():
            self.log_tree.delete(it)

        def _add_section(title, text):
            node = self.log_tree.insert("", "end", text=title, open=False)
            content = (text or "").strip() or "(sin datos)"
            for line in content.splitlines():
                line = line.rstrip()
                if line:
                    self.log_tree.insert(node, "end", values=(line,))
            return node

        _add_section("Temporizadores de despertador (wake timers)",
                     m.get("wake_timers_text"))
        _add_section("Dispositivos con permiso para despertar",
                     m.get("wake_armed_text"))
        _add_section("Estados de suspension disponibles",
                     m.get("sleep_states_text"))

        self.populate_history()
        self.draw_chart()

    def populate_history(self):
        for item in self.hist_tree.get_children():
            self.hist_tree.delete(item)
        rows = load_history()
        for row in reversed(rows):
            self.hist_tree.insert(
                "", "end",
                values=(
                    row.get("fecha", ""),
                    row.get("salud_pct", ""),
                    row.get("carga_actual_pct", ""),
                    row.get("ciclos", ""),
                    row.get("score", ""),
                    row.get("estado", ""),
                    row.get("fast_startup", ""),
                    row.get("wake_timers", ""),
                    row.get("startup_count", ""),
                ),
            )

    def export_summary_ui(self):
        if not self.metrics:
            messagebox.showwarning(APP_TITLE, "Primero actualiza las metricas.")
            return
        path = export_summary(self.metrics, self.os_info)
        messagebox.showinfo(APP_TITLE, f"Resumen exportado en:\n{path}")

    def export_history_ui(self):
        if not HISTORY_CSV.exists():
            messagebox.showwarning(APP_TITLE, "Aun no existe historial.")
            return
        save_path = filedialog.asksaveasfilename(
            title="Guardar historial CSV",
            defaultextension=".csv",
            filetypes=[("CSV", "*.csv")],
            initialfile="historial_bateria.csv",
        )
        if not save_path:
            return
        Path(save_path).write_bytes(HISTORY_CSV.read_bytes())
        messagebox.showinfo(APP_TITLE, f"Historial exportado en:\n{save_path}")

    def clear_history_ui(self):
        if not HISTORY_CSV.exists():
            messagebox.showinfo(APP_TITLE, "No hay historial para borrar.")
            return
        if messagebox.askyesno(APP_TITLE, "Esto borra el historial CSV. Continuar?"):
            HISTORY_CSV.unlink()
            self.populate_history()
            self.draw_chart()

    def apply_optimizations_ui(self):
        if not is_admin():
            messagebox.showwarning(
                APP_TITLE,
                "Para aplicar cambios, cierra esta ventana y reinicia el programa "
                "haciendo clic derecho > 'Ejecutar como administrador'."
            )
            return
        selected = {
            "fast_startup": self.opt_fast.get(),
            "wake_timers": self.opt_wake.get(),
            "wifi_saving": self.opt_wifi.get(),
            "wsearch": self.opt_search.get(),
            "power_saver": self.opt_power.get(),
            "disable_wake_devices": self.opt_devwake.get(),
            "startup_cleanup": self.opt_startup.get(),
        }
        if not any(selected.values()):
            messagebox.showinfo(APP_TITLE, "No hay optimizaciones seleccionadas.")
            return
        if not messagebox.askyesno(APP_TITLE, "Se aplicara el perfil seleccionado. Continuar?"):
            return

        overlay = ProgressOverlay(
            self.root,
            "Aplicando optimizaciones energeticas..."
        )

        # Resetear pills de las opciones marcadas a "EN PROCESO"
        for key, val in selected.items():
            if val and key in self.opt_status_pills:
                self.opt_status_pills[key].update_text("EN PROCESO", "info")

        def worker():
            try:
                actions, failures, results = apply_safe_optimizations(selected)
            except Exception as e:
                self.root.after(0, overlay.close)
                self.root.after(0, lambda: messagebox.showerror(
                    APP_TITLE, f"Error al aplicar optimizaciones: {e}"
                ))
                return

            self.root.after(0, overlay.close)

            # Actualizar pills semaforo segun resultado
            def update_pills():
                for key, status in results.items():
                    if key in self.opt_status_pills:
                        if status == "ok":
                            self.opt_status_pills[key].update_text("APLICADO", "ok")
                        elif status == "fail":
                            self.opt_status_pills[key].update_text("FALLO", "bad")
                        else:
                            self.opt_status_pills[key].update_text("OMITIDO", "muted")
                # Las opciones no marcadas vuelven a "PENDIENTE"
                for key in self.opt_status_pills:
                    if key not in results and selected.get(key) is False:
                        self.opt_status_pills[key].update_text("PENDIENTE", "muted")
            self.root.after(0, update_pills)

            # Texto detallado en el card
            lines = ["===== CAMBIOS APLICADOS ====="]
            if actions:
                for a in actions:
                    lines.append(f"OK   {a}")
            else:
                lines.append("(ninguno)")
            if failures:
                lines.append("")
                lines.append("===== OBSERVACIONES =====")
                for f in failures:
                    lines.append(f"--   {f}")
            self.root.after(0, lambda: self.set_text(
                self.opt_result, "\n".join(lines)
            ))

            # Mensaje resumen al terminar
            n_ok = sum(1 for v in results.values() if v == "ok")
            n_fail = sum(1 for v in results.values() if v == "fail")
            n_skip = sum(1 for v in results.values() if v == "skipped")
            summary = (
                f"OPTIMIZACION FINALIZADA\n\n"
                f"Aplicadas exitosamente: {n_ok}\n"
                f"Con errores: {n_fail}\n"
                f"Sin efecto / omitidas: {n_skip}\n\n"
                f"Detalle: revisa los semaforos junto a cada opcion en esta "
                f"pestana, o el panel inferior 'Resultado de la ultima "
                f"ejecucion'.\n\n"
                f"Para revertir cualquier cambio: lanzador -> "
                f"'Historial / Revertir'."
            )
            if n_fail:
                self.root.after(0, lambda: messagebox.showwarning(
                    APP_TITLE, summary
                ))
            else:
                self.root.after(0, lambda: messagebox.showinfo(
                    APP_TITLE, summary
                ))

        threading.Thread(target=worker, daemon=True).start()


def main():
    root = Tk()
    setup_scaling(root)
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
