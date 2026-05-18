"""
Wrappers ligeros sobre CustomTkinter para botones, checkbox y entry
con bordes redondeados y look moderno consistente con la paleta del tema.

Mantenemos tk.Tk() como root (los CTk widgets funcionan dentro). Solo
sustituimos los widgets cuyo aspecto plano molesta: botones, checkboxes,
entradas y spinbox.
"""

import sys
import ctypes
import customtkinter as ctk
from .style import COLORS, FONTS, THEME_NAME


_DPI_DONE = False


def enable_high_dpi():
    """
    Habilita DPI awareness en Windows ANTES de crear la primera ventana.
    Sin esto, Windows renderiza la app a 100% y la estira como bitmap,
    dejando todos los textos borrosos en pantallas con scaling >100%.
    """
    global _DPI_DONE
    if _DPI_DONE or sys.platform != "win32":
        return
    try:
        # Per-Monitor DPI v2 (Windows 10 1703+) - lo mejor
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            # System DPI Aware (Vista+) - fallback
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass
    _DPI_DONE = True


def init_ctk():
    """Aplica DPI awareness + appearance global de CTk segun el tema."""
    enable_high_dpi()
    mode = "dark" if THEME_NAME == "dark" else "light"
    ctk.set_appearance_mode(mode)
    ctk.set_default_color_theme("blue")


class Btn(ctk.CTkButton):
    """
    Boton con esquinas redondeadas. kind = 'accent' | 'ghost' | 'danger'.
    Drop-in casi compatible con ttk.Button: pasa text, command, y
    opcionalmente width/height.
    """
    def __init__(self, master, text="", command=None, kind="ghost",
                 width=140, height=34, **kwargs):
        if kind == "accent":
            colors = dict(
                fg_color=COLORS["accent"],
                hover_color=COLORS["accent_dark"],
                text_color=COLORS["text_invert"],
                border_width=0,
            )
        elif kind == "danger":
            colors = dict(
                fg_color=COLORS["bad"],
                hover_color="#b91c1c",
                text_color=COLORS["text_invert"],
                border_width=0,
            )
        else:
            colors = dict(
                fg_color=COLORS["bg_card_alt"],
                hover_color=COLORS["bg_card"],
                text_color=COLORS["text"],
                border_color=COLORS["border"],
                border_width=1,
            )
        super().__init__(
            master, text=text, command=command,
            corner_radius=10,
            font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
            width=width, height=height,
            **colors, **kwargs,
        )


class Check(ctk.CTkCheckBox):
    """Checkbox redondeado consistente con el tema."""
    def __init__(self, master, text="", variable=None, command=None,
                 **kwargs):
        super().__init__(
            master, text=text, variable=variable, command=command,
            corner_radius=4,
            font=ctk.CTkFont(family="Segoe UI", size=11),
            text_color=COLORS["text"],
            fg_color=COLORS["accent"],
            hover_color=COLORS["accent_dark"],
            border_color=COLORS["border"],
            checkmark_color=COLORS["text_invert"],
            **kwargs,
        )


class Entry(ctk.CTkEntry):
    def __init__(self, master, textvariable=None, width=200, **kwargs):
        super().__init__(
            master, textvariable=textvariable, width=width,
            corner_radius=8, height=30,
            font=ctk.CTkFont(family="Segoe UI", size=11),
            fg_color=COLORS["bg_card_alt"],
            text_color=COLORS["text"],
            border_color=COLORS["border"],
            **kwargs,
        )


class Spin(ctk.CTkEntry):
    """Spinbox emulado: entry + dos botones +/-."""
    def __init__(self, master, from_=0, to=999, textvariable=None, **kwargs):
        # Para no complicar: usamos un Entry. El usuario escribe el numero.
        super().__init__(
            master, textvariable=textvariable, width=70,
            corner_radius=8, height=30,
            font=ctk.CTkFont(family="Segoe UI", size=11),
            fg_color=COLORS["bg_card_alt"],
            text_color=COLORS["text"],
            border_color=COLORS["border"],
            **kwargs,
        )
