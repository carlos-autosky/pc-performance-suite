"""
Centro de Seguridad - Suite de Optimizacion PC.

Combina:
1. Estado y control de Microsoft Defender (gratis, integrado en Win10/11)
2. Verificacion de archivos vs MalwareBazaar (abuse.ch, gratis sin auth)
3. (Opcional) VirusTotal API si el usuario configura una API key

NO redistribuye ningun engine antivirus comercial. Defender YA esta en
Windows. Las consultas externas solo envian SHA256 (hash, no contenido).
"""

import os
import sys
import json
import hashlib
import threading
import subprocess
import urllib.request
import urllib.parse
import urllib.error
import customtkinter as ctk
import tkinter as tk
from pathlib import Path
from datetime import datetime, timezone
from tkinter import ttk, messagebox, filedialog

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core import style as _style_mod
_style_mod.apply_saved_theme()
from core.style import COLORS, FONTS, configure_ttk, color_for_value, COPYRIGHT
from core.ui_kit import KpiCard, SectionCard, StatusPill
from core.ctk_kit import init_ctk, Btn, Check, Entry
from core.scale import setup_scaling, s
from core import config as cfg_mod
init_ctk()


APP_TITLE = "Centro de Seguridad"
APP_VERSION = "1.0.0"
SUITE_NAME = "Suite de Optimizacion PC"
MODULE_NAME = "security_center"

MALWAREBAZAAR_URL = "https://mb-api.abuse.ch/api/v1/"
VIRUSTOTAL_URL = "https://www.virustotal.com/api/v3/files/{sha256}"


# ---------- Microsoft Defender wrapper ----------

