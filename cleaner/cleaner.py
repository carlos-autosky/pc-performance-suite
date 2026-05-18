"""
Disk & Temp Cleaner - PC Performance Suite.

Detecta archivos temporales, cache de navegadores, papelera y logs.
Antes de borrar, mueve a cuarentena (rollback_log/quarantine) para
permitir restaurar. La papelera se vacia con shell, irreversible (queda
registrado pero sin contenido restaurable).
"""

import os
import sys
import shutil
import threading
import tkinter as tk
from pathlib import Path
from datetime import datetime, timedelta
from tkinter import ttk, messagebox
from concurrent.futures import ThreadPoolExecutor, as_completed

# Windows API para tamano fisico en disco (incluye placeholders OneDrive)
if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes
    _GetCompressedFileSizeW = ctypes.windll.kernel32.GetCompressedFileSizeW
    _GetCompressedFileSizeW.argtypes = [
        wintypes.LPCWSTR, ctypes.POINTER(wintypes.DWORD)
    ]
    _GetCompressedFileSizeW.restype = wintypes.DWORD
    _INVALID_FILE_SIZE = 0xFFFFFFFF
else:
    _GetCompressedFileSizeW = None


def _size_on_disk(path):
    """
    Tamano FISICO en disco. Considera placeholders de OneDrive
    (Files On-Demand), sparse files y compresion NTFS.
    Devuelve None si no se pudo determinar.
    """
    if _GetCompressedFileSizeW is None:
        return None
    try:
        high = wintypes.DWORD(0)
        low = _GetCompressedFileSizeW(str(path), ctypes.byref(high))
        if low == _INVALID_FILE_SIZE:
            err = ctypes.GetLastError()
            if err != 0:
                return None
        return (int(high.value) << 32) | int(low)
    except Exception:
        return None

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core import style as _style_mod
_style_mod.apply_saved_theme()
from core.style import COLORS, FONTS, configure_ttk, color_for_value, COPYRIGHT
from core.ui_kit import KpiCard, SectionCard, StatusPill
from core.ctk_kit import init_ctk, Btn, Check, Spin, Entry
from core.scale import setup_scaling, s
from core.progress import ProgressOverlay
import customtkinter as ctk
from core import rollback
from core import system_info
init_ctk()


APP_TITLE = "Limpiador de Disco y Temporales"
APP_VERSION = "1.0.0"
SUITE_NAME = "Suite de Optimizacion PC"
MODULE_NAME = "cleaner"

USER = os.environ.get("USERNAME", "")
LOCAL = os.environ.get("LOCALAPPDATA", "")
APPDATA = os.environ.get("APPDATA", "")
TEMP = os.environ.get("TEMP", "")
TMP = os.environ.get("TMP", "")
WINDIR = os.environ.get("WINDIR", "C:\\Windows")

DEFAULT_AGE_DAYS = 7


def fmt_bytes(n):
    return system_info.fmt_bytes(n)


CATEGORIES = [
    {
        "id": "user_temp",
        "name": "Temp del usuario",
        "desc": "%TEMP% — archivos temporales del usuario actual.",
        "paths": [TEMP, TMP],
        "skip_protect": ["chrome", "edge", "firefox"],
    },
    {
        "id": "windows_temp",
        "name": "Temp de Windows",
        "desc": "C:\\Windows\\Temp — archivos temporales del sistema (requiere admin).",
        "paths": [str(Path(WINDIR) / "Temp")],
    },
    {
        "id": "prefetch",
        "name": "Prefetch",
        "desc": "C:\\Windows\\Prefetch — datos de pre-carga obsoletos. Se reconstruye.",
        "paths": [str(Path(WINDIR) / "Prefetch")],
    },
    {
        "id": "edge_cache",
        "name": "Cache de Microsoft Edge",
        "desc": "Cache de imagenes y datos de Edge. No borra historial ni contrasenas.",
        "paths": [
            str(Path(LOCAL) / "Microsoft" / "Edge" / "User Data" / "Default" / "Cache" / "Cache_Data"),
            str(Path(LOCAL) / "Microsoft" / "Edge" / "User Data" / "Default" / "Code Cache"),
        ],
    },
    {
        "id": "chrome_cache",
        "name": "Cache de Google Chrome",
        "desc": "Cache de imagenes y datos de Chrome. No borra historial ni contrasenas.",
        "paths": [
            str(Path(LOCAL) / "Google" / "Chrome" / "User Data" / "Default" / "Cache" / "Cache_Data"),
            str(Path(LOCAL) / "Google" / "Chrome" / "User Data" / "Default" / "Code Cache"),
        ],
    },
    {
        "id": "firefox_cache",
        "name": "Cache de Firefox",
        "desc": "cache2 de Firefox. No borra historial ni contrasenas.",
        "paths": [str(Path(LOCAL) / "Mozilla" / "Firefox" / "Profiles")],
        "subglob": "*/cache2",
    },
    {
        "id": "winupdate_cache",
        "name": "Cache de Windows Update",
        "desc": "C:\\Windows\\SoftwareDistribution\\Download — descargas de WU obsoletas.",
        "paths": [str(Path(WINDIR) / "SoftwareDistribution" / "Download")],
    },
    {
        "id": "thumbnails",
        "name": "Miniaturas (thumbnails)",
        "desc": "Cache de miniaturas del Explorador.",
        "paths": [str(Path(LOCAL) / "Microsoft" / "Windows" / "Explorer")],
        "filter_ext": [".db"],
    },
    {
        "id": "logs",
        "name": "Registros antiguos",
        "desc": "Archivos *.log mayores a la antiguedad seleccionada en Temp.",
        "paths": [TEMP],
        "filter_ext": [".log", ".tmp", ".old"],
    },
    {
        "id": "crash_dumps",
        "name": "Volcados de error (crash dumps)",
        "desc": "Volcados de memoria (.dmp) que ocupan mucho espacio.",
        "paths": [
            str(Path(LOCAL) / "CrashDumps"),
            str(Path(WINDIR) / "Minidump"),
        ],
    },
]


