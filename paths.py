# paths.py
"""Dónde guarda el programa sus datos (sesiones, registro, caché del editor, sonidos propios).

  Desde el código fuente:        la carpeta del proyecto.
  Ejecutable instalado:          Documentos\\Fatiga Detector (fácil de encontrar, sobrevive a actualizar o desinstalar y
                                 siempre se puede escribir en ella).
  Ejecutable portátil (.zip):    junto al .exe, si ahí hay un archivo portable.txt.
Las sesiones (sesiones/) y participantes_privado.csv son relativos a esta carpeta: main.py la usa como carpeta de trabajo."""
import ctypes
import os
import sys
import uuid

APP_FOLDER = "Fatiga Detector"
PORTABLE_MARK = "portable.txt"


class _GUID(ctypes.Structure):
    _fields_ = [("Data1", ctypes.c_ulong), ("Data2", ctypes.c_ushort), ("Data3", ctypes.c_ushort),
                ("Data4", ctypes.c_ubyte * 8)]


def documents_folder():
    """Carpeta Documentos del usuario (respeta que esté redirigida, p. ej. a OneDrive)."""
    try:
        guid = uuid.UUID("FDD39AD0-238F-46AF-ADB4-6C85480369C7")           # FOLDERID_Documents
        ident = _GUID.from_buffer_copy(guid.bytes_le)
        pointer = ctypes.c_wchar_p()
        if ctypes.windll.shell32.SHGetKnownFolderPath(ctypes.byref(ident), 0, None, ctypes.byref(pointer)) == 0:
            path = pointer.value
            ctypes.windll.ole32.CoTaskMemFree(pointer)
            if path:
                return path
    except (AttributeError, OSError):
        pass
    return os.path.join(os.path.expanduser("~"), "Documents")


def is_portable():
    return os.path.exists(os.path.join(os.path.dirname(sys.executable), PORTABLE_MARK))


def data_dir():
    """Carpeta de datos del programa (se crea si no existe)."""
    if not getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(__file__))
    folder = os.path.dirname(sys.executable) if is_portable() else os.path.join(documents_folder(), APP_FOLDER)
    os.makedirs(folder, exist_ok=True)
    return folder
