"""
Guardian Wi-Fi - Suite de Optimizacion PC.

Bloquea redes Wi-Fi peligrosas para que tu PC no se conecte
automatica ni manualmente. Modo blacklist: tu eliges que SSIDs
NO quieres que aparezcan jamas como opcion de conexion.

Usa netsh wlan filter (incluido en Windows). Bloquear/desbloquear
requieren admin. Ver redes y perfiles NO requiere admin.

Limitaciones:
- Aplica al adaptador Wi-Fi nativo de Windows
- No bloquea Ethernet, Bluetooth tethering ni hotspot tipo USB modem
- USB Wi-Fi adapters con driver propio pueden no respetar el filtro
"""

import os
import re
import sys
import ctypes
import threading
import subprocess
import tkinter as tk
from pathlib import Path
from datetime import datetime
from tkinter import ttk, messagebox

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core import style as _style_mod
_style_mod.apply_saved_theme()
from core.style import COLORS, FONTS, configure_ttk, color_for_value, COPYRIGHT
from core.ui_kit import KpiCard, SectionCard, StatusPill
from core.ctk_kit import init_ctk, Btn, Check, Entry
from core.scale import setup_scaling, s
from core.progress import ProgressOverlay
from core import rollback
init_ctk()


APP_TITLE = "Guardian Wi-Fi"
APP_VERSION = "1.1.1"
SUITE_NAME = "Suite de Optimizacion PC"
MODULE_NAME = "wifi_guard"


