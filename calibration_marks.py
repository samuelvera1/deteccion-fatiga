# calibration_marks.py
"""
Marcas de calibración manual de un vídeo (protocolo de grabación):
  1. "Mira a la cámara"  -> tramo NEUTRO (ojos abiertos, cara quieta)
  2. "Cierra los ojos"   -> tramo OJOS CERRADOS
  3. "Ábrelos"           -> INICIO DE LA PRUEBA
El investigador marca los tres momentos con revisar.py --video; las marcas se guardan junto al vídeo
(<video>.calibracion.json) y main.py las usa al analizarlo. Los frames son la referencia exacta
(índice en orden de lectura, igual que en el análisis); los segundos son informativos.
"""
import json
import os
from datetime import datetime

MIN_NEUTRAL_FRAMES = 15   # ~0.5 s a 30 fps: mínimo para una mediana estable del ojo abierto
MIN_CLOSED_FRAMES = 10    # ~0.33 s a 30 fps


def marks_path(video_path):
    return os.path.splitext(video_path)[0] + ".calibracion.json"


def empty_marks(video_path, fps, n_frames):
    return {"video": os.path.basename(video_path), "fps": fps, "frames_video": n_frames,
            "neutro": None, "cerrado": None, "inicio_prueba": None}


def load_marks(video_path):
    """Marcas guardadas del vídeo, o None si no tiene."""
    path = marks_path(video_path)
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_marks(video_path, marks):
    fps = marks["fps"]
    for key in ("neutro", "cerrado"):
        segment = marks.get(key)
        if segment:
            segment["inicio_s"] = round(segment["inicio_frame"] / fps, 3)
            segment["fin_s"] = None if segment["fin_frame"] is None else round(segment["fin_frame"] / fps, 3)
    if marks.get("inicio_prueba"):
        marks["inicio_prueba"]["s"] = round(marks["inicio_prueba"]["frame"] / fps, 3)
    marks["marcado"] = datetime.now().isoformat(timespec="seconds")
    with open(marks_path(video_path), "w", encoding="utf-8") as f:
        json.dump(marks, f, ensure_ascii=False, indent=2)


def problems(marks):
    """Lista de problemas que impiden usar las marcas (vacía = listas para analizar)."""
    if marks is None:
        return ["no hay marcas"]
    found = []
    neutral, closed, start = marks.get("neutro"), marks.get("cerrado"), marks.get("inicio_prueba")
    for name, segment, minimum in (("neutro", neutral, MIN_NEUTRAL_FRAMES), ("ojos cerrados", closed, MIN_CLOSED_FRAMES)):
        if not segment:
            found.append(f"falta el tramo {name}")
        elif segment.get("fin_frame") is None:
            found.append(f"falta el fin del tramo {name}")
        elif segment["fin_frame"] - segment["inicio_frame"] + 1 < minimum:
            found.append(f"el tramo {name} es muy corto (mínimo {minimum} frames)")
    if not start:
        found.append("falta el inicio de la prueba")
    if found:
        return found
    if not (neutral["fin_frame"] < closed["inicio_frame"] or closed["fin_frame"] < neutral["inicio_frame"]):
        found.append("los tramos neutro y ojos cerrados se solapan")
    if max(neutral["fin_frame"], closed["fin_frame"]) >= start["frame"]:
        found.append("la prueba debe empezar después de los dos tramos de calibración")
    return found


def frame_ranges(marks):
    """(neutro_ini, neutro_fin, cerrado_ini, cerrado_fin, inicio_prueba) en frames, inclusivos."""
    n, c = marks["neutro"], marks["cerrado"]
    return n["inicio_frame"], n["fin_frame"], c["inicio_frame"], c["fin_frame"], marks["inicio_prueba"]["frame"]
