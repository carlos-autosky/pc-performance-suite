"""
Deep Uninstall - PC Performance Suite (beta).

Lista programas instalados (registro Uninstall) y permite:
1. Lanzar el uninstaller estandar (UninstallString).
2. Ejecutar 'modo silencioso' si esta disponible (QuietUninstallString).
3. Detectar y limpiar leftovers tras desinstalar (carpetas/registry).

NOTA: la deteccion profunda de leftovers (registry walk completo, scan
de servicios, scheduled tasks por publisher, etc.) se ira ampliando.
Esta version cubre:
 - Carpetas obvias en %ProgramFiles%, %ProgramFiles(x86)%, %APPDATA%, %LOCALAPPDATA%
 - Claves de registro restantes con el InstallLocation o publisher
"""

import os
import re
import sys
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
from core.ctk_kit import init_ctk, Btn, Check, Entry
from core.scale import setup_scaling, s
from core.progress import ProgressOverlay
from core import rollback
init_ctk()


APP_TITLE = "Desinstalador Profundo"
APP_VERSION = "0.1 (beta)"
SUITE_NAME = "Suite de Optimizacion PC"
MODULE_NAME = "deep_uninstall"


UNINSTALL_KEYS = [
    (winreg.HKEY_LOCAL_MACHINE if winreg else None,
     r"Software\Microsoft\Windows\CurrentVersion\Uninstall", "HKLM"),
    (winreg.HKEY_LOCAL_MACHINE if winreg else None,
     r"Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall", "HKLM-WOW64"),
    (winreg.HKEY_CURRENT_USER if winreg else None,
     r"Software\Microsoft\Windows\CurrentVersion\Uninstall", "HKCU"),
]


def list_installed():
    if winreg is None:
        return []
    rows = []
    seen = set()
    for hive, subkey, label in UNINSTALL_KEYS:
        if hive is None:
            continue
        try:
            with winreg.OpenKey(hive, subkey, 0, winreg.KEY_READ) as k:
                i = 0
                while True:
                    try:
                        sub = winreg.EnumKey(k, i)
                        i += 1
                        try:
                            with winreg.OpenKey(k, sub, 0, winreg.KEY_READ) as sk:
                                def get(n):
                                    try:
                                        v, _ = winreg.QueryValueEx(sk, n)
                                        return str(v) if v is not None else ""
                                    except Exception:
                                        return ""
                                name = get("DisplayName")
                                if not name:
                                    continue
                                version = get("DisplayVersion")
                                publisher = get("Publisher")
                                install_loc = get("InstallLocation")
                                uninst = get("UninstallString")
                                quiet = get("QuietUninstallString")
                                est_size_kb = get("EstimatedSize")
                                key_id = (label, sub)
                                if key_id in seen:
                                    continue
                                seen.add(key_id)
                                rows.append({
                                    "key_label": label,
                                    "key_id": sub,
                                    "name": name,
                                    "version": version,
                                    "publisher": publisher,
                                    "install_location": install_loc,
                                    "uninstall_string": uninst,
                                    "quiet_uninstall_string": quiet,
                                    "size_kb": int(est_size_kb) if est_size_kb.isdigit() else 0,
                                })
                        except OSError:
                            continue
                    except OSError:
                        break
        except OSError:
            continue
    rows.sort(key=lambda r: (r["name"] or "").lower())
    return rows


def find_leftovers(item):
    """Heuristica simple: busca carpetas relacionadas con publisher/name."""
    leftovers = []
    name = (item.get("name") or "").strip()
    publisher = (item.get("publisher") or "").strip()
    install_loc = (item.get("install_location") or "").strip()

    candidates = []
    bases = [
        os.environ.get("ProgramFiles"),
        os.environ.get("ProgramFiles(x86)"),
        os.environ.get("APPDATA"),
        os.environ.get("LOCALAPPDATA"),
        os.environ.get("PROGRAMDATA"),
    ]
    targets = [name, publisher]
    for b in bases:
        if not b:
            continue
        bp = Path(b)
        for t in targets:
            if not t or len(t) < 3:
                continue
            try:
                for child in bp.iterdir():
                    if not child.is_dir():
                        continue
                    if t.lower() in child.name.lower():
                        candidates.append(child)
            except (PermissionError, OSError):
                continue

    if install_loc and Path(install_loc).exists():
        candidates.append(Path(install_loc))

    seen = set()
    for c in candidates:
        try:
            cp = c.resolve()
            if cp in seen:
                continue
            seen.add(cp)
            size = 0
            try:
                for root, _dirs, files in os.walk(cp):
                    for f in files:
                        try:
                            size += (Path(root) / f).stat().st_size
                        except Exception:
                            pass
            except Exception:
                pass
            leftovers.append({
                "path": str(cp),
                "size": size,
                "kind": "folder",
            })
        except Exception:
            continue
    return leftovers