def scan_category(cat, age_days):
    """Devuelve {paths, total_size, count} de archivos elegibles."""
    cutoff = (datetime.now() - timedelta(days=age_days)).timestamp()
    files = []
    total = 0
    for raw_path in cat["paths"]:
        if not raw_path:
            continue
        base = Path(raw_path)
        if not base.exists():
            continue

        targets = [base]
        if cat.get("subglob"):
            try:
                targets = [p for p in base.glob(cat["subglob"]) if p.exists()]
            except Exception:
                targets = []

        for tgt in targets:
            try:
                for root, dirs, fnames in os.walk(tgt):
                    if cat.get("skip_protect"):
                        rl = root.lower()
                        if any(p in rl for p in cat["skip_protect"]):
                            if cat["id"] == "user_temp":
                                pass
                    for fn in fnames:
                        full = Path(root) / fn
                        try:
                            st = full.stat()
                        except OSError:
                            continue
                        if cat.get("filter_ext"):
                            if full.suffix.lower() not in cat["filter_ext"]:
                                continue
                        if st.st_mtime > cutoff and cat["id"] not in ("crash_dumps",):
                            continue
                        files.append(str(full))
                        total += st.st_size
            except Exception:
                continue
    return {"count": len(files), "size": total, "files": files}


def clean_category(cat, files, dry_run=False):
    """Mueve archivos a cuarentena (rollback). Devuelve summary."""
    if dry_run:
        return {"moved": 0, "size": 0, "entry": None, "failed": []}
    if not files:
        return {"moved": 0, "size": 0, "entry": None, "failed": []}

    entry, failed = rollback.quarantine_files_batch(
        module=MODULE_NAME,
        paths=files,
        group_label=f"Limpieza: {cat['name']} ({len(files)} archivos)",
    )
    if entry is None:
        return {"moved": 0, "size": 0, "entry": None, "failed": failed}
    return {
        "moved": entry["payload"]["count"],
        "size": entry["payload"]["total_bytes"],
        "entry": entry,
        "failed": failed,
    }


# ---------- Explorador de tamano de carpetas ----------

def _dir_size_recursive(path):
    """
    Suma recursiva. Devuelve (logical_size, physical_size, file_count).
    physical_size considera placeholders OneDrive (tamano real en disco).
    """
    total_logical = 0
    total_physical = 0
    file_count = 0
    try:
        for root, _dirs, files in os.walk(path):
            for f in files:
                full = os.path.join(root, f)
                try:
                    st = os.stat(full)
                    total_logical += st.st_size
                    file_count += 1
                except (OSError, PermissionError):
                    continue
                pd = _size_on_disk(full)
                total_physical += pd if pd is not None else st.st_size
    except (PermissionError, OSError):
        pass
    return total_logical, total_physical, file_count


def scan_folder_contents(path, on_progress=None, on_started=None):
    """
    Lista subcarpetas y archivos en path con su tamano total recursivo.
    Devuelve lista [{name, full_path, is_dir, size, file_count}]
    ordenada de MAYOR a MENOR por tamano.
    Usa threads para acelerar el computo de tamanos de subcarpetas.

    on_progress: callback(done:int, total:int, current_name:str) llamado
                 cada vez que se completa el calculo de una subcarpeta.
    on_started:  callback(total_dirs:int, file_count:int) al inicio,
                 una vez que ya se sabe el total a procesar.
    """
    p = Path(path)
    if not p.exists() or not p.is_dir():
        return []

    items = []
    dir_entries = []

    try:
        for entry in os.scandir(p):
            try:
                if entry.is_dir(follow_symlinks=False):
                    dir_entries.append(entry)
                elif entry.is_file(follow_symlinks=False):
                    try:
                        st = entry.stat()
                        pd = _size_on_disk(entry.path)
                        items.append({
                            "name": entry.name,
                            "full_path": entry.path,
                            "is_dir": False,
                            "size": st.st_size,
                            "size_disk": pd if pd is not None else st.st_size,
                            "file_count": 1,
                        })
                    except OSError:
                        pass
            except OSError:
                continue
    except (PermissionError, OSError):
        return []

    total_dirs = len(dir_entries)
    file_count = len(items)
    if on_started:
        try:
            on_started(total_dirs, file_count)
        except Exception:
            pass

    if dir_entries:
        with ThreadPoolExecutor(max_workers=8) as ex:
            futures = {ex.submit(_dir_size_recursive, e.path): e for e in dir_entries}
            done = 0
            for fut in as_completed(futures):
                entry = futures[fut]
                try:
                    size_log, size_phy, count = fut.result()
                except Exception:
                    size_log, size_phy, count = 0, 0, 0
                items.append({
                    "name": entry.name,
                    "full_path": entry.path,
                    "is_dir": True,
                    "size": size_log,
                    "size_disk": size_phy,
                    "file_count": count,
                })
                done += 1
                if on_progress:
                    try:
                        on_progress(done, total_dirs, entry.name)
                    except Exception:
                        pass

    # Ordena por tamano FISICO (lo que realmente ocupa)
    items.sort(key=lambda x: x.get("size_disk", x["size"]), reverse=True)
    return items


# ---------- Treemap (slice-and-dice) ----------

# Paleta de colores planos para el treemap
TREEMAP_PALETTE = [
    "#3b82f6", "#22c55e", "#f59e0b", "#ef4444",
    "#a855f7", "#06b6d4", "#84cc16", "#ec4899",
    "#14b8a6", "#f97316", "#6366f1", "#eab308",
    "#10b981", "#d946ef", "#0ea5e9", "#facc15",
]
TREEMAP_FILE_COLOR = "#6b7280"


def squarify(items, x, y, w, h):
    """
    Devuelve [(item, (rx, ry, rw, rh))] usando slice-and-dice.
    Items deben tener 'size_disk' o 'size'.
    """
    if not items or w <= 0 or h <= 0:
        return []

    def get_size(it):
        return it.get("size_disk", it.get("size", 0)) or 0

    items = sorted(items, key=get_size, reverse=True)
    items = [it for it in items if get_size(it) > 0]
    if not items:
        return []

    out = []
    _slice_and_dice(items, x, y, w, h, out, get_size)
    return out


