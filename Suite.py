"""
PC Performance Suite - Lanzador principal.
KPIs en vivo + grid de herramientas + acceso al historial de rollback.
"""

import sys
import threading
import subprocess
import tkinter as tk
from pathlib import Path
from tkinter import ttk, messagebox

from core import style as style_mod
style_mod.apply_saved_theme()
from core.style import COLORS, FONTS, configure_ttk, color_for_value, COPYRIGHT
from core.ui_kit import KpiCard, ToolCard, SectionCard, StatusPill, round_rect
from core.scale import setup_scaling, s
from core.ctk_kit import init_ctk, Btn, Check
from core import system_info
from core import rollback
from core import config as cfg_mod
init_ctk()


SUITE_NAME = "Suite de Optimizacion PC"
SUITE_VERSION = "0.6.6"
TAGLINE = "Optimiza, limpia y revierte cualquier cambio con un clic."

BASE_DIR = Path(__file__).resolve().parent


TOOLS = [
    {
        "id": "battery",
        "icon": "\U0001F50B",  # battery
        "name": "Monitor de Bateria PRO",
        "version": "v3.0.0",
        "desc": "Salud de bateria, ciclos, tiempo restante, recomendaciones y optimizacion energetica reversible.",
        "script": "battery_monitor/battery_monitor_v3.py",
        "status": "ready",
    },
    {
        "id": "cleaner",
        "icon": "\U0001F9F9",  # broom
        "name": "Limpiador de Disco y Temporales",
        "version": "v1.0.0",
        "desc": "Limpia archivos temporales, cache de navegadores, papelera y registros. Cuarentena reversible antes de borrar.",
        "script": "cleaner/cleaner.py",
        "status": "ready",
    },
    {
        "id": "startup",
        "icon": "\U0001F680",  # rocket
        "name": "Analizador de Inicio",
        "version": "v1.0.0",
        "desc": "Detecta programas de inicio sospechosos o de poco uso. Habilita o deshabilita con un clic, todo reversible.",
        "script": "startup_analyzer/startup_analyzer.py",
        "status": "ready",
    },
    {
        "id": "security",
        "icon": "\U0001F6E1",  # shield
        "name": "Centro de Seguridad",
        "version": "v1.0.0",
        "desc": "Estado y control de Microsoft Defender + verificacion de archivos contra MalwareBazaar y VirusTotal.",
        "script": "security_center/security_center.py",
        "status": "ready",
    },
    {
        "id": "wifi_guard",
        "icon": "\U0001F4F6",  # antenna bars
        "name": "Guardian Wi-Fi",
        "version": "v1.0.0",
        "desc": "Bloquea redes Wi-Fi peligrosas para que tu PC nunca se conecte a ellas. Lista negra reversible + olvidar perfiles.",
        "script": "wifi_guard/wifi_guard.py",
        "status": "ready",
    },
    {
        "id": "uninstall",
        "icon": "\U0001F5D1",  # wastebasket
        "name": "Desinstalador Profundo",
        "version": "v0.1 (beta)",
        "desc": "Desinstalador profundo con deteccion de archivos residuales en registro, archivos y servicios.",
        "script": "deep_uninstall/deep_uninstall.py",
        "status": "ready",
    },
    {
        "id": "cpu",
        "icon": "\U0001F525",  # fire (CPU/temperatura)
        "name": "Monitor de CPU y Temperatura",
        "version": "v1.0.0",
        "desc": "Uso por nucleo, frecuencia, temperatura (si esta disponible) y procesos principales en tiempo real.",
        "script": "cpu_monitor/cpu_monitor.py",
        "status": "ready",
    },
    {
        "id": "conflicts",
        "icon": "\U000026A0",  # warning
        "name": "Detector de Conflictos",
        "version": "v1.0.0",
        "desc": "Detecta apps redundantes corriendo a la vez (2 antivirus, varios cloud sync, multiples launchers...) que ralentizan tu PC.",
        "script": "conflict_detector/conflict_detector.py",
        "status": "ready",
    },
    {
        "id": "memory",
        "icon": "\U0001F9E0",  # brain (memoria)
        "name": "Optimizador de Memoria",
        "version": "v1.0.0",
        "desc": "Libera memoria RAM con EmptyWorkingSet (seguro), lista procesos por consumo y permite terminar procesos.",
        "script": "memory_optimizer/memory_optimizer.py",
        "status": "ready",
    },
]


