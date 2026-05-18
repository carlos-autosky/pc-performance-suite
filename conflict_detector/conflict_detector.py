"""
Detector de Conflictos - Suite de Optimizacion PC.

Detecta apps que cumplen el mismo rol y se ejecutan simultaneamente,
ralentizando Windows. Por ejemplo: 2 antivirus, 3 cloud sync, 5
launchers de juegos, multiples updaters, etc.

Por cada categoria curada con patrones de proceso, si encuentra 2+
procesos distintos corriendo a la vez, lo reporta como conflicto.

Recomienda ACCION concreta: cual conservar, cual desinstalar.
"""

import os
import sys
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
from core.ctk_kit import init_ctk, Btn, Check
from core.scale import setup_scaling, s
from core.progress import ProgressOverlay
init_ctk()


APP_TITLE = "Detector de Conflictos"
APP_VERSION = "1.0.0"
SUITE_NAME = "Suite de Optimizacion PC"
MODULE_NAME = "conflict_detector"


# ---------- Catalogo de categorias ----------
# Cada categoria: id, name, severity, processes (list of substrings - case insensitive)
# severity: "alto" (frenan PC, conflictos), "medio" (RAM/IO), "bajo" (ruido)
# advice: que hacer al detectar 2+ procesos en esta categoria