def _slice_and_dice(items, x, y, w, h, out, get_size):
    if not items or w <= 1 or h <= 1:
        return
    total = sum(get_size(it) for it in items)
    if total <= 0:
        return
    if len(items) == 1:
        out.append((items[0], (x, y, w, h)))
        return

    # Tomar items hasta que sumen ~50% del total
    half = total / 2
    cum = 0
    split = 1
    for i, it in enumerate(items):
        cum += get_size(it)
        if cum >= half:
            split = max(1, i + 1)
            break

    a = items[:split]
    b = items[split:]
    sum_a = sum(get_size(it) for it in a)
    sum_b = sum(get_size(it) for it in b)
    if sum_a == 0 and sum_b == 0:
        return

    horizontal = w >= h
    if horizontal:
        wa = w * (sum_a / total) if total > 0 else 0
        if len(a) == 1:
            out.append((a[0], (x, y, wa, h)))
        else:
            _slice_and_dice(a, x, y, wa, h, out, get_size)
        if len(b) == 1:
            out.append((b[0], (x + wa, y, w - wa, h)))
        elif b:
            _slice_and_dice(b, x + wa, y, w - wa, h, out, get_size)
    else:
        ha = h * (sum_a / total) if total > 0 else 0
        if len(a) == 1:
            out.append((a[0], (x, y, w, ha)))
        else:
            _slice_and_dice(a, x, y, w, ha, out, get_size)
        if len(b) == 1:
            out.append((b[0], (x, y + ha, w, h - ha)))
        elif b:
            _slice_and_dice(b, x, y + ha, w, h - ha, out, get_size)


# ---------- UI ----------