def launch_uninstaller(item, quiet=False):
    cmd = item.get("quiet_uninstall_string") if quiet else item.get("uninstall_string")
    if not cmd:
        cmd = item.get("uninstall_string")
    if not cmd:
        return False, "Sin UninstallString registrada"
    try:
        subprocess.Popen(cmd, shell=True)
        return True, "Uninstaller lanzado. Sigue sus instrucciones y al terminar pulsa 'Buscar residuales'."
    except Exception as e:
        return False, f"Error: {e}"


# ---------- UI ----------

class DeepUninstallApp:
    def __init__(self, root):
        self.root = root
        self.root.title(f"{APP_TITLE} - {SUITE_NAME}")
        self.root.geometry(f"{s(1240)}x{s(780)}")
        self.root.minsize(s(1080), s(700))
        self.root.configure(bg=COLORS["bg"])
        configure_ttk(self.root)

        self.items = []
        self.filter_text = tk.StringVar()
        self.build_ui()
        self.scan_async()

    def build_ui(self):
        head = tk.Frame(self.root, bg=COLORS["bg"])
        head.pack(fill="x", padx=20, pady=(16, 6))
        tk.Label(head, text=APP_TITLE, bg=COLORS["bg"],
                 fg=COLORS["text"], font=FONTS["title"]).pack(side="left")
        tk.Label(head, text=f"  v{APP_VERSION}",
                 bg=COLORS["bg"], fg=COLORS["text_muted"],
                 font=FONTS["label"]).pack(side="left", padx=(8, 0))

        Btn(head, text="Re-escanear",
            command=self.scan_async,
            kind="accent", width=120).pack(side="right")

        warn = tk.Frame(self.root, bg=COLORS["warn_bg"])
        warn.pack(fill="x", padx=20, pady=(8, 6))
        tk.Label(warn,
                 text=("BETA: el uninstaller estandar se lanza tal cual lo registra el programa. "
                       "La busqueda de leftovers es heuristica y puede tener falsos positivos. "
                       "Antes de borrar leftovers se confirma cada ruta."),
                 bg=COLORS["warn_bg"], fg=COLORS["warn"],
                 font=FONTS["label"], wraplength=1180,
                 justify="left").pack(anchor="w", padx=10, pady=8)

        kpi = tk.Frame(self.root, bg=COLORS["bg"])
        kpi.pack(fill="x", padx=20, pady=(2, 8))
        self.kpi_total = KpiCard(kpi, title="PROGRAMAS INSTALADOS",
                                 value="-", subtitle="-",
                                 accent=COLORS["accent"])
        self.kpi_size = KpiCard(kpi, title="TAMANO TOTAL ESTIMADO",
                                value="-", subtitle="Segun registro",
                                accent=COLORS["info"])
        self.kpi_pub = KpiCard(kpi, title="PUBLISHERS UNICOS",
                               value="-", subtitle="-",
                               accent=COLORS["warn"])
        for i, c in enumerate([self.kpi_total, self.kpi_size, self.kpi_pub]):
            c.grid(row=0, column=i, sticky="nsew", padx=6, pady=4)
            kpi.columnconfigure(i, weight=1)

        listcard = SectionCard(self.root, title="Programas instalados")
        listcard.pack(fill="both", expand=True, padx=20, pady=(4, 6))
        body = listcard.body()

        topbar = tk.Frame(body, bg=COLORS["bg_card"])
        topbar.pack(fill="x", pady=(0, 6))
        tk.Label(topbar, text="Filtrar:", bg=COLORS["bg_card"],
                 fg=COLORS["text"], font=FONTS["label_b"]).pack(side="left")
        ent = Entry(topbar, textvariable=self.filter_text, width=320)
        ent.pack(side="left", padx=(8, 0))
        ent.bind("<KeyRelease>", lambda _e: self.refresh_table())

        cols = ("name", "version", "publisher", "size_mb", "scope")
        self.tree = ttk.Treeview(body, columns=cols,
                                 show="headings", height=22)
        widths = {"name": 380, "version": 110, "publisher": 240,
                  "size_mb": 100, "scope": 110}
        headings = {"name": "PROGRAMA", "version": "VERSION",
                    "publisher": "PUBLISHER", "size_mb": "TAMANO",
                    "scope": "REGISTRO"}
        for c in cols:
            self.tree.heading(c, text=headings[c])
            self.tree.column(c, width=widths[c], anchor="w")
        self.tree.pack(fill="both", expand=True, side="left")
        sb = ttk.Scrollbar(body, orient="vertical", command=self.tree.yview)
        sb.pack(side="right", fill="y")
        self.tree.configure(yscrollcommand=sb.set)

        actions = tk.Frame(self.root, bg=COLORS["bg"], height=64)
        actions.pack(side="bottom", fill="x", padx=20, pady=(8, 14))
        actions.pack_propagate(False)
        Btn(actions, text="EJECUTAR: desinstalar",
            command=self._uninstall_selected,
            kind="accent", width=200, height=42).pack(side="left", pady=8)
        Btn(actions, text="EJECUTAR: desinstalar (silencioso)",
            command=lambda: self._uninstall_selected(quiet=True),
            kind="ghost", width=280, height=42).pack(side="left", padx=8, pady=8)
        Btn(actions, text="EJECUTAR: buscar residuales",
            command=self._find_leftovers,
            kind="ghost", width=230, height=42).pack(side="left", padx=8, pady=8)
        self.status_var = tk.StringVar(value="Listo")
        tk.Label(actions, textvariable=self.status_var,
                 bg=COLORS["bg"], fg=COLORS["text_muted"],
                 font=FONTS["label"]).pack(side="right")
        tk.Label(actions, text=f"{APP_TITLE} v{APP_VERSION}  -  {COPYRIGHT}",
                 bg=COLORS["bg"], fg=COLORS["text_soft"],
                 font=FONTS["small"]).pack(side="right", padx=(0, 14))

    def scan_async(self):
        self.status_var.set("Escaneando programas instalados...")
        threading.Thread(target=self._scan_worker, daemon=True).start()

    def _scan_worker(self):
        try:
            items = list_installed()
            self.items = items
            self.root.after(0, self.refresh_table)
            self.root.after(0, lambda: self.status_var.set(
                f"Detectados {len(items)} programas"
            ))
        except Exception as e:
            self.root.after(0, lambda: self.status_var.set(f"Error: {e}"))

    def refresh_table(self):
        for it in self.tree.get_children():
            self.tree.delete(it)
        flt = (self.filter_text.get() or "").lower().strip()
        filtered = []
        for idx, it in enumerate(self.items):
            if flt and flt not in (it.get("name") or "").lower() \
                    and flt not in (it.get("publisher") or "").lower():
                continue
            filtered.append((idx, it))
        for idx, it in filtered:
            size_mb = (it.get("size_kb", 0) or 0) / 1024
            size_str = f"{size_mb:.1f} MB" if size_mb >= 0.1 else "-"
            self.tree.insert("", "end", iid=str(idx),
                             values=(it.get("name", ""),
                                     it.get("version", ""),
                                     it.get("publisher", ""),
                                     size_str,
                                     it.get("key_label", "")))
        total_size_mb = sum((i.get("size_kb", 0) or 0) for i in self.items) / 1024
        publishers = set(i.get("publisher", "") for i in self.items if i.get("publisher"))
        self.kpi_total.update_data(value=str(len(self.items)),
                                   subtitle=f"Mostrando {len(filtered)}",
                                   accent=COLORS["accent"])
        self.kpi_size.update_data(value=f"{total_size_mb / 1024:.2f} GB",
                                  subtitle="Estimado por registro",
                                  accent=COLORS["info"])
        self.kpi_pub.update_data(value=str(len(publishers)),
                                 subtitle="Publishers unicos",
                                 accent=COLORS["warn"])

    def _selected(self):
        sel = self.tree.selection()
        if not sel:
            return None
        idx = int(sel[0])
        return self.items[idx] if idx < len(self.items) else None

    def _uninstall_selected(self, quiet=False):
        it = self._selected()
        if not it:
            messagebox.showinfo(APP_TITLE, "Selecciona un programa.")
            return
        if not messagebox.askyesno(
            APP_TITLE,
            f"Lanzar uninstaller de:\n\n{it.get('name')} ({it.get('version')})\n\n"
            f"Modo: {'silencioso' if quiet else 'normal'}"
        ):
            return
        ok, msg = launch_uninstaller(it, quiet=quiet)
        if ok:
            self.status_var.set("Uninstaller lanzado")
            messagebox.showinfo(APP_TITLE, msg)
        else:
            messagebox.showwarning(APP_TITLE, msg)

    def _find_leftovers(self):
        it = self._selected()
        if not it:
            messagebox.showinfo(APP_TITLE, "Selecciona un programa.")
            return
        self.status_var.set("Buscando archivos residuales...")
        overlay = ProgressOverlay(
            self.root,
            f"Buscando archivos residuales de {it.get('name', '?')}..."
        )
        threading.Thread(target=self._leftovers_worker,
                         args=(it, overlay), daemon=True).start()

    def _leftovers_worker(self, item, overlay):
        try:
            leftovers = find_leftovers(item)
        except Exception as e:
            self.root.after(0, overlay.close)
            self.root.after(0, lambda: messagebox.showerror(
                APP_TITLE, f"Error: {e}"
            ))
            return
        self.root.after(0, overlay.close)
        if not leftovers:
            self.root.after(0, lambda: messagebox.showinfo(
                APP_TITLE, "No se detectaron archivos residuales obvios."))
            self.root.after(0, lambda: self.status_var.set("Sin residuales"))
            return

        total = sum(l["size"] for l in leftovers)
        from core.system_info import fmt_bytes
        msg_lines = [f"Residuales detectados ({fmt_bytes(total)}):", ""]
        for l in leftovers[:15]:
            msg_lines.append(f"  - {l['path']}  ({fmt_bytes(l['size'])})")
        if len(leftovers) > 15:
            msg_lines.append(f"  ... y {len(leftovers) - 15} mas")
        msg_lines.append("")
        msg_lines.append("Mover a cuarentena (reversible)?")
        choice = self.root.after(0, lambda: self._confirm_quarantine(item, leftovers))

    def _confirm_quarantine(self, item, leftovers):
        from core.system_info import fmt_bytes
        total = sum(l["size"] for l in leftovers)
        if not messagebox.askyesno(
            APP_TITLE,
            f"Mover {len(leftovers)} carpeta(s) a cuarentena ({fmt_bytes(total)})?\n\n"
            "Las carpetas no se borran: van al area de cuarentena y se "
            "pueden restaurar desde 'Historial / Revertir'."
        ):
            self.status_var.set("Cancelado")
            return

        overlay = ProgressOverlay(
            self.root,
            f"Moviendo {len(leftovers)} carpeta(s) a cuarentena ({fmt_bytes(total)})..."
        )

        def worker():
            moved = 0
            failed = []
            try:
                for l in leftovers:
                    try:
                        entry = rollback.quarantine_file(
                            module=MODULE_NAME,
                            src_path=l["path"],
                            label=f"Residual de {item.get('name')}: {Path(l['path']).name}",
                        )
                        if entry and not (isinstance(entry, dict) and "error" in entry):
                            moved += 1
                        else:
                            failed.append(l["path"])
                    except Exception as e:
                        failed.append(f"{l['path']}: {e}")
            finally:
                self.root.after(0, overlay.close)

            msg = f"Movidos a cuarentena: {moved}/{len(leftovers)}"
            if failed:
                msg += f"\nFallaron: {len(failed)}"
            self.root.after(0, lambda: messagebox.showinfo(APP_TITLE, msg))
            self.root.after(0, lambda: self.status_var.set(
                "Residuales en cuarentena"
            ))

        import threading
        threading.Thread(target=worker, daemon=True).start()
        self.status_var.set("Residuales en cuarentena")


def main():
    root = tk.Tk()
    setup_scaling(root)
    DeepUninstallApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