CATEGORIES = [
    {
        "id": "antivirus_thirdparty",
        "name": "Antivirus de terceros",
        "severity": "alto",
        "processes": [
            ("avastsvc", "Avast"),
            ("avgsvc", "AVG"),
            ("kavfs", "Kaspersky"),
            ("kavsvc", "Kaspersky"),
            ("avp", "Kaspersky"),
            ("mcshield", "McAfee"),
            ("masvc", "McAfee Agent"),
            ("ekrn", "ESET"),
            ("egui", "ESET"),
            ("nortonsecurity", "Norton"),
            ("nis", "Norton Internet Security"),
            ("bdagent", "BitDefender"),
            ("bdservicehost", "BitDefender Service"),
            ("trendmicro", "Trend Micro"),
            ("tmlisten", "Trend Micro"),
            ("malwarebytes", "Malwarebytes"),
            ("mbamservice", "Malwarebytes"),
            ("sophos", "Sophos"),
            ("savservice", "Sophos"),
            ("webroot", "Webroot"),
            ("wrsa", "Webroot"),
            ("avira", "Avira"),
            ("avgnt", "Avira"),
            ("f-secure", "F-Secure"),
            ("fsav", "F-Secure"),
            ("comodo", "Comodo"),
            ("cmdagent", "Comodo"),
            ("zonealarm", "ZoneAlarm AV"),
            ("totaldefense", "Total Defense"),
            ("emsisoft", "Emsisoft"),
            ("a2start", "Emsisoft"),
        ],
        "advice": (
            "Tener 2+ antivirus reales corriendo causa freezes, escaneos "
            "duplicados y conflictos de cuarentena. Conserva UNO y desinstala "
            "el resto. Si tienes Defender activo y un AV de terceros, Defender "
            "se desactiva auto pero conviene tener solo uno habilitado."
        ),
    },
    {
        "id": "cloud_sync",
        "name": "Servicios de sincronizacion en la nube",
        "severity": "medio",
        "processes": [
            ("onedrive.exe", "OneDrive"),
            ("googledrivefs", "Google Drive"),
            ("googledrivesync", "Google Drive"),
            ("dropbox", "Dropbox"),
            ("icloud", "iCloud"),
            ("megasync", "MEGAsync"),
            ("box", "Box Drive"),
            ("nextcloud", "Nextcloud"),
            ("syncthing", "Syncthing"),
            ("pcloud", "pCloud"),
            ("yandex.disk", "Yandex Disk"),
        ],
        "advice": (
            "Cada cliente cloud indexa todos sus archivos y vigila cambios. "
            "3+ corriendo simultaneo puede consumir 500 MB+ de RAM y mucho I/O. "
            "Considera pausar los que no uses activamente o desinstalar duplicados."
        ),
    },
    {
        "id": "vpn",
        "name": "Clientes VPN",
        "severity": "alto",
        "processes": [
            ("nordvpn-service", "NordVPN"),
            ("nordvpn", "NordVPN"),
            ("expressvpn", "ExpressVPN"),
            ("protonvpn-service", "ProtonVPN"),
            ("protonvpn", "ProtonVPN"),
            ("openvpn", "OpenVPN"),
            ("wireguard", "WireGuard"),
            ("tunnelbear", "TunnelBear"),
            ("hotspotshield", "Hotspot Shield"),
            ("hssvr", "Hotspot Shield"),
            ("cyberghost", "CyberGhost"),
            ("surfshark", "Surfshark"),
            ("piavpn", "PIA VPN"),
            ("openvpn-gui", "OpenVPN GUI"),
        ],
        "advice": (
            "Multiples VPNs activas pueden romper la conectividad de red, "
            "rutas conflictivas y DNS leaks. Desactiva o desinstala todas "
            "salvo la que vas a usar."
        ),
    },
    {
        "id": "game_launchers",
        "name": "Launchers de juegos",
        "severity": "medio",
        "processes": [
            ("steam", "Steam"),
            ("epicgameslauncher", "Epic Games"),
            ("eaapp", "EA App"),
            ("origin", "Origin"),
            ("ubisoftconnect", "Ubisoft Connect"),
            ("upc", "Ubisoft Connect"),
            ("battle.net", "Battle.net"),
            ("agent.exe", "Battle.net Agent"),
            ("galaxyclient", "GOG Galaxy"),
            ("riotclient", "Riot Client"),
            ("eaapp", "EA App"),
            ("rockstargameslauncher", "Rockstar Launcher"),
            ("xboxapp", "Xbox App"),
            ("xboxpcapp", "Xbox PC App"),
        ],
        "advice": (
            "Launchers en background = 50-150 MB cada uno + actualizadores "
            "automaticos. Configuralos para NO arrancar con Windows (en sus "
            "settings). Solo abre el que vas a usar."
        ),
    },
    {
        "id": "chat_apps",
        "name": "Apps de chat / colaboracion",
        "severity": "medio",
        "processes": [
            ("slack", "Slack"),
            ("teams", "Teams"),
            ("discord", "Discord"),
            ("whatsapp", "WhatsApp"),
            ("telegram", "Telegram"),
            ("signal", "Signal"),
            ("skype", "Skype"),
            ("zoom", "Zoom"),
            ("webex", "Webex"),
            ("element", "Element"),
            ("rocket.chat", "Rocket.Chat"),
            ("mattermost", "Mattermost"),
        ],
        "advice": (
            "Cada chat consume 200-500 MB y se sincroniza en background. "
            "Considera cerrar los que no uses activamente. Para WhatsApp/"
            "Telegram tambien existe la version web/PWA mas ligera."
        ),
    },
    {
        "id": "cleaners",
        "name": "Optimizadores / cleaners",
        "severity": "alto",
        "processes": [
            ("ccleaner", "CCleaner"),
            ("advsystemcare", "Advanced SystemCare"),
            ("iobit", "IObit"),
            ("smartdef", "Smart Defrag"),
            ("cleanmaster", "Clean Master"),
            ("revouninstaller", "Revo Uninstaller"),
            ("wisecleaner", "Wise Cleaner"),
            ("glaryutilities", "Glary Utilities"),
            ("avgtuneup", "AVG TuneUp"),
            ("avasttuneup", "Avast Cleanup"),
            ("tuneup", "TuneUp Utilities"),
        ],
        "advice": (
            "Multiples optimizadores compiten por los mismos archivos y "
            "configuraciones, pueden chocar al limpiar. Conserva UNO. "
            "Esta misma suite ya cubre gran parte de lo que hacen estos."
        ),
    },
    {
        "id": "updaters",
        "name": "Actualizadores en background",
        "severity": "bajo",
        "processes": [
            ("jusched", "Java Updater"),
            ("adobearm", "Adobe Updater"),
            ("aam", "Adobe Application Manager"),
            ("creative cloud", "Adobe Creative Cloud"),
            ("googleupdater", "Google Updater"),
            ("googleupdate", "Google Updater"),
            ("mssoftwareassetmanagement", "Microsoft AssetManagement"),
            ("appleupdate", "Apple Software Update"),
            ("itunessoftwareupdate", "iTunes Updater"),
            ("speccyupdate", "Speccy Updater"),
            ("ccupdate", "CCleaner Updater"),
        ],
        "advice": (
            "Updaters en background revisan cada N minutos y descargan en "
            "silencio. 3+ activos generan ruido constante de CPU y red. "
            "En tarea programada se pueden deshabilitar (Startup Analyzer)."
        ),
    },
    {
        "id": "gpu_helpers",
        "name": "Helpers de GPU",
        "severity": "medio",
        "processes": [
            ("nvcontainer", "NVIDIA Container"),
            ("nvidiashare", "NVIDIA Share / ShadowPlay"),
            ("nvtray", "NVIDIA Tray"),
            ("geforce experience", "GeForce Experience"),
            ("nvbroadcast", "NVIDIA Broadcast"),
            ("rtss", "RivaTuner Statistics Server"),
            ("msiafterburner", "MSI Afterburner"),
            ("amdsoftware", "AMD Software"),
            ("radeonsettings", "Radeon Settings"),
            ("openhardwaremonitor", "OpenHardwareMonitor"),
            ("hwinfo64", "HWiNFO64"),
            ("hwinfo32", "HWiNFO32"),
            ("aida64", "AIDA64"),
            ("coretemp", "CoreTemp"),
        ],
        "advice": (
            "Helpers de GPU/hardware monitor compiten por sensores y "
            "consumen CPU constante. Si solo necesitas el panel principal "
            "del fabricante, deshabilita los extra (overlay, telemetria)."
        ),
    },
    {
        "id": "oem_telemetry",
        "name": "Software del fabricante (OEM)",
        "severity": "medio",
        "processes": [
            ("hpsupportsolutionsframework", "HP Support Assistant"),
            ("hpsa", "HP Support Assistant"),
            ("dellsupportassist", "Dell SupportAssist"),
            ("dellupdate", "Dell Update"),
            ("supportassistagent", "Dell SupportAssist Agent"),
            ("lenovo.modern.imcontroller", "Lenovo Vantage"),
            ("lenovovantageservice", "Lenovo Vantage"),
            ("lenovoutility", "Lenovo Utility"),
            ("acerregistration", "Acer Registration"),
            ("armourycrate", "ASUS Armoury Crate"),
            ("asus", "ASUS Tools"),
            ("rogliveservice", "ROG Live Service"),
            ("aurahalservice", "ASUS Aura"),
            ("samsungupdate", "Samsung Update"),
        ],
        "advice": (
            "Software OEM hace telemetria agresiva y suele incluir varias "
            "tareas programadas. Si no usas las funciones del panel del "
            "fabricante, considera desinstalar (mantienes solo los drivers)."
        ),
    },
    {
        "id": "browsers",
        "name": "Navegadores en uso simultaneo",
        "severity": "medio",
        "processes": [
            ("chrome.exe", "Google Chrome"),
            ("msedge.exe", "Microsoft Edge"),
            ("firefox.exe", "Firefox"),
            ("opera.exe", "Opera"),
            ("brave.exe", "Brave"),
            ("vivaldi.exe", "Vivaldi"),
            ("safari.exe", "Safari"),
        ],
        "advice": (
            "Tener 2+ navegadores abiertos a la vez consume 500 MB-2 GB. "
            "Cada uno con sus extensiones, multiples tabs y procesos por tab. "
            "Si no comparas en ambos, cierra el que no uses."
        ),
    },
    {
        "id": "firewall_extra",
        "name": "Firewalls de terceros",
        "severity": "alto",
        "processes": [
            ("zonealarm", "ZoneAlarm"),
            ("comodo firewall", "Comodo Firewall"),
            ("cmdagent", "Comodo"),
            ("glasswire", "GlassWire"),
            ("tinywall", "TinyWall"),
            ("simplewall", "SimpleWall"),
            ("netlimiter", "NetLimiter"),
            ("peerblock", "PeerBlock"),
        ],
        "advice": (
            "Firewall extra encima del de Windows puede causar conflictos "
            "de filtrado, dropped packets, y juegos / video calls que no "
            "conectan. Conserva uno solo (preferible Windows Firewall + "
            "deshabilita el extra) o uninstala el redundante."
        ),
    },
]


