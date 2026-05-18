"""
Monitor de CPU y Temperatura - Suite de Optimizacion PC.

- Uso global y por nucleo (grafica en vivo)
- Frecuencia actual / minima / maxima
- Cantidad de nucleos fisicos y logicos
- Temperatura via WMI MSAcpi_ThermalZoneTemperature (si disponible)
- Top procesos por consumo de CPU
- Auto-actualizacion cada 1.5 seg
"""

import os
import sys
import json
import time
import subprocess
import threading
import tkinter as tk
from collections import deque
from pathlib import Path
from datetime import datetime
from tkinter import ttk, messagebox

import psutil

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core import style as _style_mod
_style_mod.apply_saved_theme()
from core.style import COLORS, FONTS, configure_ttk, color_for_value, COPYRIGHT
from core.ui_kit import KpiCard, SectionCard, StatusPill
from core.ctk_kit import init_ctk, Btn, Check
from core.scale import setup_scaling, s
from core import system_info
init_ctk()


APP_TITLE = "Monitor de CPU y Temperatura"
APP_VERSION = "1.0.0"
SUITE_NAME = "Suite de Optimizacion PC"
MODULE_NAME = "cpu_monitor"


# ---------- Recoleccion ----------

_CPU_PRIMED = False


def _prime_cpu():
    global _CPU_PRIMED
    if not _CPU_PRIMED:
        psutil.cpu_percent(interval=None, percpu=True)
        _CPU_PRIMED = True


def cpu_snapshot():
    _prime_cpu()
    pct = psutil.cpu_percent(interval=None)
    per_core = psutil.cpu_percent(interval=None, percpu=True)
    freq = psutil.cpu_freq()
    return {
        "percent": round(pct, 1),
        "per_core": [round(p, 1) for p in per_core],
        "freq_current": round(freq.current, 0) if freq else None,
        "freq_min": round(freq.min, 0) if freq and freq.min else None,
        "freq_max": round(freq.max, 0) if freq and freq.max else None,
        "physical": psutil.cpu_count(logical=False) or 0,
        "logical": psutil.cpu_count(logical=True) or 0,
    }