def launch_tool(tool):
    if tool["status"] != "ready":
        messagebox.showinfo(
            SUITE_NAME,
            f"{tool['name']} aun no esta implementado.\nProximamente."
        )
        return
    script = BASE_DIR / tool["script"]
    if not script.exists():
        messagebox.showerror(
            SUITE_NAME, f"No se encuentra:\n{script}"
        )
        return
    try:
        subprocess.Popen(
            [sys.executable, str(script)],
            cwd=str(BASE_DIR),
            creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
        )
    except Exception as e:
        messagebox.showerror(SUITE_NAME, f"Error al lanzar:\n{e}")


def open_rollback_window(parent):
    win = tk.Toplevel(parent)
    win.title("Historial de cambios y reversion")
    win.geometry("980x560")
    win.configure(bg=COLORS["bg"])

    head = tk.Frame(win, bg=COLORS["bg"])
    head.pack(fill="x", padx=18, pady=(16, 8))
    tk.Label(head, text="Historial de cambios reversibles",
             bg=COLORS["bg"], fg=COLORS["text"], font=FONTS["h1"]).pack(side="left")
    tk.Label(head, text="Selecciona un cambio y pulsa 'Revertir' para restaurarlo.",
             bg=COLORS["bg"], fg=COLORS["text_muted"],
             font=FONTS["label"]).pack(side="left", padx=(14, 0))

    body = tk.Frame(win, bg=COLORS["bg"])
    body.pack(fill="both", expand=True, padx=18, pady=(0, 16))

    cols = ("ts", "module", "kind", "label", "state")
    tree = ttk.Treeview(body, columns=cols, show="headings", height=18)
    headings = {
        "ts": "FECHA", "module": "MODULO", "kind": "TIPO",
        "label": "DESCRIPCION", "state": "ESTADO"
    }
    # (sin cambios en headings - ya estan en espanol)
    widths = {"ts": 150, "module": 110, "kind": 160, "label": 380, "state": 100}
    for c in cols:
        tree.heading(c, text=headings[c])
        tree.column(c, width=widths[c], anchor="w")
    tree.pack(side="left", fill="both", expand=True)

    sb = ttk.Scrollbar(body, orient="vertical", command=tree.yview)
    sb.pack(side="right", fill="y")
    tree.configure(yscrollcommand=sb.set)

    foot = tk.Frame(win, bg=COLORS["bg"])
    foot.pack(fill="x", padx=18, pady=(0, 16))

    stats_var = tk.StringVar(value="")
    tk.Label(foot, textvariable=stats_var, bg=COLORS["bg"],
             fg=COLORS["text_muted"], font=FONTS["label"]).pack(side="left")

    show_all = tk.BooleanVar(value=False)

    def reload():
        for it in tree.get_children():
            tree.delete(it)
        rows = rollback.list_entries(only_active=not show_all.get())
        for e in rows:
            state = "REVERTIDO" if e.get("reverted") else "ACTIVO"
            tree.insert("", "end", iid=e["id"],
                        values=(e["ts"], e["module"], e["kind"],
                                e["label"], state))
        st = rollback.stats()
        stats_var.set(
            f"Activos: {st['active_entries']}  /  "
            f"Revertidos: {st['reverted_entries']}  /  "
            f"Cuarentena: {system_info.fmt_bytes(st['quarantine_bytes'])}"
        )

    def revert_selected():
        sel = tree.selection()
        if not sel:
            messagebox.showinfo("Reversion", "Selecciona una entrada.")
            return
        eid = sel[0]
        if not messagebox.askyesno("Reversion",
                                   "Revertir el cambio seleccionado?"):
            return
        ok, msg = rollback.revert_entry(eid)
        if ok:
            messagebox.showinfo("Reversion", msg)
        else:
            messagebox.showwarning("Reversion", msg)
        reload()

    Btn(foot, text="Refrescar", command=reload,
        kind="ghost", width=110).pack(side="right", padx=(8, 0))
    Btn(foot, text="Revertir seleccion", command=revert_selected,
        kind="accent", width=180).pack(side="right", padx=(8, 0))
    Check(foot, text="Mostrar revertidos", variable=show_all,
          command=reload).pack(side="right", padx=(8, 0))

    reload()


