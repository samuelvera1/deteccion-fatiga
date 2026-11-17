"""E12: estado de ojo cerrado (cierre >= 0,80) por intervalo de |cabeceo| en Eyeblink8, incluidos los cuadros fuera de
rango, y disponibilidad de la alerta en UTA-RLDD con distintos límites de cabeceo. Criterio en el registro (E12).
Uso: python e12_cabeceo.py DATOS_EB8 SESIONES_EB8 SESIONES_RLDD SALIDA.json"""
import csv
import glob
import json
import math
import os
import statistics
import sys
from collections import deque

MARGIN = 2
BINS = [(0, 10), (10, 15), (15, 20), (20, 25), (25, 30)]
LIMITS = [10, 15, 20, 25, 30]
MAX_YAW = 40.0
MAX_FRAME_WEIGHT = 0.2


def wilson(k, n, z=1.96):
    if n == 0:
        return None, None, None
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return p, max(0.0, c - h), min(1.0, c + h)


def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def parse_tag(path):
    rows, started = {}, False
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            if line.startswith("#start"):
                started = True
                continue
            if not started or line.startswith("#end") or ":" not in line:
                continue
            p = line.strip().split(":")
            rows[int(p[0])] = {"blink": int(p[1]), "lfc": p[3] == "C", "lnv": p[4] == "N",
                               "rfc": p[5] == "C", "rnv": p[6] == "N"}
    return rows


def load_eb8(data, session):
    vid = session.rsplit("_EB8_", 1)[1]
    tag = parse_tag(glob.glob(os.path.join(data, vid, "*.tag"))[0])
    blinks = {f for f, r in tag.items() if r["blink"] != -1}
    near = set()
    for f in blinks:
        near.update(range(f - MARGIN, f + MARGIN + 1))
    frames = []      # (|cabeceo|, cabeceo, apertura/abierto, clase, postura_valida)
    for r in csv.DictReader(open(os.path.join(session, "traza.csv"), encoding="utf-8")):
        if r["fase"] != "monitoreo":
            continue
        fr = int(r["frame"])
        ear, base, pitch, yaw = num(r["ear"]), num(r["ear_baseline"]), num(r["cabeza_pitch"]), num(r["cabeza_yaw"])
        a = tag.get(fr)
        if ear is None or not base or pitch is None or yaw is None or a is None or a["lnv"] or a["rnv"]:
            continue
        cls = "pos" if a["lfc"] and a["rfc"] else ("neg" if fr not in near else "int")
        frames.append((abs(pitch), pitch, abs(yaw), ear / base, cls, r["postura_valida"] == "1"))
    # proporción propia como en E8: mediana de apertura/abierto en los positivos con postura válida
    own = [x for _, _, _, x, c, v in frames if c == "pos" and v]
    return vid, frames, statistics.median(own) if own else None


def eb8(data, sessions):
    recs = [load_eb8(data, s) for s in sorted(glob.glob(os.path.join(sessions, "*_EB8_*")))]
    own = {vid: ratio for vid, _, ratio in recs}
    table = {}
    for lo, hi in BINS:
        for sign in ("todos", "abajo", "arriba"):
            tp = npos = fp = nneg = 0
            for vid, frames, _ in recs:
                ratio = statistics.median(v for k, v in own.items() if k != vid and v is not None)
                thr = 0.2 + 0.8 * ratio
                for ap, p, ay, x, c, _ in frames:
                    if ay > MAX_YAW or not ((lo == 0 and ap <= hi) or (lo < ap <= hi)):
                        continue
                    if sign == "abajo" and p <= 0 or sign == "arriba" and p > 0:
                        continue
                    closed = x <= thr
                    if c == "pos":
                        npos += 1
                        tp += closed
                    elif c == "neg":
                        nneg += 1
                        fp += closed
            sens = wilson(tp, npos)
            fpr = wilson(fp, nneg)
            table[f"{lo}-{hi}|{sign}"] = {"positivos": npos, "vp": tp, "sens": sens[0], "sens_ic95": sens[1:],
                                         "negativos": nneg, "fp": fp, "fp_tasa": fpr[0], "fp_ic95": fpr[1:]}
    # criterio
    limit = 10
    for lo, hi in BINS[1:]:
        t = table[f"{lo}-{hi}|todos"]
        ok = (t["negativos"] >= 500 and t["fp_tasa"] <= 0.01 and t["positivos"] >= 30 and t["sens"] >= 0.80)
        for sign in ("abajo", "arriba"):
            s = table[f"{lo}-{hi}|{sign}"]
            if s["negativos"] >= 500 and s["fp_tasa"] > 0.01:
                ok = False
        if not ok:
            break
        limit = hi
    return {"proporciones_propias": own, "tabla": table, "limite_adoptado": limit}