def temperature_celsius():
    """
    Devuelve la temperatura en grados C. None si no esta disponible.
    Usa WMI MSAcpi_ThermalZoneTemperature (no todos los equipos lo exponen).
    """
    if sys.platform != "win32":
        return None
    cmd = (
        'powershell -NoProfile -Command "'
        'Get-CimInstance -Namespace root/wmi '
        '-ClassName MSAcpi_ThermalZoneTemperature '
        '-ErrorAction SilentlyContinue | '
        'Select-Object CurrentTemperature | ConvertTo-Json -Compress"'
    )
    try:
        cp = subprocess.run(cmd, capture_output=True, text=True,
                            shell=True, timeout=5,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        out = (cp.stdout or "").strip()
        if not out:
            return None
        data = json.loads(out)
        if isinstance(data, list):
            data = data[0] if data else {}
        raw = data.get("CurrentTemperature")
        if raw is None:
            return None
        return round((raw - 2732) / 10.0, 1)
    except Exception:
        return None


def list_processes_by_cpu(top_n=25):
    rows = []
    for p in psutil.process_iter(["pid"]):
        try:
            p.cpu_percent(None)
        except Exception:
            pass
    time.sleep(0.4)
    for p in psutil.process_iter(
        ["pid", "name", "username", "cpu_percent", "memory_percent"]
    ):
        try:
            info = p.info
            rows.append({
                "pid": info.get("pid"),
                "name": info.get("name") or "",
                "cpu": round(info.get("cpu_percent") or 0.0, 1),
                "mem": round(info.get("memory_percent") or 0.0, 1),
                "user": (info.get("username") or "").split("\\")[-1],
            })
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    rows.sort(key=lambda r: (r["cpu"], r["mem"]), reverse=True)
    return rows[:top_n]


# ---------- UI ----------

class CpuApp:
    HISTORY_LEN = 60  # ultimos 60 puntos de historia

    def __init__(self, root):
        self.root = root
        self.root.title(f"{APP_TITLE} - {SUITE_NAME}")
        self.root.geometry(f"{s(1240)}x{s(780)}")
        self.root.minsize(s(1080), s(700))
        self.root.configure(bg=COLORS["bg"])
        configure_ttk(self.root)

        self.history = deque(maxlen=self.HISTORY_LEN)
        self.per_core_history = []
        self.auto_refresh = tk.BooleanVar(value=True)
        self._refresh_job = None
        self.last_temp = None

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
                 text="Uso por nucleo, frecuencia, temperatura y procesos en tiempo real.",
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
        self.kpi_cpu = KpiCard(kpi, title="USO DE CPU",
                               value="-", subtitle="-",
                               accent=COLORS["warn"],
                               show_bar=True, bar_invert=True)
        self.kpi_freq = KpiCard(kpi, title="FRECUENCIA",
                                value="-", subtitle="-",
                                accent=COLORS["info"], show_bar=False)
        self.kpi_cores = KpiCard(kpi, title="NUCLEOS",
                                 value="-", subtitle="-",
                                 accent=COLORS["accent"], show_bar=False)
        self.kpi_temp = KpiCard(kpi, title="TEMPERATURA",
                                value="-", subtitle="-",
                                accent=COLORS["info"], show_bar=False)
        for i, c in enumerate([self.kpi_cpu, self.kpi_freq,
                               self.kpi_cores, self.kpi_temp]):
            c.grid(row=0, column=i, sticky="nsew", padx=6, pady=4)
            kpi.columnconfigure(i, weight=1)

        # Footer abajo
        actions = tk.Frame(self.root, bg=COLORS["bg"], height=64)
        actions.pack(side="bottom", fill="x", padx=20, pady=(8, 14))
        actions.pack_propagate(False)
        Btn(actions, text="EJECUTAR: terminar proceso seleccionado",
            command=self._kill_selected,
            kind="danger", width=320, height=42).pack(side="left", pady=8)
        self.status_var = tk.StringVar(value="Listo")
        tk.Label(actions, textvariable=self.status_var,
                 bg=COLORS["bg"], fg=COLORS["text_muted"],
                 font=FONTS["label"]).pack(side="right")
        tk.Label(actions, text=f"{APP_TITLE} v{APP_VERSION}  -  {COPYRIGHT}",
                 bg=COLORS["bg"], fg=COLORS["text_soft"],
                 font=FONTS["small"]).pack(side="right", padx=(0, 14))

        # Grafica de CPU global (historica)
        chart_card = SectionCard(self.root,
                                 title="Uso de CPU - ultimos 60 puntos")
        chart_card.pack(fill="x", padx=20, pady=(4, 4))
        self.chart_canvas = tk.Canvas(chart_card.body(),
                                      bg=COLORS["bg_card"],
                                      height=160, highlightthickness=0)
        self.chart_canvas.pack(fill="both", expand=True)
        self.chart_canvas.bind("<Configure>",
                                lambda _e: self._draw_chart())

        # Bara de uso por nucleo (visualmente parecida al Task Manager)
        cores_card = SectionCard(self.root,
                                 title="Uso por nucleo")
        cores_card.pack(fill="x", padx=20, pady=(4, 4))
        self.cores_canvas = tk.Canvas(cores_card.body(),
                                       bg=COLORS["bg_card"],
                                       height=120, highlightthickness=0)
        self.cores_canvas.pack(fill="both", expand=True)
        self.cores_canvas.bind("<Configure>",
                                lambda _e: self._draw_cores())

        # Tabla top procesos
        proc_card = SectionCard(self.root,
                                title="Procesos por uso de CPU")
        proc_card.pack(fill="both", expand=True, padx=20, pady=(4, 6))
        body = proc_card.body()
        cols = ("pid", "name", "cpu", "mem", "user")
        self.tree = ttk.Treeview(body, columns=cols,
                                 show="headings", height=10)
        headings = {"pid": "PID", "name": "PROCESO",
                    "cpu": "% CPU", "mem": "% MEMORIA",
                    "user": "USUARIO"}
        widths = {"pid": 70, "name": 360, "cpu": 100,
                  "mem": 110, "user": 200}
        anchors = {"pid": "e", "name": "w", "cpu": "e",
                   "mem": "e", "user": "w"}
        for c in cols:
            self.tree.heading(c, text=headings[c])
            self.tree.column(c, width=widths[c], anchor=anchors[c])
        self.tree.pack(side="left", fill="both", expand=True)
        sb = ttk.Scrollbar(body, orient="vertical", command=self.tree.yview)
        sb.pack(side="right", fill="y")
        self.tree.configure(yscrollcommand=sb.set)

    # ---------- Refresh loop ----------

    def _on_toggle_refresh(self):
        if self.auto_refresh.get():
            self._schedule_refresh()
            self.status_var.set("Auto-actualizacion activada (cada 1.5 seg)")
        else:
            if self._refresh_job:
                self.root.after_cancel(self._refresh_job)
                self._refresh_job = None
            self.status_var.set("Auto-actualizacion desactivada")

    def _schedule_refresh(self):
        if not self.auto_refresh.get():
            return
        self._refresh_job = self.root.after(1500, self._tick)

    def _tick(self):
        if self.auto_refresh.get():
            self.refresh_async()
            self._schedule_refresh()

    def refresh_async(self):
        threading.Thread(target=self._refresh_worker, daemon=True).start()

    def _refresh_worker(self):
        try:
            cpu = cpu_snapshot()
            # Temperatura solo cada 5 ticks (es la lectura mas lenta)
            if not hasattr(self, "_temp_counter"):
                self._temp_counter = 0
            self._temp_counter += 1
            if self._temp_counter % 5 == 1 or self.last_temp is None:
                self.last_temp = temperature_celsius()
            procs = list_processes_by_cpu(top_n=25)
            self.root.after(0, self._populate, cpu, self.last_temp, procs)
        except Exception as e:
            self.root.after(0, lambda: self.status_var.set(f"Error: {e}"))

    def _populate(self, cpu, temp, procs):
        cpu_color = color_for_value(cpu["percent"], (50, 80), invert=True)
        self.kpi_cpu.update_data(
            value=f"{cpu['percent']:.0f}%",
            subtitle=f"Promedio global",
            accent=cpu_color,
            bar_value=cpu["percent"], bar_max=100,
        )

        freq = cpu["freq_current"]
        if freq:
            sub = "MHz"
            if cpu["freq_max"]:
                sub = f"max {cpu['freq_max']:.0f} MHz"
            self.kpi_freq.update_data(
                value=f"{freq:.0f}",
                subtitle=sub,
                accent=COLORS["info"],
            )
        else:
            self.kpi_freq.update_data(
                value="N/D", subtitle="MHz",
                accent=COLORS["text_muted"],
            )

        self.kpi_cores.update_data(
            value=f"{cpu['logical']}",
            subtitle=f"{cpu['physical']} fisicos / {cpu['logical']} logicos",
            accent=COLORS["accent"],
        )

        if temp is not None:
            tcolor = color_for_value(temp, (60, 80), invert=True)
            self.kpi_temp.update_data(
                value=f"{temp:.0f}°C",
                subtitle="WMI ThermalZone",
                accent=tcolor,
            )
        else:
            self.kpi_temp.update_data(
                value="N/D",
                subtitle="Sensor no expuesto por WMI",
                accent=COLORS["text_muted"],
            )

        # Historico
        self.history.append(cpu["percent"])
        self.per_core_history = cpu["per_core"]
        self._draw_chart()
        self._draw_cores()

        # Tabla
        for it in self.tree.get_children():
            self.tree.delete(it)
        for p in procs:
            self.tree.insert("", "end", iid=str(p["pid"]),
                             values=(p["pid"], p["name"],
                                     f"{p['cpu']:.1f}",
                                     f"{p['mem']:.1f}",
                                     p["user"]))

        self.status_var.set(
            f"Actualizado {datetime.now():%H:%M:%S}"
        )

    # ---------- Charts ----------

    def _draw_chart(self):
        c = self.chart_canvas
        c.delete("all")
        w = c.winfo_width()
        h = c.winfo_height()
        if w < 50 or h < 50:
            return

        ml, mr, mt, mb = 50, 14, 10, 22
        pw = w - ml - mr
        ph = h - mt - mb

        # Grid
        for i in range(0, 5):
            y = mt + ph * (1 - i / 4)
            c.create_line(ml, y, ml + pw, y, fill=COLORS["border_soft"])
            c.create_text(ml - 8, y, text=f"{i*25}%", anchor="e",
                          font=FONTS["small"], fill=COLORS["text_muted"])

        c.create_line(ml, mt + ph, ml + pw, mt + ph, fill=COLORS["border"])

        n = len(self.history)
        if n < 2:
            c.create_text(w / 2, h / 2,
                          text="Recolectando datos...",
                          fill=COLORS["text_muted"],
                          font=FONTS["body"])
            return

        # Linea + relleno
        points = []
        for i, v in enumerate(self.history):
            x = ml + pw * (i / max(1, self.HISTORY_LEN - 1))
            y = mt + ph * (1 - max(0, min(100, v)) / 100)
            points.extend([x, y])
        # Relleno area (poligono cerrado)
        fill_pts = list(points)
        fill_pts.extend([ml + pw * ((n - 1) / max(1, self.HISTORY_LEN - 1)),
                         mt + ph,
                         ml, mt + ph])
        c.create_polygon(fill_pts, fill=COLORS["info_bg"], outline="")
        c.create_line(*points, fill=COLORS["accent"], width=2,
                      smooth=False)

        # Valor actual
        last = self.history[-1] if self.history else 0
        c.create_text(ml + pw - 4, mt + 4,
                      text=f"{last:.0f}%", anchor="ne",
                      font=FONTS["h2"], fill=COLORS["accent"])

    def _draw_cores(self):
        c = self.cores_canvas
        c.delete("all")
        w = c.winfo_width()
        h = c.winfo_height()
        if w < 50 or h < 50 or not self.per_core_history:
            return

        n = len(self.per_core_history)
        margin = 10
        gap = 6
        avail_w = w - 2 * margin - gap * (n - 1)
        bar_w = max(20, avail_w / n)
        max_h = h - 30

        for i, val in enumerate(self.per_core_history):
            x1 = margin + i * (bar_w + gap)
            x2 = x1 + bar_w
            v = max(0, min(100, val))
            bar_h = (v / 100) * max_h
            y2 = h - 14
            y1 = y2 - bar_h

            # Fondo (track)
            c.create_rectangle(x1, h - 14 - max_h, x2, y2,
                                fill=COLORS["bg_card_alt"], outline="")
            # Bar
            color = color_for_value(v, (50, 80), invert=True)
            c.create_rectangle(x1, y1, x2, y2, fill=color, outline="")
            # Etiqueta
            c.create_text((x1 + x2) / 2, y2 + 8,
                           text=f"#{i}", anchor="n",
                           font=FONTS["small"],
                           fill=COLORS["text_muted"])
            # Valor en lo alto del bar (si cabe)
            if bar_h > 16:
                c.create_text((x1 + x2) / 2, y1 + 2,
                               text=f"{v:.0f}", anchor="n",
                               font=FONTS["small"],
                               fill=COLORS["text_invert"])

    def _kill_selected(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo(APP_TITLE, "Selecciona un proceso de la tabla.")
            return
        try:
            pid = int(sel[0])
        except ValueError:
            return
        try:
            proc = psutil.Process(pid)
            name = proc.name()
        except psutil.Error:
            messagebox.showwarning(APP_TITLE, "Proceso ya no existe.")
            return

        if not messagebox.askyesno(
            APP_TITLE,
            f"Terminar proceso?\n\nPID: {pid}\nNombre: {name}\n\n"
            "ATENCION: NO es reversible. Datos no guardados se pierden."
        ):
            return
        try:
            proc.terminate()
            self.status_var.set(f"Proceso {pid} terminado")
            self.root.after(800, self.refresh_async)
        except psutil.AccessDenied:
            messagebox.showwarning(
                APP_TITLE,
                "Acceso denegado. Reinicia como administrador para "
                "terminar procesos del sistema."
            )
        except Exception as e:
            messagebox.showerror(APP_TITLE, f"Error: {e}")


def main():
    root = tk.Tk()
    setup_scaling(root)
    CpuApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
