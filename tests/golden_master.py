# tests/golden_master.py
"""Prueba de caracterización: analiza vídeos grabados con el reloj del propio vídeo (determinista) y compara
el resumen y los CSV con los guardados antes de refactorizar. Si algo cambia, el refactor alteró resultados.

    python tests/golden_master.py --generar     # guarda la referencia (solo con el código de partida)
    python tests/golden_master.py               # verifica contra la referencia
"""
import argparse
import csv
import hashlib
import json
import os
import sys
import tempfile

import cv2

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from fatigue_framework import FatigueMonitor  # noqa: E402

GOLDEN = os.path.join(os.path.dirname(os.path.abspath(__file__)), "golden_master.json")
# Sesiones grabadas (en sesiones/, fuera del repositorio) usadas como entrada; calibración automática
VIDEOS = [
    "sesiones/20261017_120014_Samuel_Vera/grabacion.mp4",
    "sesiones/20261017_120716_Samuel_Vera/grabacion.mp4",
    "sesiones/20261017_114229_Samuel_Vera/grabacion.mp4",
]


def _headless():
    cv2.imshow = lambda *a, **k: None
    cv2.waitKey = lambda *a, **k: 255
    cv2.destroyAllWindows = lambda *a, **k: None
    cv2.getWindowProperty = lambda *a, **k: 1


def _sha(path, skip_column=None):
    """Hash del CSV; skip_column excluye una columna que depende del reloj del sistema."""
    with open(path, encoding="utf-8", newline="") as f:
        rows = list(csv.reader(f))
    if skip_column in rows[0]:
        idx = rows[0].index(skip_column)
        rows = [row[:idx] + row[idx + 1:] for row in rows]
    return hashlib.sha256(json.dumps(rows).encode("utf-8")).hexdigest()


def analyze(video):
    with tempfile.TemporaryDirectory() as tmp:
        monitor = FatigueMonitor(video_source=video, subject_id="golden", sessions_dir=tmp, alert_sound=False)
        monitor.start()
        session_dir = monitor.session.dir
        resumen = json.loads(json.dumps(monitor.session.metadata["resumen"]))
        return {
            "resumen": resumen,
            "traza_sha256": _sha(os.path.join(session_dir, "traza.csv")),
            "eventos_sha256": _sha(os.path.join(session_dir, "eventos.csv"), "Timestamp"),
        }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--generar", action="store_true")
    args = parser.parse_args()
    _headless()
    current = {}
    for rel in VIDEOS:
        path = os.path.join(ROOT, rel)
        if not os.path.exists(path):
            sys.exit(f"Falta el vídeo de referencia: {rel}")
        print(f"Analizando {rel} ...")
        current[rel] = analyze(path)
    if args.generar:
        with open(GOLDEN, "w", encoding="utf-8") as f:
            json.dump(current, f, indent=1, ensure_ascii=False, sort_keys=True)
        print(f"Referencia guardada en {GOLDEN}")
        return
    with open(GOLDEN, encoding="utf-8") as f:
        golden = json.load(f)
    failed = False
    for rel, now in current.items():
        if json.loads(json.dumps(now, sort_keys=True)) == golden.get(rel):
            print(f"OK       {rel}")
        else:
            failed = True
            print(f"DIFIERE  {rel}")
            ref = golden.get(rel, {})
            for key in ("traza_sha256", "eventos_sha256"):
                if ref.get(key) != now[key]:
                    print(f"   {key} cambió")
            for key, value in now["resumen"].items():
                if ref.get("resumen", {}).get(key) != value:
                    print(f"   resumen[{key}]: {ref.get('resumen', {}).get(key)!r} -> {value!r}")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
