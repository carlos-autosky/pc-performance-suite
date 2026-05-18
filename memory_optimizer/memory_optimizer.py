"""
Optimizador de Memoria - Suite de Optimizacion PC.

- Muestra el uso actual de RAM (total, usada, libre, swap)
- Lista los procesos que mas RAM consumen, refrescando en vivo
- Permite "liberar memoria" usando EmptyWorkingSet (psapi):
  el OS marca las paginas del proceso como liberables y las
  reasigna a otros si las necesita. Es seguro (el proceso sigue
  corriendo) y reversible naturalmente: el OS recarga lo que
  el proceso vuelva a usar.
- Permite terminar procesos seleccionados con confirmacion.
"""

import os
import sys
import ctypes
import threading
import tkinter as tk
from pathlib import Path
from datetime import datetime
from tkinter import ttk, messagebox

import psutil

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core import style as _style_mod
_style_mod.apply_saved_theme()
from core.style import COLORS, FONTS, configure_ttk, color_for_value, COPYRIGHT
from core.ui_kit import KpiCard, SectionCard, StatusPill
from core.ctk_kit import init_ctk, Btn, Check, Entry
from core.scale import setup_scaling, s
from core.progress import ProgressOverlay
from core import system_info
from core import rollback
init_ctk()


APP_TITLE = "Optimizador de Memoria"
APP_VERSION = "1.0.0"
SUITE_NAME = "Suite de Optimizacion PC"
MODULE_NAME = "memory_optimizer"


# ---------- API Windows: EmptyWorkingSet ----------

if sys.platform == "win32":
    from ctypes import wintypes
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _psapi = ctypes.WinDLL("psapi", use_last_error=True)

    _PROCESS_SET_QUOTA = 0x0100
    _PROCESS_QUERY_INFORMATION = 0x0400
    _PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

    _kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    _kernel32.OpenProcess.restype = wintypes.HANDLE
    _kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    _kernel32.CloseHandle.restype = wintypes.BOOL
    _psapi.EmptyWorkingSet.argtypes = [wintypes.HANDLE]
    _psapi.EmptyWorkingSet.restype = wintypes.BOOL
else:
    _kernel32 = _psapi = None


def empty_working_set(pid):
    """Libera el working set de un proceso. True si OK."""
    if _psapi is None:
        return False
    h = _kernel32.OpenProcess(
        _PROCESS_SET_QUOTA | _PROCESS_QUERY_INFORMATION, False, int(pid)
    )
    if not h:
        return False
    try:
        return bool(_psapi.EmptyWorkingSet(h))
    finally:
        _kernel32.CloseHandle(h)


def fmt_bytes(n):
    return system_info.fmt_bytes(n)


# ---------- Recoleccion ----------

def list_processes(top_n=30):
    """
    Devuelve top procesos por uso de RAM (working set).
    Cada item: pid, name, rss_bytes, rss_pct, cpu_pct, user, exe
    """
    rows = []
    # primera lectura para cebar cpu_percent
    for p in psutil.process_iter(["pid"]):
        try:
            p.cpu_percent(None)
        except Exception:
            pass
    # tras un instante, segunda lectura con datos reales
    import time
    time.sleep(0.4)

    total_ram = psutil.virtual_memory().total or 1
    for p in psutil.process_iter(
        ["pid", "name", "username", "memory_info", "cpu_percent", "exe"]
    ):
        try:
            info = p.info
            rss = (info.get("memory_info").rss
                   if info.get("memory_info") else 0)
            rows.append({
                "pid": info.get("pid"),
                "name": info.get("name") or "",
                "rss": rss,
                "rss_pct": (rss / total_ram) * 100 if total_ram else 0,
                "cpu": round(info.get("cpu_percent") or 0.0, 1),
                "user": (info.get("username") or "").split("\\")[-1],
                "exe": info.get("exe") or "",
            })
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    rows.sort(key=lambda r: r["rss"], reverse=True)
    return rows[:top_n]


