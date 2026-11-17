"""E8: estado «ojo cerrado» de PERCLOS (cierre >= 0,80) contra la anotación por cuadro de Eyeblink8 (LE_FC/RE_FC).

Criterio fijado antes de calcular en docs/registro_experimentos.md (E8). Uso:
python e8_perclos.py CARPETA_EYEBLINK8 CARPETA_SESIONES SALIDA_JSON
"""
import csv
import glob
import json
import math
import os
import statistics
import sys

P80 = 0.80
MARGIN = 2              # cuadros alrededor de cada parpadeo que no cuentan como negativos
WINDOW_S = 60.0
MIN_VALID_S = 54.0      # misma exigencia que la alerta (MIN_VALID_FRACTION 0,9)
FALLBACK_RATIO = 0.25   # CLOSED_FALLBACK_RATIO del sistema
LAGS = range(-3, 4)


def wilson(k, n, z=1.96):
    if n == 0:
        return None, None, None
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return p, max(0.0, c - h), min(1.0, c + h)


def parse_tag(path):
    rows, started, values = {}, False, {}
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            if line.startswith("#start"):
                started = True
                continue
            if not started or not line.strip() or line.startswith("#"):
                continue
            p = line.strip().split(":")
            if len(p) < 7:
                continue
            for i in (3, 4, 5, 6):
                values.setdefault(i, {}).setdefault(p[i], 0)
                values[i][p[i]] += 1
            rows[int(p[0])] = {"blink": int(p[1]), "lfc": p[3] == "C", "lnv": p[4] == "N",
                               "rfc": p[5] == "C", "rnv": p[6] == "N"}
    return rows, values


def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def load(data, session):
    vid = session.rsplit("_EB8_", 1)[1]
    meta = json.load(open(os.path.join(session, "metadata.json"), encoding="utf-8"))
    fps = meta.get("fps_nativo_fuente") or 30.0
    rows, values = parse_tag(glob.glob(os.path.join(data, vid, "*.tag"))[0])
    blink_frames = {f for f, r in rows.items() if r["blink"] != -1}
    near_blink = set()
    for f in blink_frames:
        near_blink.update(range(f - MARGIN, f + MARGIN + 1))
    frames = []          # (frame, ear/ojo abierto, clase) de los cuadros evaluables
    first_monitor = None
    for r in csv.DictReader(open(os.path.join(session, "traza.csv"), encoding="utf-8")):
        if r["fase"] != "monitoreo":
            continue
        fr = int(r["frame"])
        if first_monitor is None:
            first_monitor = fr
        ear, base = num(r["ear"]), num(r["ear_baseline"])
        a = rows.get(fr)
        if (r["postura_valida"] != "1" or ear is None or not base or a is None or a["lnv"] or a["rnv"]):
            continue
        if a["lfc"] and a["rfc"]:
            cls = "pos"
        elif fr not in near_blink:
            cls = "neg"
        else:
            cls = "int"
        frames.append((fr, ear / base, cls, fr in blink_frames))
    pos_ratios = [x for _, x, c, _ in frames if c == "pos"]
    return {"vid": vid, "fps": fps, "frames": frames, "first": first_monitor, "values": values,
            "own_ratio": statistics.median(pos_ratios) if pos_ratios else None}


