# evaluar.py
"""
Evaluación del sistema frente a la referencia humana (anotaciones en modo ciego hechas con revisar.py).
Las definiciones y el plan de evaluación (clases, emparejamiento, exclusiones, métricas) están fijados en
docs/guia_anotacion.md, antes de ver resultados.

Uso:
    python evaluar.py "sesiones\\<sesion>"                          # una sesión
    python evaluar.py "sesiones\\<sesion1>" "sesiones\\<sesion2>"     # varias: por sesión, por persona y total
    python evaluar.py "sesiones\\<sesion>" --acuerdo "Nombre"         # acuerdo entre anotadores (guía, sección 5)
    python evaluar.py "sesiones\\<sesion>" --referencia anotaciones_revision.csv
        (solo exploratorio: una revisión hecha viendo al sistema NO es referencia)

En cada sesión escribe evaluacion_<referencia>.json (métricas) y evaluacion_<referencia>_eventos.csv: cada
evento con su resultado y datos para el análisis de errores (cierre máximo, giro de cabeza, tiempo desde
que la postura volvió a ser válida...).
"""
import argparse
import bisect
import csv
import json
import math
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime

from revisar import annotations_file
from session_recorder import SessionRecorder

CLASSES = ("parpadeo", "bostezo", "cierre_largo")
SYSTEM_TYPES = {"PARPADEO": "parpadeo", "PARPADEO_PROLONGADO": "parpadeo",
                "BOSTEZO": "bostezo", "MICRO_BOSTEZO": "bostezo"}
# Eventos que el sistema descartó a propósito: se cruzan con la referencia para estimar el efecto de la regla
DISCARD_TYPES = {"PARPADEO_DESCARTADO_GIRO": "parpadeo", "SONRISA": "bostezo"}
REFERENCE_TYPES = {"PARPADEO": "parpadeo", "BOSTEZO": "bostezo", "MICRO_BOSTEZO": "bostezo",
                   "MICRO_SUENO": "cierre_largo"}
TOLERANCE_S = {"parpadeo": 0.10, "bostezo": 0.0, "cierre_largo": 0.0}   # guía, sección 4 (borrador)
Z95 = 1.959964
MAX_TRACE_GAP_S = 0.2       # un hueco mayor en la traza (sin rostro) corta un tramo de ojo cerrado
DEFAULT_REFERENCE = "anotaciones_ciego.csv"
EVENT_COLUMNS = ["clase", "origen", "tipo", "inicio_s", "fin_s", "duracion_s", "resultado",
                 "resultado_postura_valida", "pareja", "motivo_exclusion", "cierre_max", "boca_max",
                 "vel_cabeza_max", "s_desde_postura_valida", "comentario"]
LANDIS_KOCH = [(0.0, "pobre"), (0.20, "leve"), (0.40, "aceptable"), (0.60, "moderado"),
               (0.80, "sustancial"), (1.0, "casi perfecto")]


# ---------------------------------------------------------------------- utilidades