def _ps(cmd, timeout=30):
    """Ejecuta PowerShell oculto y devuelve stdout."""
    try:
        cp = subprocess.run(
            ["powershell", "-NoProfile", "-Command", cmd],
            capture_output=True, text=True, timeout=timeout,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return cp.returncode, (cp.stdout or "").strip(), (cp.stderr or "").strip()
    except Exception as e:
        return 1, "", str(e)


def _ms_date_to_iso(value):
    """Convierte '/Date(1777816238000)/' a string legible."""
    if not value:
        return None
    if isinstance(value, str) and value.startswith("/Date("):
        try:
            ms = int(value[6:].rstrip("/").rstrip(")").split("+")[0].split("-")[0])
            dt = datetime.fromtimestamp(ms / 1000, tz=timezone.utc).astimezone()
            return dt.strftime("%Y-%m-%d %H:%M")
        except Exception:
            return value
    return value


def defender_status():
    """Devuelve dict con estado de Defender. None si falla."""
    cmd = (
        "Get-MpComputerStatus | Select-Object "
        "AntivirusEnabled,RealTimeProtectionEnabled,IoavProtectionEnabled,"
        "BehaviorMonitorEnabled,AntiSpywareEnabled,IsTamperProtected,"
        "AntivirusSignatureLastUpdated,AntivirusSignatureVersion,"
        "AntispywareSignatureLastUpdated,AntispywareSignatureVersion,"
        "QuickScanEndTime,FullScanEndTime,QuickScanAge,FullScanAge,"
        "ProductStatus,ComputerState,DefenderSignaturesOutOfDate "
        "| ConvertTo-Json -Compress"
    )
    code, out, err = _ps(cmd)
    if code != 0 or not out:
        return None
    try:
        d = json.loads(out)
        for k in ("AntivirusSignatureLastUpdated", "AntispywareSignatureLastUpdated",
                  "QuickScanEndTime", "FullScanEndTime"):
            if k in d:
                d[k] = _ms_date_to_iso(d.get(k))
        return d
    except Exception:
        return None


def defender_threats(limit=50):
    """Lista las amenazas detectadas (historico de Defender)."""
    cmd = (
        "Get-MpThreatDetection | Sort-Object InitialDetectionTime -Descending | "
        f"Select-Object -First {limit} ThreatID,ActionSuccess,InitialDetectionTime,"
        "Resources,DomainUser,RemediationTime,CleaningActionID,"
        "ProcessName,ThreatStatusID | ConvertTo-Json -Compress"
    )
    code, out, _ = _ps(cmd)
    if code != 0 or not out:
        return []
    try:
        data = json.loads(out)
        if isinstance(data, dict):
            data = [data]
        for d in data:
            if "InitialDetectionTime" in d:
                d["InitialDetectionTime"] = _ms_date_to_iso(d.get("InitialDetectionTime"))
            if "RemediationTime" in d:
                d["RemediationTime"] = _ms_date_to_iso(d.get("RemediationTime"))
        return data
    except Exception:
        return []


def defender_active_threats():
    """Amenazas actualmente activas (no remediadas)."""
    cmd = (
        "Get-MpThreat | Select-Object ThreatID,ThreatName,SeverityID,"
        "CategoryID,DidThreatExecute | ConvertTo-Json -Compress"
    )
    code, out, _ = _ps(cmd)
    if code != 0 or not out:
        return []
    try:
        data = json.loads(out)
        if isinstance(data, dict):
            data = [data]
        return data or []
    except Exception:
        return []


def defender_update():
    """Actualiza definiciones. Devuelve (ok, msg)."""
    code, out, err = _ps("Update-MpSignature; Write-Host OK", timeout=180)
    if code == 0 and "OK" in out:
        return True, "Definiciones actualizadas correctamente."
    return False, (err or out or "Error desconocido").strip()


def defender_scan(scan_type="QuickScan", path=None):
    """Lanza escaneo. Tipos: QuickScan, FullScan, CustomScan."""
    if scan_type == "CustomScan" and path:
        cmd = f"Start-MpScan -ScanType CustomScan -ScanPath '{path}'; Write-Host DONE"
        timeout = 1800
    elif scan_type == "FullScan":
        cmd = "Start-MpScan -ScanType FullScan; Write-Host DONE"
        timeout = 7200
    else:
        cmd = "Start-MpScan -ScanType QuickScan; Write-Host DONE"
        timeout = 600
    code, out, err = _ps(cmd, timeout=timeout)
    if code == 0 and "DONE" in out:
        return True, "Escaneo finalizado."
    return False, (err or out or "Error").strip()


# ---------- Hash + reputation ----------

def file_sha256(path, chunk=1024 * 1024):
    """Calcula SHA256 leyendo el archivo en chunks."""
    h = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            while True:
                b = f.read(chunk)
                if not b:
                    break
                h.update(b)
        return h.hexdigest()
    except Exception:
        return None


def query_malwarebazaar(sha256, auth_key=None):
    """
    Consulta abuse.ch MalwareBazaar por SHA256.
    Desde Oct/2023 requiere Auth-Key (gratis en https://auth.abuse.ch/).
    """
    headers = {"User-Agent": "PC-Performance-Suite/1.0"}
    if auth_key:
        headers["Auth-Key"] = auth_key
    try:
        data = urllib.parse.urlencode({
            "query": "get_info",
            "hash": sha256,
        }).encode("utf-8")
        req = urllib.request.Request(
            MALWAREBAZAAR_URL, data=data, headers=headers,
        )
        with urllib.request.urlopen(req, timeout=15) as r:
            body = r.read().decode("utf-8", errors="ignore")
        d = json.loads(body)
        status = d.get("query_status")
        if status == "ok":
            samples = d.get("data") or []
            return {"found": True, "samples": samples, "raw": d}
        elif status == "hash_not_found":
            return {"found": False, "samples": [], "raw": d}
        else:
            return {"found": False, "samples": [], "raw": d, "error": status}
    except urllib.error.HTTPError as e:
        if e.code == 401:
            return {"error": "Auth-Key requerida (gratis en auth.abuse.ch)"}
        return {"error": f"HTTP {e.code}"}
    except urllib.error.URLError as e:
        return {"error": f"Sin conexion: {e}"}
    except Exception as e:
        return {"error": str(e)}


def query_virustotal(sha256, api_key):
    """
    Consulta VirusTotal API v3 por SHA256.
    Requiere API key (free tier: 4 req/min, 500/dia).
    """
    if not api_key:
        return {"error": "Sin API key configurada"}
    try:
        url = VIRUSTOTAL_URL.format(sha256=sha256)
        req = urllib.request.Request(
            url, headers={"x-apikey": api_key,
                          "User-Agent": "PC-Performance-Suite/1.0"},
        )
        with urllib.request.urlopen(req, timeout=15) as r:
            body = r.read().decode("utf-8", errors="ignore")
        d = json.loads(body)
        attrs = (d.get("data") or {}).get("attributes") or {}
        stats = attrs.get("last_analysis_stats") or {}
        return {
            "found": True,
            "malicious": stats.get("malicious", 0),
            "suspicious": stats.get("suspicious", 0),
            "harmless": stats.get("harmless", 0),
            "undetected": stats.get("undetected", 0),
            "total": sum(stats.values()) if stats else 0,
            "names": list((attrs.get("names") or [])[:5]),
            "popular_threat": (attrs.get("popular_threat_classification") or {})
                              .get("suggested_threat_label", ""),
            "first_seen": _ts_to_iso(attrs.get("first_submission_date")),
            "last_seen": _ts_to_iso(attrs.get("last_analysis_date")),
        }
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return {"found": False}
        if e.code == 401:
            return {"error": "API key invalida"}
        if e.code == 429:
            return {"error": "Limite de cuota alcanzado (4/min)"}
        return {"error": f"HTTP {e.code}"}
    except Exception as e:
        return {"error": str(e)}


def _ts_to_iso(ts):
    if not ts:
        return ""
    try:
        return datetime.fromtimestamp(int(ts), tz=timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M")
    except Exception:
        return ""


# ---------- UI ----------

class SecurityApp:
    def __init__(self, root):
        self.root = root
        self.root.title(f"{APP_TITLE} - {SUITE_NAME}")
        self.root.geometry(f"{s(1240)}x{s(820)}")
        self.root.minsize(s(1080), s(720))
        self.root.configure(bg=COLORS["bg"])
        configure_ttk(self.root)

        self.defender_data = None
        self.threats_data = []
        self.current_hash = tk.StringVar(value="")
        self.current_path = tk.StringVar(value="")
        self.vt_api_key = tk.StringVar(value=cfg_mod.get("vt_api_key", "") or "")
        self.mb_auth_key = tk.StringVar(value=cfg_mod.get("mb_auth_key", "") or "")

        self.build_ui()
        self.refresh_defender_async()

    def build_ui(self):
        head = tk.Frame(self.root, bg=COLORS["bg"])
        head.pack(fill="x", padx=20, pady=(16, 6))
        left = tk.Frame(head, bg=COLORS["bg"])
        left.pack(side="left")
        tk.Label(left, text=APP_TITLE, bg=COLORS["bg"],
                 fg=COLORS["text"], font=FONTS["title"]).pack(anchor="w")
        tk.Label(left,
                 text="Estado de Microsoft Defender + verificacion de archivos contra MalwareBazaar / VirusTotal.",
                 bg=COLORS["bg"], fg=COLORS["text_muted"],
                 font=FONTS["body"]).pack(anchor="w", pady=(4, 0))

        right = tk.Frame(head, bg=COLORS["bg"])
        right.pack(side="right")
        Btn(right, text="Actualizar estado",
            command=self.refresh_defender_async,
            kind="accent", width=160).pack(side="right")

        # KPIs Defender
        kpi = tk.Frame(self.root, bg=COLORS["bg"])
        kpi.pack(fill="x", padx=20, pady=(10, 8))
        self.kpi_av = KpiCard(kpi, title="ANTIVIRUS",
                              value="-", subtitle="-",
                              accent=COLORS["info"], show_bar=False)
        self.kpi_rt = KpiCard(kpi, title="PROTECCION EN TIEMPO REAL",
                              value="-", subtitle="-",
                              accent=COLORS["info"], show_bar=False)
        self.kpi_sig = KpiCard(kpi, title="DEFINICIONES",
                               value="-", subtitle="-",
                               accent=COLORS["info"], show_bar=False)
        self.kpi_threats = KpiCard(kpi, title="AMENAZAS HISTORICAS",
                                   value="-", subtitle="-",
                                   accent=COLORS["info"], show_bar=False)
        for i, c in enumerate([self.kpi_av, self.kpi_rt,
                               self.kpi_sig, self.kpi_threats]):
            c.grid(row=0, column=i, sticky="nsew", padx=6, pady=4)
            kpi.columnconfigure(i, weight=1)

        # Tabview
        nb = ctk.CTkTabview(
            self.root,
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
        nb.pack(fill="both", expand=True, padx=20, pady=(4, 10))
        for name in ["Defender", "Verificar archivo", "Amenazas detectadas",
                     "Configuracion"]:
            nb.add(name)
        self.tab_def = nb.tab("Defender")
        self.tab_check = nb.tab("Verificar archivo")
        self.tab_threats = nb.tab("Amenazas detectadas")
        self.tab_config = nb.tab("Configuracion")

        self.status_var = tk.StringVar(value="Listo")
        bar = tk.Frame(self.root, bg=COLORS["bg"])
        bar.pack(fill="x", padx=20, pady=(0, 10))
        tk.Label(bar, textvariable=self.status_var,
                 bg=COLORS["bg"], fg=COLORS["text_muted"],
                 font=FONTS["small"]).pack(side="left")
        tk.Label(bar,
                 text=f"{APP_TITLE} v{APP_VERSION}  -  {COPYRIGHT}",
                 bg=COLORS["bg"], fg=COLORS["text_soft"],
                 font=FONTS["small"]).pack(side="right")

        self._build_defender_tab()
        self._build_check_tab()
        self._build_threats_tab()
        self._build_config_tab()

    def _build_defender_tab(self):
        parent = self.tab_def

        # Acciones
        actions = SectionCard(parent, title="Acciones rapidas")
        actions.pack(fill="x", padx=8, pady=(8, 4))
        body = actions.body()
        row = tk.Frame(body, bg=COLORS["bg_card"])
        row.pack(fill="x", pady=4)
        self._def_btns = []
        b1 = Btn(row, text="EJECUTAR: escaneo rapido",
                 command=lambda: self._scan_async("QuickScan"),
                 kind="accent", width=220)
        b1.pack(side="left", padx=(0, 6))
        b2 = Btn(row, text="EJECUTAR: escaneo completo",
                 command=lambda: self._scan_async("FullScan"),
                 kind="ghost", width=220)
        b2.pack(side="left", padx=6)
        b3 = Btn(row, text="EJECUTAR: escaneo personalizado",
                 command=self._scan_custom,
                 kind="ghost", width=240)
        b3.pack(side="left", padx=6)
        b4 = Btn(row, text="Actualizar definiciones",
                 command=self._update_signatures_async,
                 kind="ghost", width=200)
        b4.pack(side="left", padx=6)
        self._def_btns = [b1, b2, b3, b4]

        warn = tk.Label(
            body,
            text=("Los escaneos completo y personalizado pueden tardar varios minutos. "
                  "La ventana sigue respondiendo y veras el resultado al terminar."),
            bg=COLORS["bg_card"], fg=COLORS["text_muted"],
            font=FONTS["label"], justify="left", wraplength=900,
        )
        warn.pack(anchor="w", pady=(6, 6))

        # Barra de progreso (visible solo durante operaciones)
        self._def_prog_frame = tk.Frame(body, bg=COLORS["bg_card"])
        self._def_prog_frame.pack(fill="x", pady=(0, 4))
        self._def_prog_label = tk.Label(
            self._def_prog_frame, text="",
            bg=COLORS["bg_card"], fg=COLORS["accent"],
            font=FONTS["label_b"], anchor="w"
        )
        self._def_prog_bar = ctk.CTkProgressBar(
            self._def_prog_frame, mode="indeterminate",
            progress_color=COLORS["accent"],
            fg_color=COLORS["bg_card_alt"],
            border_color=COLORS["border"],
            height=14,
        )
        # Ambos ocultos por default (no pack)

        # Detalles del estado (tabla)
        details = SectionCard(parent, title="Estado detallado de Microsoft Defender")
        details.pack(fill="both", expand=True, padx=8, pady=(4, 8))
        body = details.body()
        cols = ("campo", "valor")
        self.def_tree = ttk.Treeview(body, columns=cols,
                                     show="headings", height=18)
        self.def_tree.heading("campo", text="PROPIEDAD")
        self.def_tree.heading("valor", text="VALOR")
        self.def_tree.column("campo", width=300, anchor="w")
        self.def_tree.column("valor", width=600, anchor="w")
        self.def_tree.pack(side="left", fill="both", expand=True)
        sb = ttk.Scrollbar(body, orient="vertical",
                           command=self.def_tree.yview)
        sb.pack(side="right", fill="y")
        self.def_tree.configure(yscrollcommand=sb.set)

    def _build_check_tab(self):
        parent = self.tab_check

        # Selector
        sel = SectionCard(parent, title="Archivo a verificar")
        sel.pack(fill="x", padx=8, pady=(8, 4))
        body = sel.body()
        row = tk.Frame(body, bg=COLORS["bg_card"])
        row.pack(fill="x", pady=4)
        tk.Label(row, text="Ruta:", bg=COLORS["bg_card"],
                 fg=COLORS["text"], font=FONTS["label_b"]).pack(side="left")
        ent = Entry(row, textvariable=self.current_path, width=600)
        ent.pack(side="left", padx=8, fill="x", expand=True)
        Btn(row, text="Examinar...",
            command=self._browse_file,
            kind="ghost", width=120).pack(side="left", padx=4)

        row2 = tk.Frame(body, bg=COLORS["bg_card"])
        row2.pack(fill="x", pady=(8, 0))
        tk.Label(row2, text="SHA256:", bg=COLORS["bg_card"],
                 fg=COLORS["text"], font=FONTS["label_b"]).pack(side="left")
        tk.Label(row2, textvariable=self.current_hash,
                 bg=COLORS["bg_card"], fg=COLORS["text_muted"],
                 font=FONTS["mono"]).pack(side="left", padx=8)

        actions = tk.Frame(body, bg=COLORS["bg_card"])
        actions.pack(fill="x", pady=(10, 0))
        self._check_btn = Btn(actions, text="EJECUTAR: calcular hash y consultar",
                              command=self._check_async,
                              kind="accent", width=320)
        self._check_btn.pack(side="left")

        # Barra de progreso (oculta hasta que se inicie verificacion)
        self._check_prog_frame = tk.Frame(body, bg=COLORS["bg_card"])
        self._check_prog_frame.pack(fill="x", pady=(8, 0))
        self._check_prog_label = tk.Label(
            self._check_prog_frame, text="",
            bg=COLORS["bg_card"], fg=COLORS["accent"],
            font=FONTS["label_b"], anchor="w"
        )
        self._check_prog_bar = ctk.CTkProgressBar(
            self._check_prog_frame, mode="indeterminate",
            progress_color=COLORS["accent"],
            fg_color=COLORS["bg_card_alt"],
            border_color=COLORS["border"],
            height=14,
        )

        # Resultados
        results = SectionCard(parent,
                              title="Resultados de reputacion (consulta solo se envia el hash)")
        results.pack(fill="both", expand=True, padx=8, pady=(4, 8))
        body = results.body()

        cols = ("fuente", "resultado", "detalle")
        self.check_tree = ttk.Treeview(body, columns=cols,
                                       show="headings", height=14)
        self.check_tree.heading("fuente", text="FUENTE")
        self.check_tree.heading("resultado", text="RESULTADO")
        self.check_tree.heading("detalle", text="DETALLE")
        self.check_tree.column("fuente", width=180, anchor="w")
        self.check_tree.column("resultado", width=200, anchor="w")
        self.check_tree.column("detalle", width=620, anchor="w")
        self.check_tree.pack(side="left", fill="both", expand=True)
        sb = ttk.Scrollbar(body, orient="vertical",
                           command=self.check_tree.yview)
        sb.pack(side="right", fill="y")
        self.check_tree.configure(yscrollcommand=sb.set)

        self.check_tree.tag_configure("ok",
                                       background=COLORS["tree_row_ok"])
        self.check_tree.tag_configure("warn",
                                       background=COLORS["tree_row_warn"])
        self.check_tree.tag_configure("bad",
                                       background=COLORS["tree_row_bad"])

    def _build_threats_tab(self):
        parent = self.tab_threats

        top = tk.Frame(parent, bg=COLORS["bg"])
        top.pack(fill="x", padx=8, pady=(8, 4))
        Btn(top, text="Recargar lista",
            command=self._reload_threats,
            kind="ghost", width=140).pack(side="left")
        tk.Label(top,
                 text="Historico de detecciones de Microsoft Defender en este equipo.",
                 bg=COLORS["bg"], fg=COLORS["text_muted"],
                 font=FONTS["label"]).pack(side="left", padx=12)

        wrap = SectionCard(parent, title="Amenazas detectadas")
        wrap.pack(fill="both", expand=True, padx=8, pady=(4, 8))
        body = wrap.body()
        cols = ("fecha", "id", "proceso", "recurso", "accion", "estado")
        self.th_tree = ttk.Treeview(body, columns=cols,
                                    show="headings", height=18)
        headings = {"fecha": "FECHA", "id": "ID AMENAZA",
                    "proceso": "PROCESO", "recurso": "RECURSO",
                    "accion": "ACCION", "estado": "ESTADO"}
        widths = {"fecha": 140, "id": 100, "proceso": 200,
                  "recurso": 380, "accion": 100, "estado": 100}
        for c in cols:
            self.th_tree.heading(c, text=headings[c])
            self.th_tree.column(c, width=widths[c], anchor="w")
        self.th_tree.pack(side="left", fill="both", expand=True)
        sb = ttk.Scrollbar(body, orient="vertical",
                           command=self.th_tree.yview)
        sb.pack(side="right", fill="y")
        self.th_tree.configure(yscrollcommand=sb.set)

    def _build_config_tab(self):
        parent = self.tab_config

        # MalwareBazaar
        wrap_mb = SectionCard(parent,
                              title="MalwareBazaar Auth-Key (recomendado, gratis)")
        wrap_mb.pack(fill="x", padx=8, pady=(8, 4))
        body = wrap_mb.body()
        info_mb = tk.Label(
            body,
            text=("MalwareBazaar (abuse.ch) requiere desde 2023 una Auth-Key gratuita "
                  "para consultas. Es totalmente gratis, sin email obligatorio.\n"
                  "1) Visita https://auth.abuse.ch/  2) Registrate  3) Copia tu Auth-Key aqui."),
            bg=COLORS["bg_card"], fg=COLORS["text_muted"],
            font=FONTS["body"], wraplength=900, justify="left",
        )
        info_mb.pack(anchor="w", pady=(0, 8))
        row = tk.Frame(body, bg=COLORS["bg_card"])
        row.pack(fill="x", pady=4)
        tk.Label(row, text="Auth-Key:", bg=COLORS["bg_card"],
                 fg=COLORS["text"], font=FONTS["label_b"]).pack(side="left")
        Entry(row, textvariable=self.mb_auth_key, width=500).pack(
            side="left", padx=8, fill="x", expand=True
        )
        Btn(row, text="Guardar",
            command=self._save_mb_key,
            kind="accent", width=120).pack(side="left", padx=4)

        # VirusTotal
        wrap = SectionCard(parent,
                           title="VirusTotal API-Key (opcional, 70+ motores AV)")
        wrap.pack(fill="x", padx=8, pady=(8, 4))
        body = wrap.body()
        info = tk.Label(
            body,
            text=("VirusTotal agrupa el resultado de 70+ motores antivirus. "
                  "Necesitas una cuenta gratis en virustotal.com para obtener una API key. "
                  "Free tier: 4 consultas/min, 500/dia. Sin key, no se consulta VT."),
            bg=COLORS["bg_card"], fg=COLORS["text_muted"],
            font=FONTS["body"], wraplength=900, justify="left",
        )
        info.pack(anchor="w", pady=(0, 8))

        row = tk.Frame(body, bg=COLORS["bg_card"])
        row.pack(fill="x", pady=4)
        tk.Label(row, text="API-Key:", bg=COLORS["bg_card"],
                 fg=COLORS["text"], font=FONTS["label_b"]).pack(side="left")
        Entry(row, textvariable=self.vt_api_key, width=500).pack(
            side="left", padx=8, fill="x", expand=True
        )
        Btn(row, text="Guardar",
            command=self._save_vt_key,
            kind="accent", width=120).pack(side="left", padx=4)

        about = SectionCard(parent, title="Acerca de las fuentes")
        about.pack(fill="both", expand=True, padx=8, pady=(8, 8))
        body = about.body()
        text = tk.Text(body, wrap="word",
                        bg=COLORS["bg_card"], fg=COLORS["text"],
                        relief="flat", borderwidth=0,
                        padx=12, pady=10, font=FONTS["body"])
        text.pack(fill="both", expand=True)
        text.insert("1.0",
            "MICROSOFT DEFENDER\n"
            "  Engine antivirus integrado en Windows 10/11. Esta suite solo lo controla\n"
            "  via PowerShell (Get-MpComputerStatus, Start-MpScan, Update-MpSignature).\n"
            "  No reemplaza a Defender, lo complementa con un panel unificado.\n\n"
            "MALWAREBAZAAR (abuse.ch)\n"
            "  Base de datos publica de samples de malware confirmado. Gratis, sin auth.\n"
            "  Solo enviamos el hash SHA256 (no el archivo). Si el hash existe en su\n"
            "  base, devuelve familia, primera/ultima vez vista, y plataformas afectadas.\n"
            "  Url: https://bazaar.abuse.ch/\n\n"
            "VIRUSTOTAL (Google)\n"
            "  Agrega resultado de 70+ motores antivirus comerciales para un mismo hash.\n"
            "  Requiere cuenta gratis. Solo enviamos hash, nunca contenido de archivos.\n"
            "  Url: https://www.virustotal.com/\n\n"
            "PRIVACIDAD\n"
            "  Esta suite NO sube archivos a ningun lado. Solo se calcula el hash SHA256\n"
            "  del archivo localmente (numero unico de 64 caracteres) y se consulta si\n"
            "  ese hash es conocido como malicioso. El hash no permite reconstruir el\n"
            "  archivo original."
        )
        text.config(state="disabled")

    # ---------- Helpers de progreso ----------

    def _show_def_progress(self, text):
        self._def_prog_label.config(text=text)
        self._def_prog_label.pack(fill="x", padx=2, pady=(2, 4))
        self._def_prog_bar.pack(fill="x", padx=2, pady=(0, 6))
        try:
            self._def_prog_bar.start()
        except Exception:
            pass
        for b in self._def_btns:
            try:
                b.configure(state="disabled")
            except Exception:
                pass

    def _hide_def_progress(self):
        try:
            self._def_prog_bar.stop()
        except Exception:
            pass
        self._def_prog_bar.pack_forget()
        self._def_prog_label.pack_forget()
        for b in self._def_btns:
            try:
                b.configure(state="normal")
            except Exception:
                pass

    def _show_check_progress(self, text):
        self._check_prog_label.config(text=text)
        self._check_prog_label.pack(fill="x", padx=2, pady=(4, 4))
        self._check_prog_bar.pack(fill="x", padx=2, pady=(0, 6))
        try:
            self._check_prog_bar.start()
        except Exception:
            pass
        try:
            self._check_btn.configure(state="disabled")
        except Exception:
            pass

    def _hide_check_progress(self):
        try:
            self._check_prog_bar.stop()
        except Exception:
            pass
        self._check_prog_bar.pack_forget()
        self._check_prog_label.pack_forget()
        try:
            self._check_btn.configure(state="normal")
        except Exception:
            pass

    # ---------- Acciones ----------

    def refresh_defender_async(self):
        self.status_var.set("Consultando Microsoft Defender...")
        threading.Thread(target=self._refresh_def_worker, daemon=True).start()

    def _refresh_def_worker(self):
        d = defender_status()
        threats = defender_threats(limit=200)
        self.root.after(0, self._populate_defender, d, threats)

    def _populate_defender(self, d, threats):
        if not d:
            self.status_var.set("No se pudo consultar Defender")
            self.kpi_av.update_data(value="N/D", subtitle="Error",
                                     accent=COLORS["bad"])
            return

        self.defender_data = d
        self.threats_data = threats

        av_on = d.get("AntivirusEnabled", False)
        rt_on = d.get("RealTimeProtectionEnabled", False)
        self.kpi_av.update_data(
            value="Activo" if av_on else "Inactivo",
            subtitle="Tamper Protection: " + ("Si" if d.get("IsTamperProtected") else "No"),
            accent=COLORS["ok"] if av_on else COLORS["bad"],
        )
        self.kpi_rt.update_data(
            value="Activa" if rt_on else "Desactivada",
            subtitle="Behavior Monitor: " + ("Si" if d.get("BehaviorMonitorEnabled") else "No"),
            accent=COLORS["ok"] if rt_on else COLORS["warn"],
        )
        sig_age = d.get("AntivirusSignatureLastUpdated") or "N/D"
        sig_ver = d.get("AntivirusSignatureVersion") or "N/D"
        self.kpi_sig.update_data(
            value=sig_ver,
            subtitle=f"Actualizadas: {sig_age}",
            accent=COLORS["info"],
        )
        n_threats = len(threats)
        self.kpi_threats.update_data(
            value=str(n_threats),
            subtitle="Detecciones historicas" if n_threats else "Sin amenazas detectadas",
            accent=COLORS["bad"] if n_threats > 0 else COLORS["ok"],
        )

        # Tabla de detalles
        for it in self.def_tree.get_children():
            self.def_tree.delete(it)
        rows = [
            ("Antivirus activo", "Si" if d.get("AntivirusEnabled") else "No"),
            ("Proteccion en tiempo real", "Si" if d.get("RealTimeProtectionEnabled") else "No"),
            ("Anti-spyware", "Si" if d.get("AntiSpywareEnabled") else "No"),
            ("Behavior Monitor", "Si" if d.get("BehaviorMonitorEnabled") else "No"),
            ("Proteccion IOAV (descargas)", "Si" if d.get("IoavProtectionEnabled") else "No"),
            ("Tamper Protection", "Si" if d.get("IsTamperProtected") else "No"),
            ("Definiciones AV - version", str(d.get("AntivirusSignatureVersion") or "N/D")),
            ("Definiciones AV - actualizadas", str(d.get("AntivirusSignatureLastUpdated") or "N/D")),
            ("Definiciones Spyware - version", str(d.get("AntispywareSignatureVersion") or "N/D")),
            ("Definiciones Spyware - actualizadas", str(d.get("AntispywareSignatureLastUpdated") or "N/D")),
            ("Definiciones desactualizadas", "Si" if d.get("DefenderSignaturesOutOfDate") else "No"),
            ("Ultimo escaneo rapido", str(d.get("QuickScanEndTime") or "N/D")),
            ("Antiguedad escaneo rapido (dias)", str(d.get("QuickScanAge") or "N/D")),
            ("Ultimo escaneo completo", str(d.get("FullScanEndTime") or "N/D")),
            ("Antiguedad escaneo completo (dias)", str(d.get("FullScanAge") or "N/D")),
            ("ProductStatus", str(d.get("ProductStatus") or "0")),
            ("ComputerState", str(d.get("ComputerState") or "0")),
        ]
        for k, v in rows:
            self.def_tree.insert("", "end", values=(k, v))

        # Tabla amenazas
        self._populate_threats_tree(threats)

        self.status_var.set(f"Estado actualizado {datetime.now():%H:%M:%S}")

    def _populate_threats_tree(self, threats):
        for it in self.th_tree.get_children():
            self.th_tree.delete(it)
        if not threats:
            return
        for t in threats:
            resources = t.get("Resources") or []
            if isinstance(resources, list):
                resource = "; ".join(str(x) for x in resources[:2])
            else:
                resource = str(resources)
            self.th_tree.insert("", "end", values=(
                t.get("InitialDetectionTime") or "",
                t.get("ThreatID") or "",
                t.get("ProcessName") or "",
                resource[:120],
                "OK" if t.get("ActionSuccess") else "Fallo",
                str(t.get("ThreatStatusID") or ""),
            ))

    def _reload_threats(self):
        self.status_var.set("Recargando amenazas...")
        def worker():
            threats = defender_threats(limit=200)
            self.threats_data = threats
            self.root.after(0, self._populate_threats_tree, threats)
            self.root.after(0, lambda: self.status_var.set(
                f"{len(threats)} detecciones cargadas"
            ))
        threading.Thread(target=worker, daemon=True).start()

    def _update_signatures_async(self):
        self.status_var.set("Actualizando definiciones...")
        self._show_def_progress(
            "Descargando definiciones desde Microsoft Update... (1-2 min)"
        )
        def worker():
            try:
                ok, msg = defender_update()
            finally:
                self.root.after(0, self._hide_def_progress)
            self.root.after(0, lambda: messagebox.showinfo(APP_TITLE, msg))
            self.root.after(0, self.refresh_defender_async)
        threading.Thread(target=worker, daemon=True).start()

    def _scan_async(self, scan_type):
        if scan_type == "FullScan":
            if not messagebox.askyesno(
                APP_TITLE,
                "Un escaneo completo puede tardar 30-60 min y usar mucha CPU.\n\n"
                "Continuar?"
            ):
                return
        labels = {
            "QuickScan": "Escaneo rapido en curso... revisando areas criticas (2-5 min)",
            "FullScan": "Escaneo completo en curso... revisando todo el disco (30-60 min)",
            "CustomScan": "Escaneo personalizado en curso...",
        }
        self.status_var.set(f"Escaneo {scan_type} en curso...")
        self._show_def_progress(labels.get(scan_type, "Escaneo en curso..."))

        def worker():
            try:
                ok, msg = defender_scan(scan_type)
            finally:
                self.root.after(0, self._hide_def_progress)
            self.root.after(0, lambda: messagebox.showinfo(
                APP_TITLE, f"{scan_type}: {msg}"
            ))
            self.root.after(0, self.refresh_defender_async)
        threading.Thread(target=worker, daemon=True).start()

    def _scan_custom(self):
        path = filedialog.askdirectory(title="Carpeta a escanear")
        if not path:
            return
        self.status_var.set(f"Escaneando {path} ...")
        self._show_def_progress(
            f"Escaneo personalizado en curso... carpeta: {path}"
        )

        def worker():
            try:
                ok, msg = defender_scan("CustomScan", path)
            finally:
                self.root.after(0, self._hide_def_progress)
            self.root.after(0, lambda: messagebox.showinfo(APP_TITLE, msg))
            self.root.after(0, self.refresh_defender_async)
        threading.Thread(target=worker, daemon=True).start()

    def _browse_file(self):
        path = filedialog.askopenfilename(title="Selecciona archivo a verificar")
        if path:
            self.current_path.set(path)
            self.current_hash.set("")

    def _check_async(self):
        path = self.current_path.get().strip()
        if not path:
            messagebox.showinfo(APP_TITLE, "Selecciona o escribe la ruta de un archivo.")
            return
        if not Path(path).exists():
            messagebox.showwarning(APP_TITLE, "El archivo no existe.")
            return
        if not Path(path).is_file():
            messagebox.showwarning(APP_TITLE, "Selecciona un archivo, no una carpeta.")
            return

        try:
            size = Path(path).stat().st_size
            size_text = f" ({size / (1024*1024):.1f} MB)" if size > 1024*1024 else ""
        except Exception:
            size_text = ""

        self.status_var.set(f"Calculando SHA256 de {path}...")
        self._show_check_progress(
            f"Calculando hash SHA256 del archivo{size_text}..."
        )
        for it in self.check_tree.get_children():
            self.check_tree.delete(it)
        threading.Thread(target=self._check_worker,
                         args=(path,), daemon=True).start()

    def _check_worker(self, path):
        try:
            sha = file_sha256(path)
            if not sha:
                self.root.after(0, self._hide_check_progress)
                self.root.after(0, lambda: messagebox.showerror(
                    APP_TITLE, "No se pudo calcular el hash."
                ))
                return
            self.root.after(0, lambda: self.current_hash.set(sha))
            self.root.after(0, lambda: self._check_prog_label.config(
                text="Hash calculado. Consultando MalwareBazaar..."
            ))
            self.root.after(0, lambda: self.status_var.set(
                "Consultando MalwareBazaar..."
            ))

            # MalwareBazaar
            mb_key = self.mb_auth_key.get().strip() or None
            mb = query_malwarebazaar(sha, auth_key=mb_key)
            self.root.after(0, self._add_check_row, "MalwareBazaar", mb, "mb")

            # VirusTotal (opcional)
            api_key = self.vt_api_key.get().strip()
            if api_key:
                self.root.after(0, lambda: self._check_prog_label.config(
                    text="Consultando VirusTotal (70+ motores)..."
                ))
                self.root.after(0, lambda: self.status_var.set(
                    "Consultando VirusTotal..."
                ))
                vt = query_virustotal(sha, api_key)
                self.root.after(0, self._add_check_row, "VirusTotal", vt, "vt")
            else:
                self.root.after(0, self._add_check_row,
                                 "VirusTotal",
                                 {"error": "Sin API key (configurar en pestana Configuracion)"},
                                 "vt")
        finally:
            self.root.after(0, self._hide_check_progress)

        self.root.after(0, lambda: self.status_var.set("Verificacion completa."))

    def _add_check_row(self, source, result, kind):
        if "error" in result:
            self.check_tree.insert("", "end", tags=("warn",), values=(
                source, "Error", result["error"]
            ))
            return

        if kind == "mb":
            if result.get("found"):
                samples = result.get("samples") or []
                if samples:
                    s = samples[0]
                    detail = (
                        f"Familia: {s.get('signature','?')}  |  "
                        f"Tipo: {s.get('file_type','?')}  |  "
                        f"Primera vez: {s.get('first_seen','?')}"
                    )
                else:
                    detail = "Hash conocido como malicioso"
                self.check_tree.insert("", "end", tags=("bad",), values=(
                    source, "MALICIOSO (conocido)", detail
                ))
            else:
                self.check_tree.insert("", "end", tags=("ok",), values=(
                    source, "No conocido como malware",
                    "El hash no aparece en la base publica de samples confirmados."
                ))

        elif kind == "vt":
            if not result.get("found"):
                self.check_tree.insert("", "end", tags=("ok",), values=(
                    source, "No analizado",
                    "VirusTotal no tiene este archivo en su base. Sin evidencia de malware."
                ))
                return
            mal = result.get("malicious", 0)
            sus = result.get("suspicious", 0)
            tot = result.get("total", 0)
            harmless = result.get("harmless", 0) + result.get("undetected", 0)
            label = result.get("popular_threat") or ""
            if mal == 0 and sus == 0:
                tag = "ok"
                verdict = f"LIMPIO segun {tot} motores"
            elif mal >= 5:
                tag = "bad"
                verdict = f"MALICIOSO ({mal}/{tot} motores)"
            else:
                tag = "warn"
                verdict = f"Sospechoso ({mal} maliciosos, {sus} sospechosos / {tot})"
            detail = (
                f"Limpio: {harmless}  |  "
                f"Etiqueta comun: {label or '-'}  |  "
                f"Visto por primera vez: {result.get('first_seen','?')}"
            )
            self.check_tree.insert("", "end", tags=(tag,), values=(
                source, verdict, detail
            ))

    def _save_vt_key(self):
        cfg_mod.set_value("vt_api_key", self.vt_api_key.get().strip())
        messagebox.showinfo(APP_TITLE, "VirusTotal API-Key guardada.")

    def _save_mb_key(self):
        cfg_mod.set_value("mb_auth_key", self.mb_auth_key.get().strip())
        messagebox.showinfo(APP_TITLE, "MalwareBazaar Auth-Key guardada.")


def main():
    root = tk.Tk()
    setup_scaling(root)
    SecurityApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
