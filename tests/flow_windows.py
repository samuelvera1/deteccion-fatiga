# tests/flow_windows.py
"""Prueba del flujo con ventanas (inicio -> sesión -> resumen -> nueva sesión -> salir) con un vídeo grabado en lugar de
la cámara y sin abrir ventanas. Se ejecuta a mano (como golden_master.py), tarda unos 50 s:
    python tests/flow_windows.py"""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import gui  # noqa: E402
import main  # noqa: E402
from tests import golden_master as gm  # noqa: E402

VIDEO = os.path.join(ROOT, gm.VIDEOS[0])
gm._headless()
# las sesiones de la prueba se guardan en una carpeta temporal, no en sesiones/ del proyecto
os.chdir(tempfile.mkdtemp(prefix="flujo_ventanas_"))
calls = {"start": 0, "summary": [], "camera": 0}


def fake_start():
    calls["start"] += 1
    return {"name": "", "condition": "con_gafas", "record": False} if calls["start"] <= 2 else None


def fake_summary(view):
    calls["summary"].append(view)
    return "new" if len(calls["summary"]) == 1 else None


gui.ask_start, gui.show_summary = fake_start, fake_summary
gui.camera_error = lambda: calls.__setitem__("camera", calls["camera"] + 1) or None
real_parse = main.parse_args
main.parse_args = lambda argv=None: real_parse(list(argv or []) + ["--fuente", VIDEO, "--sin-sonido"] if argv is not None else None)
cameras = iter([False, True, True])             # la primera comprobación de cámara falla, pero el aviso sale con "Salir"
main.camera_available = lambda index=0: next(cameras)

# 1) sin cámara y el usuario elige salir: no empieza ninguna sesión
main.run_with_windows()
assert calls["camera"] == 1 and not calls["summary"], "con cámara ausente y 'Salir' no debe empezar la sesión"

# 2) con cámara: dos sesiones seguidas ("Nueva sesión") y luego salir
calls["start"] = 0
main.run_with_windows()
views = calls["summary"]
assert len(views) == 2, f"se esperaban 2 resúmenes, hubo {len(views)}"
view = views[0]
print("participante:", view["participant"], "| gafas:", view["glasses"], "| duración:", view["duration"])
print("parpadeos:", view["blinks"], view["blinks_sub"], "| bostezos:", view["yawns"], view["yawns_sub"], "| PERCLOS:", view["perclos"])
print("niveles:", [(lv["name"], lv["time"], lv["percent"]) for lv in view["levels"]])
print("carpeta:", view["folder"], "|", view["build"], "| fiable:", view["reliable"])
assert view["participant"] == "Anónimo" and view["glasses"] == "Con gafas"
assert view["blinks"] == "4" and view["yawns"] == "2", "no coincide con la referencia de golden_master (4 parpadeos, 2 bostezos)"
print("FLUJO OK")
