"""
Paleta de colores y estilos compartidos para PC Performance Suite.
Soporta tema 'light' y 'dark'. Los modulos leen `COLORS` (dict mutable),
asi que al cambiar tema con `set_theme()` se actualizan los valores
para todas las cards y widgets que se construyan despues.
"""

LIGHT = {
    "bg":           "#f4f6fb",
    "bg_card":      "#ffffff",
    "bg_card_alt":  "#f9fafc",
    "bg_sidebar":   "#1f2937",
    "border":       "#e5e7eb",
    "border_soft":  "#eef0f3",

    "text":         "#0f172a",
    "text_muted":   "#64748b",
    "text_soft":    "#94a3b8",
    "text_invert":  "#ffffff",

    "accent":       "#3b82f6",
    "accent_dark":  "#2563eb",

    "ok":           "#16a34a",
    "ok_bg":        "#dcfce7",
    "warn":         "#d97706",
    "warn_bg":      "#fef3c7",
    "bad":          "#dc2626",
    "bad_bg":       "#fee2e2",
    "info":         "#0284c7",
    "info_bg":      "#e0f2fe",

    "track":        "#e5e7eb",

    "tree_row_bad":  "#fff5f5",
    "tree_row_warn": "#fefce8",
    "tree_row_ok":   "#f0fdf4",
}

DARK = {
    "bg":           "#0b1220",
    "bg_card":      "#161e2e",
    "bg_card_alt":  "#1f2937",
    "bg_sidebar":   "#0f172a",
    "border":       "#2a3447",
    "border_soft":  "#1e2738",

    "text":         "#f1f5f9",
    "text_muted":   "#cbd5e1",
    "text_soft":    "#94a3b8",
    "text_invert":  "#0f172a",

    "accent":       "#60a5fa",
    "accent_dark":  "#3b82f6",

    "ok":           "#4ade80",
    "ok_bg":        "#14532d",
    "warn":         "#fbbf24",
    "warn_bg":      "#713f12",
    "bad":          "#f87171",
    "bad_bg":       "#7f1d1d",
    "info":         "#38bdf8",
    "info_bg":      "#0c4a6e",

    "track":        "#334155",

    "tree_row_bad":  "#3a1d1d",
    "tree_row_warn": "#3a2d10",
    "tree_row_ok":   "#0f3a22",
}

# Tema activo (mutable - se actualiza con set_theme)
COLORS = dict(DARK)
THEME_NAME = "dark"

SUITE_VERSION = "0.6.6"
COPYRIGHT = "Copyright (c) KrlosEdu / 2026"


def apply_saved_theme():
    """Carga la preferencia desde config.json y aplica."""
    try:
        from . import config
        name = config.get("theme", "dark")
        set_theme(name)
    except Exception:
        pass

FONTS = {
    "title":    ("Segoe UI", 22, "bold"),
    "subtitle": ("Segoe UI", 11),
    "h1":       ("Segoe UI", 16, "bold"),
    "h2":       ("Segoe UI", 13, "bold"),
    "kpi":      ("Segoe UI", 18, "bold"),
    "kpi_sm":   ("Segoe UI", 14, "bold"),
    "label":    ("Segoe UI", 9),
    "label_b":  ("Segoe UI", 9, "bold"),
    "body":     ("Segoe UI", 10),
    "mono":     ("Consolas", 10),
    "badge":    ("Segoe UI", 9, "bold"),
    "small":    ("Segoe UI", 8),
}


def set_theme(name):
    """Cambia el tema activo. Llamar antes de crear la UI."""
    global THEME_NAME
    palette = DARK if name == "dark" else LIGHT
    COLORS.clear()
    COLORS.update(palette)
    THEME_NAME = name


def color_for_value(value, thresholds=(50, 80), invert=False):
    """
    Devuelve color segun rangos.
    Default: <50 bad, <80 warn, >=80 ok (mejor mientras mayor).
    invert=True: <50 ok, <80 warn, >=80 bad (peor mientras mayor, ej. uso de CPU).
    """
    if value is None:
        return COLORS["text_muted"]
    low, high = thresholds
    if not invert:
        if value < low:
            return COLORS["bad"]
        if value < high:
            return COLORS["warn"]
        return COLORS["ok"]
    else:
        if value < low:
            return COLORS["ok"]
        if value < high:
            return COLORS["warn"]
        return COLORS["bad"]


