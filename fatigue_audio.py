# fatigue_audio.py
"""Avisos sonoros de la calibración (el sujeto tiene los ojos cerrados y no ve la pantalla)."""


def retry_beep():
    """Dos tonos graves, distintos del pitido agudo de 'abre los ojos': el intento no salió, mira la pantalla."""
    try:
        import winsound
        winsound.Beep(500, 180)
        winsound.Beep(400, 260)
    except Exception:
        print("\a\a", end="", flush=True)


def beep():
    """Aviso sonoro (el sujeto tiene los ojos cerrados y no ve la pantalla)."""
    try:
        import winsound
        winsound.Beep(1200, 250)
    except Exception:
        print("\a", end="", flush=True)
