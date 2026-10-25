# version.py
"""Versión del software y datos de la compilación del ejecutable.

VERSION es la versión del software (semántica: MAYOR.MENOR.PARCHE). Los resultados que se reporten deben
citar la versión y el commit con que se obtuvieron. build_info.json lo escribe build.py al compilar el
ejecutable: así una sesión hecha con el .exe (que no tiene git) registra igualmente de qué commit salió."""
import json
import os
import sys

VERSION = "1.0.0"


def is_frozen():
    """True si se ejecuta como ejecutable (PyInstaller) y no desde el código fuente."""
    return bool(getattr(sys, "frozen", False))


def build_info():
    """Datos fijados al compilar (commit, cambios sin commit, fecha); None si se ejecuta desde el código."""
    path = os.path.join(getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__))), "build_info.json")
    if not is_frozen() or not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)
