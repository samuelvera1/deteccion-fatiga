# fatigue_yawn.py
"""Detector de bostezos de dos niveles, con descarte de sonrisas."""
from fatigue_config import Thresholds


class YawnDetector:
    """Bostezo de dos niveles (exagerado y micro) a partir de la apertura de la boca en unidades de IPD.

    profile: SubjectProfile ya calibrado (boca neutra). tiers: [(factor, delta mínimo, segundos)] del nivel
    exagerado y del micro. log_event(tipo, ear, duración, end_time) registra los eventos de la sesión.
    on_yawn(total) se llama al contar cada bostezo."""

    TIER_EXAGGERATED, TIER_MICRO = Thresholds.YAWN_TIER_EXAGGERATED, Thresholds.YAWN_TIER_MICRO
    GAP_FRAMES = Thresholds.YAWN_GAP_FRAMES
    COOLDOWN_SECONDS = Thresholds.YAWN_COOLDOWN_SECONDS
    SMILE_MIN_WIDTH_RATIO = Thresholds.SMILE_MIN_WIDTH_RATIO
    SMILE_MAX_JAW_DROP = Thresholds.SMILE_MAX_JAW_DROP

    def __init__(self, profile, tiers, log_event):
        self.profile = profile
        self.tiers = tiers
        self._log_event = log_event
        self.on_yawn = None
        self.count = 0                        # total (exagerados + micro)
        self.micro_count = 0
        self.smile_count = 0                  # episodios de boca abierta descartados como sonrisa
        self.durations = []                   # duración de la apertura bucal de cada bostezo contado
        self.reset()

    def reset(self):
        """Descarta el episodio en curso (los contadores se conservan)."""
        self.run_start = [None, None]         # inicio de la racha sostenida de cada nivel
        self.run_gap = [0, 0]                 # frames consecutivos por debajo del umbral de cada nivel
        self.counted = False
        self.exaggerated = False              # el episodio actual alcanzó el nivel 1
        self.cooldown_until = 0.0
        self.episode_start = None             # inicio del episodio de boca abierta en curso
        self.last_open = None                 # último instante con la boca sobre el umbral micro
        self.smile_seen = False               # el episodio en curso tuvo forma de sonrisa

    def thresholds(self):
        """Umbral de apertura bucal de cada nivel: [exagerado, micro].
        Umbral de cada nivel = max(factor * boca neutra, boca neutra + min_delta) en unidades de IPD. El margen
        mínimo es necesario porque con labios cerrados la boca neutra es ~0 y 1.3x de ~0 lo superaría
        cualquier sílaba."""
        neutral = self.profile.neutral_mouth_ratio
        return [max(neutral * factor, neutral + min_delta) for factor, min_delta, _ in self.tiers]

    def is_smile(self, shape):
        """Sonrisa (FACS, AU12 'lip corner puller'): boca claramente más ancha que en reposo sin la caída de
        mandíbula propia del bostezo. Umbrales PROVISIONALES ajustados con datos sin etiquetar (ver
        SMILE_MIN_WIDTH_RATIO). La elevación de comisuras se sigue registrando en la traza, pero no decide."""
        p = self.profile
        # Sin un ancho de boca neutro válido (malla degenerada) no se decide: si no, todo parecería sonrisa
        if shape is None or p.neutral_mouth_width is None or p.neutral_mouth_width < 0.1:
            return False
        width, jaw, _ = shape
        return (width >= p.neutral_mouth_width * self.SMILE_MIN_WIDTH_RATIO
                and jaw - p.neutral_jaw < self.SMILE_MAX_JAW_DROP)

    def update(self, mouth, now, ear, shape=None):
        """Devuelve (bostezo_en_curso, bloquea_parpadeos).
        Se cuenta en cuanto se cumple cualquier nivel (aviso inmediato); el tipo (BOSTEZO o
        MICRO_BOSTEZO) se registra al terminar el episodio, porque un bostezo exagerado siempre
        cumple antes el nivel micro (umbral más bajo y duración más corta).
        Mientras la forma de la boca sea de sonrisa (is_smile) el episodio no se cuenta; si termina sin
        contarse y hubo sonrisa, se registra un evento SONRISA (para poder revisar los descartes)."""
        if now < self.cooldown_until and self.run_start[self.TIER_MICRO] is None:
            return False, True

        for tier, threshold in enumerate(self.thresholds()):
            if mouth > threshold:
                if self.run_start[tier] is None:
                    self.run_start[tier] = now
                    if tier == self.TIER_MICRO:
                        self.episode_start, self.smile_seen = now, False
                if tier == self.TIER_MICRO:
                    self.last_open = now      # último frame con la boca sobre el umbral (fin del episodio)
                self.run_gap[tier] = 0
            elif self.run_start[tier] is not None:
                self.run_gap[tier] += 1
                if self.run_gap[tier] > self.GAP_FRAMES:
                    self.run_start[tier] = None

        smiling = self.run_start[self.TIER_MICRO] is not None and self.is_smile(shape)
        self.smile_seen = self.smile_seen or smiling
        # Un episodio que mostró forma de sonrisa solo puede contarse como bostezo si aparece después la
        # señal propia del bostezo (caída de mandíbula); si no, al cerrar la boca (frames de tolerancia) la
        # forma deja de ser de sonrisa y el episodio se colaba como bostezo.
        jaw_drop = (shape[1] - self.profile.neutral_jaw
                    if shape is not None and self.profile.neutral_jaw is not None else None)
        vetoed = smiling or (self.smile_seen and not (jaw_drop is not None and jaw_drop >= self.SMILE_MAX_JAW_DROP))
        sustained = [start is not None and now - start >= min_seconds
                     for start, (_, _, min_seconds) in zip(self.run_start, self.tiers)]
        if sustained[self.TIER_EXAGGERATED] and not vetoed:
            self.exaggerated = True
        if any(sustained) and not self.counted and not vetoed:
            self.counted = True
            self.count += 1
            if self.on_yawn:
                self.on_yawn(self.count)

        if self.run_start[self.TIER_MICRO] is None:      # fin del episodio
            self._close_episode(now, ear)

        is_yawning = self.counted
        # Solo un bostezo confirmado bloquea parpadeos (hablar no debe bloquearlos)
        return is_yawning, is_yawning or now < self.cooldown_until

    def _close_episode(self, now, ear):
        # El episodio se cierra GAP_FRAMES frames después de que la boca baje del umbral:
        # el evento se registra en el último frame con la boca abierta, con la duración de la apertura
        start, end = self.episode_start, self.last_open
        duration = end - start if start is not None and end is not None else None
        if self.counted:
            if not self.exaggerated:
                self.micro_count += 1
            if duration is not None:
                self.durations.append(duration)
            self._log_event("BOSTEZO" if self.exaggerated else "MICRO_BOSTEZO", ear, duration, end)
            self.cooldown_until = now + self.COOLDOWN_SECONDS
        elif self.smile_seen and start is not None:
            self.smile_count += 1
            self._log_event("SONRISA", ear, duration, end)
        self.run_start[self.TIER_EXAGGERATED] = None
        self.counted = False
        self.exaggerated = False
        self.episode_start, self.smile_seen, self.last_open = None, False, None
