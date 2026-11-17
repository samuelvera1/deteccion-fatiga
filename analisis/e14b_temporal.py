"""E14b: referencia temporal (solo fuera del rango de la calibración original). Criterio en el registro (E14b).
Uso: python e14b_temporal.py SESIONES_RLDD DATOS_EB8 SESIONES_EB8 SESION_POSTURAS SALIDA.json"""
import csv
import json
import os
import statistics
import sys
from collections import deque

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import e14_reref as e  # noqa: E402


def simulate_b(frames, base, ratio):
    """Misma salida que e14_reref.simulate: (válido_actual, válido_b, cerrado_actual, cerrado_b), disparos."""
    thr = e.threshold(ratio)
    temp = None                          # (giro, cabeceo, ojo abierto) de la referencia temporal
    window = deque()
    triggers, out = [], []
    for t, y, p, ear in frames:
        cur_valid = not e.out_of_range(p, y)
        open_used = None
        if cur_valid:
            open_used = base
            window.clear()
        elif temp is not None and not e.out_of_range(p - temp[1], y - temp[0]):
            open_used = temp[2]
            window.clear()
        else:
            window.append((t, y, p, ear))
            while window and window[0][0] < t - e.HOLD_S:
                window.popleft()
            if window[-1][0] - window[0][0] >= e.HOLD_S - 0.5:
                ps, ys = [w[2] for w in window], [w[1] for w in window]
                if statistics.pstdev(ps) <= e.MAX_STD and statistics.pstdev(ys) <= e.MAX_STD:
                    mp, my = statistics.median(ps), statistics.median(ys)
                    if abs(mp) <= e.CAP_PITCH and abs(my) <= e.CAP_YAW:
                        ears = sorted(w[3] for w in window)
                        p90 = ears[int(0.9 * (len(ears) - 1))]
                        temp = (my, mp, statistics.median([x for x in ears if x >= 0.75 * p90]))
                        triggers.append((round(t, 1), round(mp, 1), round(my, 1)))
                        window.clear()
                        open_used = temp[2]
        b_valid = open_used is not None
        out.append((cur_valid, b_valid, ear / base <= thr, b_valid and ear / open_used <= thr, open_used))
    return out, triggers


def posture_check(session):
    """(4): sesión de posturas, ángulos respecto a la calibración reconstruidos sumando cada REFERENCIA_REHECHA."""
    meta = json.load(open(os.path.join(session, "metadata.json"), encoding="utf-8"))
    t0 = meta["resumen"]["inicio_monitoreo_s"]
    rebases = []
    for ev in csv.DictReader(open(os.path.join(session, "eventos.csv"), encoding="utf-8")):
        if ev["Evento"] == "REFERENCIA_REHECHA":
            parts = ev["Valor"].split()
            rebases.append((float(ev["t_s"]), float(parts[1]), float(parts[3])))      # giro, cabeceo
    rows = [r for r in csv.DictReader(open(os.path.join(session, "traza.csv"), encoding="utf-8"))
            if r["fase"] == "monitoreo" and e.num(r["cabeza_pitch"]) is not None]
    base = e.num(rows[0]["ear_baseline"])
    ratio = e.num(rows[0]["ear_cerrado"]) / base
    frames = []
    for r in rows:
        t = float(r["t"])
        off = (0.0, 0.0)
        for tr, gy, gp in rebases:
            if t >= tr:
                off = (gy, gp)
        frames.append((t, e.num(r["cabeza_yaw"]) + off[0], e.num(r["cabeza_pitch"]) + off[1], e.num(r["ear"])))
    res, trig = simulate_b(frames, base, ratio)
    closed = ratio * base

    def closure(ear, open_ear):
        return (open_ear - ear) / (open_ear - ratio * open_ear)
    end = [(f, r) for f, r in zip(frames, res) if f[0] - t0 >= 178]
    with_b = statistics.median(closure(f[3], r[4]) for f, r in end if r[4] is not None)
    calib = statistics.median((base - f[3]) / (base - closed) for f, _ in end)
    eyes_down = [closure(f[3], r[4]) for f, r in zip(frames, res) if 103 <= f[0] - t0 < 108 and r[4] is not None]
    return {"disparos": trig, "final_cierre_b": round(with_b, 3), "final_cierre_calibracion": round(calib, 3),
            "C4": abs(with_b - calib) <= 0.10,
            "ojos_abajo_cierre_b_mediana": round(statistics.median(eyes_down), 3) if eyes_down else None}


def main():
    rldd_sessions, eb8_data, eb8_sessions, posture, out = sys.argv[1:6]
    e.simulate = lambda frames, base, ratio: ([r[:4] for r in simulate_b(frames, base, ratio)[0]],
                                              simulate_b(frames, base, ratio)[1])
    videos, pooled = e.rldd(rldd_sessions)
    totals, eb8_triggers = e.eb8(eb8_data, eb8_sessions)
    av_cur = statistics.mean(v["disponible_actual"] for v in videos.values())
    av_b = statistics.mean(v["disponible_e14"] for v in videos.values())
    frac = {k: (100 * v[1] / v[0] if v[0] else None) for k, v in pooled.items()}
    rec_s = pooled["recuperado"][0]
    c1 = av_b - av_cur >= 10
    c2 = rec_s >= 60 and frac["recuperado"] is not None and frac["recuperado"] <= frac["comun"] + 2
    b = totals["e14"]
    sens, fpr = b[0] / b[1], b[2] / b[3]
    c3 = fpr <= 0.01 and sens >= 0.80
    pc = posture_check(posture)
    report = {"rldd": videos, "disponibilidad": {"actual": round(av_cur, 1), "e14b": round(av_b, 1)},
              "alerta_cerrado_pct": frac, "recuperado_s": rec_s, "eb8": {"sens": sens, "fp": fpr},
              "eb8_disparos": eb8_triggers, "posturas": pc, "C1": c1, "C2": c2, "C3": c3, "C4": pc["C4"],
              "adoptar": c1 and c2 and c3 and pc["C4"]}
    json.dump(report, open(out, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    for name, v in videos.items():
        if v["rehechas"] or v["disponible_actual"] < 95:
            print(f"{name:18} disp {v['disponible_actual']:5.1f} -> {v['disponible_e14']:5.1f}  PERCLOS "
                  f"{v['perclos_actual']:.1f} -> {v['perclos_e14']:.1f}  temporales {v['rehechas']}")
    print(f"C1 disponibilidad media {av_cur:.1f} % -> {av_b:.1f} % ({'cumple' if c1 else 'no cumple'})")
    print(f"C2 alerta: comunes {frac['comun']:.2f} %, recuperados {frac['recuperado']:.2f} % con {rec_s:.0f} s "
          f"({'cumple' if c2 else 'no cumple'})")
    print(f"C3 Eyeblink8: sens {sens:.3f}, FP {100 * fpr:.3f} % ({'cumple' if c3 else 'no cumple'})")
    print(f"C4 posturas: final con E14b {pc['final_cierre_b']:+.3f} vs calibración {pc['final_cierre_calibracion']:+.3f} "
          f"({'cumple' if pc['C4'] else 'no cumple'}); temporales {pc['disparos']}; ojos abajo {pc['ojos_abajo_cierre_b_mediana']}")
    print("ADOPTAR:", report["adoptar"])


if __name__ == "__main__":
    main()