class HeaderKPIs(tk.Frame):
    """Banda con 4 KPIs en vivo: CPU, RAM, Disco, Bateria."""
    def __init__(self, parent):
        super().__init__(parent, bg=COLORS["bg"])
        self.cards = {
            "cpu":  KpiCard(self, title="CPU", value="-",
                            subtitle="-", show_bar=True, bar_invert=True),
            "ram":  KpiCard(self, title="MEMORIA", value="-",
                            subtitle="-", show_bar=True, bar_invert=True),
            "disk": KpiCard(self, title="DISCO C:", value="-",
                            subtitle="-", show_bar=True, bar_invert=True),
            "batt": KpiCard(self, title="BATERIA", value="-",
                            subtitle="-", show_bar=True, bar_invert=False),
        }
        for i, c in enumerate(self.cards.values()):
            c.grid(row=0, column=i, sticky="nsew", padx=6, pady=4)
            self.columnconfigure(i, weight=1)

    def update_data(self, snap):
        cpu = snap["cpu"]
        ram = snap["ram"]
        disk = snap["disk"]
        batt = snap["battery"]

        cpu_color = color_for_value(cpu["percent"], (50, 80), invert=True)
        self.cards["cpu"].update_data(
            value=f"{cpu['percent']:.0f}%",
            subtitle=f"{cpu['cores']} cores / {cpu['threads']} hilos"
                     + (f"  -  {cpu['freq_mhz']:.0f} MHz" if cpu['freq_mhz'] else ""),
            accent=cpu_color,
            bar_value=cpu["percent"],
            bar_max=100,
        )

        ram_color = color_for_value(ram["percent"], (50, 80), invert=True)
        self.cards["ram"].update_data(
            value=f"{ram['percent']:.0f}%",
            subtitle=f"{ram['used_text']} / {ram['total_text']}",
            accent=ram_color,
            bar_value=ram["percent"],
            bar_max=100,
        )

        disk_color = color_for_value(disk["percent"], (50, 85), invert=True)
        self.cards["disk"].update_data(
            value=f"{disk['percent']:.0f}%",
            subtitle=f"Libre: {disk['free_text']} / {disk['total_text']}",
            accent=disk_color,
            bar_value=disk["percent"],
            bar_max=100,
        )

        if batt.get("has_battery"):
            pct = batt.get("percent") or 0
            color = color_for_value(pct, (20, 50), invert=False)
            sub = "Cargando" if batt.get("plugged") else "En bateria"
            self.cards["batt"].update_data(
                value=f"{pct:.0f}%",
                subtitle=sub,
                accent=color,
                bar_value=pct,
                bar_max=100,
            )
        else:
            self.cards["batt"].update_data(
                value="N/A", subtitle="Sin bateria",
                accent=COLORS["text_muted"], bar_value=0, bar_max=100,
            )


