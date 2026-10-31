# fatigue_audio.py
"""Sonidos del programa: avisos de la calibración (el sujeto tiene los ojos cerrados y no ve la pantalla) y melodías
de advertencia de las alertas de fatiga."""
import os
import sys

SOUND_FILES = {"NORMAL": "normal.wav", "PRECAUCION": "precaucion.wav", "SOMNOLENCIA": "somnolencia.wav",
               "MICRO_SUENO": "microsueno.wav"}


def _sound_path(level):
    """Archivo de la melodía de un nivel. Primero la carpeta 'sonidos' junto al programa (para poner música propia:
    mismo nombre, formato .wav) y, si no hay, la melodía incluida."""
    name = SOUND_FILES.get(level)
    if not name:
        return None
    import paths
    bundled = os.path.join(getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__))), "assets", "sounds", name)
    for path in (os.path.join(paths.data_dir(), "sonidos", name), bundled):
        if os.path.exists(path):
            return path
    return None


def play_alert(level):
    """Melodía de advertencia del nivel, sin bloquear el análisis. Devuelve False si no pudo sonar."""
    path = _sound_path(level)
    if path is None:
        return False
    try:
        import winsound
        winsound.PlaySound(path, winsound.SND_FILENAME | winsound.SND_ASYNC)
        return True
    except Exception:
        return False


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