def liberate_all(skip_critical=True):
    """
    Aplica EmptyWorkingSet a todos los procesos accesibles.
    Devuelve (ok_count, fail_count, total_bytes_freed_estimated).
    """
    critical_names = {
        "system idle process", "system", "registry", "wininit.exe",
        "csrss.exe", "smss.exe", "services.exe", "lsass.exe",
        "winlogon.exe", "fontdrvhost.exe", "memcompression",
    }
    before_total = 0
    after_total = 0
    ok = 0
    fail = 0
    snapshot = []
    for p in psutil.process_iter(["pid", "name", "memory_info"]):
        try:
            name = (p.info.get("name") or "").lower()
            if skip_critical and name in critical_names:
                continue
            rss_before = p.info.get("memory_info").rss if p.info.get("memory_info") else 0
            snapshot.append((p.info["pid"], name, rss_before))
            before_total += rss_before
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    for pid, name, _rss in snapshot:
        if empty_working_set(pid):
            ok += 1
        else:
            fail += 1

    # medir despues (instantaneo - el OS ya descargo working set)
    import time
    time.sleep(0.5)
    for pid, _name, _rss in snapshot:
        try:
            after_total += psutil.Process(pid).memory_info().rss
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

    freed = max(0, before_total - after_total)
    return ok, fail, freed


# ---------- UI ----------

