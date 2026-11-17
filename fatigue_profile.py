# fatigue_profile.py
"""Perfil facial del sujeto (calibración) y puerta de estabilidad de la malla facial."""
import numpy as np


class SubjectProfile:
    """
    Perfil facial del sujeto:
      - Ojo abierto, boca neutra e IPD: medianas de `calibration_frames` frames mirando al frente.
      - Ojo cerrado: mediana de `closed_frames` frames con los ojos cerrados a petición. MediaPipe no
        llega a apertura 0 con el ojo cerrado, así que el % de cierre (necesario para el P80 de
        Wierwille et al., 1994) solo puede medirse entre los niveles abierto y cerrado de cada sujeto.
        Se mide una sola vez (al inicio o con recalibración manual). En las recalibraciones
        automáticas se reutiliza como proporción cerrado/abierto aplicada al nuevo ojo abierto.
        SUPUESTO (pendiente de verificar): esa proporción no cambia al ponerse/quitarse las gafas.
    """

    def __init__(self, calibration_frames=90, closed_frames=30):
        self.calibration_frames = calibration_frames
        self.closed_frames = closed_frames
        self.closed_ratio = None              # ojo cerrado / ojo abierto en el momento de medirlo
        self.closed_level_measured = None     # False si se usó el valor de reserva por timeout
        self.closed_phase_ratios = []
        self.reset()

    def reset(self, keep_closed_ratio=False):
        """keep_closed_ratio=True conserva la proporción de ojo cerrado (recalibración automática)."""
        self._ear_samples = []
        self._mouth_samples = []
        self._ipd_samples = []
        self._shape_samples = []
        self._closed_samples = []
        self.open_ear_baseline = None
        self.neutral_mouth_ratio = None
        self.ipd_baseline = None
        # Forma neutra de la boca (unidades de IPD): ancho entre comisuras, distancia nariz-mentón y
        # elevación de las comisuras respecto al labio superior (para distinguir sonrisa de bostezo)
        self.neutral_mouth_width = None
        self.neutral_jaw = None
        self.neutral_corner_lift = None
        self.closed_ear_level = None
        self.closed_level_reused = False
        if not keep_closed_ratio:
            self.closed_phase_ratios = []     # apertura / ojo abierto en cada frame del paso de ojos cerrados
            self.closed_ratio = None
            self.closed_level_measured = None

    @property
    def is_calibrated(self):
        return self.open_ear_baseline is not None

    @property
    def is_closed_calibrated(self):
        return self.closed_ear_level is not None

    @property
    def progress(self):
        return min(len(self._ear_samples) / float(self.calibration_frames), 1.0)

    @property
    def closed_progress(self):
        return min(len(self._closed_samples) / float(self.closed_frames), 1.0)

    def observe_closed_phase(self, ear):
        """Registra cada frame del paso de ojos cerrados (diagnóstico de cuánto capta la malla el cierre)."""
        self.closed_phase_ratios.append(ear / self.open_ear_baseline)

    @property
    def closed_phase_min_ratio(self):
        """Apertura mínima observada con los ojos cerrados (percentil 5, robusto a frames sueltos)."""
        return float(np.percentile(self.closed_phase_ratios, 5)) if self.closed_phase_ratios else None

    def add_closed_sample(self, ear):
        """Acumula un frame con el ojo cerrado; devuelve True cuando se fija el nivel de ojo cerrado."""
        self._closed_samples.append(ear)
        if len(self._closed_samples) < self.closed_frames:
            return False
        self._set_closed_level(float(np.median(self._closed_samples)), measured=True)
        return True

    def closed_samples_enough(self, min_samples=10):
        return len(self._closed_samples) >= min_samples

    def restart_closed_phase(self):
        """Nuevo intento del paso de ojos cerrados: descarta lo acumulado en el intento fallido."""
        self._closed_samples = []
        self.closed_phase_ratios = []

    def finish_closed_on_timeout(self, fallback_ratio, min_samples=10):
        """Tiempo agotado: con >= min_samples frames cerrados se usa su mediana (medido); si no, el
        valor de reserva fallback_ratio x ojo abierto (no medido)."""
        if len(self._closed_samples) >= min_samples:
            self._set_closed_level(float(np.median(self._closed_samples)), measured=True)
        else:
            self._set_closed_level(self.open_ear_baseline * fallback_ratio, measured=False)

    def _set_closed_level(self, level, measured):
        self.closed_ear_level = level
        self.closed_ratio = level / self.open_ear_baseline
        self.closed_level_measured = measured

    def rebase_open(self, open_ear):
        """E14: nueva apertura de ojo abierto tras un cambio de postura sostenido; el ojo cerrado conserva su
        proporción respecto al abierto (como en las recalibraciones automáticas)."""
        self.open_ear_baseline = float(open_ear)
        if self.closed_ratio is not None:
            self.closed_ear_level = self.closed_ratio * self.open_ear_baseline

    def closure(self, ear):
        """Fracción de cierre del párpado: 0 = abierto como en la calibración, 1 = cerrado."""
        span = self.open_ear_baseline - self.closed_ear_level
        return (self.open_ear_baseline - ear) / span if span > 0 else 0.0

    def add_sample(self, ear, mouth_ratio, ipd, mouth_shape=None, auto_finish=True):
        """Acumula un frame neutro; devuelve True en el frame en que se fija el perfil.
        mouth_shape: (ancho, mandíbula, elevación de comisuras) en unidades de IPD.
        auto_finish=False (calibración manual): solo acumula; el perfil se fija con finish_profile()."""
        self._ear_samples.append(ear)
        self._mouth_samples.append(mouth_ratio)
        self._ipd_samples.append(ipd)
        if mouth_shape is not None:
            self._shape_samples.append(mouth_shape)
        if not auto_finish or len(self._ear_samples) < self.calibration_frames:
            return False
        self.finish_profile()
        return True

    @property
    def n_open_samples(self):
        return len(self._ear_samples)

    @property
    def n_closed_samples(self):
        return len(self._closed_samples)

    def add_manual_closed_sample(self, ear):
        """Frame del tramo de ojos cerrados marcado a mano (sin filtro de apertura: lo confirma el investigador)."""
        self._closed_samples.append(ear)

    def finish_manual_closed(self):
        """Nivel de ojo cerrado = mediana del tramo marcado; registra cada frame para el diagnóstico."""
        self.closed_phase_ratios = [e / self.open_ear_baseline for e in self._closed_samples]
        self._set_closed_level(float(np.median(self._closed_samples)), measured=True)

    def finish_profile(self):
        """Fija el perfil neutro con las muestras acumuladas."""
        # La mediana descarta los parpadeos y gestos puntuales ocurridos durante la calibración
        self.open_ear_baseline = float(np.median(self._ear_samples))
        self.neutral_mouth_ratio = float(np.median(self._mouth_samples))
        self.ipd_baseline = float(np.median(self._ipd_samples))
        if self._shape_samples:
            self.neutral_mouth_width, self.neutral_jaw, self.neutral_corner_lift = (
                float(v) for v in np.median(np.array(self._shape_samples), axis=0))
        if self.closed_ratio is not None:     # recalibración automática: no se repite el paso de ojos cerrados
            self.closed_ear_level = self.closed_ratio * self.open_ear_baseline
            self.closed_level_reused = True