def is_admin():
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def _run(cmd_args, timeout=30):
    """Ejecuta netsh y devuelve (returncode, stdout, stderr) UTF-8 best-effort."""
    try:
        cp = subprocess.run(
            cmd_args, capture_output=True, timeout=timeout,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        out = _decode(cp.stdout)
        err = _decode(cp.stderr)
        return cp.returncode, out, err
    except Exception as e:
        return 1, "", str(e)


def _decode(b):
    """Decodifica bytes intentando varios encodings (netsh devuelve OEM en ES)."""
    if not b:
        return ""
    for enc in ("utf-8", "cp850", "cp1252", "latin-1"):
        try:
            return b.decode(enc, errors="ignore")
        except Exception:
            continue
    return ""


# ---------- Lecturas (no requieren admin) ----------

def list_interfaces():
    """Devuelve lista de interfaces Wi-Fi: [{name, state, ssid, signal, type}]."""
    code, out, _ = _run(["netsh", "wlan", "show", "interfaces"])
    if code != 0:
        return []
    ifs = []
    cur = {}
    for raw in out.splitlines():
        line = raw.strip()
        if not line:
            if cur:
                ifs.append(cur)
                cur = {}
            continue
        if ":" in line:
            k, _, v = line.partition(":")
            k = k.strip().lower()
            v = v.strip()
            if "nombre" in k or k == "name":
                cur["name"] = v
            elif "ssid" in k and "bssid" not in k:
                cur["ssid"] = v
            elif "estado" in k or k == "state":
                cur["state"] = v
            elif "señal" in k or "se\xf1al" in k or "signal" in k:
                cur["signal"] = v
            elif "tipo de radio" in k or "radio type" in k:
                cur["radio"] = v
    if cur:
        ifs.append(cur)
    return ifs


def list_visible_networks():
    """
    Devuelve [{ssid, auth, encryption, signal, bssids:[(bssid, signal, channel)]}]
    Una entrada por SSID detectado en rango.
    Parser robusto a encodings (cp850, cp1252) y locales (ES/EN).
    """
    code, out, _ = _run(["netsh", "wlan", "show", "networks", "mode=bssid"])
    if code != 0:
        return []
    networks = []
    cur = None
    cur_bssid = None
    for raw in out.splitlines():
        line = raw.rstrip()
        # Nueva red: "SSID N : nombre" (no BSSID)
        m_ssid = re.match(r"^\s*SSID\s+\d+\s*:\s*(.*)$", line)
        is_bssid_line = bool(re.match(r"^\s*BSSID\s+\d+\s*:", line))
        if m_ssid and not is_bssid_line:
            if cur:
                networks.append(cur)
            ssid_val = m_ssid.group(1).strip()
            cur = {
                "ssid": ssid_val if ssid_val else "<oculta>",
                "auth": "", "encryption": "",
                "signal": "", "bssids": [],
            }
            cur_bssid = None
            continue
        if cur is None:
            continue
        if ":" not in line:
            continue
        k, _, v = line.partition(":")
        k_lower = k.lower().strip()
        v_clean = v.strip()
        # BSSID nuevo
        if is_bssid_line:
            cur_bssid = {"bssid": v_clean, "signal": "", "channel": ""}
            cur["bssids"].append(cur_bssid)
            continue
        # Autenticacion: detectar por subcadena 'autentic' (funciona en
        # cualquier encoding aunque la 'ó' venga como '\xa2' o similar)
        if "autentic" in k_lower or "authentic" in k_lower:
            cur["auth"] = v_clean
            continue
        # Cifrado
        if "cifrad" in k_lower or "encrypt" in k_lower:
            cur["encryption"] = v_clean
            continue
        # Senal: el VALOR siempre termina con '%'. Asi independiente del nombre.
        if cur_bssid is not None and v_clean.endswith("%"):
            cur_bssid["signal"] = v_clean
            if not cur["signal"]:
                cur["signal"] = v_clean
            continue
        # Canal
        if cur_bssid is not None and ("canal" in k_lower or "channel" in k_lower):
            cur_bssid["channel"] = v_clean
    if cur:
        networks.append(cur)

    # Determinar si es abierta
    for n in networks:
        a = (n["auth"] or "").lower()
        n["is_open"] = (
            "abierta" in a or "open" in a or
            (not n["auth"] and not n["encryption"])
        )
    return networks


def encryption_friendly(enc):
    """Convierte el cifrado en algo entendible."""
    e = (enc or "").upper().strip()
    if e == "CCMP":
        return "CCMP (WPA2/WPA3 - seguro)"
    if e == "GCMP":
        return "GCMP (WPA3 - seguro)"
    if e == "TKIP":
        return "TKIP (WPA1 - obsoleto)"
    if e in ("WEP", "WEP-40", "WEP-104"):
        return f"{e} (vulnerable)"
    if not e or e in ("NONE", "NINGUNO"):
        return "Ninguno (ABIERTA - peligrosa)"
    return enc


def auth_friendly(auth):
    """Etiqueta amigable para autenticacion."""
    a = (auth or "").strip()
    if not a:
        return "Abierta (sin password)"
    return a


def get_profile_password(name):
    """
    Obtiene la contrasena guardada de un perfil. Devuelve string o None.
    netsh wlan show profile name="X" key=clear puede requerir admin
    en algunos sistemas. Si no esta autorizado, devuelve None.

    El nombre del campo en netsh varia segun version/locale:
    - "Key Content"           (EN)
    - "Material clave"        (ES Win10 antiguo)
    - "Contenido de la clave" (ES Win11 reciente)
    Lo detectamos por subcadena 'clave' o 'key content'.
    """
    code, out, err = _run([
        "netsh", "wlan", "show", "profile",
        f"name={name}", "key=clear"
    ])
    if code != 0:
        return None
    for line in out.splitlines():
        if ":" not in line:
            continue
        k, _, v = line.partition(":")
        kl = k.lower().strip()
        v_clean = v.strip()
        # Cualquier locale: key/clave + content/contenido/material
        # Esto cubre:
        # - EN:        "Key Content"
        # - ES Win11:  "Contenido de la clave"
        # - ES Win10:  "Material clave"
        # No matchea "Security key : Present" / "Clave de seguridad : Presente"
        # (no contienen "content/contenido/material").
        has_key = ("key" in kl) or ("clave" in kl)
        has_content = ("content" in kl) or ("contenido" in kl) or ("material" in kl)
        if has_key and has_content and v_clean:
            return v_clean
    return None


def get_profile_auth(name):
    """
    Devuelve el tipo de autenticacion del perfil para QR
    (WPA, WEP, nopass).
    """
    code, out, _ = _run([
        "netsh", "wlan", "show", "profile", f"name={name}"
    ])
    if code != 0:
        return "WPA"
    for line in out.splitlines():
        if ":" not in line:
            continue
        k, _, v = line.partition(":")
        kl = k.lower().strip()
        if "autentic" in kl or "authentic" in kl:
            v_low = v.strip().lower()
            if "wep" in v_low:
                return "WEP"
            if "abierta" in v_low or "open" in v_low:
                return "nopass"
            return "WPA"  # default WPA/WPA2/WPA3 todos usan "WPA" en QR
    return "WPA"


def build_wifi_qr_string(ssid, password, auth="WPA", hidden=False):
    """
    Devuelve el string estandar Wi-Fi QR:
    WIFI:T:WPA;S:NombreSSID;P:Contrasena;H:false;;
    """
    def esc(t):
        # Escape: \ ; , : "
        return (t.replace("\\", "\\\\").replace(";", r"\;")
                 .replace(",", r"\,").replace(":", r"\:")
                 .replace('"', r'\"'))
    if auth == "nopass":
        return f"WIFI:T:nopass;S:{esc(ssid)};H:{'true' if hidden else 'false'};;"
    return (f"WIFI:T:{auth};S:{esc(ssid)};P:{esc(password)};"
            f"H:{'true' if hidden else 'false'};;")


def list_saved_profiles():
    """Devuelve [{name, auth (best-effort)}]."""
    code, out, _ = _run(["netsh", "wlan", "show", "profiles"])
    if code != 0:
        return []
    profiles = []
    for raw in out.splitlines():
        # "Todos los perfiles de usuario : SSID"  o "All User Profile : SSID"
        m = re.search(r"(?:perfil|profile)[^:]*:\s*(.+?)\s*$", raw, re.IGNORECASE)
        if m:
            name = m.group(1).strip()
            if name and name not in [p["name"] for p in profiles]:
                profiles.append({"name": name, "auth": "?"})
    return profiles


def list_blocked_filters():
    """
    Devuelve lista de SSIDs en la lista de bloqueo del usuario.
    """
    code, out, _ = _run(["netsh", "wlan", "show", "filters"])
    if code != 0:
        return []
    blocked = []
    in_block_user = False
    for raw in out.splitlines():
        line = raw.strip()
        # Detectar inicio de bloque de "blocked / user"
        ll = line.lower()
        if "bloquead" in ll and "usuario" in ll:
            in_block_user = True
            continue
        if in_block_user:
            # Hasta que llegue otra seccion o linea vacia con dashes
            if ll.startswith("lista de") or ll.startswith("list of") or "----" in line:
                in_block_user = False
                continue
            # Linea con SSID: "SSID: NOMBRE   Network type: Infrastructure"
            m = re.search(r"SSID:\s*(.+?)(?:\s+Network|\s+Tipo de red|\s*$)", line)
            if m:
                ssid = m.group(1).strip().rstrip(",;")
                if ssid and "<" not in ssid:
                    blocked.append(ssid)
    return blocked


# ---------- Acciones (requieren admin) ----------

def block_ssid(ssid):
    """Bloquea un SSID. Devuelve (ok, msg)."""
    code, out, err = _run(
        ["netsh", "wlan", "add", "filter",
         "permission=block", f'ssid={ssid}',
         "networktype=infrastructure"]
    )
    if code == 0:
        return True, f"{ssid}: bloqueado"
    return False, f"{ssid}: {err.strip() or out.strip() or 'fallo'}"


def unblock_ssid(ssid):
    code, out, err = _run(
        ["netsh", "wlan", "delete", "filter",
         "permission=block", f'ssid={ssid}',
         "networktype=infrastructure"]
    )
    if code == 0:
        return True, f"{ssid}: desbloqueado"
    return False, f"{ssid}: {err.strip() or out.strip() or 'fallo'}"


def forget_profile(name):
    code, out, err = _run(["netsh", "wlan", "delete", "profile",
                           f'name={name}'])
    if code == 0:
        return True, f"{name}: olvidado"
    return False, f"{name}: {err.strip() or out.strip() or 'fallo'}"


# ---------- UI ----------

class WifiGuardApp:
    def __init__(self, root):
        self.root = root
        self.root.title(f"{APP_TITLE} - {SUITE_NAME}")
        self.root.geometry(f"{s(1180)}x{s(760)}")
        self.root.minsize(s(1000), s(660))
        self.root.configure(bg=COLORS["bg"])
        configure_ttk(self.root)

        self.networks = []
        self.profiles = []
        self.blocked = []

        self.build_ui()
        self.root.after(300, self.refresh_async)

    def build_ui(self):
        head = tk.Frame(self.root, bg=COLORS["bg"])
        head.pack(fill="x", padx=s(20), pady=(s(16), s(6)))
        left = tk.Frame(head, bg=COLORS["bg"])
        left.pack(side="left")
        tk.Label(left, text=APP_TITLE, bg=COLORS["bg"],
                 fg=COLORS["text"], font=FONTS["title"]).pack(anchor="w")
        tk.Label(left,
                 text="Bloquea redes Wi-Fi peligrosas para que tu PC nunca se conecte a ellas.",
                 bg=COLORS["bg"], fg=COLORS["text_muted"],
                 font=FONTS["body"]).pack(anchor="w", pady=(s(4), 0))

        right = tk.Frame(head, bg=COLORS["bg"])
        right.pack(side="right")
        Btn(right, text="Re-escanear",
            command=self.refresh_async,
            kind="accent", width=s(140)).pack(side="right")
        admin_label = "Administrador" if is_admin() else "Sin elevacion"
        admin_kind = "ok" if is_admin() else "warn"
        StatusPill(right, text=admin_label, kind=admin_kind,
                   width=s(130), height=s(24)).pack(side="right", padx=(0, s(8)))

        # KPIs
        kpi = tk.Frame(self.root, bg=COLORS["bg"])
        kpi.pack(fill="x", padx=s(20), pady=(s(10), s(8)))
        self.kpi_visible = KpiCard(kpi, title="REDES EN RANGO",
                                   value="-", subtitle="Detectadas ahora",
                                   accent=COLORS["accent"])
        self.kpi_open = KpiCard(kpi, title="REDES ABIERTAS",
                                value="-", subtitle="Sin contrasena (riesgo)",
                                accent=COLORS["bad"])
        self.kpi_saved = KpiCard(kpi, title="REDES GUARDADAS",
                                 value="-", subtitle="Perfiles del PC",
                                 accent=COLORS["info"])
        self.kpi_blocked = KpiCard(kpi, title="EN LISTA NEGRA",
                                   value="-", subtitle="Bloqueadas",
                                   accent=COLORS["warn"])
        for i, c in enumerate([self.kpi_visible, self.kpi_open,
                                self.kpi_saved, self.kpi_blocked]):
            c.grid(row=0, column=i, sticky="nsew", padx=s(6), pady=s(4))
            kpi.columnconfigure(i, weight=1)

        # Footer fijo abajo
        actions = tk.Frame(self.root, bg=COLORS["bg"], height=s(64))
        actions.pack(side="bottom", fill="x", padx=s(20), pady=(s(8), s(14)))
        actions.pack_propagate(False)
        self.status_var = tk.StringVar(value="Listo")
        tk.Label(actions, textvariable=self.status_var,
                 bg=COLORS["bg"], fg=COLORS["text_muted"],
                 font=FONTS["label"]).pack(side="left")
        tk.Label(actions,
                 text=f"{APP_TITLE} v{APP_VERSION}  -  {COPYRIGHT}",
                 bg=COLORS["bg"], fg=COLORS["text_soft"],
                 font=FONTS["small"]).pack(side="right")

        # Tabview
        import customtkinter as ctk
        nb = ctk.CTkTabview(
            self.root, corner_radius=10,
            fg_color=COLORS["bg_card"], border_color=COLORS["border"],
            border_width=1,
            segmented_button_fg_color=COLORS["bg_card_alt"],
            segmented_button_selected_color=COLORS["accent"],
            segmented_button_selected_hover_color=COLORS["accent_dark"],
            segmented_button_unselected_color=COLORS["bg_card_alt"],
            segmented_button_unselected_hover_color=COLORS["bg_card"],
            text_color=COLORS["text"],
        )
        nb.pack(fill="both", expand=True, padx=s(20), pady=(s(4), s(10)))
        for n in ["Redes en rango", "Redes guardadas", "Lista negra"]:
            nb.add(n)
        self.tab_visible = nb.tab("Redes en rango")
        self.tab_saved = nb.tab("Redes guardadas")
        self.tab_blocked = nb.tab("Lista negra")

        self._build_visible_tab()
        self._build_saved_tab()
        self._build_blocked_tab()

    def _build_visible_tab(self):
        parent = self.tab_visible

        # Barra de acciones de la pestana
        bar = tk.Frame(parent, bg=COLORS["bg"])
        bar.pack(fill="x", padx=s(8), pady=(s(8), s(4)))
        Btn(bar, text="EJECUTAR: bloquear seleccionada",
            command=self._block_selected_visible,
            kind="danger", width=s(280), height=s(36)).pack(side="left")
        Btn(bar, text="EJECUTAR: bloquear TODAS las abiertas",
            command=self._block_all_open,
            kind="danger", width=s(290), height=s(36)).pack(side="left", padx=s(8))
        Btn(bar, text="Conectar a esta red",
            command=self._connect_selected,
            kind="ghost", width=s(180), height=s(36)).pack(side="left")

        wrap = SectionCard(parent, title="Redes Wi-Fi en rango")
        wrap.pack(fill="both", expand=True, padx=s(8), pady=(s(4), s(8)))
        body = wrap.body()

        cols = ("ssid", "auth", "encryption", "signal", "status")
        self.vis_tree = ttk.Treeview(body, columns=cols,
                                     show="headings", height=18)
        headings = {"ssid": "SSID", "auth": "AUTENTICACION",
                    "encryption": "CIFRADO", "signal": "SENAL",
                    "status": "ESTADO"}
        widths = {"ssid": s(280), "auth": s(180),
                  "encryption": s(120), "signal": s(80),
                  "status": s(140)}
        anchors = {"ssid": "w", "auth": "w", "encryption": "w",
                   "signal": "e", "status": "w"}
        for c in cols:
            self.vis_tree.heading(c, text=headings[c])
            self.vis_tree.column(c, width=widths[c], anchor=anchors[c])
        self.vis_tree.pack(side="left", fill="both", expand=True)
        sb = ttk.Scrollbar(body, orient="vertical", command=self.vis_tree.yview)
        sb.pack(side="right", fill="y")
        self.vis_tree.configure(yscrollcommand=sb.set)

        self.vis_tree.tag_configure("open",
                                     background=COLORS["tree_row_bad"])
        self.vis_tree.tag_configure("blocked",
                                     background=COLORS["tree_row_warn"])

    def _build_saved_tab(self):
        parent = self.tab_saved
        bar = tk.Frame(parent, bg=COLORS["bg"])
        bar.pack(fill="x", padx=s(8), pady=(s(8), s(4)))
        Btn(bar, text="Mostrar contrasena",
            command=self._show_password,
            kind="ghost", width=s(180), height=s(36)).pack(side="left")
        Btn(bar, text="Generar QR para compartir",
            command=self._show_qr,
            kind="accent", width=s(220), height=s(36)).pack(side="left", padx=s(8))
        Btn(bar, text="EJECUTAR: olvidar perfil",
            command=self._forget_selected,
            kind="danger", width=s(220), height=s(36)).pack(side="left")

        wrap = SectionCard(parent, title="Redes guardadas en este PC")
        wrap.pack(fill="both", expand=True, padx=s(8), pady=(s(4), s(8)))
        body = wrap.body()

        cols = ("name",)
        self.saved_tree = ttk.Treeview(body, columns=cols,
                                        show="headings", height=18)
        self.saved_tree.heading("name", text="NOMBRE DE LA RED")
        self.saved_tree.column("name", width=s(700), anchor="w")
        self.saved_tree.pack(side="left", fill="both", expand=True)
        sb = ttk.Scrollbar(body, orient="vertical",
                            command=self.saved_tree.yview)
        sb.pack(side="right", fill="y")
        self.saved_tree.configure(yscrollcommand=sb.set)

    def _build_blocked_tab(self):
        parent = self.tab_blocked

        bar = tk.Frame(parent, bg=COLORS["bg"])
        bar.pack(fill="x", padx=s(8), pady=(s(8), s(4)))
        Btn(bar, text="EJECUTAR: desbloquear seleccionada",
            command=self._unblock_selected,
            kind="accent", width=s(290), height=s(36)).pack(side="left")
        tk.Label(bar, text="Agregar SSID a lista negra:",
                 bg=COLORS["bg"], fg=COLORS["text"],
                 font=FONTS["label_b"]).pack(side="left", padx=(s(20), s(4)))
        self.add_var = tk.StringVar()
        Entry(bar, textvariable=self.add_var, width=s(260)).pack(side="left", padx=s(4))
        Btn(bar, text="Bloquear este SSID",
            command=self._block_typed,
            kind="danger", width=s(180), height=s(36)).pack(side="left", padx=s(4))

        wrap = SectionCard(parent, title="SSIDs bloqueados (no se conectara nunca)")
        wrap.pack(fill="both", expand=True, padx=s(8), pady=(s(4), s(8)))
        body = wrap.body()

        cols = ("ssid",)
        self.blocked_tree = ttk.Treeview(body, columns=cols,
                                         show="headings", height=18)
        self.blocked_tree.heading("ssid", text="SSID BLOQUEADO")
        self.blocked_tree.column("ssid", width=s(700), anchor="w")
        self.blocked_tree.pack(side="left", fill="both", expand=True)
        sb = ttk.Scrollbar(body, orient="vertical",
                            command=self.blocked_tree.yview)
        sb.pack(side="right", fill="y")
        self.blocked_tree.configure(yscrollcommand=sb.set)

    # ---------- Refresh ----------

    def refresh_async(self):
        self.status_var.set("Escaneando redes Wi-Fi...")
        overlay = ProgressOverlay(self.root, "Escaneando redes Wi-Fi visibles...")
        threading.Thread(target=self._refresh_worker,
                         args=(overlay,), daemon=True).start()

    def _refresh_worker(self, overlay):
        try:
            networks = list_visible_networks()
            self.root.after(0, lambda: overlay.update_message(
                "Leyendo redes guardadas..."
            ))
            profiles = list_saved_profiles()
            self.root.after(0, lambda: overlay.update_message(
                "Leyendo lista negra..."
            ))
            blocked = list_blocked_filters()
        except Exception as e:
            self.root.after(0, overlay.close)
            self.root.after(0, lambda: self.status_var.set(f"Error: {e}"))
            return

        self.root.after(0, overlay.close)
        self.root.after(0, self._populate, networks, profiles, blocked)

    def _populate(self, networks, profiles, blocked):
        self.networks = networks
        self.profiles = profiles
        self.blocked = blocked

        n_visible = len(networks)
        n_open = sum(1 for n in networks if n.get("is_open"))

        self.kpi_visible.update_data(value=str(n_visible),
                                      subtitle="Detectadas ahora",
                                      accent=COLORS["accent"])
        self.kpi_open.update_data(
            value=str(n_open),
            subtitle="Sin contrasena (riesgo)" if n_open
                     else "Sin redes abiertas",
            accent=COLORS["bad"] if n_open else COLORS["ok"],
        )
        self.kpi_saved.update_data(value=str(len(profiles)),
                                    subtitle="Perfiles del PC",
                                    accent=COLORS["info"])
        self.kpi_blocked.update_data(
            value=str(len(blocked)),
            subtitle="En lista negra" if blocked else "Lista vacia",
            accent=COLORS["warn"] if blocked else COLORS["text_muted"],
        )

        # Tabla redes visibles
        for it in self.vis_tree.get_children():
            self.vis_tree.delete(it)
        blocked_set = {b.lower() for b in blocked}
        for idx, n in enumerate(networks):
            ssid = n["ssid"]
            tag = ""
            if ssid.lower() in blocked_set:
                status = "BLOQUEADA"
                tag = "blocked"
            elif n.get("is_open"):
                status = "ABIERTA (riesgo)"
                tag = "open"
            else:
                status = "Permitida"
            self.vis_tree.insert("", "end", iid=str(idx),
                                  tags=(tag,) if tag else (),
                                  values=(ssid,
                                          auth_friendly(n.get("auth", "")),
                                          encryption_friendly(n.get("encryption", "")),
                                          n.get("signal", "") or "-",
                                          status))

        # Tabla guardadas
        for it in self.saved_tree.get_children():
            self.saved_tree.delete(it)
        for idx, p in enumerate(profiles):
            self.saved_tree.insert("", "end", iid=str(idx),
                                    values=(p["name"],))

        # Tabla bloqueadas
        for it in self.blocked_tree.get_children():
            self.blocked_tree.delete(it)
        for idx, b in enumerate(blocked):
            self.blocked_tree.insert("", "end", iid=str(idx),
                                      values=(b,))

        self.status_var.set(
            f"Visible: {n_visible}  /  Abiertas: {n_open}  /  "
            f"Guardadas: {len(profiles)}  /  Bloqueadas: {len(blocked)}  -  "
            f"{datetime.now():%H:%M:%S}"
        )

    # ---------- Acciones ----------

    def _check_admin(self):
        if not is_admin():
            messagebox.showwarning(
                APP_TITLE,
                "Esta accion requiere ejecutar como administrador.\n\n"
                "Cierra esta ventana, clic derecho en el .bat de Wi-Fi Guard\n"
                "y elige 'Ejecutar como administrador'."
            )
            return False
        return True

    def _selected_visible(self):
        sel = self.vis_tree.selection()
        if not sel:
            return None
        idx = int(sel[0])
        return self.networks[idx] if 0 <= idx < len(self.networks) else None

    def _block_selected_visible(self):
        n = self._selected_visible()
        if not n:
            messagebox.showinfo(APP_TITLE, "Selecciona una red en la tabla.")
            return
        if not self._check_admin():
            return
        ssid = n["ssid"]
        if ssid == "<oculta>":
            messagebox.showwarning(APP_TITLE, "No se puede bloquear redes ocultas (sin SSID).")
            return
        if not messagebox.askyesno(
            APP_TITLE,
            f"Agregar a lista negra:\n\n{ssid}\n\n"
            "Tu PC NO se conectara a esta red ni manualmente."
        ):
            return
        self._do_block_async([ssid])

    def _block_all_open(self):
        if not self.networks:
            messagebox.showinfo(APP_TITLE, "Re-escanea redes primero.")
            return
        if not self._check_admin():
            return
        opens = [n["ssid"] for n in self.networks
                 if n.get("is_open") and n["ssid"] != "<oculta>"]
        if not opens:
            messagebox.showinfo(APP_TITLE, "No hay redes abiertas en rango.")
            return
        if not messagebox.askyesno(
            APP_TITLE,
            f"Vas a bloquear {len(opens)} redes abiertas:\n\n"
            + "\n".join(f"  - {s}" for s in opens[:10])
            + (f"\n  ... y {len(opens)-10} mas" if len(opens) > 10 else "")
            + "\n\nContinuar?"
        ):
            return
        self._do_block_async(opens)

    def _block_typed(self):
        ssid = self.add_var.get().strip()
        if not ssid:
            messagebox.showinfo(APP_TITLE, "Escribe un SSID.")
            return
        if not self._check_admin():
            return
        self._do_block_async([ssid])
        self.add_var.set("")

    def _do_block_async(self, ssids):
        overlay = ProgressOverlay(
            self.root,
            f"Bloqueando {len(ssids)} red(es)..."
        )

        def worker():
            ok_count = 0
            fail_count = 0
            errs = []
            try:
                for ssid in ssids:
                    self.root.after(0, lambda s=ssid: overlay.update_message(
                        f"Bloqueando: {s}"
                    ))
                    ok, msg = block_ssid(ssid)
                    if ok:
                        ok_count += 1
                        # Registrar en rollback
                        try:
                            from core import rollback as _rb
                            _rb._new_entry(
                                module=MODULE_NAME,
                                kind="wifi_block",
                                label=f"Wi-Fi bloqueado: {ssid}",
                                payload={"ssid": ssid, "action": "block"},
                            )
                        except Exception:
                            pass
                    else:
                        fail_count += 1
                        errs.append(msg)
            finally:
                self.root.after(0, overlay.close)
            msg = (f"Bloqueadas: {ok_count}\n"
                   f"Fallaron: {fail_count}")
            if errs:
                msg += "\n\nErrores:\n" + "\n".join(f"  - {e}" for e in errs[:5])
            self.root.after(0, lambda: messagebox.showinfo(APP_TITLE, msg))
            self.root.after(0, self.refresh_async)

        threading.Thread(target=worker, daemon=True).start()

    def _unblock_selected(self):
        sel = self.blocked_tree.selection()
        if not sel:
            messagebox.showinfo(APP_TITLE, "Selecciona un SSID bloqueado.")
            return
        if not self._check_admin():
            return
        idx = int(sel[0])
        if idx >= len(self.blocked):
            return
        ssid = self.blocked[idx]
        if not messagebox.askyesno(
            APP_TITLE,
            f"Desbloquear '{ssid}'?\n\n"
            "El PC podra volver a conectarse a esta red."
        ):
            return

        overlay = ProgressOverlay(self.root, f"Desbloqueando: {ssid}")

        def worker():
            try:
                ok, msg = unblock_ssid(ssid)
            finally:
                self.root.after(0, overlay.close)
            if ok:
                self.root.after(0, lambda: messagebox.showinfo(APP_TITLE, f"OK: {msg}"))
            else:
                self.root.after(0, lambda: messagebox.showwarning(APP_TITLE, msg))
            self.root.after(0, self.refresh_async)

        threading.Thread(target=worker, daemon=True).start()

    def _forget_selected(self):
        sel = self.saved_tree.selection()
        if not sel:
            messagebox.showinfo(APP_TITLE, "Selecciona un perfil guardado.")
            return
        idx = int(sel[0])
        if idx >= len(self.profiles):
            return
        name = self.profiles[idx]["name"]
        if not messagebox.askyesno(
            APP_TITLE,
            f"Olvidar perfil '{name}'?\n\n"
            "La contrasena guardada se eliminara. Tendras que volver a "
            "ingresarla si quieres conectarte de nuevo."
        ):
            return

        overlay = ProgressOverlay(self.root, f"Olvidando: {name}")

        def worker():
            try:
                ok, msg = forget_profile(name)
            finally:
                self.root.after(0, overlay.close)
            if ok:
                self.root.after(0, lambda: messagebox.showinfo(APP_TITLE, f"OK: {msg}"))
            else:
                self.root.after(0, lambda: messagebox.showwarning(APP_TITLE, msg))
            self.root.after(0, self.refresh_async)

        threading.Thread(target=worker, daemon=True).start()

    def _show_password(self):
        sel = self.saved_tree.selection()
        if not sel:
            messagebox.showinfo(APP_TITLE, "Selecciona un perfil de la tabla.")
            return
        idx = int(sel[0])
        if idx >= len(self.profiles):
            return
        name = self.profiles[idx]["name"]
        overlay = ProgressOverlay(self.root, f"Leyendo contrasena de: {name}")

        def worker():
            pwd = get_profile_password(name)
            self.root.after(0, overlay.close)
            if pwd is None:
                self.root.after(0, lambda: messagebox.showwarning(
                    APP_TITLE,
                    f"No se pudo obtener la contrasena de '{name}'.\n\n"
                    "Posibles causas:\n"
                    "  - El perfil no tiene clave guardada\n"
                    "  - Requiere permisos de administrador (cierra y abre con "
                    "Wifi_Guard_Admin.bat)"
                ))
                return
            if not pwd:
                self.root.after(0, lambda: messagebox.showinfo(
                    APP_TITLE,
                    f"Red '{name}' es ABIERTA (sin contrasena)."
                ))
                return
            self.root.after(0, lambda: self._show_password_window(name, pwd))

        threading.Thread(target=worker, daemon=True).start()

    def _show_password_window(self, name, password):
        win = tk.Toplevel(self.root)
        win.title(f"Contrasena - {name}")
        win.configure(bg=COLORS["bg"])
        win.transient(self.root)
        win.geometry(f"{s(520)}x{s(220)}")

        tk.Label(win, text="Red Wi-Fi", bg=COLORS["bg"],
                 fg=COLORS["text_muted"], font=FONTS["small"]).pack(pady=(s(16), 0))
        tk.Label(win, text=name, bg=COLORS["bg"],
                 fg=COLORS["text"], font=FONTS["h1"]).pack()

        tk.Label(win, text="Contrasena", bg=COLORS["bg"],
                 fg=COLORS["text_muted"],
                 font=FONTS["small"]).pack(pady=(s(14), 0))

        # Caja de password seleccionable
        pwd_var = tk.StringVar(value=password)
        ent = tk.Entry(win, textvariable=pwd_var, font=FONTS["mono"],
                        bg=COLORS["bg_card_alt"], fg=COLORS["text"],
                        relief="flat", justify="center",
                        readonlybackground=COLORS["bg_card_alt"])
        ent.pack(padx=s(40), pady=s(6), fill="x")
        ent.config(state="readonly")

        btn_row = tk.Frame(win, bg=COLORS["bg"])
        btn_row.pack(pady=s(14))

        def copy_pwd():
            self.root.clipboard_clear()
            self.root.clipboard_append(password)
            messagebox.showinfo(APP_TITLE,
                                "Contrasena copiada al portapapeles.")
        Btn(btn_row, text="Copiar al portapapeles",
            command=copy_pwd,
            kind="accent", width=s(200), height=s(36)).pack(side="left")
        Btn(btn_row, text="Cerrar",
            command=win.destroy,
            kind="ghost", width=s(120), height=s(36)).pack(side="left", padx=s(8))

    def _show_qr(self):
        sel = self.saved_tree.selection()
        if not sel:
            messagebox.showinfo(APP_TITLE, "Selecciona un perfil de la tabla.")
            return
        idx = int(sel[0])
        if idx >= len(self.profiles):
            return
        name = self.profiles[idx]["name"]
        overlay = ProgressOverlay(self.root, f"Generando QR para: {name}")

        def worker():
            try:
                pwd = get_profile_password(name) or ""
                auth = get_profile_auth(name)
            except Exception as e:
                self.root.after(0, overlay.close)
                self.root.after(0, lambda: messagebox.showerror(
                    APP_TITLE, f"Error: {e}"
                ))
                return
            self.root.after(0, overlay.close)
            if auth != "nopass" and not pwd:
                self.root.after(0, lambda: messagebox.showwarning(
                    APP_TITLE,
                    f"No se pudo obtener la contrasena de '{name}'.\n"
                    "Reabre con Wifi_Guard_Admin.bat para tener acceso a las claves."
                ))
                return
            wifi_string = build_wifi_qr_string(name, pwd, auth)
            self.root.after(0, lambda: self._show_qr_window(name, wifi_string, pwd, auth))

        threading.Thread(target=worker, daemon=True).start()

    def _show_qr_window(self, name, wifi_string, password, auth):
        try:
            import qrcode
            import qrcode.constants as qrc
        except ImportError:
            messagebox.showerror(
                APP_TITLE,
                "Falta libreria 'qrcode'. Ejecuta Install.bat o:\n"
                "  python -m pip install qrcode"
            )
            return

        # Generar matriz QR
        qr = qrcode.QRCode(
            version=None,
            error_correction=qrc.ERROR_CORRECT_M,
            box_size=1, border=2,
        )
        qr.add_data(wifi_string)
        qr.make(fit=True)
        matrix = qr.modules
        size = qr.modules_count

        # Tamano grande para que se escanee facil desde celular
        cell = s(8)
        canvas_w = size * cell

        win = tk.Toplevel(self.root)
        win.title(f"QR Wi-Fi - {name}")
        win.configure(bg=COLORS["bg"])
        win.transient(self.root)

        # Header
        head = tk.Frame(win, bg=COLORS["bg"])
        head.pack(fill="x", padx=s(20), pady=(s(16), s(6)))
        tk.Label(head, text="Escanea con tu celular para conectarte",
                 bg=COLORS["bg"], fg=COLORS["text_muted"],
                 font=FONTS["small"]).pack(anchor="w")
        tk.Label(head, text=name, bg=COLORS["bg"],
                 fg=COLORS["text"], font=FONTS["title"]).pack(anchor="w")

        # Canvas con QR
        qr_wrap = tk.Frame(win, bg="white")
        qr_wrap.pack(padx=s(20), pady=s(10))
        canvas = tk.Canvas(qr_wrap, width=canvas_w, height=canvas_w,
                            bg="white", highlightthickness=0)
        canvas.pack(padx=s(10), pady=s(10))
        for y, row in enumerate(matrix):
            for x, val in enumerate(row):
                if val:
                    canvas.create_rectangle(
                        x * cell, y * cell,
                        (x + 1) * cell, (y + 1) * cell,
                        fill="black", outline=""
                    )

        # Detalles
        detail = tk.Frame(win, bg=COLORS["bg"])
        detail.pack(fill="x", padx=s(20), pady=s(8))
        tk.Label(detail, text=f"Tipo: {auth}    Contrasena: {password or '(ninguna)'}",
                 bg=COLORS["bg"], fg=COLORS["text_muted"],
                 font=FONTS["label"]).pack(anchor="w")

        # Botones
        btns = tk.Frame(win, bg=COLORS["bg"])
        btns.pack(pady=(s(8), s(16)))

        def copy_text():
            self.root.clipboard_clear()
            self.root.clipboard_append(wifi_string)
            messagebox.showinfo(APP_TITLE, "Texto QR copiado al portapapeles.")

        def save_png():
            try:
                from tkinter import filedialog
                path = filedialog.asksaveasfilename(
                    defaultextension=".png",
                    filetypes=[("PNG", "*.png")],
                    initialfile=f"wifi_{name}.png",
                )
                if not path:
                    return
                # Guardar con qrcode (necesita Pillow). Si no esta, ofrecer .ps
                try:
                    img = qrcode.make(wifi_string)
                    img.save(path)
                    messagebox.showinfo(APP_TITLE, f"QR guardado en:\n{path}")
                except Exception:
                    # Fallback: PostScript desde el canvas
                    ps_path = str(Path(path).with_suffix(".ps"))
                    canvas.postscript(file=ps_path, colormode="color")
                    messagebox.showinfo(
                        APP_TITLE,
                        f"PNG requiere Pillow. Guardado como PostScript:\n{ps_path}\n\n"
                        "Para PNG instala Pillow: pip install Pillow"
                    )
            except Exception as e:
                messagebox.showerror(APP_TITLE, f"Error: {e}")

        Btn(btns, text="Copiar texto WIFI:",
            command=copy_text,
            kind="ghost", width=s(180), height=s(36)).pack(side="left", padx=s(4))
        Btn(btns, text="Guardar como imagen",
            command=save_png,
            kind="accent", width=s(180), height=s(36)).pack(side="left", padx=s(4))
        Btn(btns, text="Cerrar",
            command=win.destroy,
            kind="ghost", width=s(100), height=s(36)).pack(side="left", padx=s(4))

    def _connect_selected(self):
        n = self._selected_visible()
        if not n:
            messagebox.showinfo(APP_TITLE, "Selecciona una red.")
            return
        ssid = n["ssid"]
        if ssid == "<oculta>":
            messagebox.showwarning(APP_TITLE, "No se puede conectar a redes ocultas desde aqui.")
            return
        # netsh wlan connect requiere perfil existente o creacion previa
        code, out, err = _run(["netsh", "wlan", "connect", f'name={ssid}'])
        if code == 0:
            messagebox.showinfo(APP_TITLE,
                                f"Solicitud de conexion enviada a {ssid}.\n\n"
                                "Si la contrasena no esta guardada, Windows "
                                "te pedira ingresarla.")
        else:
            messagebox.showwarning(APP_TITLE,
                                    f"No se pudo conectar a {ssid}:\n{err or out}")


def main():
    root = tk.Tk()
    setup_scaling(root)
    WifiGuardApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