def configure_ttk(root):
    """Aplica estilos ttk consistentes con el tema activo."""
    from tkinter import ttk
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except Exception:
        pass

    c = COLORS
    is_dark = THEME_NAME == "dark"

    style.configure(".", background=c["bg"], foreground=c["text"], font=FONTS["body"])
    style.configure("TFrame", background=c["bg"])
    style.configure("Card.TFrame", background=c["bg_card"])
    style.configure("CardAlt.TFrame", background=c["bg_card_alt"])
    style.configure("TLabel", background=c["bg"], foreground=c["text"])
    style.configure("Card.TLabel", background=c["bg_card"], foreground=c["text"])
    style.configure("Muted.TLabel", background=c["bg"],
                    foreground=c["text_muted"], font=FONTS["label"])
    style.configure("CardMuted.TLabel", background=c["bg_card"],
                    foreground=c["text_muted"], font=FONTS["label"])
    style.configure("Title.TLabel", background=c["bg"],
                    foreground=c["text"], font=FONTS["title"])
    style.configure("H1.TLabel", background=c["bg"],
                    foreground=c["text"], font=FONTS["h1"])
    style.configure("H2.TLabel", background=c["bg_card"],
                    foreground=c["text"], font=FONTS["h2"])
    style.configure("Kpi.TLabel", background=c["bg_card"],
                    foreground=c["text"], font=FONTS["kpi"])

    # Notebook
    style.configure("TNotebook", background=c["bg"], borderwidth=0)
    style.configure("TNotebook.Tab",
                    background=c["bg_card_alt"],
                    foreground=c["text_muted"],
                    padding=(14, 8), font=FONTS["label_b"],
                    borderwidth=0)
    style.map("TNotebook.Tab",
              background=[("selected", c["bg_card"])],
              foreground=[("selected", c["accent"])])

    # Botones
    style.configure("Accent.TButton",
                    background=c["accent"], foreground=c["text_invert"],
                    borderwidth=0, padding=(14, 7), font=FONTS["label_b"])
    style.map("Accent.TButton",
              background=[("active", c["accent_dark"])],
              foreground=[("active", c["text_invert"])])

    ghost_bg = c["bg_card_alt"] if is_dark else c["bg"]
    style.configure("Ghost.TButton",
                    background=ghost_bg, foreground=c["text"],
                    borderwidth=1, padding=(12, 6),
                    bordercolor=c["border"])
    style.map("Ghost.TButton",
              background=[("active", c["bg_card"])],
              foreground=[("active", c["text"])])

    style.configure("Danger.TButton",
                    background=c["bad"], foreground=c["text_invert"],
                    borderwidth=0, padding=(14, 7), font=FONTS["label_b"])
    style.map("Danger.TButton",
              background=[("active", "#b91c1c")],
              foreground=[("active", c["text_invert"])])

    # Treeview
    style.configure("Treeview",
                    background=c["bg_card"], fieldbackground=c["bg_card"],
                    foreground=c["text"], rowheight=24, borderwidth=0)
    style.configure("Treeview.Heading",
                    background=c["bg_card_alt"], foreground=c["text_muted"],
                    font=FONTS["label_b"], borderwidth=0, padding=(8, 6))
    style.map("Treeview",
              background=[("selected", c["info_bg"])],
              foreground=[("selected", c["text"])])
    style.map("Treeview.Heading",
              background=[("active", c["bg_card"])])

    # Checkbutton
    style.configure("TCheckbutton",
                    background=c["bg"], foreground=c["text"],
                    font=FONTS["label"])
    style.map("TCheckbutton",
              background=[("active", c["bg"])],
              foreground=[("active", c["text"])])

    # Entry
    style.configure("TEntry",
                    fieldbackground=c["bg_card"],
                    foreground=c["text"],
                    bordercolor=c["border"],
                    insertcolor=c["text"])

    # Spinbox
    style.configure("TSpinbox",
                    fieldbackground=c["bg_card"],
                    foreground=c["text"],
                    background=c["bg_card_alt"],
                    arrowcolor=c["text_muted"])

    # Scrollbar
    style.configure("Vertical.TScrollbar",
                    background=c["bg_card_alt"],
                    troughcolor=c["bg"],
                    bordercolor=c["bg"],
                    arrowcolor=c["text_muted"])
    style.configure("Horizontal.TScrollbar",
                    background=c["bg_card_alt"],
                    troughcolor=c["bg"],
                    bordercolor=c["bg"],
                    arrowcolor=c["text_muted"])

    return style
