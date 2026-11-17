"""E4b: duración del parpadeo alerta frente a somnoliento en UTA-RLDD (criterio en registro_experimentos.md).
Uso: python rldd_analyze_b.py [CARPETA_EVAL]"""
import csv
import glob
import json
import os
import sys
from math import comb

import numpy as np

work = sys.argv[1] if len(sys.argv) > 1 else r"C:\Users\Practicante\Documents\datasets\eval_rldd_b"
MAX_GAP = 0.2


def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def wilcoxon_greater(diffs):
    """p unilateral exacto (H1: diferencias > 0) de la prueba de rangos con signo; rangos medios en empates."""
    d = [x for x in diffs if x != 0]
    n = len(d)
    if n == 0:
        return None, None
    order = np.argsort(np.abs(d))
    ranks = np.empty(n)
    absd = np.abs(np.array(d))[order]
    i = 0
    while i < n:
        j = i
        while j + 1 < n and absd[j + 1] == absd[i]:
            j += 1
        ranks[order[i:j + 1]] = (i + j) / 2 + 1
        i = j + 1
    r2 = (ranks * 2).astype(int)                       # rangos enteros (los medios son x.5)
    w = sum(r for r, x in zip(r2, d) if x > 0)
    dist = np.zeros(r2.sum() + 1)
    dist[0] = 1
    for r in r2:
        dist[r:] = dist[r:] + dist[:-r].copy() if r else dist
    dist /= dist.sum()
    return w / 2, float(dist[w:].sum())


videos = {}
for sdir in sorted(glob.glob(os.path.join(work, "sesiones", "*_RLDD_*"))):
    meta = json.load(open(os.path.join(sdir, "metadata.json"), encoding="utf-8"))
    res = meta.get("resumen")
    if not res:
        continue
    tag = sdir.rsplit("_RLDD_", 1)[1]
    fold_part, subj, label = tag.rsplit("_", 2)
    start = res.get("inicio_monitoreo_s")
    count_t, prev = 0.0, None
    for r in csv.DictReader(open(os.path.join(sdir, "traza.csv"), encoding="utf-8")):
        t = num(r["t"])
        ok = r["fase"] == "monitoreo"
        if prev is not None and ok and prev[1] and 0 < t - prev[0] <= MAX_GAP:
            count_t += t - prev[0]
        prev = (t, ok)
    durations = [num(e["Duracion_s"]) for e in csv.DictReader(open(os.path.join(sdir, "eventos.csv"), encoding="utf-8"))
                 if e["Evento"] in ("PARPADEO", "PARPADEO_PROLONGADO") and start is not None
                 and (num(e["t_s"]) or -1) >= start]
    face = res["frames_con_rostro"] / res["frames"] if res.get("frames") else 0
    videos[(f"{fold_part}/{subj}", label)] = {
        "ok": face >= 0.5 and count_t >= 180 and len(durations) > 0, "face": face, "min": count_t / 60,
        "n": len(durations), "med": float(np.median(durations)) if durations else None,
        "rate": len(durations) / (count_t / 60) if count_t else None,
        "long": float(np.mean([x >= 0.5 for x in durations])) if durations else None}

people = sorted({p for p, _ in videos})
pairs, excluded = [], []
for p in people:
    a, s = videos.get((p, "0")), videos.get((p, "10"))
    if a and s and a["ok"] and s["ok"]:
        pairs.append((p, s["med"] - a["med"], a, s))
    else:
        excluded.append(p)
print(f"{len(people)} personas procesadas; válidas {len(pairs)}; excluidas {len(excluded)}: {', '.join(excluded)}")
for p, d, a, s in pairs:
    print(f"  {p:<18} alerta {a['med']:.3f} s ({a['n']} parp.)  somnoliento {s['med']:.3f} s ({s['n']})  {d * 1000:+5.0f} ms")
diffs = [d for _, d, _, _ in pairs]
if diffs:
    k, n = sum(d > 0 for d in diffs), sum(d != 0 for d in diffs)
    p_sign = sum(comb(n, i) for i in range(k, n + 1)) / 2 ** n
    w, p_w = wilcoxon_greater(diffs)
    rng = np.random.default_rng(1)
    boots = [np.median(rng.choice(diffs, len(diffs))) for _ in range(5000)]
    lo, hi = np.percentile(boots, [2.5, 97.5])
    print(f"\nMediana de las diferencias {np.median(diffs) * 1000:+.0f} ms (IC 95 % bootstrap {lo * 1000:+.0f} a {hi * 1000:+.0f} ms)")
    print(f"Positivas {k} de {n}; signos p = {p_sign:.4f}; Wilcoxon W+ = {w}, p = {p_w:.4f}")
    if len(pairs) < 15:
        print(f"Criterio: solo {len(pairs)} personas válidas (se exigen 15): aún no evaluable")
    else:
        print("Criterio:", "APOYA la hipótesis" if p_w < 0.05 else "NO apoya la hipótesis")
    for key, name in (("rate", "parpadeos/min"), ("long", "proporción >= 0,5 s")):
        print(f"  exploratorio {name}: alerta {np.mean([a[key] for _, _, a, _ in pairs]):.3f} | "
              f"somnoliento {np.mean([s[key] for _, _, _, s in pairs]):.3f}")
