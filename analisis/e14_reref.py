"""E14: simula sobre las trazas la regla «rehacer la referencia con un cambio de postura sostenido» y la compara con
la versión actual (abajo 10°, arriba 15°, giro 40°). Criterio en el registro (E14).
Uso: python e14_reref.py SESIONES_RLDD DATOS_EB8 SESIONES_EB8 SALIDA.json"""
import csv
import glob
import json
import math
import os
import statistics
import sys
from collections import deque

DOWN, UP, YAW = 10.0, 15.0, 40.0
HOLD_S, MAX_STD = 20.0, 4.0
CAP_PITCH, CAP_YAW = 30.0, 40.0
RLDD_RATIO = 0.2945
P80 = 0.80
MARGIN = 2


def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def out_of_range(p, y):
    return p > DOWN or -p > UP or abs(y) > YAW


def threshold(ratio):
    return 1.0 - P80 * (1.0 - ratio)          # cierre >= 0,80  <=>  apertura/abierto <= 0,2 + 0,8 r


def simulate(frames, base, ratio):
    """frames: lista de (t, yaw, pitch, ear). Devuelve por cuadro (válido_actual, válido_e14, cerrado_actual,
    cerrado_e14) y el número de veces que se rehizo la referencia."""
    thr = threshold(ratio)
    ref_y = ref_p = 0.0
    open_e14 = base
    window = deque()
    triggers = []
    out = []
    for t, y, p, ear in frames:
        cur_valid = not out_of_range(p, y)
        e_valid = not out_of_range(p - ref_p, y - ref_y)
        window.append((t, y, p, ear, e_valid))
        while window and window[0][0] < t - HOLD_S:
            window.popleft()
        if (not e_valid and window[-1][0] - window[0][0] >= HOLD_S - 0.5 and not any(w[4] for w in window)):
            ps, ys = [w[2] for w in window], [w[1] for w in window]
            if statistics.pstdev(ps) <= MAX_STD and statistics.pstdev(ys) <= MAX_STD:
                mp, my = statistics.median(ps), statistics.median(ys)
                if abs(mp) <= CAP_PITCH and abs(my) <= CAP_YAW:
                    ears = sorted(w[3] for w in window)
                    p90 = ears[int(0.9 * (len(ears) - 1))]
                    open_e14 = statistics.median([e for e in ears if e >= 0.75 * p90])
                    ref_p, ref_y = mp, my
                    triggers.append((round(t, 1), round(mp, 1), round(my, 1)))
                    window.clear()
                    e_valid = True
        out.append((cur_valid, e_valid, ear / base <= thr, ear / open_e14 <= thr))
    return out, triggers


def availability(times, valid):
    hist, total, last, avail, span, prev = deque(), 0.0, None, 0.0, 0.0, None
    t0 = times[0]
    for t, v in zip(times, valid):
        if prev is not None and t - t0 >= 60:
            step = min(t - prev, 0.2)
            span += step
            avail += step if total >= 54 - 1e-9 else 0.0
        prev = t
        if not v:
            last = None
            continue
        dt = 0.0 if last is None else min(max(t - last, 0.0), 0.2)
        last = t
        hist.append((t, dt))
        total += dt
        while hist and hist[0][0] < t - 60:
            total -= hist.popleft()[1]
    return avail / span if span else None


def weights(times):
    return [min(b - a, 0.2) for a, b in zip(times, times[1:])] + [0.0]


def rldd(sessions):
    videos, pooled = {}, {"comun": [0.0, 0.0], "recuperado": [0.0, 0.0], "comun_actual": [0.0, 0.0]}
    for s in sorted(glob.glob(os.path.join(sessions, "*_RLDD_*"))):
        name = s.rsplit("_RLDD_", 1)[1]
        rows = [r for r in csv.DictReader(open(os.path.join(s, "traza.csv"), encoding="utf-8"))
                if r["fase"] == "monitoreo" and num(r["cabeza_pitch"]) is not None and num(r["ear"]) is not None]
        base = num(rows[0]["ear_baseline"])
        frames = [(float(r["t"]), num(r["cabeza_yaw"]) or 0.0, num(r["cabeza_pitch"]), num(r["ear"])) for r in rows]
        res, trig = simulate(frames, base, RLDD_RATIO)
        times = [f[0] for f in frames]
        w = weights(times)
        av_cur = availability(times, [r[0] for r in res])
        av_e14 = availability(times, [r[1] for r in res])

        def perclos(valid_idx, closed_idx):
            tot = sum(wi for wi, r in zip(w, res) if r[valid_idx])
            return 100 * sum(wi for wi, r in zip(w, res) if r[valid_idx] and r[closed_idx]) / tot if tot else None
        videos[name] = {"disponible_actual": round(100 * av_cur, 1), "disponible_e14": round(100 * av_e14, 1),
                        "rehechas": trig, "perclos_actual": perclos(0, 2), "perclos_e14": perclos(1, 3)}
        if name.endswith("_0"):
            for wi, r in zip(w, res):
                if r[0] and r[1]:
                    pooled["comun"][0] += wi
                    pooled["comun"][1] += wi * r[3]
                    pooled["comun_actual"][0] += wi
                    pooled["comun_actual"][1] += wi * r[2]
                elif r[1] and not r[0]:
                    pooled["recuperado"][0] += wi
                    pooled["recuperado"][1] += wi * r[3]
    return videos, pooled


def parse_tag(path):
    rows, started = {}, False
    for line in open(path, encoding="utf-8", errors="replace"):
        if line.startswith("#start"):
            started = True
            continue
        if not started or line.startswith("#end") or ":" not in line:
            continue
        p = line.strip().split(":")
        rows[int(p[0])] = {"blink": int(p[1]), "lfc": p[3] == "C", "lnv": p[4] == "N", "rfc": p[5] == "C",
                           "rnv": p[6] == "N"}
    return rows