SEVERITY_COLOR = {
    "alto":  "bad",
    "medio": "warn",
    "bajo":  "info",
}


# ---------- Deteccion ----------

def _proc_list():
    """Snapshot de procesos: lista de dicts con name lower y memoria."""
    rows = []
    for p in psutil.process_iter(["pid", "name", "memory_info", "exe"]):
        try:
            info = p.info
            name = (info.get("name") or "").lower()
            rss = info.get("memory_info").rss if info.get("memory_info") else 0
            rows.append({
                "pid": info.get("pid"),
                "name": name,
                "name_orig": info.get("name") or "",
                "exe": info.get("exe") or "",
                "rss": rss,
            })
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return rows


def detect_conflicts():
    """
    Devuelve lista de conflictos detectados:
    [{
        "category_id", "category_name", "severity",
        "matches": [{"label", "process", "pid", "rss"}],
        "advice"
    }]
    Solo retorna categorias con 2+ matches DISTINTOS por etiqueta.
    """
    procs = _proc_list()
    out = []
    for cat in CATEGORIES:
        matches = []
        seen_labels = set()
        for proc in procs:
            for pattern, label in cat["processes"]:
                if pattern in proc["name"]:
                    if label not in seen_labels:
                        matches.append({
                            "label": label,
                            "process": proc["name_orig"],
                            "pid": proc["pid"],
                            "rss": proc["rss"],
                            "exe": proc["exe"],
                        })
                        seen_labels.add(label)
        if len(matches) >= 2:
            total_rss = sum(m["rss"] for m in matches)
            out.append({
                "category_id": cat["id"],
                "category_name": cat["name"],
                "severity": cat["severity"],
                "matches": matches,
                "advice": cat["advice"],
                "total_rss": total_rss,
            })
    return out


