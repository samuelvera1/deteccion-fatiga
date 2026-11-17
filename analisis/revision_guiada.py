"""Revisión de las sesiones guiadas: lo que pidió la voz (guia_voz.csv) contra lo que detectó el sistema en vivo.
Uso: python revision_guiada.py SESION [SESION ...]"""
import csv
import json
import os
import sys

SINGLE = {"Haz un parpadeo.", "Otro parpadeo.", "Uno más.", "Parpadea.", "Parpadeo lento."}
BLINKS = {"PARPADEO", "PARPADEO_PROLONGADO"}


def review(session):
    meta = json.load(open(os.path.join(session, "metadata.json"), encoding="utf-8"))
    t0 = meta["resumen"]["inicio_monitoreo_s"]
    cues = [(float(c["t_real_s"]), c["texto"]) for c in csv.DictReader(open(os.path.join(session, "guia_voz.csv"),
                                                                           encoding="utf-8"))]
    ev = [(float(e["t_s"]) - t0, e["Evento"], float(e["Duracion_s"] or 0)) for e in
          csv.DictReader(open(os.path.join(session, "eventos.csv"), encoding="utf-8"))]
    rows = [r for r in csv.DictReader(open(os.path.join(session, "traza.csv"), encoding="utf-8"))
            if r["fase"] == "monitoreo" and r["cierre"]]
    trace = [(float(r["t"]) - t0, float(r["cierre"]), r["postura_valida"] == "1") for r in rows]

    def blinks_in(a, b):
        return [x for x in ev if x[1] in BLINKS and a <= x[0] - x[2] <= b]     # por el inicio del parpadeo

    single = [t for t, x in cues if x in SINGLE]
    hit = sum(1 for t in single if blinks_in(t, t + 2.5))
    triples = [t for t, x in cues if x == "Tres parpadeos seguidos."]
    triple_hits = sum(min(3, len(blinks_in(t, t + 3.5))) for t in triples)
    closures, opened = [], None
    for t, x in cues:
        if x == "Cierra.":
            opened = t
        elif x == "Abre." and opened is not None:
            closures.append((opened, t))
            opened = None
    closure_rows = []
    for a, b in closures:
        seg = [(c, v) for tt, c, v in trace if a + 0.3 <= tt <= b + 0.6]
        closed = sum(1 for c, v in seg if c >= 0.8)
        closure_rows.append((a, b - a, closed / max(1, len(seg)), max((c for c, _ in seg), default=None)))
    detected = sum(1 for _, d, frac, _ in closure_rows if frac >= 0.5)
    windows = [(a - 0.5, b + 2.0) for a, b in closures]
    false_ms = [round(t, 1) for t, e, d in ev if e == "MICRO_SUENO" and d < 1.1
                and not any(a <= t - d <= b for a, b in windows)]
    squints, opened = [], None
    for t, x in cues:
        if x.startswith("Entrecierra"):
            opened = t
        elif x == "Normal." and opened is not None:
            squints.append((opened, t))
            opened = None
    sq = [c for tt, c, v in trace if any(a + 1 <= tt <= b for a, b in squints)]
    print(f"\n== {os.path.basename(session)}  ({meta['condicion']}, commit {meta['git']['commit'][:7]})")
    print(f"   parpadeos sueltos pedidos: {hit}/{len(single)} contados;  series de 3: {triple_hits}/{3 * len(triples)}")
    print(f"   cierres pedidos detectados (>= 50 % del cierre con cierre >= 0,8): {detected}/{len(closures)}")
    for a, d, frac, mx in closure_rows:
        if frac < 0.5:
            print(f"      no detectado: {a:6.1f} s ({d:.1f} s), {100 * frac:.0f} % del tiempo >= 0,8, cierre máximo {mx:+.2f}")
    print(f"   micro-sueños fuera de los cierres pedidos: {false_ms or 'ninguno'}")
    if sq:
        print(f"   entrecerrar (trampa): {100 * sum(c >= 0.8 for c in sq) / len(sq):.1f} % de cuadros con cierre >= 0,8")


for s in sys.argv[1:]:
    review(s)
