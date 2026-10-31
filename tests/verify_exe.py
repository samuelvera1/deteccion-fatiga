# tests/verify_exe.py
"""Comprueba que el ejecutable da EXACTAMENTE los mismos resultados que el código fuente: analiza un vídeo de la
referencia de golden_master con el .exe y compara resumen, traza.csv, eventos.csv y parámetros con tests/golden_master.json.

    python tests/verify_exe.py                      # usa dist/FatigaDetector/FatigaDetector-consola.exe
    python tests/verify_exe.py RUTA\FatigaDetector.exe

Hacerlo con cada ejecutable que se entregue. Las sesiones de prueba se borran al terminar."""
import hashlib
import json
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import golden_master as gm  # noqa: E402


def main():
    exe = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "dist", "FatigaDetector", "FatigaDetector-consola.exe")
    if not os.path.exists(exe):
        sys.exit(f"No existe {exe} (compílalo con: python build.py)")
    video = gm.VIDEOS[0]
    with open(gm.GOLDEN, encoding="utf-8") as f:
        gold = json.load(f)[video]
    sessions = os.path.join(os.path.dirname(exe), "sesiones")
    existed = os.path.exists(sessions)
    subprocess.run([exe, "--fuente", os.path.join(ROOT, video), "--sujeto", "golden", "--sin-sonido"],
                   check=True, capture_output=True)
    try:
        folder = max((os.path.join(sessions, d) for d in os.listdir(sessions) if d.endswith("_golden")),
                     key=os.path.getmtime)
        with open(os.path.join(folder, "metadata.json"), encoding="utf-8") as f:
            meta = json.load(f)
        checks = {
            "resumen": json.dumps(meta["resumen"], sort_keys=True) == json.dumps(gold["resumen"], sort_keys=True),
            "traza.csv": gm._sha(os.path.join(folder, "traza.csv")) == gold["traza_sha256"],
            "eventos.csv": gm._sha(os.path.join(folder, "eventos.csv"), "Timestamp") == gold["eventos_sha256"],
            "parámetros": hashlib.sha256(json.dumps(meta["parametros"], sort_keys=True, default=str).encode("utf-8")
                                         ).hexdigest() == gold["parametros_sha256"],
        }
        print(f"Ejecutable {meta['software']['version']}, commit {(meta['git']['commit'] or '?')[:7]}, "
              f"cambios sin commit: {meta['git']['cambios_sin_commit'] or 'ninguno'}")
        for name, ok in checks.items():
            print(f"  {name:<12} {'IGUAL' if ok else 'DIFIERE'}")
    finally:
        shutil.rmtree(sessions, ignore_errors=True) if not existed else shutil.rmtree(folder, ignore_errors=True)
        private = os.path.join(os.path.dirname(exe), "participantes_privado.csv")
        if os.path.exists(private) and not existed:
            os.remove(private)
    sys.exit(0 if all(checks.values()) else 1)


if __name__ == "__main__":
    main()