def evaluate(rec, ratio):
    thr = 0.2 + 0.8 * ratio            # cierre >= 0,80  <=>  apertura/abierto <= 1 - 0,8 (1 - proporción)
    closed = {fr: x <= thr for fr, x, _, _ in rec["frames"]}
    tp = sum(1 for fr, _, c, _ in rec["frames"] if c == "pos" and closed[fr])
    npos = sum(1 for _, _, c, _ in rec["frames"] if c == "pos")
    fp = sum(1 for fr, _, c, _ in rec["frames"] if c == "neg" and closed[fr])
    nneg = sum(1 for _, _, c, _ in rec["frames"] if c == "neg")
    nint = sum(1 for _, _, c, _ in rec["frames"] if c == "int")
    int_closed = sum(1 for fr, _, c, _ in rec["frames"] if c == "int" and closed[fr])
    lags = {}
    for k in LAGS:
        hit = n = 0
        for fr, _, c, _ in rec["frames"]:
            if c == "pos" and (fr + k) in closed:
                n += 1
                hit += closed[fr + k]
        lags[k] = (hit, n)
    fps, win = rec["fps"], {}
    for fr, _, c, blink in rec["frames"]:
        w = int((fr - rec["first"]) / fps // WINDOW_S)
        s = win.setdefault(w, [0, 0, 0, 0])
        s[0] += 1
        s[1] += closed[fr]
        s[2] += c == "pos"
        s[3] += blink
    windows = []
    for w, (n, sys_c, fc, bl) in sorted(win.items()):
        if n / fps < MIN_VALID_S:
            continue
        windows.append({"ventana": w, "cuadros": n, "perclos_sistema": 100 * sys_c / n,
                        "perclos_cerrado_total": 100 * fc / n, "perclos_parpadeo": 100 * bl / n})
    return {"tp": tp, "npos": npos, "fp": fp, "nneg": nneg, "nint": nint, "int_closed": int_closed,
            "lags": lags, "windows": windows, "umbral_apertura_rel": thr}


def summarize(name, results):
    tp = sum(r["tp"] for r in results.values())
    npos = sum(r["npos"] for r in results.values())
    fp = sum(r["fp"] for r in results.values())
    nneg = sum(r["nneg"] for r in results.values())
    nint = sum(r["nint"] for r in results.values())
    ic = sum(r["int_closed"] for r in results.values())
    sens, slo, shi = wilson(tp, npos)
    fpr, flo, fhi = wilson(fp, nneg)
    wins = [w for r in results.values() for w in r["windows"]]
    inside = sum(1 for w in wins if w["perclos_cerrado_total"] - 1 <= w["perclos_sistema"] <= w["perclos_parpadeo"] + 1)
    diffs = [w["perclos_sistema"] - w["perclos_cerrado_total"] for w in wins]
    bias = statistics.mean(diffs) if diffs else None
    sd = statistics.stdev(diffs) if len(diffs) > 1 else None
    lag = {k: sum(r["lags"][k][0] for r in results.values()) / max(1, sum(r["lags"][k][1] for r in results.values()))
           for k in LAGS}
    out = {"nivel": name, "sensibilidad": sens, "sens_ic95": [slo, shi], "positivos": npos, "verdaderos_pos": tp,
           "falsos_pos_tasa": fpr, "fp_ic95": [flo, fhi], "negativos": nneg, "falsos_pos": fp,
           "intermedios": nint, "intermedios_cerrados": ic, "ventanas": len(wins), "ventanas_dentro": inside,
           "ventanas_dentro_frac": inside / len(wins) if wins else None,
           "bland_altman_vs_cerrado_total": {"sesgo": bias, "de": sd,
                                             "lim": [bias - 1.96 * sd, bias + 1.96 * sd] if sd is not None else None},
           "sens_por_desfase": lag,
           "por_video": {v: {"sens": r["tp"] / r["npos"] if r["npos"] else None, "pos": r["npos"],
                             "fp": r["fp"], "neg": r["nneg"], "umbral_apertura_rel": round(r["umbral_apertura_rel"], 4),
                             "ventanas": r["windows"]} for v, r in results.items()}}
    if name == "principal":
        out["C1"] = sens is not None and sens >= 0.80
        out["C2"] = fpr is not None and fpr <= 0.01
        out["C3"] = bool(wins) and inside / len(wins) >= 0.90
        out["validado"] = out["C1"] and out["C2"] and out["C3"]
    return out


def main():
    data, sessions, out_path = sys.argv[1:4]
    recs = [load(data, s) for s in sorted(glob.glob(os.path.join(sessions, "*_EB8_*")))]
    for rec in recs:
        n = {c: sum(1 for f in rec["frames"] if f[2] == c) for c in ("pos", "neg", "int")}
        print(f"EB8_{rec['vid']:>2}: evaluables {len(rec['frames'])} (pos {n['pos']}, neg {n['neg']}, int {n['int']}), "
              f"proporción propia {rec['own_ratio']:.3f}, valores tag {rec['values']}")
    own = {r["vid"]: r["own_ratio"] for r in recs}
    levels = {
        "principal": {r["vid"]: statistics.median(v for k, v in own.items() if k != r["vid"]) for r in recs},
        "reserva": {r["vid"]: FALLBACK_RATIO for r in recs},
        "techo_circular": own,
    }
    report = {"proporciones_propias": own}
    for name, ratios in levels.items():
        results = {r["vid"]: evaluate(r, ratios[r["vid"]]) for r in recs}
        report[name] = summarize(name, results)
        report[name]["proporcion_usada"] = ratios
        s = report[name]
        print(f"\n[{name}] sensibilidad {s['sensibilidad']:.3f} (IC95 {s['sens_ic95'][0]:.3f}-{s['sens_ic95'][1]:.3f}, "
              f"{s['verdaderos_pos']}/{s['positivos']}) | FP {100 * s['falsos_pos_tasa']:.2f} % "
              f"({s['falsos_pos']}/{s['negativos']}, IC95 {100 * s['fp_ic95'][0]:.2f}-{100 * s['fp_ic95'][1]:.2f}) | "
              f"intermedios cerrados {s['intermedios_cerrados']}/{s['intermedios']} | "
              f"ventanas dentro {s['ventanas_dentro']}/{s['ventanas']}")
        ba = s["bland_altman_vs_cerrado_total"]
        print(f"   Bland-Altman PERCLOS sistema - cerrado total: sesgo {ba['sesgo']:+.2f} pp, "
              f"límites {ba['lim'][0]:+.2f} a {ba['lim'][1]:+.2f} pp")
        print("   sensibilidad por desfase: " + ", ".join(f"{k:+d}: {v:.3f}" for k, v in s["sens_por_desfase"].items()))
        print("   por video: " + ", ".join(f"{v}: {d['sens']:.2f} ({d['fp']}/{d['neg']} FP)"
                                         for v, d in s["por_video"].items()))
        if "validado" in s:
            print(f"   C1 {s['C1']} | C2 {s['C2']} | C3 {s['C3']} -> validado {s['validado']}")
    json.dump(report, open(out_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1, default=str)


main()
