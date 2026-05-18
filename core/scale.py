"""
DPI scaling helper para que la app se vea consistente en cualquier
escala de Windows: 100%, 125%, 150%, 175%, 200%, 250%.

Uso:
    from core.scale import setup_scaling, s

    def main():
        root = tk.Tk()
        setup_scaling(root)   # detecta DPI real
        root.geometry(f"{s(1280)}x{s(900)}")
        ...

s(N) devuelve N multiplicado por el factor DPI actual (entero).
- DPI 100%  -> s(100) = 100
- DPI 125%  -> s(100) = 125
- DPI 150%  -> s(100) = 150
- DPI 200%  -> s(100) = 200

Las fuentes en puntos (no en px negativos) Tkinter las escala solo,
asi que NO hace falta envolverlas con s(). Solo dimensiones en px:
geometry, minsize, width, height, padx, pady.
"""

_SCALE = 1.0


def setup_scaling(root):
    """
    Detecta el DPI logico actual desde Tk y guarda el factor.
    Llamar UNA VEZ tras crear el root, antes de usar s().
    Multiplica por el factor del usuario guardado en config (ui_scale).
    """
    global _SCALE
    try:
        # winfo_fpixels('1i') devuelve px por pulgada en el monitor del root.
        # 96 dpi = 100% scaling. 120 = 125%. 144 = 150%. 192 = 200%.
        dpi = float(root.winfo_fpixels("1i"))
        factor = dpi / 96.0
        # Multiplicar por preferencia de usuario (1.0 = sin cambio)
        try:
            from . import config
            user_scale = float(config.get("ui_scale", 1.0) or 1.0)
        except Exception:
            user_scale = 1.0
        factor *= user_scale
        _SCALE = max(0.5, min(3.5, factor))
    except Exception:
        _SCALE = 1.0


def s(value):
    """Escala un valor en pixeles. Devuelve int redondeado."""
    if value is None:
        return 0
    return int(round(float(value) * _SCALE))


def get_scale():
    """Factor actual (float)."""
    return _SCALE
