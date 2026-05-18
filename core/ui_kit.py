"""
Componentes UI reutilizables (Tkinter Canvas) para look moderno.
Cards con esquinas redondeadas, KPIs, barras de progreso, badges.
"""

import tkinter as tk
from tkinter import ttk

from .style import COLORS, FONTS, color_for_value


def round_rect(canvas, x1, y1, x2, y2, r=12, **kwargs):
    """Dibuja rectangulo con esquinas redondeadas en un Canvas."""
    points = [
        x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r,
        x2, y2 - r, x2, y2, x2 - r, y2, x1 + r, y2,
        x1, y2, x1, y2 - r, x1, y1 + r, x1, y1,
    ]
    return canvas.create_polygon(points, smooth=True, **kwargs)


class KpiCard(tk.Canvas):
    """
    Tarjeta KPI compacta: titulo arriba, valor al centro, subtitulo abajo,
    barra de progreso opcional y banda de acento lateral.
    Default height 100. Texto largo se reduce automaticamente.
    """
    def __init__(self, parent, title="", value="-", subtitle="",
                 accent=None, width=240, height=100, show_bar=False,
                 bar_value=0, bar_max=100, bar_invert=False):
        super().__init__(parent, width=width, height=height,
                         bg=COLORS["bg"], highlightthickness=0, bd=0)
        self._cw = width
        self._ch = height
        self._title = title
        self._value = value
        self._subtitle = subtitle
        self._accent = accent or COLORS["accent"]
        self._show_bar = show_bar
        self._bar_value = bar_value
        self._bar_max = bar_max
        self._bar_invert = bar_invert
        self.bind("<Configure>", self._on_resize)
        self._draw()

    def _on_resize(self, event):
        self._cw = max(180, event.width)
        self._ch = max(80, event.height)
        self._draw()

    def _value_font(self):
        """Elige fuente segun longitud del valor para evitar overflow."""
        v = str(self._value)
        # Si es texto largo (>= 8 chars) o tiene espacios, usa fuente mas chica
        if len(v) >= 10:
            return ("Segoe UI", 12, "bold")
        if len(v) >= 8 or " " in v:
            return FONTS["kpi_sm"]
        return FONTS["kpi"]

    def _draw(self):
        self.delete("all")
        w, h = self._cw, self._ch

        round_rect(self, 1, 1, w - 1, h - 1, r=12,
                   fill=COLORS["bg_card"], outline=COLORS["border"], width=1)

        self.create_rectangle(1, 1, 5, h - 1, fill=self._accent, outline=self._accent)

        # ----- Layout vertical sin solapamientos -----
        # Title (top)
        self.create_text(16, 10, text=self._title.upper(), anchor="nw",
                         fill=COLORS["text_muted"], font=FONTS["small"])

        # Bar (bottom-most)
        bar_h = 4
        bar_pad_bottom = 10
        bar_y_top = h - bar_pad_bottom - bar_h
        if self._show_bar:
            bar_x1 = 16
            bar_x2 = w - 16
            self.create_rectangle(bar_x1, bar_y_top, bar_x2, bar_y_top + bar_h,
                                  fill=COLORS["track"], outline="")
            try:
                pct = max(0.0, min(1.0, float(self._bar_value) / max(1, self._bar_max)))
            except Exception:
                pct = 0.0
            fill_color = color_for_value(
                pct * 100, thresholds=(50, 80), invert=self._bar_invert
            )
            if pct > 0:
                self.create_rectangle(bar_x1, bar_y_top,
                                      bar_x1 + (bar_x2 - bar_x1) * pct,
                                      bar_y_top + bar_h,
                                      fill=fill_color, outline="")

        # Subtitle (just above bar) — anchor "sw"
        # Garantizo 8 px de margen entre subtitulo y barra
        sub_y_baseline = (bar_y_top - 8) if self._show_bar else (h - 8)
        if self._subtitle:
            self.create_text(16, sub_y_baseline,
                             text=self._subtitle, anchor="sw",
                             fill=COLORS["text_muted"], font=FONTS["label"])
        # Top del subtitle (estimacion: 14 px arriba de su baseline)
        sub_top = sub_y_baseline - 14

        # Title termina aprox en y=22 (font small ~12 px desde y=10)
        title_bottom = 22

        # Value CENTRADO verticalmente entre el title y el subtitle
        value_center_y = (title_bottom + sub_top) // 2
        self.create_text(16, value_center_y, text=str(self._value),
                         anchor="w",
                         fill=COLORS["text"], font=self._value_font())

    def update_data(self, value=None, subtitle=None, accent=None,
                    bar_value=None, bar_max=None):
        if value is not None:
            self._value = value
        if subtitle is not None:
            self._subtitle = subtitle
        if accent is not None:
            self._accent = accent
        if bar_value is not None:
            self._bar_value = bar_value
        if bar_max is not None:
            self._bar_max = bar_max
        self._draw()


