"""
Startup Analyzer - PC Performance Suite.

Detecta programas que arrancan con Windows desde:
- Registro: HKCU/HKLM Run y RunOnce
- Carpetas Startup (usuario y All Users)
- Tareas programadas marcadas como 'AtLogon'

Aplica un 'score de sospechoso' (0-100) basado en heuristicas:
- Path en %TEMP% / %APPDATA%\\Local\\Temp / sin ruta absoluta
- Sin firma digital
- Nombre random (entropy alta)
- Path en directorio de usuario poco comun
- Ejecutable inexistente

Permite habilitar/deshabilitar entradas con rollback reversible.
"""

import os
import re
import sys
import math
import threading
import subprocess
import tkinter as tk
from pathlib import Path
from tkinter import ttk, messagebox

try:
    import winreg
except ImportError:
    winreg = None

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core import style as _style_mod
_style_mod.apply_saved_theme()
from core.style import COLORS, FONTS, configure_ttk, COPYRIGHT
from core.ui_kit import KpiCard, SectionCard, StatusPill
from core.ctk_kit import init_ctk, Btn, Check
from core.scale import setup_scaling, s
from core.progress import ProgressOverlay
from core import rollback
init_ctk()


APP_TITLE = "Analizador de Inicio"
APP_VERSION = "1.0.0"
SUITE_NAME = "Suite de Optimizacion PC"
MODULE_NAME = "startup_analyzer"


REG_RUN_LOCATIONS = [
    ("HKCU", r"Software\Microsoft\Windows\CurrentVersion\Run", "winreg.HKEY_CURRENT_USER"),
    ("HKCU", r"Software\Microsoft\Windows\CurrentVersion\RunOnce", "winreg.HKEY_CURRENT_USER"),
    ("HKLM", r"Software\Microsoft\Windows\CurrentVersion\Run", "winreg.HKEY_LOCAL_MACHINE"),
    ("HKLM", r"Software\Microsoft\Windows\CurrentVersion\RunOnce", "winreg.HKEY_LOCAL_MACHINE"),
    ("HKLM", r"Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Run", "winreg.HKEY_LOCAL_MACHINE"),
]


def hive_const(hive_name):
    if winreg is None:
        return None
    return {
        "HKCU": winreg.HKEY_CURRENT_USER,
        "HKLM": winreg.HKEY_LOCAL_MACHINE,
    }.get(hive_name)


def list_registry_run():
    if winreg is None:
        return []
    rows = []
    for hive_name, subkey, _ in REG_RUN_LOCATIONS:
        h = hive_const(hive_name)
        try:
            with winreg.OpenKey(h, subkey, 0, winreg.KEY_READ) as k:
                i = 0
                while True:
                    try:
                        name, value, _t = winreg.EnumValue(k, i)
                        rows.append({
                            "source": "registry",
                            "hive": hive_name,
                            "subkey": subkey,
                            "name": name,
                            "command": str(value),
                            "enabled": True,
                        })
                        i += 1
                    except OSError:
                        break
        except OSError:
            continue
    return rows


def list_startup_folders():
    rows = []
    folders = []
    appdata = os.environ.get("APPDATA")
    if appdata:
        folders.append(("user", Path(appdata) / "Microsoft" / "Windows" /
                        "Start Menu" / "Programs" / "Startup"))
    programdata = os.environ.get("PROGRAMDATA")
    if programdata:
        folders.append(("all_users", Path(programdata) / "Microsoft" / "Windows" /
                        "Start Menu" / "Programs" / "StartUp"))
    for scope, folder in folders:
        if not folder.exists():
            continue
        for p in folder.iterdir():
            try:
                if p.is_file():
                    rows.append({
                        "source": "folder",
                        "scope": scope,
                        "folder": str(folder),
                        "name": p.stem,
                        "command": str(p.resolve() if p.exists() else p),
                        "path": str(p),
                        "enabled": True,
                    })
            except Exception:
                continue
    return rows