class SustainedClosureFilter:
    """Paso de ojos cerrados: deja pasar solo los cuadros de un cierre sostenido (al menos min_seconds seguidos bajo
    el umbral, con huecos de hasta gap_frames cuadros), no los de los parpadeos espontáneos."""

    def __init__(self, min_seconds, gap_frames):
        self.min_seconds = min_seconds
        self.gap_frames = gap_frames
        self.reset()

    def reset(self):
        self._pending = []
        self._start = None
        self._gap = 0
        self._sustained = False

    def update(self, ear, below, now):
        """Devuelve las aperturas que pasan a contar como ojo cerrado (al confirmarse el cierre, las del tramo)."""
        if not below:
            if self._start is not None and self._gap < self.gap_frames:
                self._gap += 1
                return []
            self.reset()
            return []
        self._gap = 0
        if self._start is None:
            self._start = now
        if self._sustained:
            return [ear]
        self._pending.append(ear)
        if now - self._start >= self.min_seconds:
            self._sustained = True
            released, self._pending = self._pending, []
            return released
        return []


class LandmarkStabilityGate:
    """
    Puerta de estabilidad de landmarks: el rostro debe estar quieto durante la calibración.
    - Movimiento: máximo desplazamiento entre frames de landmarks rígidos, en unidades de la
      distancia entre ojos (independiente de la distancia a la cámara).
    - deformation (opcional): penalización externa; el monitor pasa infinito si la cabeza no está de
      frente (orientación fuera de POSE_STABLE_MAX), para no calibrar con la cabeza girada.
    """

    RIGID_LANDMARKS = [33, 133, 362, 263, 168, 6, 1, 10, 152, 234, 454]

    def __init__(self, required_frames=15, max_motion=0.03, max_deformation=0.08):
        self.required_frames = required_frames
        self.max_motion = max_motion
        self.max_deformation = max_deformation
        self.reset()

    def reset(self):
        self._prev = None
        self.stable_frames = 0
        self.motion = None
        self.deformation = None

    @property
    def is_ready(self):
        return self.stable_frames >= self.required_frames

    def update(self, face, deformation=0.0):
        """Evalúa un frame; devuelve True si es estable. Llamar a reset() cuando se pierde el rostro."""
        pts = np.asarray(face, dtype=np.float64)
        eye_dist = float(np.linalg.norm((pts[33] + pts[133]) / 2.0 - (pts[362] + pts[263]) / 2.0))
        rigid = pts[self.RIGID_LANDMARKS]
        if self._prev is None or eye_dist <= 0:
            self.motion = float("inf")
        else:
            self.motion = float(np.max(np.linalg.norm(rigid - self._prev, axis=1))) / eye_dist
        self._prev = rigid
        self.deformation = deformation

        is_stable = self.motion <= self.max_motion and deformation <= self.max_deformation
        self.stable_frames = self.stable_frames + 1 if is_stable else 0
        return is_stable
