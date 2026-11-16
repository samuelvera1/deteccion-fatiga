# fatigue_eyes.py
"""Detección de parpadeos, PERCLOS y micro-sueño a partir del cierre del párpado."""
from collections import deque

import numpy as np

from fatigue_config import Thresholds


class EyeEventDetector(Thresholds):
    """Parpadeos (referencia local), PERCLOS P80 y micro-sueño.

    profile: SubjectProfile calibrado; perclos: PerclosWindow; head: HeadPoseTracker (velocidad de giro).
    log_event(tipo, ear, duración, end_time=None) registra los eventos de la sesión. on_blink(total) se llama
    al contar cada parpadeo normal."""

    def __init__(self, profile, perclos, head, log_event):
        self.profile = profile
        self.perclos = perclos
        self.head = head
        self._log_event = log_event
        self.on_blink = None
        self.blink_count = 0
        self.long_blink_count = 0             # parpadeos prolongados (>= LONG_BLINK_SECONDS, sin micro-sueño)
        self.blink_durations = []             # duración (s) de cada parpadeo normal y prolongado
        self.fast_turn_rejected = 0           # caídas de apertura descartadas por giro rápido de cabeza
        self.shallow_rejected = 0             # caídas de apertura descartadas por poco profundas
        self._last_microsleep_log = 0.0
        self.reset()

    def reset(self):
        """Descarta el episodio en curso y la referencia local (los contadores se conservan)."""
        self.eyes_closed = False              # cierre sostenido (P80 con histéresis) para el micro-sueño
        self.closed_since = None
        self.blink_refractory = 0
        self.blink_closed = False             # estado del detector de parpadeos (referencia local)
        self.blink_closed_frames = 0
        self.blink_dip = 0.0
        self.blink_started = None             # instante en que empezó el episodio de cierre en curso
        self.blink_had_microsleep = False     # el episodio en curso llegó a micro-sueño
        self.blink_peak_seen = False          # el parpadeo en curso ya llegó a cierre completo
        self.blink_split = None               # reapertura parcial pendiente dentro de una ráfaga
        self.blink_in_burst = False           # el cierre en curso empezó en una reapertura parcial (ráfaga)
        self.blink_ref = None
        self.blink_start_ref = None           # referencia local al empezar el parpadeo en curso (profundidad)
        self._ear_history = deque()           # (t, apertura) del último segundo, para la referencia local
        self._last_blink_ref = None
        self.blink_max_head_speed = 0.0       # giro de cabeza máximo (°/s) durante el cierre en curso

    def _local_blink_reference(self, ear, now, eye_shut):
        """Percentil alto de la apertura entre BLINK_REF_WINDOW[0] y [1] s antes de `now`.
        Con el ojo cerrado (eye_shut) el frame NO entra en la referencia: así, durante un cierre largo la
        referencia queda congelada en el ojo abierto de antes del cierre, en vez de adaptarse al ojo
        cerrado (lo que hacía contar como parpadeos las fluctuaciones dentro del cierre). Sin frames en
        la ventana se mantiene la última referencia válida."""
        if not eye_shut:
            self._ear_history.append((now, ear))
        oldest, newest = self.BLINK_REF_WINDOW
        while self._ear_history and self._ear_history[0][0] < now - oldest:
            self._ear_history.popleft()
        window = [e for t, e in self._ear_history if t < now - newest]
        if len(window) > 5:
            self._last_blink_ref = float(np.percentile(window, self.BLINK_REF_PERCENTILE))
        return self._last_blink_ref

    def _update_blinks(self, ear, yawn_blocks_blinks, eye_shut, now):
        """Parpadeo como caída transitoria respecto a la referencia local, con histéresis.
        No se descartan parpadeos por oclusión: el umbral de deformación (0.08 IPD) se estimó con un solo
        sujeto y en otro (S02, sesiones 20261006_114449 / _114612) marcaba como ocluido el 15-37 % de los
        frames sin manos en la cara (giros de cabeza), descartando parpadeos reales."""
        self.blink_ref = ref = self._local_blink_reference(ear, now, eye_shut)
        if ref is None:
            return
        if self.blink_closed:
            self.blink_closed = ear < ref * (self.BLINK_LOCAL_FACTOR + self.BLINK_REOPEN_MARGIN)
        else:
            self.blink_closed = ear < ref * self.BLINK_LOCAL_FACTOR

        if self.blink_closed:
            if self.blink_closed_frames == 0:
                self.blink_dip, self.blink_started, self.blink_had_microsleep = ear, now, False
                self.blink_peak_seen, self.blink_split, self.blink_in_burst = False, None, False
                self.blink_max_head_speed = 0.0
                self.blink_start_ref = ref
            self.blink_dip = min(self.blink_dip, ear)
            self.blink_max_head_speed = max(self.blink_max_head_speed, self.head.speed or 0.0)
            self.blink_closed_frames += 1
            if self.profile.closed_level_measured:
                self._split_burst(ear, ref, yawn_blocks_blinks, now)
        elif self.blink_closed_frames > 0:
            # El último parpadeo de una ráfaga también es "de ráfaga": el periodo refractario que activó el
            # anterior no debe anularlo (antes se perdía si duraba < 3 frames tras la reapertura parcial)
            self._classify_closure_episode(ear, ref, yawn_blocks_blinks, now, self.blink_closed_frames, self.blink_dip,
                                           in_burst=self.blink_in_burst)
            self.blink_closed_frames = 0

        if self.blink_refractory > 0:
            self.blink_refractory -= 1

    def _split_burst(self, ear, ref, yawn_blocks_blinks, now):
        """Ráfagas de parpadeos: entre parpadeos seguidos el ojo no llega a abrirse del todo y el
        detector los juntaba en un único cierre largo (contado además como prolongado). Cada vez que el
        párpado vuelve a cerrarse >= BURST_PEAK_CLOSURE tras una reapertura parcial por debajo de
        BURST_REOPEN_CLOSURE, se cierra el parpadeo anterior (en el instante de la reapertura) y empieza
        uno nuevo. Requiere el nivel de ojo cerrado medido (la escala de cierre debe ser fiable)."""
        closure = self.profile.closure(ear)
        if self.blink_split is None:
            if closure >= self.BURST_PEAK_CLOSURE:
                self.blink_peak_seen = True
            elif self.blink_peak_seen and closure < self.BURST_REOPEN_CLOSURE:
                # reapertura parcial: (instante, frames y mínimo del parpadeo anterior, frames y mínimo desde aquí)
                self.blink_split = [now, self.blink_closed_frames - 1, self.blink_dip, 1, ear]
            return
        split_t, frames_before, dip_before, frames_after, dip_after = self.blink_split
        if closure >= self.BURST_PEAK_CLOSURE:
            # nuevo cierre completo: el parpadeo anterior terminó en la reapertura parcial
            self._classify_closure_episode(ear, ref, yawn_blocks_blinks, split_t, frames_before, dip_before,
                                           in_burst=True)
            self.blink_started, self.blink_closed_frames = split_t, frames_after + 1
            self.blink_dip, self.blink_peak_seen, self.blink_split = min(dip_after, ear), True, None
            self.blink_in_burst = True
            self.blink_start_ref = ref
        else:
            self.blink_split[3], self.blink_split[4] = frames_after + 1, min(dip_after, ear)

    def _classify_closure_episode(self, ear, ref, yawn_blocks_blinks, end_time, frames, dip, in_burst=False):
        """Clasifica un episodio de cierre ya terminado por su duración:
           < LONG_BLINK_SECONDS                                   -> PARPADEO
           >= LONG_BLINK_SECONDS, cierre >= 80 % y sin micro-sueño -> PARPADEO_PROLONGADO
           con micro-sueño durante el episodio                    -> ya registrado como MICRO_SUENO
        in_burst: parpadeo de una ráfaga, separado por una reapertura parcial medida; no aplica el periodo
        refractario (que evita contar dos veces un mismo parpadeo, no parpadeos distintos seguidos)."""
        duration = end_time - self.blink_started
        is_fast_blink = frames == 1 and dip < ref * (self.BLINK_LOCAL_FACTOR - self.BLINK_DEEP_MARGIN)
        if not (frames >= self.MIN_BLINK_FRAMES or is_fast_blink):
            return                            # ruido de 1 frame
        if (self.blink_refractory > 0 and not in_burst) or yawn_blocks_blinks or self.blink_had_microsleep:
            return
        if (self.blink_max_head_speed > self.FAST_HEAD_SPEED
                and self.profile.closure(dip) < self.P80_CLOSURE):
            # caída de apertura durante un giro rápido de cabeza sin cierre real del párpado
            self.fast_turn_rejected += 1
            self._log_event("PARPADEO_DESCARTADO_GIRO", ear, duration, end_time=end_time)
            return
        start_ref = self.blink_start_ref or ref
        if start_ref and 1.0 - dip / start_ref < self.BLINK_MIN_DEPTH:
            # caída de apertura poco profunda (mirada, gesto, ruido de la malla): no es un parpadeo
            self.shallow_rejected += 1
            self._log_event("PARPADEO_DESCARTADO_PROFUNDIDAD", ear, duration, end_time=end_time)
            return
        # end_time: en una ráfaga, el parpadeo termina en la reapertura parcial (anterior al frame actual);
        # registrarlo en el frame actual desplazaba su intervalo [t_s - duración, t_s] unas décimas
        if duration < self.LONG_BLINK_SECONDS:
            self.blink_count += 1
            self.blink_durations.append(duration)
            self._log_event("PARPADEO", ear, duration, end_time=end_time)
            if self.on_blink:
                self.on_blink(self.blink_count)
        elif self.profile.closure(dip) >= self.LONG_BLINK_MIN_CLOSURE:
            self.long_blink_count += 1
            self.blink_durations.append(duration)
            self._log_event("PARPADEO_PROLONGADO", ear, duration, end_time=end_time)
        else:
            return                            # entrecerrar los ojos: ni parpadeo ni cierre
        self.blink_refractory = self.BLINK_REFRACTORY_FRAMES

    def update(self, ear, yawn_blocks_blinks, now, pose_valid=True):
        """Parpadeos (referencia local), PERCLOS P80 y micro-sueño. Devuelve micro-sueño activo.
        El % de cierre se mide entre los niveles abierto y cerrado calibrados del sujeto: entrecerrar
        los ojos (al bostezar, hablar o mirar abajo) no llega al 80 % y no cuenta como cierre.
        Con la postura fuera de rango (pose_valid=False) no se cuentan parpadeos ni PERCLOS (la apertura 2D
        del ojo no es fiable); el micro-sueño se sigue evaluando por seguridad."""
        closure = self.profile.closure(ear)
        if pose_valid:
            self._update_blinks(ear, yawn_blocks_blinks, closure >= self.MICROSLEEP_EXIT_CLOSURE, now)
            self.perclos.update(closure >= self.P80_CLOSURE, now)
        else:
            self.blink_closed, self.blink_closed_frames = False, 0   # se descarta el episodio en curso
            self.perclos.skip_gap()                                   # el hueco no pesa en el PERCLOS

        # Cierre sostenido con histéresis: entra con >= 80 %, sale por debajo de 70 %
        self.eyes_closed = closure >= (self.MICROSLEEP_EXIT_CLOSURE if self.eyes_closed else self.P80_CLOSURE)
        if not self.eyes_closed:
            self.closed_since = None
            return False
        if self.closed_since is None:
            self.closed_since = now
        if now - self.closed_since < self.MICROSLEEP_SECONDS:
            return False
        self.blink_had_microsleep = True      # el episodio en curso ya no puede ser un parpadeo prolongado
        if now - self._last_microsleep_log > 1.0:
            # Duracion_s = tiempo con el ojo cerrado hasta este registro (se registra cada segundo)
            self._log_event("MICRO_SUENO", ear, now - self.closed_since)
            self._last_microsleep_log = now
        return True