class StatusPill(tk.Canvas):
    """Etiqueta tipo pildora con color semantico, opcionalmente clickeable."""
    def __init__(self, parent, text="", kind="info", width=110, height=24,
                 on_click=None):
        super().__init__(parent, width=width, height=height,
                         bg=COLORS["bg"], highlightthickness=0, bd=0)
        self._text = text
        self._kind = kind
        self._cw = width
        self._ch = height
        self._on_click = on_click
        if on_click:
            self.bind("<Button-1>", lambda _e: self._safe_click())
            self.bind("<Enter>", lambda _e: self.config(cursor="hand2"))
            self.bind("<Leave>", lambda _e: self.config(cursor=""))
        self._draw()

    def _safe_click(self):
        try:
            if self._on_click:
                self._on_click()
        except Exception:
            pass

    def _draw(self):
        self.delete("all")
        kind_to_colors = {
            "ok":   (COLORS["ok"], COLORS["ok_bg"]),
            "warn": (COLORS["warn"], COLORS["warn_bg"]),
            "bad":  (COLORS["bad"], COLORS["bad_bg"]),
            "info": (COLORS["info"], COLORS["info_bg"]),
            "muted":(COLORS["text_muted"], COLORS["bg_card_alt"]),
        }
        fg, bg = kind_to_colors.get(self._kind, kind_to_colors["info"])
        round_rect(self, 1, 1, self._cw - 1, self._ch - 1, r=11,
                   fill=bg, outline="")
        self.create_text(self._cw // 2, self._ch // 2,
                         text=self._text, fill=fg, font=FONTS["badge"])

    def update_text(self, text=None, kind=None):
        if text is not None:
            self._text = text
        if kind is not None:
            self._kind = kind
        self._draw()


class ScrollableFrame:
    """
    Helper que crea un frame con scroll vertical. Uso:
        sf = ScrollableFrame(parent)
        sf.pack(fill="both", expand=True)
        # Mete cosas dentro de sf.body()
        tk.Label(sf.body(), text="hola").pack()
    """
    def __init__(self, parent, bg=None):
        self._bg = bg or COLORS["bg"]
        self.outer = tk.Frame(parent, bg=self._bg)
        self._canvas = tk.Canvas(self.outer, bg=self._bg,
                                  highlightthickness=0, bd=0)
        self._scrollbar = ttk.Scrollbar(self.outer, orient="vertical",
                                          command=self._canvas.yview)
        self._inner = tk.Frame(self._canvas, bg=self._bg)

        self._win = self._canvas.create_window(
            (0, 0), window=self._inner, anchor="nw"
        )
        self._inner.bind("<Configure>", self._on_inner_configure)
        self._canvas.bind("<Configure>", self._on_canvas_configure)
        self._canvas.configure(yscrollcommand=self._scrollbar.set)

        self._canvas.pack(side="left", fill="both", expand=True)
        self._scrollbar.pack(side="right", fill="y")

        # Mouse wheel: solo cuando el cursor esta sobre el canvas
        self._canvas.bind("<Enter>", self._bind_wheel)
        self._canvas.bind("<Leave>", self._unbind_wheel)

    def _on_inner_configure(self, _e):
        self._canvas.configure(scrollregion=self._canvas.bbox("all"))

    def _on_canvas_configure(self, e):
        # Hacer que el frame interno se estire al ancho del canvas
        self._canvas.itemconfig(self._win, width=e.width)

    def _bind_wheel(self, _e):
        self._canvas.bind_all("<MouseWheel>", self._on_wheel)

    def _unbind_wheel(self, _e):
        self._canvas.unbind_all("<MouseWheel>")

    def _on_wheel(self, event):
        self._canvas.yview_scroll(int(-event.delta / 120), "units")

    def pack(self, **kwargs):
        self.outer.pack(**kwargs)

    def grid(self, **kwargs):
        self.outer.grid(**kwargs)

    def body(self):
        return self._inner


class SectionCard(tk.Frame):
    """Card contenedor con titulo opcional y padding."""
    def __init__(self, parent, title=None, padding=14):
        super().__init__(parent, bg=COLORS["bg_card"],
                         highlightbackground=COLORS["border"],
                         highlightthickness=1)
        self._inner = tk.Frame(self, bg=COLORS["bg_card"])
        self._inner.pack(fill="both", expand=True, padx=padding, pady=padding)
        if title:
            tk.Label(self._inner, text=title, bg=COLORS["bg_card"],
                     fg=COLORS["text"], font=FONTS["h2"],
                     anchor="w").pack(fill="x", pady=(0, 8))

    def body(self):
        return self._inner


