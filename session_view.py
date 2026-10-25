# session_view.py
"""Datos de la ventana de resumen: convierte el metadata.json de una sesión en lo que se muestra, ya formateado
(español: coma decimal, mm:ss, singular y plural). Sin interfaz, para poder probarlo sin abrir ventanas."""
import os
from datetime import datetime

import version

LEVELS = ("NORMAL", "PRECAUCION", "SOMNOLENCIA", "MICRO_SUENO")
LEVEL_NAMES = {"NORMAL": "NORMAL", "PRECAUCION": "PRECAUCIÓN", "SOMNOLENCIA": "SOMNOLENCIA",
               "MICRO_SUENO": "MICRO-SUEÑO"}
GLASSES = {"con_gafas": "Con gafas", "sin_gafas": "Sin gafas"}


def decimal(value, digits=1):
    """Número con coma decimal: 6.4 -> '6,4'."""
    return f"{value:.{digits}f}".replace(".", ",")


def percent(value):
    """'80,7 %' y '5,0 %'; sin decimales solo en los extremos ('0 %', '100 %')."""
    return f"{round(value)} %" if value < 0.05 or value > 99.95 else f"{decimal(value)} %"


def clock(seconds):
    """Duración como mm:ss (h:mm:ss si pasa de una hora)."""
    total = int(round(seconds or 0))
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes:02d}:{secs:02d}"


def plural(count, singular, plural_form):
    return f"{count} {singular if count == 1 else plural_form}"


def summary_view(meta, reliable, folder):
    """meta: contenido de metadata.json al terminar la sesión. reliable: si el cierre del ojo se midió bien
    (FatigueMonitor.closure_reliable). folder: carpeta donde quedó la sesión."""
    summary = meta["resumen"]
    fatigue = summary.get("fatiga") or {"tiempo_por_nivel_s": {}, "alertas": {}}
    seconds = {level: float(fatigue["tiempo_por_nivel_s"].get(level, 0.0)) for level in LEVELS}
    total = sum(seconds.values())
    alerts = fatigue.get("alertas", {})
    levels = [{"key": level, "name": LEVEL_NAMES[level], "seconds": seconds[level], "time": clock(seconds[level]),
               "percent": percent(seconds[level] / total * 100) if total else "—",
               "share": seconds[level] / total if total else 0.0,
               "alerts": "—" if level == "NORMAL" else str(alerts.get(level, 0))} for level in LEVELS]

    subject = meta.get("sujeto") or "anonimo"
    blinks, long_blinks = summary["parpadeos"], summary["parpadeos_prolongados"]
    yawns, micro_yawns = summary["bostezos"], summary["micro_bostezos"]
    mean_blink = summary.get("duracion_media_parpadeo_s")
    commit = ((meta.get("git") or {}).get("commit") or "")[:7]
    software = meta.get("software") or {}
    return {
        "participant": "Anónimo" if subject == "anonimo" else subject,
        "glasses": GLASSES.get(meta.get("condicion"), "Gafas: no indicado"),
        "when": datetime.fromisoformat(meta["inicio"]).strftime("%d/%m/%Y · %H:%M"),
        "duration": clock(summary["duracion_s"]),
        "reliable": bool(reliable),
        "counted": summary.get("inicio_monitoreo_s") is not None and total > 0,
        "blinks": str(blinks),
        "blinks_sub": [plural(long_blinks, "prolongado", "prolongados"),
                       f"media {decimal(mean_blink, 2)} s" if mean_blink else "sin duración media"],
        "yawns": str(yawns),
        "yawns_sub": [plural(micro_yawns, "micro-bostezo", "micro-bostezos")],
        "perclos": f"{decimal(summary['perclos_final_pct'])} %",
        "perclos_sub": "ventana de 60 s" if reliable else "no fiable",
        "levels": levels,
        "recalibrations": str(summary["recalibraciones"]),
        "fps": decimal(meta.get("rendimiento", {}).get("fps_procesamiento_medio") or 0),
        "folder": os.path.abspath(folder),
        "build": f"v{software.get('version', version.VERSION)} · commit {commit or 'desconocido'}",
    }