def list_scheduled_logon():
    """Tareas programadas del usuario que disparan en logon."""
    rows = []
    cmd = (
        'powershell -NoProfile -Command "'
        'Get-ScheduledTask | Where-Object {$_.State -ne \\"Disabled\\" -and '
        '($_.Triggers | Where-Object {$_.CimClass.CimClassName -eq '
        '\\"MSFT_TaskLogonTrigger\\"}).Count -gt 0} | '
        'Select-Object TaskName,TaskPath,@{N=\\"Action\\";E={'
        '($_.Actions | Select-Object -First 1).Execute}} | ConvertTo-Json"'
    )
    try:
        cp = subprocess.run(cmd, capture_output=True, text=True,
                            shell=True, timeout=30,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if cp.returncode != 0 or not cp.stdout.strip():
            return rows
        import json as _json
        data = _json.loads(cp.stdout)
        if isinstance(data, dict):
            data = [data]
        for d in data or []:
            rows.append({
                "source": "scheduled_task",
                "task_name": d.get("TaskName"),
                "task_path": d.get("TaskPath"),
                "name": d.get("TaskName"),
                "command": d.get("Action") or "",
                "enabled": True,
            })
    except Exception:
        pass
    return rows


def collect_all():
    """Une todas las fuentes."""
    items = []
    items += list_registry_run()
    items += list_startup_folders()
    items += list_scheduled_logon()
    return items


# ---------- Heuristicas de sospechoso ----------

def _shannon(s):
    if not s:
        return 0.0
    from collections import Counter
    counts = Counter(s)
    total = len(s)
    entropy = 0.0
    for c in counts.values():
        p = c / total
        entropy -= p * math.log2(p)
    return entropy


def _extract_exe_path(command):
    """Saca la ruta del ejecutable del comando."""
    if not command:
        return None
    cmd = command.strip()
    if cmd.startswith('"'):
        end = cmd.find('"', 1)
        if end > 0:
            return cmd[1:end]
    parts = cmd.split(" ", 1)
    return parts[0]


def is_signed(exe_path):
    """Verifica firma digital con powershell. None si no determinable."""
    if not exe_path or not Path(exe_path).exists():
        return None
    try:
        cmd = (
            f'powershell -NoProfile -Command '
            f'"(Get-AuthenticodeSignature \'{exe_path}\').Status"'
        )
        cp = subprocess.run(cmd, capture_output=True, text=True,
                            shell=True, timeout=10,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        out = (cp.stdout or "").strip()
        if "Valid" in out:
            return True
        if "NotSigned" in out or "HashMismatch" in out:
            return False
        return None
    except Exception:
        return None


def score_suspicious(item, check_signature=False):
    """
    Devuelve (score 0-100, list_of_reasons).
    100 = muy sospechoso, 0 = muy confiable.
    """
    score = 0
    reasons = []
    cmd = item.get("command", "") or ""
    name = item.get("name", "") or ""

    exe = _extract_exe_path(cmd)

    if exe:
        exe_low = exe.lower()
        if "\\temp\\" in exe_low or "/temp/" in exe_low:
            score += 35
            reasons.append("Ejecutable en %TEMP%")
        if "\\appdata\\local\\temp" in exe_low:
            score += 35
            reasons.append("Ejecutable en LocalAppData/Temp")
        if "\\downloads\\" in exe_low:
            score += 20
            reasons.append("Ejecutable en Downloads")
        if "\\users\\" in exe_low and "\\appdata\\roaming\\" not in exe_low:
            if "\\program files" not in exe_low:
                score += 10
                reasons.append("Ejecutable en perfil de usuario")
        if not Path(exe).exists():
            score += 25
            reasons.append("Ejecutable inexistente")

        ent = _shannon(Path(exe).name.lower())
        if ent > 4.2 and len(Path(exe).stem) >= 8:
            score += 15
            reasons.append(f"Nombre con entropia alta ({ent:.1f})")

        if not re.match(r"^[a-zA-Z]:\\", exe):
            score += 10
            reasons.append("Sin ruta absoluta")
    else:
        score += 30
        reasons.append("Comando sin ejecutable identificable")

    nm_low = name.lower()
    known_safe = ["onedrive", "edge", "chrome", "firefox", "claude",
                  "discord", "spotify", "steam", "teams", "slack",
                  "skype", "zoom", "dropbox", "vmware", "vbox",
                  "intel", "nvidia", "amd", "realtek", "synaptics",
                  "windows", "microsoft", "security health",
                  "sharex", "1password", "bitwarden"]
    if any(k in nm_low for k in known_safe):
        score = max(0, score - 25)
        reasons.append("Nombre conocido")

    if check_signature and exe:
        sig = is_signed(exe)
        if sig is True:
            score = max(0, score - 15)
            reasons.append("Firma digital valida")
        elif sig is False:
            score += 20
            reasons.append("Sin firma digital valida")

    score = max(0, min(100, score))
    return score, reasons


def disable_entry(item):
    """
    Deshabilita una entrada de inicio. Devuelve (ok, msg, rollback_entry).
    """
    src = item.get("source")
    if src == "registry":
        entry = rollback.registry_delete_value(
            module=MODULE_NAME,
            hive_name=item["hive"],
            subkey=item["subkey"],
            value_name=item["name"],
            label=f"Inicio deshabilitado: {item['hive']}\\{item['name']}",
        )
        if entry is None:
            return False, "No se pudo leer el valor", None
        if isinstance(entry, dict) and "error" in entry:
            return False, entry["error"], None
        return True, "Deshabilitado (reversible desde rollback)", entry

    if src == "folder":
        path = Path(item["path"])
        if not path.exists():
            return False, "Acceso directo no encontrado", None
        result = rollback.quarantine_file(
            module=MODULE_NAME,
            src_path=str(path),
            label=f"Startup: {path.name}",
        )
        if result is None:
            return False, "No se pudo mover", None
        if isinstance(result, dict) and "error" in result:
            return False, result["error"], None
        return True, "Archivo movido a cuarentena (reversible)", result

    if src == "scheduled_task":
        cmd = (f'schtasks /Change /TN "{item["task_path"]}{item["task_name"]}" '
               '/DISABLE')
        cp = subprocess.run(cmd, capture_output=True, text=True,
                            shell=True, timeout=15,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if cp.returncode == 0:
            return True, "Tarea deshabilitada (revertir manual: /ENABLE)", None
        return False, (cp.stderr or cp.stdout or "Error").strip(), None

    return False, "Tipo no soportado", None


# ---------- UI ----------

class StartupApp:
    def __init__(self, root):
        self.root = root
        self.root.title(f"{APP_TITLE} - {SUITE_NAME}")
        self.root.geometry(f"{s(1240)}x{s(780)}")
        self.root.minsize(s(1080), s(700))
        self.root.configure(bg=COLORS["bg"])
        configure_ttk(self.root)

        self.items = []
        self.check_sig = tk.BooleanVar(value=False)
        self.show_safe = tk.BooleanVar(value=True)
        self.build_ui()
        self.scan_async()

    def build_ui(self):
        head = tk.Frame(self.root, bg=COLORS["bg"])
        head.pack(fill="x", padx=20, pady=(16, 6))
        left = tk.Frame(head, bg=COLORS["bg"])
        left.pack(side="left")
        tk.Label(left, text=APP_TITLE, bg=COLORS["bg"],
                 fg=COLORS["text"], font=FONTS["title"]).pack(anchor="w")
        tk.Label(left,
                 text="Programas que arrancan con Windows. Puntuacion de sospechoso y deshabilitar reversible.",
                 bg=COLORS["bg"], fg=COLORS["text_muted"],
                 font=FONTS["body"]).pack(anchor="w", pady=(4, 0))

        right = tk.Frame(head, bg=COLORS["bg"])
        right.pack(side="right")
        Btn(right, text="Re-escanear",
            command=self.scan_async,
            kind="accent", width=120).pack(side="right")
        Check(right, text="Verificar firma digital (lento)",
              variable=self.check_sig).pack(side="right", padx=(0, 12))

        kpi = tk.Frame(self.root, bg=COLORS["bg"])
        kpi.pack(fill="x", padx=20, pady=(10, 8))
        self.kpi_total = KpiCard(kpi, title="ENTRADAS DE INICIO",
                                 value="-", subtitle="-",
                                 accent=COLORS["accent"])
        self.kpi_susp = KpiCard(kpi, title="SOSPECHOSAS",
                                value="-", subtitle="Puntuacion >= 60",
                                accent=COLORS["bad"])
        self.kpi_warn = KpiCard(kpi, title="A REVISAR",
                                value="-", subtitle="Puntuacion 30-59",
                                accent=COLORS["warn"])
        self.kpi_ok = KpiCard(kpi, title="CONFIABLES",
                              value="-", subtitle="Puntuacion < 30",
                              accent=COLORS["ok"])
        for i, c in enumerate([self.kpi_total, self.kpi_susp,
                               self.kpi_warn, self.kpi_ok]):
            c.grid(row=0, column=i, sticky="nsew", padx=6, pady=4)
            kpi.columnconfigure(i, weight=1)

        listcard = SectionCard(self.root, title="Programas de inicio detectados")
        listcard.pack(fill="both", expand=True, padx=20, pady=(4, 6))
        body = listcard.body()

        topbar = tk.Frame(body, bg=COLORS["bg_card"])
        topbar.pack(fill="x", pady=(0, 6))
        Check(topbar, text="Mostrar tambien confiables",
              variable=self.show_safe,
              command=self.refresh_table).pack(side="left")
        tk.Label(topbar,
                 text="Doble clic en una fila para ver detalles y deshabilitar.",
                 bg=COLORS["bg_card"], fg=COLORS["text_muted"],
                 font=FONTS["label"]).pack(side="right")

        cols = ("score", "name", "source", "hive", "command", "reasons")
        self.tree = ttk.Treeview(body, columns=cols,
                                 show="headings", height=20)
        widths = {"score": 80, "name": 220, "source": 100,
                  "hive": 90, "command": 380, "reasons": 360}
        headings = {"score": "PUNT.", "name": "NOMBRE", "source": "ORIGEN",
                    "hive": "HIVE/ORIGEN", "command": "COMANDO",
                    "reasons": "RAZONES"}
        for c in cols:
            self.tree.heading(c, text=headings[c])
            self.tree.column(c, width=widths[c], anchor="w")
        self.tree.pack(fill="both", expand=True, side="left")
        sb = ttk.Scrollbar(body, orient="vertical", command=self.tree.yview)
        sb.pack(side="right", fill="y")
        self.tree.configure(yscrollcommand=sb.set)

        self.tree.tag_configure("bad", background=COLORS["tree_row_bad"],
                                foreground=COLORS["text"])
        self.tree.tag_configure("warn", background=COLORS["tree_row_warn"],
                                foreground=COLORS["text"])
        self.tree.tag_configure("ok", background=COLORS["tree_row_ok"],
                                foreground=COLORS["text"])
        self.tree.bind("<Double-1>", self._on_double)

        actions = tk.Frame(self.root, bg=COLORS["bg"], height=64)
        actions.pack(side="bottom", fill="x", padx=20, pady=(8, 14))
        actions.pack_propagate(False)
        Btn(actions, text="EJECUTAR: deshabilitar seleccionado (reversible)",
            command=self._disable_selected,
            kind="danger", width=380, height=42).pack(side="left", pady=8)
        Btn(actions, text="Ver detalle",
            command=self._show_details,
            kind="ghost", width=120, height=42).pack(side="left", padx=8, pady=8)
        self.status_var = tk.StringVar(value="Listo")
        tk.Label(actions, textvariable=self.status_var,
                 bg=COLORS["bg"], fg=COLORS["text_muted"],
                 font=FONTS["label"]).pack(side="right")
        tk.Label(actions, text=f"{APP_TITLE} v{APP_VERSION}  -  {COPYRIGHT}",
                 bg=COLORS["bg"], fg=COLORS["text_soft"],
                 font=FONTS["small"]).pack(side="right", padx=(0, 14))

    def scan_async(self):
        self.status_var.set("Escaneando entradas de inicio...")
        threading.Thread(target=self._scan_worker, daemon=True).start()

    def _scan_worker(self):
        try:
            items = collect_all()
            check_sig = self.check_sig.get()
            for it in items:
                score, reasons = score_suspicious(it, check_signature=check_sig)
                it["score"] = score
                it["reasons"] = reasons
            self.items = items
            self.root.after(0, self.refresh_table)
            self.root.after(0, lambda: self.status_var.set(
                f"Encontradas {len(items)} entradas"
            ))
        except Exception as e:
            self.root.after(0, lambda: self.status_var.set(f"Error: {e}"))

    def refresh_table(self):
        for it in self.tree.get_children():
            self.tree.delete(it)

        n_susp = sum(1 for x in self.items if x["score"] >= 60)
        n_warn = sum(1 for x in self.items if 30 <= x["score"] < 60)
        n_ok = sum(1 for x in self.items if x["score"] < 30)
        self.kpi_total.update_data(value=str(len(self.items)),
                                   subtitle="Total detectadas",
                                   accent=COLORS["accent"])
        self.kpi_susp.update_data(value=str(n_susp), subtitle="Puntuacion >= 60",
                                  accent=COLORS["bad"])
        self.kpi_warn.update_data(value=str(n_warn), subtitle="Puntuacion 30-59",
                                  accent=COLORS["warn"])
        self.kpi_ok.update_data(value=str(n_ok), subtitle="Puntuacion < 30",
                                accent=COLORS["ok"])

        items_sorted = sorted(self.items, key=lambda x: x["score"], reverse=True)
        for idx, it in enumerate(items_sorted):
            sc = it["score"]
            if sc < 30 and not self.show_safe.get():
                continue
            tag = "bad" if sc >= 60 else "warn" if sc >= 30 else "ok"
            hive_or_origin = (it.get("hive") or it.get("scope")
                              or it.get("task_path", "") or "-")
            self.tree.insert("", "end", iid=str(idx), tags=(tag,),
                             values=(
                                 sc, it.get("name", ""),
                                 it.get("source", ""),
                                 hive_or_origin,
                                 it.get("command", "")[:200],
                                 ", ".join(it.get("reasons", []))[:200],
                             ))
        self._items_sorted = items_sorted

    def _selected_item(self):
        sel = self.tree.selection()
        if not sel:
            return None
        idx = int(sel[0])
        return self._items_sorted[idx] if idx < len(self._items_sorted) else None

    def _show_details(self):
        it = self._selected_item()
        if not it:
            messagebox.showinfo(APP_TITLE, "Selecciona una entrada.")
            return
        details = [
            f"Nombre: {it.get('name')}",
            f"Origen: {it.get('source')}",
            f"Hive/Scope: {it.get('hive') or it.get('scope') or it.get('task_path', '-')}",
            f"Comando: {it.get('command')}",
            f"Puntuacion sospechosa: {it.get('score')}/100",
            "",
            "Razones:",
        ]
        for r in it.get("reasons", []):
            details.append(f"  - {r}")
        messagebox.showinfo(APP_TITLE, "\n".join(details))

    def _on_double(self, _event):
        self._show_details()

    def _disable_selected(self):
        it = self._selected_item()
        if not it:
            messagebox.showinfo(APP_TITLE, "Selecciona una entrada.")
            return
        if not messagebox.askyesno(
            APP_TITLE,
            f"Deshabilitar '{it.get('name')}'?\n\n"
            "Se aplicara con rollback reversible:\n"
            "  - Registro: borrado con valor previo guardado\n"
            "  - Carpeta Startup: movido a cuarentena\n"
            "  - Tarea programada: desactivada (revertir manual)"
        ):
            return

        overlay = ProgressOverlay(
            self.root,
            f"Deshabilitando '{it.get('name')}'..."
        )

        def worker():
            try:
                ok, msg, _entry = disable_entry(it)
            except Exception as e:
                self.root.after(0, overlay.close)
                self.root.after(0, lambda: messagebox.showerror(
                    APP_TITLE, f"Error: {e}"
                ))
                return
            self.root.after(0, overlay.close)
            if ok:
                self.root.after(0, lambda: messagebox.showinfo(APP_TITLE, msg))
                self.root.after(0, self.scan_async)
            else:
                self.root.after(0, lambda: messagebox.showwarning(
                    APP_TITLE, f"No se aplico: {msg}"
                ))

        threading.Thread(target=worker, daemon=True).start()


def main():
    root = tk.Tk()
    setup_scaling(root)
    StartupApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
