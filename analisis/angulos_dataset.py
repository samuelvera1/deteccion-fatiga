"""Cómo está colocada cada persona respecto a su cámara en los datasets: giro (yaw) y cabeceo (pitch) ABSOLUTOS de la
cara respecto a la cámara (misma fórmula que camara_yaw_grados), 1 cuadro por segundo, y tamaño de la cara.
Uso: python angulos_dataset.py SALIDA.json VIDEO [VIDEO ...]   (etiqueta = carpeta/archivo)"""
import json
import os
import statistics
import sys
from concurrent.futures import ProcessPoolExecutor

REPO = r"C:\Users\Practicante\Downloads\vision computacional"


def analyze(path):
    sys.path.insert(0, REPO)
    import cv2
    import numpy as np

    import fatigue_geometry
    from fatigue_core import FaceMeshDetector
    det = FaceMeshDetector(staticMode=True, maxFaces=1, minDetectionCon=0.5, minTrackCon=0.5, refineLandmarks=True)
    cap = cv2.VideoCapture(path)
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    step = max(1, int(round(fps)))
    yaws, pitches, ipds, n, i = [], [], [], 0, 0
    width = None
    while True:
        if i % step:
            if not cap.grab():
                break
            i += 1
            continue
        ok, img = cap.read()
        if not ok:
            break
        i += 1
        n += 1
        width = img.shape[1]
        _, faces = det.findFaceMesh(img, draw=False)
        if not faces:
            continue
        f3 = det.faces3d[0]
        axes = fatigue_geometry.face_axes(f3)
        if axes is None:
            continue
        yaws.append(float(np.degrees(np.arctan2(axes[0, 2], axes[2, 2]))))
        pitches.append(float(np.degrees(np.arcsin(np.clip(-axes[1, 2], -1, 1)))))
        ipds.append(float(np.linalg.norm(f3[468, :2] - f3[473, :2])) / width if len(f3) > 473 else float("nan"))
    cap.release()

    def q(v, p):
        s = sorted(v)
        return round(s[int(p * (len(s) - 1))], 1) if s else None
    return {"video": path, "muestras": n, "con_cara": len(yaws), "ancho_px": width,
            "yaw_mediana": q(yaws, 0.5), "yaw_p10": q(yaws, 0.1), "yaw_p90": q(yaws, 0.9),
            "pitch_mediana": q(pitches, 0.5), "pitch_p10": q(pitches, 0.1), "pitch_p90": q(pitches, 0.9),
            "ipd_rel_mediana": round(statistics.median(ipds), 4) if ipds else None}


def main():
    out, videos = sys.argv[1], sys.argv[2:]
    with ProcessPoolExecutor(max_workers=3) as ex:
        results = list(ex.map(analyze, videos))
    json.dump(results, open(out, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    for r in results:
        print(f"{os.path.relpath(r['video'], os.path.dirname(os.path.dirname(r['video']))):24} cara {r['con_cara']}/{r['muestras']}  "
              f"yaw {r['yaw_mediana']} [{r['yaw_p10']}, {r['yaw_p90']}]  pitch {r['pitch_mediana']} "
              f"[{r['pitch_p10']}, {r['pitch_p90']}]  ipd/ancho {r['ipd_rel_mediana']}")


if __name__ == "__main__":
    main()