def availability(rows, limit, fraction=0.9):
    """Fracción del tiempo de monitoreo (desde 60 s) con >= fraction * 60 s válidos en la ventana deslizante."""
    hist, total, last = deque(), 0.0, None
    avail = span = 0.0
    t_start, prev = None, None
    for t, pitch, yaw in rows:
        if t_start is None:
            t_start = t
        if prev is not None and t - t_start >= 60:
            step = min(t - prev, MAX_FRAME_WEIGHT)
            span += step
            avail += step if total >= fraction * 60 - 1e-9 else 0.0
        prev = t
        if pitch is None or abs(pitch) > limit or abs(yaw) > MAX_YAW:
            last = None
            continue
        dt = 0.0 if last is None else min(max(t - last, 0.0), MAX_FRAME_WEIGHT)
        last = t
        hist.append((t, dt))
        total += dt
        while hist and hist[0][0] < t - 60:
            total -= hist.popleft()[1]
    return avail / span if span else None


def rldd(sessions):
    out = []
    for s in sorted(glob.glob(os.path.join(sessions, "*_RLDD_*"))):
        rows = []
        for r in csv.DictReader(open(os.path.join(s, "traza.csv"), encoding="utf-8")):
            if r["fase"] != "monitoreo":
                continue
            rows.append((float(r["t"]), num(r["cabeza_pitch"]), num(r["cabeza_yaw"]) or 0.0))
        if not rows:
            continue
        dur = rows[-1][0] - rows[0][0]
        w = [min(b[0] - a[0], MAX_FRAME_WEIGHT) for a, b in zip(rows, rows[1:])]
        tot = sum(w)
        pitch_out = sum(d for d, r in zip(w, rows) if r[1] is not None and abs(r[1]) > 10 and abs(r[2]) <= MAX_YAW)
        yaw_out = sum(d for d, r in zip(w, rows) if abs(r[2]) > MAX_YAW)
        pitches = [r[1] for r in rows if r[1] is not None]
        rec = {"video": s.rsplit("_RLDD_", 1)[1], "monitoreo_s": round(dur, 1),
               "fuera_cabeceo_pct": round(100 * pitch_out / tot, 1), "fuera_giro_pct": round(100 * yaw_out / tot, 1),
               "cabeceo_mediana": round(statistics.median(pitches), 1),
               "cabeceo_p90_abs": round(sorted(abs(p) for p in pitches)[int(0.9 * len(pitches))], 1),
               "disponible_pct": {str(L): round(100 * availability(rows, L), 1) for L in LIMITS},
               "disponible_pct_fraccion_075": {str(L): round(100 * availability(rows, L, 0.75), 1) for L in (10,)}}
        out.append(rec)
    return out


def main():
    data, eb8_sessions, rldd_sessions, out_path = sys.argv[1:5]
    report = {"eyeblink8": eb8(data, eb8_sessions), "uta_rldd": rldd(rldd_sessions)}
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=1, ensure_ascii=False)
    t = report["eyeblink8"]["tabla"]
    print("Eyeblink8 por |cabeceo| (todos / abajo / arriba):")
    for lo, hi in BINS:
        for sign in ("todos", "abajo", "arriba"):
            r = t[f"{lo}-{hi}|{sign}"]
            sens = "-" if r["sens"] is None else f"{r['sens']:.3f}"
            fpr = "-" if r["fp_tasa"] is None else f"{100 * r['fp_tasa']:.2f} %"
            print(f"  {lo:>2}-{hi:<2} {sign:6} pos {r['positivos']:5} sens {sens:>5}   neg {r['negativos']:6} FP {fpr}")
    print("Límite adoptado según el criterio:", report["eyeblink8"]["limite_adoptado"])
    print("\nUTA-RLDD:")
    for r in report["uta_rldd"]:
        print(f"  {r['video']:>20} {r['monitoreo_s']:6.0f} s  fuera cabeceo {r['fuera_cabeceo_pct']:5.1f} %  giro "
              f"{r['fuera_giro_pct']:5.1f} %  mediana {r['cabeceo_mediana']:6.1f}  p90|c| {r['cabeceo_p90_abs']:5.1f}  "
              f"disponible {r['disponible_pct']}")


if __name__ == "__main__":
    main()