def read_csv(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def to_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def overlaps(a_start, a_end, b_start, b_end, tol=0.0):
    return a_start <= b_end + tol and a_end >= b_start - tol


def merge(intervals):
    merged = []
    for start, end in sorted(intervals):
        if merged and start <= merged[-1][1] + 1e-6:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def new_event(cls, origin, kind, start, end, comment=""):
    return {"clase": cls, "origen": origin, "tipo": kind, "inicio": start, "fin": max(end, start),
            "resultado": "", "resultado_postura_valida": "", "pareja": "", "motivo_exclusion": "",
            "comentario": comment}


def wilson(successes, n):
    """Intervalo de confianza del 95 % de Wilson (1927) para una proporción."""
    if n == 0:
        return None
    p = successes / n
    denominator = 1 + Z95 ** 2 / n
    center = (p + Z95 ** 2 / (2 * n)) / denominator
    margin = Z95 * math.sqrt(p * (1 - p) / n + Z95 ** 2 / (4 * n * n)) / denominator
    return [round(max(0.0, center - margin), 4), round(min(1.0, center + margin), 4)]


def metrics(tp, fp, fn):
    return {"aciertos": tp, "falsos_positivos": fp, "falsos_negativos": fn,
            "sensibilidad": round(tp / (tp + fn), 4) if tp + fn else None,
            "sensibilidad_ic95": wilson(tp, tp + fn),
            "precision": round(tp / (tp + fp), 4) if tp + fp else None,
            "precision_ic95": wilson(tp, tp + fp),
            "f1": round(2 * tp / (2 * tp + fp + fn), 4) if tp + fp + fn else None}


def bland_altman(pairs):
    """Acuerdo de duraciones (Bland y Altman, 1986): sesgo = media de (sistema - referencia) y límites de
    acuerdo = sesgo ± 1.96 DE. pairs: [(duración sistema, duración referencia), ...]."""
    result = {"n": len(pairs)}
    if len(pairs) < 2:
        return result
    diffs = [s - r for s, r in pairs]
    bias = sum(diffs) / len(diffs)
    sd = math.sqrt(sum((d - bias) ** 2 for d in diffs) / (len(diffs) - 1))
    result.update({"sesgo_s": round(bias, 4), "de_s": round(sd, 4),
                   "limites_acuerdo_s": [round(bias - 1.96 * sd, 4), round(bias + 1.96 * sd, 4)],
                   "media_sistema_s": round(sum(s for s, _ in pairs) / len(pairs), 4),
                   "media_referencia_s": round(sum(r for _, r in pairs) / len(pairs), 4)})
    return result


def match(system, reference, tol):
    """Emparejamiento uno a uno por solapamiento de intervalos (con tolerancia). Voraz: primero los pares
    que más se solapan; con eventos que no se solapan entre sí equivale al emparejamiento máximo."""
    candidates = []
    for i, s in enumerate(system):
        for j, r in enumerate(reference):
            if overlaps(s["inicio"], s["fin"], r["inicio"], r["fin"], tol):
                overlap = min(s["fin"], r["fin"]) - max(s["inicio"], r["inicio"])
                center_gap = abs((s["inicio"] + s["fin"]) - (r["inicio"] + r["fin"])) / 2
                candidates.append((-overlap, center_gap, i, j))
    candidates.sort()
    used_s, used_r, pairs = set(), set(), []
    for _, _, i, j in candidates:
        if i not in used_s and j not in used_r:
            used_s.add(i)
            used_r.add(j)
            pairs.append((i, j))
    return pairs


# ---------------------------------------------------------------------- datos de la sesión

class Session:
    def __init__(self, path):
        self.dir = path
        meta_path = os.path.join(path, "metadata.json")
        if not os.path.exists(meta_path):
            sys.exit(f"No es una carpeta de sesión (falta metadata.json): {path}")
        with open(meta_path, encoding="utf-8") as f:
            self.meta = json.load(f)
        self.summary = self.meta.get("resumen") or {}
        if not self.summary:
            sys.exit(f"La sesión {path} no terminó bien (metadata.json sin resumen).")
        self.id = self.meta.get("sesion_id") or os.path.basename(os.path.normpath(path))
        self.subject = self.meta.get("codigo_anonimo") or self.meta.get("sujeto") or "?"
        self.fps = self.meta.get("fps_nativo_fuente") or 30.0
        self.events = read_csv(os.path.join(path, "eventos.csv"))
        trace_path = os.path.join(path, "traza.csv")
        self.trace = self._load_trace(trace_path) if os.path.exists(trace_path) else []
        self.trace_t = [r["t"] for r in self.trace]
        self.start = self.summary.get("inicio_monitoreo_s")
        if self.start is None:      # sesiones anteriores a ese campo: primer frame en monitoreo
            self.start = next((r["t"] for r in self.trace if r["fase"] == "monitoreo"), None)
        self.end = self.summary.get("duracion_s")
        self.microsleep_min_s = ((self.meta.get("parametros") or {}).get("ojos") or {}).get("microsueno_min_s", 1.0)
        self.reentries = self._posture_reentries()

    def _load_trace(self, path):
        rows = []
        for r in read_csv(path):
            t = to_float(r.get("t"))
            if t is None:
                continue
            rows.append({"t": t, "fase": r.get("fase", ""), "cerrado": r.get("eyes_closed") == "1",
                         "postura_valida": r.get("postura_valida") == "1", "cierre": to_float(r.get("cierre")),
                         "boca": to_float(r.get("mouth")), "vel": to_float(r.get("cabeza_vel"))})
        return sorted(rows, key=lambda r: r["t"])

    def _posture_reentries(self):
        """Instantes en que la postura vuelve a ser válida durante el conteo."""
        times, previous = [], None
        for r in self.trace:
            if r["fase"] != "monitoreo":
                previous = None
                continue
            if previous is False and r["postura_valida"]:
                times.append(r["t"])
            previous = r["postura_valida"]
        return times

    def trace_stats(self, start, end):
        """Datos de la traza durante un evento, para el análisis de errores."""
        i0 = bisect.bisect_left(self.trace_t, start - 1e-6)
        i1 = bisect.bisect_right(self.trace_t, end + 1e-6)
        rows = self.trace[i0:i1]

        def peak(key):
            values = [r[key] for r in rows if r[key] is not None]
            return round(max(values), 4) if values else None

        before = [t for t in self.reentries if t <= start + 1e-6]
        return {"cierre_max": peak("cierre"), "boca_max": peak("boca"), "vel_cabeza_max": peak("vel"),
                "s_desde_postura_valida": round(start - before[-1], 3) if before else None}

    def not_counting_intervals(self):
        """Tramos tras el inicio del conteo en los que el sistema no contaba (recalibración con la tecla C)."""
        if self.start is None:
            return []
        dt = 1.0 / self.fps
        return merge([(r["t"], r["t"] + dt) for r in self.trace if r["t"] >= self.start and r["fase"] != "monitoreo"])

    def invalid_posture_intervals(self):
        """Tramos de conteo con la postura fuera de rango o sin rostro detectado (huecos en la traza)."""
        dt = 1.0 / self.fps
        intervals, previous = [], None
        for r in self.trace:
            if r["fase"] != "monitoreo":
                previous = None
                continue
            if previous is not None and r["t"] - previous["t"] > 1.5 * dt:
                intervals.append((previous["t"] + dt, r["t"]))
            if not r["postura_valida"]:
                intervals.append((r["t"], r["t"] + dt))
            previous = r
        return merge(intervals)

    def system_events(self):
        events = []
        for r in self.events:
            kind = r["Evento"]
            cls = SYSTEM_TYPES.get(kind) or DISCARD_TYPES.get(kind)
            if cls is None:
                continue
            end = to_float(r["t_s"])
            duration = to_float(r.get("Duracion_s")) or 0.0
            events.append(new_event(cls, "sistema" if kind in SYSTEM_TYPES else "descarte", kind, end - duration, end))
        return events + self._long_closures()

    def _long_closures(self):
        """Tramos con el ojo cerrado (estado del sistema con histéresis, columna eyes_closed de la traza) de al
        menos microsueno_min_s: lo mismo que el sistema registra como MICRO_SUENO, pero con su fin real (los
        eventos MICRO_SUENO se escriben cada segundo y no marcan el final)."""
        if not self.trace:
            return self._long_closures_from_events()
        dt = 1.0 / self.fps
        episodes, run = [], None
        for r in self.trace:
            if run is not None and (not r["cerrado"] or r["t"] - run[1] > MAX_TRACE_GAP_S):
                end = r["t"] if not r["cerrado"] and r["t"] - run[1] <= MAX_TRACE_GAP_S else run[1] + dt
                if run[1] - run[0] >= self.microsleep_min_s - 1e-9:
                    episodes.append((run[0], end))
                run = None
            if r["cerrado"]:
                run = [r["t"], r["t"]] if run is None else [run[0], r["t"]]
        if run is not None and run[1] - run[0] >= self.microsleep_min_s - 1e-9:
            episodes.append((run[0], run[1] + dt))
        return [new_event("cierre_largo", "sistema", "MICRO_SUENO", s, e) for s, e in episodes]

    def _long_closures_from_events(self):
        ends = {}
        for r in self.events:
            if r["Evento"] == "MICRO_SUENO":
                end = to_float(r["t_s"])
                start = round(end - (to_float(r.get("Duracion_s")) or 0.0), 2)
                ends[start] = max(ends.get(start, end), end)
        return [new_event("cierre_largo", "sistema", "MICRO_SUENO", s, e) for s, e in sorted(ends.items())]


class Reference:
    """Anotaciones de una persona (anotaciones_*.csv de revisar.py)."""

    def __init__(self, path):
        self.path, self.name = path, os.path.basename(path)
        rows = read_csv(path)
        self.blind = bool(rows) and all(r.get("ciego") == "1" for r in rows)
        self.events, self.not_evaluable, self.warnings = [], [], []
        points = notes = 0
        for r in rows:
            start, end = to_float(r["t_s"]), to_float(r.get("fin_t_s"))
            if end is None:
                end, points = start, points + 1
            kind = r["tipo"]
            if kind == "NO_EVALUABLE":
                self.not_evaluable.append((start, end, r.get("comentario", "")))
            elif kind in REFERENCE_TYPES:
                self.events.append(new_event(REFERENCE_TYPES[kind], "referencia", kind, start, end,
                                             r.get("comentario", "")))
            else:
                notes += 1
        if not self.blind:
            self.warnings.append(f"{self.name} NO es una referencia en modo ciego: resultados solo exploratorios")
        if points:
            self.warnings.append(f"{points} anotaciones sin fin (formato antiguo): se tratan como instantes")
        if notes:
            self.warnings.append(f"{notes} anotaciones PROBLEMA (notas de revisión) no se usan en la evaluación")
        for cls in CLASSES:
            spans = sorted((e["inicio"], e["fin"]) for e in self.events if e["clase"] == cls)
            duplicated = sum(1 for a, b in zip(spans, spans[1:]) if b[0] <= a[1])
            if duplicated:
                self.warnings.append(f"{duplicated} anotaciones de {cls} se solapan con otra: ¿duplicadas?")


# ---------------------------------------------------------------------- evaluación

def exclusion_reason(event, start, exclusions):
    if start is None:
        return "el conteo no empezó"
    if event["inicio"] < start:
        return "antes del inicio del conteo"
    for s, e, reason in exclusions:
        if overlaps(event["inicio"], event["fin"], s, e):
            return reason
    return ""


def evaluate(session, reference):
    system = session.system_events()
    ref = [dict(e) for e in reference.events]
    exclusions = [(s, e, f"no evaluable: {c}" if c else "no evaluable") for s, e, c in reference.not_evaluable]
    exclusions += [(s, e, "recalibrando") for s, e in session.not_counting_intervals()]
    for event in system + ref:
        event["motivo_exclusion"] = exclusion_reason(event, session.start, exclusions)
        if event["motivo_exclusion"]:
            event["resultado"] = "excluido"

    principal, durations, yawn_types = {}, {}, Counter()
    for cls in CLASSES:
        sys_c = [e for e in system if e["clase"] == cls and e["origen"] == "sistema" and not e["resultado"]]
        ref_c = [e for e in ref if e["clase"] == cls and not e["resultado"]]
        pairs = match(sys_c, ref_c, TOLERANCE_S[cls])
        for i, j in pairs:
            s, r = sys_c[i], ref_c[j]
            s["resultado"] = r["resultado"] = "acierto"
            s["pareja"], r["pareja"] = f"{r['inicio']:.3f}-{r['fin']:.3f}", f"{s['inicio']:.3f}-{s['fin']:.3f}"
            if cls == "bostezo":
                yawn_types[f"sistema {s['tipo']} / referencia {r['tipo']}"] += 1
        for e in sys_c:
            e["resultado"] = e["resultado"] or "falso_positivo"
        for e in ref_c:
            e["resultado"] = e["resultado"] or "falso_negativo"
        principal[cls] = metrics(len(pairs), len(sys_c) - len(pairs), len(ref_c) - len(pairs))
        durations[cls] = [(round(sys_c[i]["fin"] - sys_c[i]["inicio"], 4), round(ref_c[j]["fin"] - ref_c[j]["inicio"], 4))
                          for i, j in pairs
                          if sys_c[i]["fin"] > sys_c[i]["inicio"] and ref_c[j]["fin"] > ref_c[j]["inicio"]]
        principal[cls]["duraciones"] = bland_altman(durations[cls])

    # Análisis secundario de parpadeos: solo con postura válida y rostro detectado
    invalid = session.invalid_posture_intervals()

    def valid_posture(e):
        return not any(overlaps(e["inicio"], e["fin"], s, t) for s, t in invalid)

    sys_b = [e for e in system if e["clase"] == "parpadeo" and e["origen"] == "sistema"
             and e["resultado"] != "excluido" and valid_posture(e)]
    ref_b = [e for e in ref if e["clase"] == "parpadeo" and e["resultado"] != "excluido" and valid_posture(e)]
    pairs_b = match(sys_b, ref_b, TOLERANCE_S["parpadeo"])
    for i, j in pairs_b:
        sys_b[i]["resultado_postura_valida"] = ref_b[j]["resultado_postura_valida"] = "acierto"
    for e in sys_b:
        e["resultado_postura_valida"] = e["resultado_postura_valida"] or "falso_positivo"
    for e in ref_b:
        e["resultado_postura_valida"] = e["resultado_postura_valida"] or "falso_negativo"
    secondary = metrics(len(pairs_b), len(sys_b) - len(pairs_b), len(ref_b) - len(pairs_b))
    secondary["tiempo_postura_invalida_s"] = round(sum(t - s for s, t in invalid), 2)

    # Descartes del sistema: ¿eran eventos reales? (estimación: con la regla desactivada, un descarte que se
    # solapa con un evento anotado sin pareja habría sido un acierto; si no, un falso positivo)
    discards = {}
    for kind, cls in DISCARD_TYPES.items():
        missed = [e for e in ref if e["clase"] == cls and e["resultado"] == "falso_negativo"]
        counts = Counter()
        for d in (e for e in system if e["tipo"] == kind and not e["resultado"]):
            real = any(overlaps(d["inicio"], d["fin"], r["inicio"], r["fin"], TOLERANCE_S[cls]) for r in missed)
            d["resultado"] = "descarte_de_evento_real" if real else "descarte_correcto"
            counts[d["resultado"]] += 1
        discards[kind] = {"total": sum(counts.values()), "eran_eventos_reales": counts["descarte_de_evento_real"],
                          "correctos": counts["descarte_correcto"]}

    for event in system + ref:
        event.update(session.trace_stats(event["inicio"], event["fin"]))

    git = session.meta.get("git") or {}
    warnings = list(reference.warnings)
    if git.get("cambios_sin_commit"):
        warnings.append("la sesión se analizó con cambios sin commit: esa versión del sistema no es reproducible")
    excluded = {origin: dict(Counter(e["motivo_exclusion"].split(":")[0] for e in group if e["resultado"] == "excluido"))
                for origin, group in (("sistema", system), ("referencia", ref))}
    report = {
        "sesion": session.id, "sujeto": session.subject,
        "referencia": reference.name, "referencia_ciega": reference.blind, "avisos": warnings,
        "version_sistema": {"commit": git.get("commit"), "cambios_sin_commit": git.get("cambios_sin_commit")},
        "version_evaluador": SessionRecorder._git_info(),
        "evaluado": datetime.now().isoformat(timespec="seconds"),
        "parametros": {"tolerancia_s": TOLERANCE_S, "intervalos": "Wilson 95 %",
                       "duraciones": "Bland-Altman, sesgo ± 1.96 DE", "plan": "docs/guia_anotacion.md"},
        "inicio_conteo_s": session.start, "fin_s": session.end,
        "tiempo_no_evaluable_s": round(sum(e - s for s, e, _ in exclusions), 2),
        "principal": principal,
        "secundario_parpadeos_postura_valida": secondary,
        "tipo_bostezo": dict(yawn_types),
        "descartes": discards,
        "excluidos": excluded,
        "pares_duracion": durations,
    }
    return report, system + ref


# ---------------------------------------------------------------------- acuerdo entre anotadores

def cohen_kappa(a, b):
    n = len(a)
    if n == 0:
        return None
    po = sum(x == y for x, y in zip(a, b)) / n
    pa, pb = sum(a) / n, sum(b) / n
    pe = pa * pb + (1 - pa) * (1 - pb)
    return None if pe >= 1 else (po - pe) / (1 - pe)


def landis_koch(kappa):
    if kappa is None:
        return "-"
    if kappa < 0:
        return "pobre"
    return next(label for limit, label in LANDIS_KOCH if kappa <= limit + 1e-12)


def agreement(session, ref_a, ref_b):
    """Kappa de Cohen frame a frame y F1 por evento entre dos anotadores (guía, sección 5)."""
    exclusions = [(s, e) for s, e, _ in ref_a.not_evaluable + ref_b.not_evaluable] + session.not_counting_intervals()
    n_frames = int(round(session.end * session.fps)) if session.end else 0
    first = int(math.ceil(session.start * session.fps)) if session.start is not None else n_frames
    frames = [f for f in range(first, n_frames)
              if not any(s <= f / session.fps <= e for s, e in exclusions)]
    result = {}
    for cls in CLASSES:
        a = [e for e in ref_a.events if e["clase"] == cls and e["inicio"] >= (session.start or 0)
             and not any(overlaps(e["inicio"], e["fin"], s, t) for s, t in exclusions)]
        b = [e for e in ref_b.events if e["clase"] == cls and e["inicio"] >= (session.start or 0)
             and not any(overlaps(e["inicio"], e["fin"], s, t) for s, t in exclusions)]
        pairs = match(b, a, TOLERANCE_S[cls])
        label_a = [any(e["inicio"] <= f / session.fps <= e["fin"] for e in a) for f in frames]
        label_b = [any(e["inicio"] <= f / session.fps <= e["fin"] for e in b) for f in frames]
        kappa = cohen_kappa(label_a, label_b)
        tp = len(pairs)
        result[cls] = {"eventos_" + ref_a.name: len(a), "eventos_" + ref_b.name: len(b), "coinciden": tp,
                       "f1_eventos": round(2 * tp / (len(a) + len(b)), 4) if a or b else None,
                       "kappa_frames": None if kappa is None else round(kappa, 4),
                       "kappa_interpretacion": landis_koch(kappa), "frames": len(frames)}
    return result


# ---------------------------------------------------------------------- salida

def fmt_ci(value, ci):
    if value is None:
        return "     -          "
    return f"{value:4.2f} ({ci[0]:.2f}-{ci[1]:.2f})"


def print_metrics_table(rows):
    print(f"  {'clase':<13} {'aciertos':>8} {'FP':>4} {'FN':>4}   {'sensibilidad (IC95)':<20} "
          f"{'precisión (IC95)':<20} {'F1':>5}")
    for name, m in rows:
        f1 = "-" if m["f1"] is None else f"{m['f1']:.2f}"
        print(f"  {name:<13} {m['aciertos']:>8} {m['falsos_positivos']:>4} {m['falsos_negativos']:>4}   "
              f"{fmt_ci(m['sensibilidad'], m['sensibilidad_ic95']):<20} "
              f"{fmt_ci(m['precision'], m['precision_ic95']):<20} {f1:>5}")


def print_report(report):
    print(f"\nSesión {report['sesion']}  ·  sujeto {report['sujeto']}  ·  referencia {report['referencia']}")
    for warning in report["avisos"]:
        print(f"  [AVISO] {warning}")
    print_metrics_table([(cls, report["principal"][cls]) for cls in CLASSES]
                        + [("parpadeo*", report["secundario_parpadeos_postura_valida"])])
    print("  * parpadeos solo con postura válida y rostro detectado")
    for cls in CLASSES:
        d = report["principal"][cls]["duraciones"]
        if d.get("sesgo_s") is not None:
            low, high = d["limites_acuerdo_s"]
            print(f"  Duración {cls} (sistema - referencia): sesgo {d['sesgo_s']:+.3f} s, "
                  f"límites de acuerdo {low:+.3f} a {high:+.3f} s (n = {d['n']})")
    if report["tipo_bostezo"]:
        print("  Tipo de bostezo (pares):", ", ".join(f"{k}: {v}" for k, v in report["tipo_bostezo"].items()))
    for kind, d in report["descartes"].items():
        if d["total"]:
            print(f"  Descartes {kind}: {d['total']} ({d['eran_eventos_reales']} coincidían con un evento anotado "
                  f"que el sistema no detectó)")
    for origin, counts in report["excluidos"].items():
        if counts:
            print(f"  Excluidos ({origin}): " + ", ".join(f"{k}: {v}" for k, v in counts.items()))


def write_outputs(session, reference, report, events):
    stem = os.path.splitext(reference.name)[0].replace("anotaciones_", "")
    with open(os.path.join(session.dir, f"evaluacion_{stem}.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    with open(os.path.join(session.dir, f"evaluacion_{stem}_eventos.csv"), "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=EVENT_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for e in sorted(events, key=lambda e: (e["clase"], e["inicio"])):
            writer.writerow({**e, "inicio_s": f"{e['inicio']:.3f}", "fin_s": f"{e['fin']:.3f}",
                             "duracion_s": f"{e['fin'] - e['inicio']:.3f}"})
    return os.path.join(session.dir, f"evaluacion_{stem}.json")


def combine(reports):
    """Suma aciertos, falsos positivos y falsos negativos de varias sesiones."""
    total = {}
    for cls in CLASSES:
        counts = [report["principal"][cls] for report in reports]
        total[cls] = metrics(sum(m["aciertos"] for m in counts), sum(m["falsos_positivos"] for m in counts),
                             sum(m["falsos_negativos"] for m in counts))
        total[cls]["duraciones"] = bland_altman([p for report in reports for p in report["pares_duracion"][cls]])
    second = [report["secundario_parpadeos_postura_valida"] for report in reports]
    total["parpadeo_postura_valida"] = metrics(sum(m["aciertos"] for m in second),
                                               sum(m["falsos_positivos"] for m in second),
                                               sum(m["falsos_negativos"] for m in second))
    return total


def parse_args():
    parser = argparse.ArgumentParser(description="Evaluación del sistema frente a la referencia humana")
    parser.add_argument("sesiones", nargs="+", help="carpetas de sesión (sesiones/<fecha>_<sujeto>)")
    parser.add_argument("--referencia", default=DEFAULT_REFERENCE,
                        help="archivo de anotaciones de cada sesión (por defecto anotaciones_ciego.csv, la referencia "
                             "en modo ciego)")
    parser.add_argument("--acuerdo", metavar="NOMBRE",
                        help="acuerdo entre anotaciones_ciego.csv y las del segundo anotador NOMBRE")
    parser.add_argument("--salida", help="con varias sesiones: guarda el resumen conjunto en este archivo JSON")
    return parser.parse_args()


def main():
    args = parse_args()
    if args.acuerdo:
        for path in args.sesiones:
            session = Session(path)
            files = [annotations_file(path, True), annotations_file(path, True, args.acuerdo)]
            missing = [f for f in files if not os.path.exists(f)]
            if missing:
                print(f"{path}: faltan {', '.join(os.path.basename(f) for f in missing)}")
                continue
            ref_a, ref_b = Reference(files[0]), Reference(files[1])
            result = agreement(session, ref_a, ref_b)
            print(f"\nAcuerdo entre anotadores · sesión {session.id}")
            for cls, r in result.items():
                kappa = "-" if r["kappa_frames"] is None else f"{r['kappa_frames']:.2f}"
                f1 = "-" if r["f1_eventos"] is None else f"{r['f1_eventos']:.2f}"
                print(f"  {cls:<13} kappa por frame {kappa} ({r['kappa_interpretacion']}), F1 por evento {f1}, "
                      f"eventos {r['eventos_' + ref_a.name]} / {r['eventos_' + ref_b.name]}")
            out = os.path.join(path, f"acuerdo_{os.path.splitext(ref_b.name)[0].replace('anotaciones_', '')}.json")
            with open(out, "w", encoding="utf-8") as f:
                json.dump({"sesion": session.id, "anotadores": [ref_a.name, ref_b.name], "acuerdo": result,
                           "evaluado": datetime.now().isoformat(timespec="seconds")}, f, ensure_ascii=False, indent=2)
        return

    reports = []
    for path in args.sesiones:
        session = Session(path)
        ref_path = os.path.join(path, args.referencia)
        if not os.path.exists(ref_path):
            print(f"\n{path}: no hay {args.referencia}. La referencia se anota con:\n"
                  f'  python revisar.py "{path}" --ciego')
            continue
        reference = Reference(ref_path)
        report, events = evaluate(session, reference)
        out = write_outputs(session, reference, report, events)
        print_report(report)
        print(f"  Resultados: {out}")
        reports.append(report)

    if len(reports) > 1:
        by_subject = defaultdict(list)
        for report in reports:
            by_subject[report["sujeto"]].append(report)
        summary = {"sesiones": [r["sesion"] for r in reports], "total": combine(reports),
                   "por_sujeto": {s: combine(rs) for s, rs in by_subject.items()},
                   "evaluado": datetime.now().isoformat(timespec="seconds")}
        for subject, total in summary["por_sujeto"].items():
            print(f"\nSujeto {subject} ({len(by_subject[subject])} sesiones)")
            print_metrics_table([(cls, total[cls]) for cls in CLASSES]
                                + [("parpadeo*", total["parpadeo_postura_valida"])])
        print(f"\nTOTAL ({len(reports)} sesiones, {len(by_subject)} sujetos)")
        print_metrics_table([(cls, summary["total"][cls]) for cls in CLASSES]
                            + [("parpadeo*", summary["total"]["parpadeo_postura_valida"])])
        print("  Los eventos de una misma persona no son independientes: los intervalos del total son "
              "orientativos; reporta también los resultados por sujeto.")
        if args.salida:
            with open(args.salida, "w", encoding="utf-8") as f:
                json.dump(summary, f, ensure_ascii=False, indent=2)
            print(f"  Resumen conjunto: {args.salida}")


if __name__ == "__main__":
    main()