class CleanerApp:
    def __init__(self, root):
        self.root = root
        self.root.title(f"{APP_TITLE} - {SUITE_NAME}")
        self.root.geometry(f"{s(1280)}x{s(960)}")
        self.root.minsize(s(1100), s(820))
        self.root.configure(bg=COLORS["bg"])
        configure_ttk(self.root)

        self.age_days = tk.IntVar(value=DEFAULT_AGE_DAYS)
        self.scan_results = {}
        self.cat_vars = {c["id"]: tk.BooleanVar(value=True) for c in CATEGORIES}
        self.row_widgets = {}

        self.build_ui()
        self.scan_async()

    def build_ui(self):
        head = tk.Frame(self.root, bg=COLORS["bg"])
        head.pack(fill="x", padx=20, pady=(16, 6))
        left = tk.Frame(head, bg=COLORS["bg"])
        left.pack(side="left")
        tk.Label(left, text=APP_TITLE, bg=COLORS["bg"], fg=COLORS["text"],
                 font=FONTS["title"]).pack(anchor="w")
        tk.Label(left,
                 text="Categorias predefinidas reversibles + Explorador de carpetas con borrado.",
                 bg=COLORS["bg"], fg=COLORS["text_muted"],
                 font=FONTS["body"]).pack(anchor="w", pady=(4, 0))

        right = tk.Frame(head, bg=COLORS["bg"])
        right.pack(side="right")
        Btn(right, text="Historial / Revertir",
            command=self.open_rollback,
            kind="ghost", width=170).pack(side="right", padx=(0, 8))

        kpi = tk.Frame(self.root, bg=COLORS["bg"])
        kpi.pack(fill="x", padx=20, pady=(10, 8))

        self.kpi_total = KpiCard(kpi, title="ESPACIO RECUPERABLE",
                                 value="-", subtitle="-",
                                 accent=COLORS["accent"], show_bar=False)
        self.kpi_files = KpiCard(kpi, title="ARCHIVOS DETECTADOS",
                                 value="-", subtitle="-",
                                 accent=COLORS["info"], show_bar=False)
        self.kpi_disk = KpiCard(kpi, title="DISCO C: USADO",
                                value="-", subtitle="-",
                                accent=COLORS["warn"],
                                show_bar=True, bar_invert=True)
        self.kpi_quar = KpiCard(kpi, title="EN CUARENTENA",
                                value="-", subtitle="-",
                                accent=COLORS["info"], show_bar=False)
        for i, c in enumerate([self.kpi_total, self.kpi_files,
                               self.kpi_disk, self.kpi_quar]):
            c.grid(row=0, column=i, sticky="nsew", padx=6, pady=4)
            kpi.columnconfigure(i, weight=1)

        # Tabview moderno (segmented button)
        self.nb = ctk.CTkTabview(
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
            text_color_disabled=COLORS["text_soft"],
        )
        self.nb.pack(fill="both", expand=True, padx=20, pady=(4, 0))

        self.nb.add("Categorias predefinidas")
        self.nb.add("Explorador de carpetas")
        self.tab_cats = self.nb.tab("Categorias predefinidas")
        self.tab_explorer = self.nb.tab("Explorador de carpetas")

        self.status_var = tk.StringVar(value="Listo")

        self._build_categories_tab()
        self._build_explorer_tab()

        # Pie de firma con copyright
        signbar = tk.Frame(self.root, bg=COLORS["bg"])
        signbar.pack(side="bottom", fill="x", padx=20, pady=(0, 8))
        tk.Label(signbar,
                 text=f"{APP_TITLE} v{APP_VERSION}  -  {COPYRIGHT}",
                 bg=COLORS["bg"], fg=COLORS["text_soft"],
                 font=FONTS["small"]).pack(side="right")

    def _build_categories_tab(self):
        parent = self.tab_cats

        # Footer fijo abajo
        actions = tk.Frame(parent, bg=COLORS["bg"], height=64)
        actions.pack(side="bottom", fill="x", padx=4, pady=(8, 8))
        actions.pack_propagate(False)
        Btn(actions, text="EJECUTAR: limpiar (cuarentena reversible)",
            command=self.clean_async,
            kind="accent", width=340, height=42).pack(side="left", pady=8)
        Btn(actions, text="Marcar todos",
            command=lambda: self._toggle_all(True),
            kind="ghost", width=130, height=42).pack(side="left", padx=8, pady=8)
        Btn(actions, text="Desmarcar todos",
            command=lambda: self._toggle_all(False),
            kind="ghost", width=140, height=42).pack(side="left", pady=8)
        Btn(actions, text="Re-escanear",
            command=self.scan_async,
            kind="ghost", width=130, height=42).pack(side="left", padx=8, pady=8)

        controls = SectionCard(parent, title="Filtros y opciones")
        controls.pack(fill="x", padx=4, pady=(8, 6))
        body = controls.body()
        row = tk.Frame(body, bg=COLORS["bg_card"])
        row.pack(fill="x")
        tk.Label(row, text="Antiguedad minima de archivos:",
                 bg=COLORS["bg_card"], fg=COLORS["text"],
                 font=FONTS["label_b"]).pack(side="left")
        Spin(row, from_=0, to=365,
             textvariable=self.age_days).pack(side="left", padx=(8, 4))
        tk.Label(row, text="dias  -  archivos mas recientes se conservan",
                 bg=COLORS["bg_card"], fg=COLORS["text_muted"],
                 font=FONTS["label"]).pack(side="left", padx=(0, 16))
        Btn(row, text="Aplicar filtro y re-escanear",
            command=self.scan_async,
            kind="ghost", width=200).pack(side="left")

        cats = SectionCard(parent, title="Categorias detectadas")
        cats.pack(fill="both", expand=True, padx=4, pady=(4, 6))
        body = cats.body()

        hdr = tk.Frame(body, bg=COLORS["bg_card"])
        hdr.pack(fill="x")
        for label, w in [("", 30), ("CATEGORIA", 280),
                         ("DETALLE", 380), ("ARCHIVOS", 90),
                         ("TAMANO", 110), ("ESTADO", 100)]:
            tk.Label(hdr, text=label, bg=COLORS["bg_card"],
                     fg=COLORS["text_muted"], font=FONTS["small"],
                     width=int(w / 8), anchor="w").pack(side="left", padx=4)

        self.rows_frame = tk.Frame(body, bg=COLORS["bg_card"])
        self.rows_frame.pack(fill="both", expand=True, pady=(8, 0))

        for cat in CATEGORIES:
            r = tk.Frame(self.rows_frame, bg=COLORS["bg_card"])
            r.pack(fill="x", pady=2)
            cb = Check(r, text="", variable=self.cat_vars[cat["id"]])
            cb.pack(side="left", padx=4)
            tk.Label(r, text=cat["name"], bg=COLORS["bg_card"],
                     fg=COLORS["text"], font=FONTS["label_b"],
                     width=34, anchor="w").pack(side="left", padx=4)
            tk.Label(r, text=cat["desc"], bg=COLORS["bg_card"],
                     fg=COLORS["text_muted"], font=FONTS["label"],
                     width=46, anchor="w").pack(side="left", padx=4)
            count_var = tk.StringVar(value="-")
            size_var = tk.StringVar(value="-")
            state_pill = StatusPill(
                r, text="ESCANEANDO",
                kind="info", width=100, height=22,
                on_click=lambda c=cat: self._open_category_folder(c),
            )
            tk.Label(r, textvariable=count_var, bg=COLORS["bg_card"],
                     fg=COLORS["text"], font=FONTS["label"],
                     width=11, anchor="w").pack(side="left", padx=4)
            tk.Label(r, textvariable=size_var, bg=COLORS["bg_card"],
                     fg=COLORS["text"], font=FONTS["label_b"],
                     width=14, anchor="w").pack(side="left", padx=4)
            state_pill.pack(side="left", padx=4)
            self.row_widgets[cat["id"]] = {
                "count_var": count_var, "size_var": size_var,
                "state_pill": state_pill,
            }

    def _build_explorer_tab(self):
        parent = self.tab_explorer
        self.explorer_path_var = tk.StringVar(value="C:\\")
        self.explorer_items = {}
        self.explorer_status_var = tk.StringVar(
            value="Selecciona una ruta y pulsa 'Explorar' (puede tardar segun el tamano)."
        )

        # Footer abajo con EJECUTAR borrar
        footer = tk.Frame(parent, bg=COLORS["bg"], height=64)
        footer.pack(side="bottom", fill="x", padx=4, pady=(8, 8))
        footer.pack_propagate(False)
        Btn(footer, text="EJECUTAR: borrar carpeta seleccionada",
            command=self._explorer_delete,
            kind="danger", width=340, height=42).pack(side="left", pady=8)
        Btn(footer, text="Entrar",
            command=self._explorer_enter,
            kind="ghost", width=100, height=42).pack(side="left", padx=8, pady=8)
        tk.Label(footer, textvariable=self.explorer_status_var,
                 bg=COLORS["bg"], fg=COLORS["text_muted"],
                 font=FONTS["label"]).pack(side="right", padx=8)

        # Toolbar de navegacion
        bar_card = SectionCard(parent, title="Navegacion")
        bar_card.pack(fill="x", padx=4, pady=(8, 6))
        bar = bar_card.body()
        row = tk.Frame(bar, bg=COLORS["bg_card"])
        row.pack(fill="x")
        Btn(row, text="< Subir",
            command=self._explorer_up,
            kind="ghost", width=90).pack(side="left")
        Btn(row, text="Carpeta usuario",
            command=self._explorer_user,
            kind="ghost", width=140).pack(side="left", padx=4)

        # Selector de unidad (combobox)
        tk.Label(row, text="  Unidad:",
                 bg=COLORS["bg_card"], fg=COLORS["text_muted"],
                 font=FONTS["label_b"]).pack(side="left", padx=(12, 4))
        drives = self._list_drive_paths()
        self.drive_combo = ttk.Combobox(
            row, values=drives, state="readonly", width=10
        )
        if drives:
            self.drive_combo.set(drives[0])
        self.drive_combo.bind(
            "<<ComboboxSelected>>",
            lambda _e: self._on_drive_selected(),
        )
        self.drive_combo.pack(side="left", padx=4)

        # Examinar carpeta (filedialog nativo de Windows)
        Btn(row, text="Examinar carpeta...",
            command=self._browse_folder,
            kind="accent", width=180).pack(side="left", padx=8)

        Btn(row, text="Refrescar discos",
            command=self._refresh_drives,
            kind="ghost", width=140).pack(side="left", padx=(8, 0))

        path_row = tk.Frame(bar, bg=COLORS["bg_card"])
        path_row.pack(fill="x", pady=(8, 0))
        tk.Label(path_row, text="Ruta:",
                 bg=COLORS["bg_card"], fg=COLORS["text"],
                 font=FONTS["label_b"]).pack(side="left")
        path_entry = Entry(path_row, textvariable=self.explorer_path_var, width=600)
        path_entry.pack(side="left", padx=8, fill="x", expand=True)
        path_entry.bind("<Return>", lambda _e: self._explorer_scan())
        Btn(path_row, text="Explorar",
            command=self._explorer_scan,
            kind="accent", width=120).pack(side="left", padx=4)

        # Barra de progreso (visible solo durante el escaneo)
        self._prog_wrap = tk.Frame(parent, bg=COLORS["bg"])
        self._prog_wrap.pack(fill="x", padx=4, pady=(2, 4))
        self.explorer_progress_label = tk.Label(
            self._prog_wrap, text="",
            bg=COLORS["bg"], fg=COLORS["accent"],
            font=FONTS["label_b"], anchor="w"
        )
        self.explorer_progress = ctk.CTkProgressBar(
            self._prog_wrap, mode="indeterminate",
            progress_color=COLORS["accent"],
            fg_color=COLORS["bg_card_alt"],
            border_color=COLORS["border"],
            height=14,
        )
        self.explorer_progress.set(0)
        # Por default ocultos; aparecen al iniciar escaneo

        # PanedWindow: treemap arriba, tabla abajo. Divisor arrastrable
        # para que el usuario decida cuanto espacio dar a cada uno.
        paned = ttk.PanedWindow(parent, orient="vertical")
        paned.pack(fill="both", expand=True, padx=4, pady=(8, 4))

        # ----- Pane 1: Treemap -----
        tm_card = tk.Frame(paned, bg=COLORS["bg_card"],
                            highlightbackground=COLORS["border"],
                            highlightthickness=1)
        tk.Label(tm_card,
                 text="Mapa proporcional  (arrastra el divisor para resize)",
                 bg=COLORS["bg_card"], fg=COLORS["text"],
                 font=FONTS["h2"], anchor="w").pack(fill="x", padx=14, pady=(10, 4))
        self.treemap_canvas = tk.Canvas(
            tm_card, bg=COLORS["bg_card_alt"],
            highlightthickness=0,
        )
        self.treemap_canvas.pack(fill="both", expand=True, padx=14, pady=(0, 14))
        self.treemap_canvas.bind("<Configure>", lambda _e: self._draw_treemap())
        self.treemap_canvas.bind("<Button-1>", self._on_treemap_click)
        self.treemap_canvas.bind("<Motion>", self._on_treemap_hover)
        self.treemap_canvas.bind(
            "<Leave>", lambda _e: self.treemap_canvas.delete("tooltip")
        )
        self._treemap_rects = []  # [(item, (x,y,w,h))]
        self._treemap_tooltip = None
        paned.add(tm_card, weight=1)

        # ----- Pane 2: Tabla de Contenido -----
        tree_card = SectionCard(paned, title="Contenido (mayor a menor tamano)")
        body = tree_card.body()
        paned.add(tree_card, weight=2)

        cols = ("name", "size_disk", "size", "pct", "files")
        self.explorer_tree = ttk.Treeview(body, columns=cols,
                                          show="headings", height=18)
        headings = {"name": "NOMBRE",
                    "size_disk": "EN DISCO",
                    "size": "TOTAL (logico)",
                    "pct": "%",
                    "files": "ARCHIVOS"}
        widths = {"name": 380, "size_disk": 120, "size": 130,
                  "pct": 70, "files": 100}
        anchors = {"name": "w", "size_disk": "e", "size": "e",
                   "pct": "e", "files": "e"}
        for c in cols:
            self.explorer_tree.heading(c, text=headings[c])
            self.explorer_tree.column(c, width=widths[c], anchor=anchors[c])
        self.explorer_tree.pack(side="left", fill="both", expand=True)
        sb = ttk.Scrollbar(body, orient="vertical",
                           command=self.explorer_tree.yview)
        sb.pack(side="right", fill="y")
        self.explorer_tree.configure(yscrollcommand=sb.set)
        self.explorer_tree.bind("<Double-1>", lambda _e: self._explorer_enter())

    def _toggle_all(self, value):
        for v in self.cat_vars.values():
            v.set(value)

    def _open_category_folder(self, cat):
        """Abre el Explorador de Windows en la carpeta de la categoria."""
        paths = cat.get("paths", []) or []
        opened = []
        not_found = []
        for raw in paths:
            if not raw:
                continue
            p = Path(raw)
            target = None
            if cat.get("subglob"):
                try:
                    matches = list(p.glob(cat["subglob"]))
                    if matches:
                        target = str(matches[0])
                except Exception:
                    pass
            if not target and p.exists():
                target = str(p)
            if not target:
                not_found.append(raw)
                continue
            try:
                os.startfile(target)
                opened.append(target)
            except Exception:
                try:
                    import subprocess
                    subprocess.Popen(["explorer", target])
                    opened.append(target)
                except Exception as e:
                    not_found.append(f"{target}: {e}")
        if not opened:
            messagebox.showinfo(
                APP_TITLE,
                f"No se encontro la carpeta de '{cat['name']}'.\n\n"
                f"Rutas que intente:\n" + "\n".join(f"- {x}" for x in not_found)
            )

    # ---------- Explorador de carpetas ----------

    def _list_drive_paths(self):
        """Devuelve lista de mountpoints: ['C:\\\\', 'D:\\\\', ...]."""
        import psutil
        drives = []
        try:
            for p in psutil.disk_partitions(all=False):
                drives.append(p.mountpoint)
        except Exception:
            pass
        if not drives:
            drives = ["C:\\"]
        return drives

    def _on_drive_selected(self):
        """Cuando el usuario elige una unidad del combobox, solo carga
        la ruta en el campo. NO escanea automaticamente — el usuario
        decide si pulsa Explorar o navega antes a una subcarpeta."""
        drive = self.drive_combo.get()
        if drive:
            self.explorer_path_var.set(drive)
            self.explorer_status_var.set(
                f"Unidad seleccionada: {drive}. Pulsa 'Explorar' o "
                "'Examinar carpeta...' para elegir una subcarpeta."
            )

    def _browse_folder(self):
        """Abre filedialog nativo para que el usuario elija cualquier
        carpeta del sistema. Tras elegir, lanza el escaneo automatico."""
        from tkinter import filedialog
        initial = self.explorer_path_var.get() or "C:\\"
        try:
            path = filedialog.askdirectory(
                title="Selecciona la carpeta a explorar",
                initialdir=initial,
                mustexist=True,
            )
        except Exception:
            path = ""
        if not path:
            return
        # Normalizar a backslash
        path = str(Path(path))
        self.explorer_path_var.set(path)
        self._explorer_scan()

    def _list_drives(self):
        """
        Devuelve [(label, mountpoint, kind_text)] para cada disco montado.
        kind_text: 'fijo', 'extraible', 'red', 'cd', etc.
        """
        import psutil
        rows = []
        try:
            for p in psutil.disk_partitions(all=False):
                mp = p.mountpoint
                opts = (p.opts or "").lower()
                # Determinar tipo
                if "removable" in opts or "cdrom" in opts:
                    kind_text = "Extraible"
                elif "fixed" in opts:
                    kind_text = "Fijo"
                elif p.fstype.lower() in ("cdfs", "udf"):
                    kind_text = "CD/DVD"
                else:
                    kind_text = p.fstype or "?"
                # Tamano libre/total para subtitulo
                try:
                    u = psutil.disk_usage(mp)
                    free_gb = u.free / (1024 ** 3)
                    total_gb = u.total / (1024 ** 3)
                    size_text = f"{free_gb:.0f}/{total_gb:.0f} GB"
                except Exception:
                    size_text = ""
                # Limpiar label: "C:\" -> "C:"
                drive_letter = mp.rstrip("\\").rstrip("/")
                label = f"{drive_letter}  {kind_text[:1]}"  # "C:  F" o "D:  E"
                rows.append((label, mp, kind_text))
        except Exception:
            pass
        # Si no detecto nada, fallback C:
        if not rows:
            rows = [("C:  F", "C:\\", "Fijo")]
        return rows

    def _explorer_goto(self, path):
        self.explorer_path_var.set(path)
        self._explorer_scan()

    def _refresh_drives(self):
        # Recrea la pestana del explorador para que detecte nuevos discos
        for w in self.tab_explorer.winfo_children():
            w.destroy()
        self._build_explorer_tab()

    def _explorer_up(self):
        p = Path(self.explorer_path_var.get())
        if p.parent != p:
            self.explorer_path_var.set(str(p.parent))
            self._explorer_scan()

    def _explorer_home(self):
        self.explorer_path_var.set("C:\\")
        self._explorer_scan()

    def _explorer_user(self):
        userdir = os.environ.get("USERPROFILE") or str(Path.home())
        self.explorer_path_var.set(userdir)
        self._explorer_scan()

    def _explorer_enter(self):
        sel = self.explorer_tree.selection()
        if not sel:
            return
        item = self.explorer_items.get(sel[0])
        if item and item["is_dir"]:
            self.explorer_path_var.set(item["full_path"])
            self._explorer_scan()

    def _show_progress(self, text="Iniciando..."):
        self.explorer_progress_label.config(text=text)
        self.explorer_progress_label.pack(fill="x", padx=4, pady=(0, 2))
        self.explorer_progress.pack(fill="x", padx=4, pady=(0, 4))
        self.explorer_progress.configure(mode="indeterminate")
        self.explorer_progress.start()

    def _hide_progress(self):
        try:
            self.explorer_progress.stop()
        except Exception:
            pass
        self.explorer_progress.pack_forget()
        self.explorer_progress_label.pack_forget()

    def _set_progress_determinate(self, done, total):
        try:
            self.explorer_progress.stop()
            self.explorer_progress.configure(mode="determinate")
            value = (done / total) if total else 0.0
            self.explorer_progress.set(min(1.0, max(0.0, value)))
        except Exception:
            pass

    def _explorer_scan(self):
        path = self.explorer_path_var.get()
        self.explorer_status_var.set(f"Escaneando {path} ...")
        for it in self.explorer_tree.get_children():
            self.explorer_tree.delete(it)
        self._show_progress(f"Leyendo estructura de {path} ...")
        threading.Thread(target=self._explorer_scan_worker,
                         args=(path,), daemon=True).start()

    def _explorer_scan_worker(self, path):
        # Callbacks que actualizan UI desde el thread (via after)
        def on_started(total_dirs, file_count):
            def update():
                if total_dirs > 0:
                    self._set_progress_determinate(0, total_dirs)
                    self.explorer_progress_label.config(
                        text=f"Calculando tamano de {total_dirs} carpetas... "
                             f"({file_count} archivos sueltos detectados)"
                    )
                else:
                    # Sin subcarpetas, solo archivos: oculta barra rapidamente
                    self.explorer_progress_label.config(
                        text=f"Sin subcarpetas. {file_count} archivos."
                    )
            self.root.after(0, update)

        def on_progress(done, total, name):
            def update():
                self._set_progress_determinate(done, total)
                pct = (done / total * 100) if total else 0
                self.explorer_progress_label.config(
                    text=f"{done}/{total} carpetas ({pct:.0f}%)  ->  {name[:60]}"
                )
            self.root.after(0, update)

        try:
            items = scan_folder_contents(
                path,
                on_progress=on_progress,
                on_started=on_started,
            )
        except Exception as e:
            self.root.after(0, lambda: self._hide_progress())
            self.root.after(0, lambda: self.explorer_status_var.set(
                f"Error al escanear: {e}"
            ))
            return

        def populate():
            self._hide_progress()
            self.explorer_items = {}
            for it in self.explorer_tree.get_children():
                self.explorer_tree.delete(it)
            if not items:
                self.explorer_status_var.set(
                    f"Vacia o sin permisos: {path}"
                )
                return
            total_disk = sum(i.get("size_disk", i["size"]) for i in items)
            total_logical = sum(i["size"] for i in items)
            for i, it in enumerate(items):
                iid = str(i)
                self.explorer_items[iid] = it
                size_disk = it.get("size_disk", it["size"])
                pct = (size_disk / total_disk * 100) if total_disk > 0 else 0
                marker = "\U0001F4C1" if it["is_dir"] else "\U0001F4C4"
                self.explorer_tree.insert(
                    "", "end", iid=iid,
                    values=(
                        f"{marker}  {it['name']}",
                        fmt_bytes(size_disk),
                        fmt_bytes(it["size"]),
                        f"{pct:.1f}%",
                        f"{it['file_count']:,}",
                    )
                )
            cloud_diff = total_logical - total_disk
            cloud_note = ""
            if cloud_diff > 100 * 1024 * 1024 and total_logical > 0:
                pct_cloud = (cloud_diff / total_logical) * 100
                cloud_note = (
                    f"  |  Archivos en la nube (no descargados): "
                    f"{fmt_bytes(cloud_diff)} ({pct_cloud:.0f}%)"
                )
            self.explorer_status_var.set(
                f"{len(items)} elementos.  "
                f"En disco: {fmt_bytes(total_disk)}  /  "
                f"Total logico: {fmt_bytes(total_logical)}{cloud_note}"
            )
            self._draw_treemap()

        self.root.after(0, populate)

    # ---------- Treemap ----------

    def _draw_treemap(self):
        c = self.treemap_canvas
        c.delete("all")
        w = c.winfo_width()
        h = c.winfo_height()
        if w < 50 or h < 50:
            return
        items = list((self.explorer_items or {}).values())
        if not items:
            c.create_text(w / 2, h / 2,
                           text="(sin datos para mostrar)",
                           fill=COLORS["text_muted"],
                           font=FONTS["body"])
            self._treemap_rects = []
            return

        rects = squarify(items, 2, 2, w - 4, h - 4)
        self._treemap_rects = rects

        # Total para porcentajes
        def get_size(it):
            return it.get("size_disk", it.get("size", 0)) or 0
        total = sum(get_size(it) for it in items) or 1

        for idx, (item, (rx, ry, rw, rh)) in enumerate(rects):
            if rw < 2 or rh < 2:
                continue
            # Color
            if item.get("is_dir"):
                color = TREEMAP_PALETTE[idx % len(TREEMAP_PALETTE)]
            else:
                color = TREEMAP_FILE_COLOR
            # Rectangulo
            c.create_rectangle(
                rx, ry, rx + rw, ry + rh,
                fill=color, outline=COLORS["bg_card"], width=1,
                tags=(f"rect_{idx}",),
            )
            # Etiqueta si cabe
            size = get_size(item)
            pct = (size / total) * 100
            label = item["name"]
            if rw > 90 and rh > 30:
                # Texto principal
                marker = "\U0001F4C1 " if item.get("is_dir") else ""
                c.create_text(
                    rx + 6, ry + 6,
                    text=f"{marker}{label[:32]}",
                    anchor="nw", fill="#ffffff",
                    font=FONTS["label_b"],
                )
                if rh > 48:
                    c.create_text(
                        rx + 6, ry + 24,
                        text=f"{fmt_bytes(size)}  -  {pct:.1f}%",
                        anchor="nw", fill="#f0f0f0",
                        font=FONTS["small"],
                    )
            elif rw > 50 and rh > 18:
                c.create_text(
                    rx + 4, ry + 4,
                    text=label[:14],
                    anchor="nw", fill="#ffffff",
                    font=FONTS["small"],
                )

    def _on_treemap_click(self, event):
        for idx, (item, (rx, ry, rw, rh)) in enumerate(self._treemap_rects):
            if rx <= event.x <= rx + rw and ry <= event.y <= ry + rh:
                # Buscar el iid en el treeview
                for iid, it in self.explorer_items.items():
                    if it.get("full_path") == item.get("full_path"):
                        self.explorer_tree.selection_set(iid)
                        self.explorer_tree.see(iid)
                        # Doble clic abrira la carpeta; un clic solo selecciona
                        if event.num == 1 and item.get("is_dir"):
                            # Permite navegar entrando con doble clic en el tree
                            pass
                        break
                break

    def _on_treemap_hover(self, event):
        c = self.treemap_canvas
        # Borra el tooltip anterior COMPLETO (texto + fondo) usando tag
        c.delete("tooltip")
        for idx, (item, (rx, ry, rw, rh)) in enumerate(self._treemap_rects):
            if rx <= event.x <= rx + rw and ry <= event.y <= ry + rh:
                size = item.get("size_disk", item.get("size", 0)) or 0
                pct = ""
                # Calcular % sobre total
                total = sum(
                    (it.get("size_disk", it.get("size", 0)) or 0)
                    for it, _r in self._treemap_rects
                ) or 1
                pct_val = (size / total) * 100
                txt = f"{item['name']}  -  {fmt_bytes(size)}  ({pct_val:.1f}%)"
                tx = min(event.x + 14, c.winfo_width() - 8)
                ty = max(event.y - 24, 6)
                text_id = c.create_text(
                    tx, ty, text=txt, anchor="w",
                    fill=COLORS["text"], font=FONTS["label_b"],
                    tags=("tooltip",),
                )
                bbox = c.bbox(text_id)
                if bbox:
                    bg = c.create_rectangle(
                        bbox[0] - 6, bbox[1] - 3, bbox[2] + 6, bbox[3] + 3,
                        fill=COLORS["bg_card"],
                        outline=COLORS["accent"], width=1,
                        tags=("tooltip",),
                    )
                    c.tag_lower(bg, text_id)
                break

    def _explorer_delete(self):
        sel = self.explorer_tree.selection()
        if not sel:
            messagebox.showinfo(APP_TITLE,
                                "Selecciona una carpeta o archivo en la tabla.")
            return
        iid = sel[0]
        item = self.explorer_items.get(iid)
        if not item:
            return

        path = item["full_path"]
        name = item["name"]
        size_text = fmt_bytes(item["size"])
        kind = "carpeta y todo su contenido" if item["is_dir"] else "archivo"

        choice = messagebox.askyesnocancel(
            APP_TITLE,
            f"Que quieres hacer con esta {kind}?\n\n"
            f"Ruta: {path}\n"
            f"Tamano: {size_text}\n"
            f"Archivos: {item['file_count']:,}\n\n"
            "[SI]  -> Mover a cuarentena (REVERSIBLE desde Historial)\n"
            "[NO]  -> Borrado PERMANENTE (NO se puede deshacer)\n"
            "[CANCELAR] -> No hacer nada"
        )
        if choice is None:
            return

        if choice is True:
            overlay = ProgressOverlay(
                self.root,
                f"Moviendo a cuarentena: {name} ({size_text})..."
            )

            def worker_quarantine():
                try:
                    entry = rollback.quarantine_file(
                        module=MODULE_NAME, src_path=path,
                        label=f"Explorador: {name} ({size_text})"
                    )
                except Exception as e:
                    self.root.after(0, overlay.close)
                    self.root.after(0, lambda: messagebox.showerror(
                        APP_TITLE, f"Error: {e}"
                    ))
                    return
                self.root.after(0, overlay.close)
                if entry and not (isinstance(entry, dict) and "error" in entry):
                    self.root.after(0, lambda: messagebox.showinfo(
                        APP_TITLE,
                        f"Movido a cuarentena.\n\n{path}\n\n"
                        "Puedes restaurarlo desde 'Historial / Revertir'."
                    ))
                    self.root.after(0, self._explorer_scan)
                else:
                    err = (entry.get("error") if isinstance(entry, dict)
                           else "permisos insuficientes o ruta protegida")
                    self.root.after(0, lambda: messagebox.showwarning(
                        APP_TITLE,
                        f"No se pudo mover a cuarentena.\n\n{err}"
                    ))

            threading.Thread(target=worker_quarantine, daemon=True).start()
            return

        # Borrado permanente
        if not messagebox.askyesno(
            APP_TITLE,
            f"CONFIRMACION FINAL\n\n"
            f"Vas a BORRAR PERMANENTEMENTE:\n\n{path}\n"
            f"({size_text}, {item['file_count']:,} archivos)\n\n"
            "Esta operacion NO SE PUEDE DESHACER.\n"
            "No habra rollback.\n\n"
            "Continuar con el borrado permanente?",
            icon="warning"
        ):
            return

        overlay = ProgressOverlay(
            self.root,
            f"Borrando permanentemente: {name} ({size_text})..."
        )

        def worker_delete():
            try:
                if item["is_dir"]:
                    shutil.rmtree(path, ignore_errors=False)
                else:
                    Path(path).unlink()
            except PermissionError as e:
                self.root.after(0, overlay.close)
                self.root.after(0, lambda: messagebox.showerror(
                    APP_TITLE,
                    f"Permiso denegado.\n\n{e}\n\n"
                    "Algunos archivos pueden estar en uso o requerir "
                    "ejecutar como administrador."
                ))
                return
            except Exception as e:
                self.root.after(0, overlay.close)
                self.root.after(0, lambda: messagebox.showerror(
                    APP_TITLE, f"Error al borrar:\n{e}"
                ))
                return
            self.root.after(0, overlay.close)
            self.root.after(0, lambda: messagebox.showinfo(
                APP_TITLE,
                f"Eliminado permanentemente:\n{path}\n({size_text})"
            ))
            self.root.after(0, self._explorer_scan)

        threading.Thread(target=worker_delete, daemon=True).start()

    def open_rollback(self):
        try:
            from Suite import open_rollback_window
            open_rollback_window(self.root)
        except Exception:
            messagebox.showinfo(APP_TITLE,
                                "Abre el lanzador principal y usa "
                                "'Historial / Revertir' para revertir cambios.")

    def scan_async(self):
        self.status_var.set("Escaneando...")
        for cat_id, w in self.row_widgets.items():
            w["state_pill"].update_text("ESCANEANDO", "info")
            w["count_var"].set("-")
            w["size_var"].set("-")
        threading.Thread(target=self._scan_worker, daemon=True).start()

    def _scan_worker(self):
        age = self.age_days.get()
        results = {}
        total_size = 0
        total_files = 0
        for cat in CATEGORIES:
            try:
                r = scan_category(cat, age)
            except Exception as e:
                r = {"count": 0, "size": 0, "files": [], "error": str(e)}
            results[cat["id"]] = r
            total_size += r["size"]
            total_files += r["count"]
            self.root.after(0, self._update_row, cat["id"], r)

        self.scan_results = results
        self.root.after(0, self._update_kpis, total_size, total_files)
        self.root.after(0, lambda: self.status_var.set(
            f"Escaneo completo - {total_files} archivos, "
            f"{fmt_bytes(total_size)} recuperables"
        ))

    def _update_row(self, cat_id, result):
        w = self.row_widgets[cat_id]
        n = result["count"]
        sz = result["size"]
        w["count_var"].set(str(n))
        w["size_var"].set(fmt_bytes(sz))
        if n == 0:
            w["state_pill"].update_text("LIMPIO", "ok")
        elif sz > 100 * 1024 * 1024:
            w["state_pill"].update_text("REVISAR", "warn")
        else:
            w["state_pill"].update_text("LISTO", "info")

    def _update_kpis(self, total_size, total_files):
        self.kpi_total.update_data(
            value=fmt_bytes(total_size),
            subtitle="Espacio liberable", accent=COLORS["accent"],
        )
        self.kpi_files.update_data(
            value=str(total_files),
            subtitle="Archivos detectados", accent=COLORS["info"],
        )
        d = system_info.disk_snapshot()
        self.kpi_disk.update_data(
            value=f"{d['percent']:.0f}%",
            subtitle=f"Libre: {d['free_text']} / {d['total_text']}",
            accent=color_for_value(d['percent'], (50, 85), invert=True),
            bar_value=d["percent"], bar_max=100,
        )
        st = rollback.stats()
        self.kpi_quar.update_data(
            value=fmt_bytes(st["quarantine_bytes"]),
            subtitle=f"{st['active_entries']} entrada(s) reversibles",
            accent=COLORS["info"],
        )

    def clean_async(self):
        selected = [c for c in CATEGORIES if self.cat_vars[c["id"]].get()]
        if not selected:
            messagebox.showinfo(APP_TITLE, "No hay categorias seleccionadas.")
            return
        total_size = sum(self.scan_results.get(c["id"], {}).get("size", 0)
                         for c in selected)
        total_files = sum(self.scan_results.get(c["id"], {}).get("count", 0)
                          for c in selected)
        if total_files == 0:
            messagebox.showinfo(APP_TITLE, "No hay archivos para limpiar en la seleccion.")
            return
        if not messagebox.askyesno(
            APP_TITLE,
            f"Mover a cuarentena {total_files} archivos "
            f"({fmt_bytes(total_size)})?\n\n"
            "Los archivos NO se borran inmediatamente: se mueven a un area "
            "de cuarentena y puedes restaurarlos desde 'Historial / Revertir'."
        ):
            return

        self.status_var.set("Limpiando... no cierres la ventana.")
        overlay = ProgressOverlay(
            self.root,
            f"Moviendo {total_files} archivo(s) a cuarentena..."
        )
        threading.Thread(target=self._clean_worker,
                         args=(selected, overlay), daemon=True).start()

    def _clean_worker(self, selected, overlay):
        results = []
        moved_total = 0
        size_total = 0
        try:
            for cat in selected:
                self.root.after(0, lambda n=cat["name"]:
                                overlay.update_message(f"Procesando: {n}"))
                sr = self.scan_results.get(cat["id"], {})
                files = sr.get("files", [])
                r = clean_category(cat, files)
                moved_total += r["moved"]
                size_total += r["size"]
                results.append((cat, r))
        finally:
            self.root.after(0, overlay.close)

        msg = (f"Limpieza completa.\n\n"
               f"Archivos movidos a cuarentena: {moved_total}\n"
               f"Espacio liberado: {fmt_bytes(size_total)}\n\n"
               f"Para restaurar usa 'Historial / Revertir' en el lanzador.")
        self.root.after(0, lambda: messagebox.showinfo(APP_TITLE, msg))
        self.root.after(0, lambda: self.status_var.set(
            f"Listo - {moved_total} archivos en cuarentena"
        ))
        self.root.after(0, self.scan_async)


def main():
    root = tk.Tk()
    setup_scaling(root)
    CleanerApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
