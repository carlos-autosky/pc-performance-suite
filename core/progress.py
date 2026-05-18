"""
ProgressOverlay - dialogo modal con barra de progreso indeterminada.

Uso:
    overlay = ProgressOverlay(root, "Limpiando archivos...")
    def worker():
        try:
            do_work()
        finally:
            root.after(0, overlay.close)
        root.after(0, lambda: messagebox.showinfo("OK", "Listo"))
    threading.Thread(target=worker, daemon=True).start()

El overlay bloquea la interaccion con la ventana padre (grab_set)
para evitar dobles clicks. Se puede actualizar el mensaje con
overlay.update_message("Nueva fase...").
"""

import tkinter as tk
import customtkinter as ctk

from .style import COLORS, FONTS
from .scale import s


class ProgressOverlay:
    def __init__(self, parent, message="Trabajando..."):
        self.parent = parent
        self._closed = False

        # Forzar render del parent para conseguir geometria real
        try:
            parent.update_idletasks()
        except Exception:
            pass

        self.win = tk.Toplevel(parent)
        self.win.title("Procesando...")
        # NO overrideredirect ni grab_set: causan invisibilidad en algunos sistemas
        try:
            self.win.transient(parent)
        except Exception:
            pass
        self.win.configure(bg=COLORS["bg_card"])
        try:
            self.win.attributes("-topmost", True)
        except Exception:
            pass

        ww = s(500)
        wh = s(160)

        # Centrar sobre el parent
        try:
            px = parent.winfo_rootx()
            py = parent.winfo_rooty()
            pw = parent.winfo_width()
            ph = parent.winfo_height()
            if pw < 100 or ph < 100:
                pw = parent.winfo_screenwidth()
                ph = parent.winfo_screenheight()
                px = py = 0
            x = px + max(0, (pw - ww) // 2)
            y = py + max(0, (ph - wh) // 2)
            self.win.geometry(f"{ww}x{wh}+{x}+{y}")
        except Exception:
            self.win.geometry(f"{ww}x{wh}")

        # Forzar visibilidad
        try:
            self.win.deiconify()
            self.win.lift()
            self.win.focus_force()
        except Exception:
            pass

        # Borde de acento
        outer = tk.Frame(self.win, bg=COLORS["accent"])
        outer.pack(fill="both", expand=True)
        inner = tk.Frame(outer, bg=COLORS["bg_card"])
        inner.pack(fill="both", expand=True, padx=2, pady=2)

        title = tk.Label(inner, text="Procesando...",
                         bg=COLORS["bg_card"], fg=COLORS["text_muted"],
                         font=FONTS["small"], anchor="w")
        title.pack(fill="x", padx=s(20), pady=(s(14), 0))

        self._msg_var = tk.StringVar(value=message)
        self.msg_label = tk.Label(inner, textvariable=self._msg_var,
                                   bg=COLORS["bg_card"], fg=COLORS["text"],
                                   font=FONTS["h2"], anchor="w",
                                   wraplength=ww - s(40), justify="left")
        self.msg_label.pack(fill="x", padx=s(20), pady=(s(2), s(12)))

        self.bar = ctk.CTkProgressBar(
            inner, mode="indeterminate",
            progress_color=COLORS["accent"],
            fg_color=COLORS["bg_card_alt"],
            border_color=COLORS["border"],
            width=ww - s(40), height=s(14),
        )
        self.bar.pack(padx=s(20), pady=(0, s(14)))
        try:
            self.bar.start()
        except Exception:
            pass

        # No grab_set: en algunos sistemas hace que la ventana quede invisible

    def update_message(self, message):
        if self._closed:
            return
        try:
            self._msg_var.set(message)
        except Exception:
            pass

    def close(self):
        if self._closed:
            return
        self._closed = True
        try:
            self.bar.stop()
        except Exception:
            pass
        try:
            self.win.grab_release()
        except Exception:
            pass
        try:
            self.win.destroy()
        except Exception:
            pass


def run_with_progress(root, message, work_fn, on_done=None,
                      on_error=None, message_updates=None):
    """
    Helper de alto nivel: muestra overlay, lanza work_fn en thread,
    cierra overlay al terminar y llama on_done(result) o on_error(exc).

    work_fn debe ser callable() -> result (cualquier cosa).
    on_done(result) se llama en el hilo de UI tras cerrar el overlay.
    on_error(exception) idem para errores.
    """
    import threading

    overlay = ProgressOverlay(root, message)

    def worker():
        result = None
        err = None
        try:
            result = work_fn()
        except Exception as e:
            err = e
        finally:
            root.after(0, overlay.close)

        if err and on_error:
            root.after(0, lambda: on_error(err))
        elif on_done:
            root.after(0, lambda: on_done(result))

    threading.Thread(target=worker, daemon=True).start()
    return overlay