class SuiteApp:
    def __init__(self, root):
        self.root = root
        self.root.title(f"{SUITE_NAME} v{SUITE_VERSION}")
        self.root.geometry(f"{s(1180)}x{s(780)}")
        self.root.minsize(s(1040), s(700))
        self.root.configure(bg=COLORS["bg"])
        configure_ttk(self.root)

        self._refresh_job = None
        self._build()
        self._refresh_async()
        self._schedule_refresh()

    def _build(self):
        outer = tk.Frame(self.root, bg=COLORS["bg"])
        outer.pack(fill="both", expand=True, padx=24, pady=18)

        head = tk.Frame(outer, bg=COLORS["bg"])
        head.pack(fill="x")

        left = tk.Frame(head, bg=COLORS["bg"])
        left.pack(side="left")
        # Fila 1: titulo + version + OS en una sola linea
        top_row = tk.Frame(left, bg=COLORS["bg"])
        top_row.pack(anchor="w")
        tk.Label(top_row, text=SUITE_NAME, bg=COLORS["bg"],
                 fg=COLORS["text"], font=FONTS["title"]).pack(side="left")
        tk.Label(top_row,
                 text=f"  v{SUITE_VERSION}  -  {system_info.os_label()}",
                 bg=COLORS["bg"], fg=COLORS["text_muted"],
                 font=FONTS["label"]).pack(side="left", padx=(s(10), 0),
                                            pady=(s(12), 0))
        # Fila 2: tagline
        tk.Label(left, text=TAGLINE, bg=COLORS["bg"],
                 fg=COLORS["text_muted"], font=FONTS["body"]).pack(
                     anchor="w", pady=(s(2), 0))

        right = tk.Frame(head, bg=COLORS["bg"])
        right.pack(side="right")
        Btn(right, text="Historial / Revertir",
            command=lambda: open_rollback_window(self.root),
            kind="ghost", width=170).pack(side="right", padx=(8, 0))
        Btn(right, text="Actualizar",
            command=self._refresh_async,
            kind="accent", width=110).pack(side="right")
        Btn(right, text="Tamano UI",
            command=self._open_ui_scale_dialog,
            kind="ghost", width=110).pack(side="right", padx=(0, 8))
        theme_btn_text = ("Tema: oscuro" if style_mod.THEME_NAME == "dark"
                          else "Tema: claro")
        Btn(right, text=theme_btn_text,
            command=self._toggle_theme,
            kind="ghost", width=130).pack(side="right", padx=(0, 8))

        self.kpis = HeaderKPIs(outer)
        self.kpis.pack(fill="x", pady=(18, 8))

        rb_stats = rollback.stats()
        if rb_stats["active_entries"] > 0:
            banner = tk.Frame(outer, bg=COLORS["info_bg"],
                              highlightbackground=COLORS["info"],
                              highlightthickness=1)
            banner.pack(fill="x", pady=(0, 8))
            tk.Label(
                banner,
                text=(f"  {rb_stats['active_entries']} cambio(s) reversible(s) en "
                      f"historial. Cuarentena: "
                      f"{system_info.fmt_bytes(rb_stats['quarantine_bytes'])}"),
                bg=COLORS["info_bg"], fg=COLORS["info"],
                font=FONTS["label_b"]
            ).pack(side="left", padx=12, pady=8)
            Btn(banner, text="Ver historial",
                command=lambda: open_rollback_window(self.root),
                kind="ghost", width=130).pack(side="right", padx=8, pady=6)

        section_label = tk.Label(outer, text="HERRAMIENTAS",
                                 bg=COLORS["bg"], fg=COLORS["text_muted"],
                                 font=FONTS["small"])
        section_label.pack(anchor="w", pady=(14, 6))

        grid = tk.Frame(outer, bg=COLORS["bg"])
        grid.pack(fill="both", expand=True)
        cols = 3
        for c in range(cols):
            grid.columnconfigure(c, weight=1)
        for i, tool in enumerate(TOOLS):
            r, c = divmod(i, cols)
            card = ToolCard(grid,
                            name=tool["name"], version=tool["version"],
                            desc=tool["desc"], status=tool["status"],
                            icon=tool.get("icon", ""),
                            on_open=lambda t=tool: launch_tool(t))
            card.grid(row=r, column=c, sticky="nsew", padx=6, pady=6)
            grid.rowconfigure(r, weight=1)

        foot = tk.Frame(self.root, bg=COLORS["bg"])
        foot.pack(fill="x", padx=24, pady=(0, 14))
        self.status_var = tk.StringVar(value="Listo")
        tk.Label(foot, textvariable=self.status_var,
                 bg=COLORS["bg"], fg=COLORS["text_muted"],
                 font=FONTS["small"]).pack(side="left")
        tk.Label(foot,
                 text=f"{SUITE_NAME} v{SUITE_VERSION}  -  {COPYRIGHT}",
                 bg=COLORS["bg"], fg=COLORS["text_soft"],
                 font=FONTS["small"]).pack(side="right")

    def _open_ui_scale_dialog(self):
        current = float(cfg_mod.get("ui_scale", 1.0) or 1.0)
        win = tk.Toplevel(self.root)
        win.title("Tamano de UI")
        win.configure(bg=COLORS["bg"])
        win.transient(self.root)
        win.geometry(f"{s(440)}x{s(280)}")

        tk.Label(win, text="Tamano de la interfaz",
                 bg=COLORS["bg"], fg=COLORS["text"],
                 font=FONTS["title"]).pack(pady=(s(18), s(4)))
        tk.Label(win,
                 text=("Si la app se ve muy grande o muy pequena, ajusta\n"
                       "este factor. Se multiplica sobre el DPI del sistema.\n"
                       "Cambio aplica al reiniciar la app."),
                 bg=COLORS["bg"], fg=COLORS["text_muted"],
                 font=FONTS["body"], justify="center").pack(pady=(0, s(14)))

        choices = [
            ("75 %  (compacto)", 0.75),
            ("90 %  (un poco menor)", 0.90),
            ("100 % (normal, default)", 1.00),
            ("110 % (un poco mayor)", 1.10),
            ("125 % (grande)", 1.25),
        ]
        var = tk.DoubleVar(value=current)

        for label, val in choices:
            tk.Radiobutton(
                win, text=f"  {label}", value=val, variable=var,
                bg=COLORS["bg"], fg=COLORS["text"],
                selectcolor=COLORS["bg_card"],
                activebackground=COLORS["bg"],
                activeforeground=COLORS["text"],
                font=FONTS["body"], anchor="w",
            ).pack(fill="x", padx=s(40), pady=s(2))

        btns = tk.Frame(win, bg=COLORS["bg"])
        btns.pack(pady=s(14))

        def apply_and_close():
            cfg_mod.set_value("ui_scale", float(var.get()))
            from tkinter import messagebox
            if messagebox.askyesno(
                SUITE_NAME,
                f"Tamano guardado: {int(var.get()*100)}%.\n\n"
                "Reiniciar la suite ahora para aplicarlo?"
            ):
                python = sys.executable
                subprocess.Popen([python, str(BASE_DIR / "Suite.py")],
                                 cwd=str(BASE_DIR))
                self.root.destroy()
            else:
                win.destroy()

        Btn(btns, text="Guardar y reiniciar",
            command=apply_and_close,
            kind="accent", width=180).pack(side="left", padx=4)
        Btn(btns, text="Cancelar",
            command=win.destroy,
            kind="ghost", width=120).pack(side="left", padx=4)

    def _toggle_theme(self):
        new = "light" if style_mod.THEME_NAME == "dark" else "dark"
        cfg_mod.set_value("theme", new)
        if messagebox.askyesno(
            SUITE_NAME,
            f"Tema guardado: {new}.\n\nReiniciar la suite ahora para aplicarlo?"
        ):
            python = sys.executable
            subprocess.Popen([python, str(BASE_DIR / "Suite.py")],
                             cwd=str(BASE_DIR))
            self.root.destroy()

    def _refresh_async(self):
        threading.Thread(target=self._refresh_worker, daemon=True).start()

    def _refresh_worker(self):
        try:
            snap = system_info.all_snapshots()
            self.root.after(0, lambda: self.kpis.update_data(snap))
            self.root.after(0, lambda: self.status_var.set(
                f"Metricas actualizadas"
            ))
        except Exception as e:
            self.root.after(0, lambda: self.status_var.set(f"Error: {e}"))

    def _schedule_refresh(self):
        self._refresh_job = self.root.after(3000, self._tick)

    def _tick(self):
        self._refresh_async()
        self._refresh_job = self.root.after(3000, self._tick)


def main():
    root = tk.Tk()
    setup_scaling(root)
    SuiteApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