def eb8(data, sessions):
    recs = []
    for s in sorted(glob.glob(os.path.join(sessions, "*_EB8_*"))):
        vid = s.rsplit("_EB8_", 1)[1]
        tag = parse_tag(glob.glob(os.path.join(data, vid, "*.tag"))[0])
        rows = [r for r in csv.DictReader(open(os.path.join(s, "traza.csv"), encoding="utf-8"))
                if r["fase"] == "monitoreo" and num(r["cabeza_pitch"]) is not None and num(r["ear"]) is not None]
        own = [num(r["ear"]) / num(r["ear_baseline"]) for r in rows
               if r["postura_valida"] == "1" and int(r["frame"]) in tag and tag[int(r["frame"])]["lfc"]
               and tag[int(r["frame"])]["rfc"] and not tag[int(r["frame"])]["lnv"] and not tag[int(r["frame"])]["rnv"]]
        recs.append((vid, tag, rows, statistics.median(own) if own else None))
    totals = {"actual": [0, 0, 0, 0], "e14": [0, 0, 0, 0]}      # vp, positivos, fp, negativos
    triggers = {}
    for vid, tag, rows, _ in recs:
        ratio = statistics.median(r for v, _, _, r in recs if v != vid and r is not None)
        base = num(rows[0]["ear_baseline"])
        frames = [(float(r["t"]), num(r["cabeza_yaw"]) or 0.0, num(r["cabeza_pitch"]), num(r["ear"])) for r in rows]
        res, trig = simulate(frames, base, ratio)
        triggers[vid] = trig
        blinks = {f for f, a in tag.items() if a["blink"] != -1}
        near = set()
        for f in blinks:
            near.update(range(f - MARGIN, f + MARGIN + 1))
        for r, (cv, ev, cc, ec) in zip(rows, res):
            fr = int(r["frame"])
            a = tag.get(fr)
            if a is None or a["lnv"] or a["rnv"]:
                continue
            cls = "pos" if a["lfc"] and a["rfc"] else ("neg" if fr not in near else None)
            for key, valid, closed in (("actual", cv, cc), ("e14", ev, ec)):
                if not valid or cls is None:
                    continue
                k = totals[key]
                if cls == "pos":
                    k[0] += closed
                    k[1] += 1
                else:
                    k[2] += closed
                    k[3] += 1
    return totals, triggers


def main():
    rldd_sessions, eb8_data, eb8_sessions, out = sys.argv[1:5]
    videos, pooled = rldd(rldd_sessions)
    totals, eb8_triggers = eb8(eb8_data, eb8_sessions)
    av_cur = statistics.mean(v["disponible_actual"] for v in videos.values())
    av_e14 = statistics.mean(v["disponible_e14"] for v in videos.values())
    rec_s = pooled["recuperado"][0]
    frac = {k: (100 * v[1] / v[0] if v[0] else None) for k, v in pooled.items()}
    c1 = av_e14 - av_cur >= 10
    c2 = rec_s >= 60 and frac["recuperado"] is not None and frac["recuperado"] <= frac["comun"] + 2
    e = totals["e14"]
    sens, fpr = e[0] / e[1], e[2] / e[3]
    c3 = fpr <= 0.01 and sens >= 0.80
    report = {"rldd": videos, "rldd_disponibilidad_media": {"actual": round(av_cur, 1), "e14": round(av_e14, 1)},
              "rldd_alerta_cerrado_pct": {k: (round(v, 2) if v is not None else None) for k, v in frac.items()},
              "rldd_alerta_recuperado_s": round(rec_s, 1),
              "eb8": {k: {"sens": v[0] / v[1], "positivos": v[1], "fp": v[2] / v[3], "negativos": v[3]}
                      for k, v in totals.items()},
              "eb8_rehechas": eb8_triggers, "C1": c1, "C2": c2, "C3": c3, "adoptar": c1 and c2 and c3}
    json.dump(report, open(out, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    print(f"{'video':18} {'disp. actual':>12} {'disp. E14':>9} {'PERCLOS act':>11} {'PERCLOS E14':>11}  rehechas")
    for name, v in videos.items():
        pa = "-" if v["perclos_actual"] is None else f"{v['perclos_actual']:.1f}"
        pe = "-" if v["perclos_e14"] is None else f"{v['perclos_e14']:.1f}"
        print(f"{name:18} {v['disponible_actual']:12.1f} {v['disponible_e14']:9.1f} {pa:>11} {pe:>11}  {v['rehechas']}")
    print(f"\nC1 disponibilidad media: {av_cur:.1f} % -> {av_e14:.1f} %  ({'cumple' if c1 else 'no cumple'})")
    print(f"C2 videos alerta: cerrado en cuadros comunes {frac['comun']:.2f} % (actual {frac['comun_actual']:.2f} %), "
          f"en recuperados {frac['recuperado'] if frac['recuperado'] is None else round(frac['recuperado'], 2)} % "
          f"con {rec_s:.0f} s recuperados ({'cumple' if c2 else 'no cumple'})")
    a = totals["actual"]
    print(f"C3 Eyeblink8: actual sens {a[0]/a[1]:.3f} FP {100*a[2]/a[3]:.3f} % | E14 sens {sens:.3f} FP {100*fpr:.3f} % "
          f"({'cumple' if c3 else 'no cumple'}); rehechas en EB8: { {k: len(v) for k, v in eb8_triggers.items()} }")
    print("ADOPTAR:", report["adoptar"])


if __name__ == "__main__":
    main()