def fmt_bytes(n):
    n = float(n or 0)
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


# ---------- UI ----------

class ConflictApp:
    def __init__(self, root):
        self.root = root
        self.root.title(f"{APP_TITLE} - {SUITE_NAME}")
        self.root.geometry(f"{s(1240)}x{s(820)}")
        self.root.minsize(s(1080), s(700))
        self.root.configure(bg=COLORS["bg"])
        configure_ttk(self.root)

        self.conflicts = []
        self.build_ui()
        self.scan_async()

    def build_ui(self):
        head = tk.Frame(self.root, bg=COLORS["bg"])
        head.pack(fill="x", padx=s(20), pady=(s(16), s(6)))
        left = tk.Frame(head, bg=COLORS["bg"])
        left.pack(side="left")
        tk.Label(left, text=APP_TITLE, bg=COLORS["bg"],
                 fg=COLORS["text"], font=FONTS["title"]).pack(anchor="w")
        tk.Label(left,
                 text="Detecta apps redundantes ejecutandose a la vez (2 antivirus, varios cloud sync, multiples launchers...).",
                 bg=COLORS["bg"], fg=COLORS["text_muted"],
                 font=FONTS["body"]).pack(anchor="w", pady=(s(4), 0))

        right = tk.Frame(head, bg=COLORS["bg"])
        right.pack(side="right")
        Btn(right, text="Re-escanear procesos",
            command=self.scan_async,
            kind="accent", width=s(180)).pack(side="right")

        kpi = tk.Frame(self.root, bg=COLORS["bg"])
        kpi.pack(fill="x", padx=s(20), pady=(s(10), s(8)))
        self.kpi_total = KpiCard(kpi, title="CONFLICTOS DETECTADOS",
                                 value="-", subtitle="-",
                                 accent=COLORS["accent"], show_bar=False)
        self.kpi_high = KpiCard(kpi, title="SEVERIDAD ALTA",
                                value="-", subtitle="Frenan tu PC",
                                accent=COLORS["bad"], show_bar=False)
        self.kpi_medium = KpiCard(kpi, title="SEVERIDAD MEDIA",
                                  value="-", subtitle="RAM / I/O",
                                  accent=COLORS["warn"], show_bar=False)
        self.kpi_ram = KpiCard(kpi, title="MEMORIA EN CONFLICTO",
                               value="-", subtitle="RAM total apps duplicadas",
                               accent=COLORS["info"], show_bar=False)
        for i, c in enumerate([self.kpi_total, self.kpi_high,
                               self.kpi_medium, self.kpi_ram]):
            c.grid(row=0, column=i, sticky="nsew", padx=s(6), pady=s(4))
            kpi.columnconfigure(i, weight=1)

        # Footer
        actions = tk.Frame(self.root, bg=COLORS["bg"], height=s(64))
        actions.pack(side="bottom", fill="x", padx=s(20), pady=(s(8), s(14)))
        actions.pack_propagate(False)
        Btn(actions, text="Ver detalle de conflicto seleccionado",
            command=self._show_detail,
            kind="ghost", width=s(290), height=s(42)).pack(side="left", pady=s(8))
        Btn(actions, text="Abrir Optimizador de Memoria",
            command=self._open_memory,
            kind="ghost", width=s(240), height=s(42)).pack(side="left", padx=s(8), pady=s(8))
        Btn(actions, text="Abrir Desinstalador Profundo",
            command=self._open_uninstall,
            kind="ghost", width=s(240), height=s(42)).pack(side="left", pady=s(8))
        self.status_var = tk.StringVar(value="Listo")
        tk.Label(actions, textvariable=self.status_var,
                 bg=COLORS["bg"], fg=COLORS["text_muted"],
                 font=FONTS["label"]).pack(side="right")
        tk.Label(actions,
                 text=f"{APP_TITLE} v{APP_VERSION}  -  {COPYRIGHT}",
                 bg=COLORS["bg"], fg=COLORS["text_soft"],
                 font=FONTS["small"]).pack(side="right", padx=(0, s(14)))

        # Tabla de conflictos
        listcard = SectionCard(self.root,
                               title="Conflictos detectados (severidad y recomendacion)")
        listcard.pack(fill="both", expand=True, padx=s(20), pady=(s(4), s(6)))
        body = listcard.body()

        cols = ("severity", "category", "duplicates", "ram", "members")
        self.tree = ttk.Treeview(body, columns=cols,
                                 show="headings", height=18)
        headings = {
            "severity": "SEVERIDAD",
            "category": "CATEGORIA",
            "duplicates": "DUPLICADOS",
            "ram": "RAM TOTAL",
            "members": "APLICACIONES DETECTADAS",
        }
        widths = {
            "severity": s(110),
            "category": s(260),
            "duplicates": s(110),
            "ram": s(120),
            "members": s(560),
        }
        anchors = {
            "severity": "w",
            "category": "w",
            "duplicates": "center",
            "ram": "e",
            "members": "w",
        }
        for c in cols:
            self.tree.heading(c, text=headings[c])
            self.tree.column(c, width=widths[c], anchor=anchors[c])
        self.tree.pack(side="left", fill="both", expand=True)
        sb = ttk.Scrollbar(body, orient="vertical",
                           command=self.tree.yview)
        sb.pack(side="right", fill="y")
        self.tree.configure(yscrollcommand=sb.set)

        self.tree.tag_configure(
            "alto", background=COLORS["tree_row_bad"],
            foreground=COLORS["text"]
        )
        self.tree.tag_configure(
            "medio", background=COLORS["tree_row_warn"],
            foreground=COLORS["text"]
        )
        self.tree.tag_configure(
            "bajo", background=COLORS["tree_row_ok"],
            foreground=COLORS["text"]
        )
        self.tree.bind("<Double-1>", lambda _e: self._show_detail())

    def scan_async(self):
        self.status_var.set("Escaneando procesos en busca de conflictos...")
        overlay = ProgressOverlay(
            self.root,
            "Escaneando procesos para detectar conflictos..."
        )
        threading.Thread(target=self._scan_worker,
                         args=(overlay,), daemon=True).start()

    def _scan_worker(self, overlay):
        try:
            conflicts = detect_conflicts()
        except Exception as e:
            self.root.after(0, overlay.close)
            self.root.after(0, lambda: self.status_var.set(f"Error: {e}"))
            return
        self.root.after(0, overlay.close)
        self.root.after(0, self._populate, conflicts)

    def _populate(self, conflicts):
        self.conflicts = conflicts

        for it in self.tree.get_children():
            self.tree.delete(it)

        n_high = sum(1 for c in conflicts if c["severity"] == "alto")
        n_med = sum(1 for c in conflicts if c["severity"] == "medio")
        n_low = sum(1 for c in conflicts if c["severity"] == "bajo")
        total_ram = sum(c["total_rss"] for c in conflicts)

        self.kpi_total.update_data(
            value=str(len(conflicts)),
            subtitle="Categorias con duplicados" if conflicts
                     else "Sin conflictos detectados",
            accent=COLORS["bad"] if n_high else
                   COLORS["warn"] if n_med else COLORS["ok"],
        )
        self.kpi_high.update_data(
            value=str(n_high), subtitle="Frenan tu PC",
            accent=COLORS["bad"] if n_high else COLORS["text_muted"],
        )
        self.kpi_medium.update_data(
            value=str(n_med), subtitle="RAM / I/O",
            accent=COLORS["warn"] if n_med else COLORS["text_muted"],
        )
        self.kpi_ram.update_data(
            value=fmt_bytes(total_ram),
            subtitle=f"En {sum(len(c['matches']) for c in conflicts)} procesos",
            accent=COLORS["info"],
        )

        # Ordena por severidad
        order = {"alto": 0, "medio": 1, "bajo": 2}
        conflicts_sorted = sorted(conflicts, key=lambda c: order.get(c["severity"], 9))

        for idx, c in enumerate(conflicts_sorted):
            members_text = ", ".join(m["label"] for m in c["matches"])
            self.tree.insert(
                "", "end", iid=str(idx), tags=(c["severity"],),
                values=(
                    c["severity"].upper(),
                    c["category_name"],
                    str(len(c["matches"])),
                    fmt_bytes(c["total_rss"]),
                    members_text,
                )
            )

        self._conflicts_sorted = conflicts_sorted

        if not conflicts:
            self.status_var.set(
                f"Sin conflictos detectados - {datetime.now():%H:%M:%S}"
            )
        else:
            self.status_var.set(
                f"{len(conflicts)} conflicto(s) detectado(s) - "
                f"{datetime.now():%H:%M:%S}"
            )

    def _selected(self):
        sel = self.tree.selection()
        if not sel:
            return None
        idx = int(sel[0])
        return (self._conflicts_sorted[idx]
                if 0 <= idx < len(self._conflicts_sorted) else None)

    def _show_detail(self):
        c = self._selected()
        if not c:
            messagebox.showinfo(APP_TITLE, "Selecciona un conflicto.")
            return
        lines = [
            f"Categoria: {c['category_name']}",
            f"Severidad: {c['severity'].upper()}",
            f"Procesos duplicados detectados: {len(c['matches'])}",
            f"RAM total consumida: {fmt_bytes(c['total_rss'])}",
            "",
            "Aplicaciones encontradas corriendo:",
        ]
        for m in c["matches"]:
            lines.append(
                f"  - {m['label']}  (proceso: {m['process']}, "
                f"PID {m['pid']}, RAM {fmt_bytes(m['rss'])})"
            )
        lines += ["", "Recomendacion:", c["advice"]]
        messagebox.showinfo(APP_TITLE, "\n".join(lines))

    def _open_memory(self):
        self._open_module("memory_optimizer/memory_optimizer.py")

    def _open_uninstall(self):
        self._open_module("deep_uninstall/deep_uninstall.py")

    def _open_module(self, rel_path):
        import subprocess
        suite_root = Path(__file__).resolve().parent.parent
        script = suite_root / rel_path
        if not script.exists():
            messagebox.showerror(APP_TITLE, f"No se encuentra:\n{script}")
            return
        try:
            subprocess.Popen(
                [sys.executable, str(script)],
                cwd=str(suite_root),
                creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
            )
        except Exception as e:
            messagebox.showerror(APP_TITLE, f"Error al abrir: {e}")


def main():
    root = tk.Tk()
    setup_scaling(root)
    ConflictApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