class MemoryApp:
    def __init__(self, root):
        self.root = root
        self.root.title(f"{APP_TITLE} - {SUITE_NAME}")
        self.root.geometry(f"{s(1240)}x{s(780)}")
        self.root.minsize(s(1080), s(700))
        self.root.configure(bg=COLORS["bg"])
        configure_ttk(self.root)

        self.processes = []
        self.auto_refresh = tk.BooleanVar(value=True)
        self._refresh_job = None
        self.build_ui()
        self.refresh_async()
        self._schedule_refresh()

    def build_ui(self):
        head = tk.Frame(self.root, bg=COLORS["bg"])
        head.pack(fill="x", padx=20, pady=(16, 6))
        left = tk.Frame(head, bg=COLORS["bg"])
        left.pack(side="left")
        tk.Label(left, text=APP_TITLE, bg=COLORS["bg"],
                 fg=COLORS["text"], font=FONTS["title"]).pack(anchor="w")
        tk.Label(left,
                 text="Liberar memoria RAM y ver los procesos que mas consumen.",
                 bg=COLORS["bg"], fg=COLORS["text_muted"],
                 font=FONTS["body"]).pack(anchor="w", pady=(4, 0))

        right = tk.Frame(head, bg=COLORS["bg"])
        right.pack(side="right")
        Btn(right, text="Actualizar",
            command=self.refresh_async,
            kind="accent", width=120).pack(side="right")
        Check(right, text="Auto-actualizar",
              variable=self.auto_refresh,
              command=self._on_toggle_refresh).pack(side="right", padx=(0, 12))

        kpi = tk.Frame(self.root, bg=COLORS["bg"])
        kpi.pack(fill="x", padx=20, pady=(10, 8))
        self.kpi_used = KpiCard(kpi, title="MEMORIA USADA",
                                value="-", subtitle="-",
                                accent=COLORS["warn"],
                                show_bar=True, bar_invert=True)
        self.kpi_free = KpiCard(kpi, title="MEMORIA LIBRE",
                                value="-", subtitle="-",
                                accent=COLORS["ok"], show_bar=False)
        self.kpi_swap = KpiCard(kpi, title="ARCHIVO DE PAGINACION",
                                value="-", subtitle="-",
                                accent=COLORS["info"],
                                show_bar=True, bar_invert=True)
        self.kpi_top = KpiCard(kpi, title="PROCESO MAYOR",
                               value="-", subtitle="-",
                               accent=COLORS["accent"], show_bar=False)
        for i, c in enumerate([self.kpi_used, self.kpi_free,
                               self.kpi_swap, self.kpi_top]):
            c.grid(row=0, column=i, sticky="nsew", padx=6, pady=4)
            kpi.columnconfigure(i, weight=1)

        # Footer fijo abajo
        actions = tk.Frame(self.root, bg=COLORS["bg"], height=64)
        actions.pack(side="bottom", fill="x", padx=20, pady=(8, 14))
        actions.pack_propagate(False)
        Btn(actions, text="EJECUTAR: liberar memoria de todos los procesos",
            command=self._liberate_all_async,
            kind="accent", width=380, height=42).pack(side="left", pady=8)
        Btn(actions, text="EJECUTAR: terminar proceso seleccionado",
            command=self._kill_selected,
            kind="danger", width=320, height=42).pack(side="left", padx=8, pady=8)
        self.status_var = tk.StringVar(value="Listo")
        tk.Label(actions, textvariable=self.status_var,
                 bg=COLORS["bg"], fg=COLORS["text_muted"],
                 font=FONTS["label"]).pack(side="right")
        tk.Label(actions, text=f"{APP_TITLE} v{APP_VERSION}  -  {COPYRIGHT}",
                 bg=COLORS["bg"], fg=COLORS["text_soft"],
                 font=FONTS["small"]).pack(side="right", padx=(0, 14))

        # Tabla de procesos
        listcard = SectionCard(self.root,
                               title="Procesos por uso de memoria")
        listcard.pack(fill="both", expand=True, padx=20, pady=(4, 6))
        body = listcard.body()

        cols = ("pid", "name", "rss", "rss_pct", "cpu", "user", "exe")
        self.tree = ttk.Treeview(body, columns=cols,
                                 show="headings", height=18)
        headings = {"pid": "PID", "name": "PROCESO",
                    "rss": "MEMORIA", "rss_pct": "% RAM",
                    "cpu": "% CPU", "user": "USUARIO",
                    "exe": "RUTA"}
        widths = {"pid": 70, "name": 220, "rss": 110, "rss_pct": 80,
                  "cpu": 80, "user": 130, "exe": 380}
        anchors = {"pid": "e", "name": "w", "rss": "e", "rss_pct": "e",
                   "cpu": "e", "user": "w", "exe": "w"}
        for c in cols:
            self.tree.heading(c, text=headings[c])
            self.tree.column(c, width=widths[c], anchor=anchors[c])
        self.tree.pack(side="left", fill="both", expand=True)
        sb = ttk.Scrollbar(body, orient="vertical", command=self.tree.yview)
        sb.pack(side="right", fill="y")
        self.tree.configure(yscrollcommand=sb.set)

    def _on_toggle_refresh(self):
        if self.auto_refresh.get():
            self._schedule_refresh()
            self.status_var.set("Auto-actualizacion activada (cada 3 seg)")
        else:
            if self._refresh_job:
                self.root.after_cancel(self._refresh_job)
                self._refresh_job = None
            self.status_var.set("Auto-actualizacion desactivada")

    def _schedule_refresh(self):
        if not self.auto_refresh.get():
            return
        self._refresh_job = self.root.after(3000, self._tick)

    def _tick(self):
        if self.auto_refresh.get():
            self.refresh_async()
            self._schedule_refresh()

    def refresh_async(self):
        threading.Thread(target=self._refresh_worker, daemon=True).start()

    def _refresh_worker(self):
        try:
            ram = system_info.ram_snapshot()
            try:
                swap = psutil.swap_memory()
                swap_data = {
                    "percent": swap.percent,
                    "used": swap.used,
                    "total": swap.total,
                }
            except Exception:
                swap_data = {"percent": 0, "used": 0, "total": 0}

            procs = list_processes(top_n=40)
            self.root.after(0, self._populate, ram, swap_data, procs)
        except Exception as e:
            self.root.after(0, lambda: self.status_var.set(f"Error: {e}"))

    def _populate(self, ram, swap_data, procs):
        used_color = color_for_value(ram["percent"], (50, 80), invert=True)
        self.kpi_used.update_data(
            value=f"{ram['percent']:.0f}%",
            subtitle=f"{ram['used_text']} / {ram['total_text']}",
            accent=used_color,
            bar_value=ram["percent"], bar_max=100,
        )
        free_pct = 100 - ram["percent"]
        self.kpi_free.update_data(
            value=fmt_bytes(ram["available"]),
            subtitle=f"{free_pct:.0f}% disponible",
            accent=COLORS["ok"] if free_pct > 25 else COLORS["warn"],
        )
        if swap_data["total"] > 0:
            swap_color = color_for_value(swap_data["percent"], (40, 70), invert=True)
            self.kpi_swap.update_data(
                value=f"{swap_data['percent']:.0f}%",
                subtitle=f"{fmt_bytes(swap_data['used'])} / {fmt_bytes(swap_data['total'])}",
                accent=swap_color,
                bar_value=swap_data["percent"], bar_max=100,
            )
        else:
            self.kpi_swap.update_data(
                value="N/D", subtitle="Sin pagefile",
                accent=COLORS["text_muted"],
            )

        if procs:
            top = procs[0]
            self.kpi_top.update_data(
                value=fmt_bytes(top["rss"]),
                subtitle=f"{top['name']} (PID {top['pid']})",
                accent=COLORS["accent"],
            )
        else:
            self.kpi_top.update_data(
                value="-", subtitle="-",
                accent=COLORS["text_muted"],
            )

        for it in self.tree.get_children():
            self.tree.delete(it)
        for p in procs:
            self.tree.insert(
                "", "end", iid=str(p["pid"]),
                values=(
                    p["pid"], p["name"],
                    fmt_bytes(p["rss"]),
                    f"{p['rss_pct']:.1f}%",
                    f"{p['cpu']:.1f}",
                    p["user"],
                    p["exe"],
                )
            )
        self.processes = procs
        self.status_var.set(
            f"{len(procs)} procesos. "
            f"Actualizado {datetime.now():%H:%M:%S}"
        )

    def _liberate_all_async(self):
        if not messagebox.askyesno(
            APP_TITLE,
            "Liberar memoria de TODOS los procesos accesibles?\n\n"
            "Esto marca las paginas como liberables. El OS recargara "
            "lo que cada proceso necesite cuando vuelva a usarlas.\n\n"
            "Es seguro y los programas siguen corriendo. Procesos del "
            "sistema criticos (csrss, lsass, etc) se omiten."
        ):
            return
        self.status_var.set("Liberando memoria...")
        overlay = ProgressOverlay(
            self.root,
            "Liberando memoria de todos los procesos accesibles..."
        )
        threading.Thread(target=self._liberate_worker,
                         args=(overlay,), daemon=True).start()

    def _liberate_worker(self, overlay):
        try:
            ok, fail, freed = liberate_all(skip_critical=True)
        finally:
            self.root.after(0, overlay.close)
        msg = (
            f"Memoria liberada: {fmt_bytes(freed)}\n\n"
            f"Procesos procesados: {ok}\n"
            f"Procesos sin permiso (omitidos): {fail}\n\n"
            "El OS recargara las paginas necesarias automaticamente."
        )
        self.root.after(0, lambda: messagebox.showinfo(APP_TITLE, msg))
        self.root.after(0, lambda: self.status_var.set(
            f"Liberados {fmt_bytes(freed)} ({ok} procesos)"
        ))
        self.root.after(0, self.refresh_async)

    def _kill_selected(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo(APP_TITLE, "Selecciona un proceso de la tabla.")
            return
        try:
            pid = int(sel[0])
        except ValueError:
            return
        proc = next((p for p in self.processes if p["pid"] == pid), None)
        if not proc:
            return
        if not messagebox.askyesno(
            APP_TITLE,
            f"Terminar proceso?\n\n"
            f"PID: {pid}\n"
            f"Nombre: {proc['name']}\n"
            f"Memoria: {fmt_bytes(proc['rss'])}\n\n"
            "ATENCION: Esta accion NO es reversible. Si terminas un\n"
            "proceso del sistema o uno con datos no guardados, puede\n"
            "haber perdida de informacion."
        ):
            return
        try:
            psutil.Process(pid).terminate()
            self.status_var.set(f"Proceso {pid} terminado")
            self.root.after(800, self.refresh_async)
        except psutil.AccessDenied:
            messagebox.showwarning(
                APP_TITLE,
                "Acceso denegado. Reinicia como administrador para "
                "poder terminar procesos del sistema."
            )
        except psutil.NoSuchProcess:
            messagebox.showwarning(APP_TITLE, "El proceso ya no existe.")
        except Exception as e:
            messagebox.showerror(APP_TITLE, f"Error: {e}")


def main():
    root = tk.Tk()
    setup_scaling(root)
    MemoryApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