class ToolCard(tk.Canvas):
    """
    Card de herramienta para el lanzador: titulo, version, descripcion, badge,
    boton principal. Click en cualquier parte abre la herramienta.
    Tras el primer click queda 'opening' por unos segundos para evitar
    aperturas duplicadas.
    """
    OPENING_LOCK_MS = 5000  # 5 seg de bloqueo tras click

    def __init__(self, parent, name="", version="", desc="",
                 status="planned", on_open=None, width=320, height=170,
                 icon=""):
        super().__init__(parent, width=width, height=height,
                         bg=COLORS["bg"], highlightthickness=0, bd=0)
        self._name = name
        self._version = version
        self._desc = desc
        self._status = status
        self._on_open = on_open
        self._icon = icon
        self._cw = width
        self._ch = height
        self._hover = False
        self._opening = False
        self.bind("<Configure>", self._on_resize)
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<Button-1>", self._on_click)
        self._draw()

    def _on_resize(self, event):
        self._cw = max(260, event.width)
        self._ch = max(160, event.height)
        self._draw()

    def _on_enter(self, _):
        if self._status == "ready" and not self._opening:
            self._hover = True
            self.config(cursor="hand2")
            self._draw()

    def _on_leave(self, _):
        self._hover = False
        if not self._opening:
            self.config(cursor="")
        self._draw()

    def _on_click(self, _):
        if self._opening:
            return
        if self._status != "ready":
            return
        if not self._on_open:
            return
        self._opening = True
        self._hover = False
        self.config(cursor="wait")
        self._draw()
        try:
            self._on_open()
        except Exception:
            self._reset_opening()
            return
        # Re-habilita despues del lock
        self.after(self.OPENING_LOCK_MS, self._reset_opening)

    def _reset_opening(self):
        self._opening = False
        self.config(cursor="")
        self._draw()

    def _draw(self):
        self.delete("all")
        w, h = self._cw, self._ch

        is_ready = self._status == "ready"
        if self._opening:
            border = COLORS["info"]
        elif self._hover and is_ready:
            border = COLORS["accent"]
        else:
            border = COLORS["border"]
        round_rect(self, 1, 1, w - 1, h - 1, r=16,
                   fill=COLORS["bg_card"], outline=border, width=1)

        if self._opening:
            accent_color = COLORS["info"]
        elif is_ready:
            accent_color = COLORS["accent"]
        else:
            accent_color = COLORS["text_soft"]
        self.create_rectangle(1, 1, 6, h - 1,
                              fill=accent_color, outline=accent_color)

        # Icono grande a la izquierda (si se proporciono)
        text_left = 22
        if self._icon:
            self.create_text(36, 30, text=self._icon, anchor="center",
                             fill=accent_color,
                             font=("Segoe UI Emoji", 22, "normal"))
            text_left = 64

        # Titulo
        title_color = COLORS["text_muted"] if self._opening else COLORS["text"]
        self.create_text(text_left, 22, text=self._name, anchor="w",
                         fill=title_color, font=FONTS["h2"])

        # Version + badge en misma altura
        version_y = 48
        if self._version:
            self.create_text(text_left, version_y, text=self._version,
                             anchor="w", fill=COLORS["text_muted"],
                             font=FONTS["label"])

        if self._opening:
            badge_text, badge_kind, badge_w = "ABRIENDO...", "info", 130
        elif is_ready:
            badge_text, badge_kind, badge_w = "ABRIR", "ok", 90
        else:
            badge_text, badge_kind, badge_w = "PROXIMAMENTE", "muted", 130
        bx2 = w - 22
        bx1 = bx2 - badge_w
        by1 = version_y - 12
        by2 = version_y + 12
        kind_to_colors = {
            "ok":   (COLORS["ok"], COLORS["ok_bg"]),
            "info": (COLORS["info"], COLORS["info_bg"]),
            "muted":(COLORS["text_muted"], COLORS["bg_card_alt"]),
        }
        fg, bg = kind_to_colors[badge_kind]
        round_rect(self, bx1, by1, bx2, by2, r=11, fill=bg, outline="")
        self.create_text((bx1 + bx2) // 2, (by1 + by2) // 2,
                         text=badge_text, fill=fg, font=FONTS["badge"])

        # Descripcion debajo del titulo (sin texto "Abrir >" al final)
        self.create_text(22, 80, text=self._desc, anchor="nw",
                         fill=COLORS["text_muted"], font=FONTS["body"],
                         width=w - 44)
