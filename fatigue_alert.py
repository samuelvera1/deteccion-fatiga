# fatigue_alert.py
"""
Nivel de fatiga y alertas en vivo a partir de los indicadores oculares.

Criterios (de la literatura; PROVISIONALES para este sistema hasta validarlos con sus propios datos):
  MICRO_SUENO  ojos >= 80 % cerrados durante >= 1 s (micro-sueño conductual, Hertig-Godeschalk et al.,
               2020): alarma inmediata, con independencia del PERCLOS.
  SOMNOLENCIA  PERCLOS >= 12 % en la ventana de 1 min: en varios estudios se clasificó como somnoliento a
               quien tenía los ojos cerrados en el 12 % o más del tiempo en 1-3 min, y los avisos a
               conductores usaron umbrales del 8-12 % en ventanas de 1-3 min (Wierwille y Ellsworth, 1994;
               Dinges et al., 1998; revisiones de Virginia Tech sobre PERCLOS).
  PRECAUCION   PERCLOS >= 8 % (extremo inferior de ese rango): solo aviso visual.
  NORMAL       por debajo.
Esos umbrales se obtuvieron con cámaras y métodos de medida del ojo distintos (infrarrojo, evaluadores
entrenados); aquí el PERCLOS se estima con MediaPipe, así que su validez debe comprobarse.

Decisiones de ingeniería (no de la literatura, ajustables): el PERCLOS solo alerta con la ventana casi
completa de datos válidos (MIN_VALID_FRACTION), un nivel se desactiva 2 puntos por debajo de su umbral
(histéresis, para que el aviso no se encienda y apague sin parar) y el sonido se repite como mucho cada
cierto tiempo.
"""

NORMAL, PRECAUCION, SOMNOLENCIA, MICRO_SUENO = "NORMAL", "PRECAUCION", "SOMNOLENCIA", "MICRO_SUENO"
LEVELS = [NORMAL, PRECAUCION, SOMNOLENCIA, MICRO_SUENO]

MESSAGES = {PRECAUCION: "PRECAUCION: signos leves de cansancio",
            SOMNOLENCIA: "SOMNOLENCIA: considera tomar un descanso",
            MICRO_SUENO: "ALERTA: OJOS CERRADOS"}
COLORS_BGR = {NORMAL: (0, 200, 110), PRECAUCION: (0, 200, 255), SOMNOLENCIA: (0, 120, 255),
              MICRO_SUENO: (0, 0, 230)}


def play_alarm(level):
    """Melodía de advertencia sin bloquear el análisis; si no hay archivo de sonido, el sonido del sistema."""
    import fatigue_audio
    if fatigue_audio.play_alert(level) or level not in (SOMNOLENCIA, MICRO_SUENO):
        return
    try:
        import winsound
        alias = "SystemHand" if level == MICRO_SUENO else "SystemExclamation"
        winsound.PlaySound(alias, winsound.SND_ALIAS | winsound.SND_ASYNC)
    except Exception:
        print("\a", end="", flush=True)


class FatigueAlert:
    CAUTION_PCT = 8.0
    DROWSY_PCT = 12.0
    HYSTERESIS_PCT = 2.0
    MIN_VALID_FRACTION = 0.9        # >= 54 s de datos válidos en la ventana de 60 s
    DROWSY_REPEAT_S = 30.0          # repetición del sonido mientras dure la somnolencia
    MICROSLEEP_REPEAT_S = 3.0       # repetición del sonido mientras los ojos sigan cerrados

    def __init__(self, window_seconds, sound=True, on_alert=None):
        self.window_seconds = window_seconds
        self.sound = sound
        self.on_alert = on_alert        # callback(nivel) al subir a un nivel con alerta
        self.level = NORMAL
        self.perclos_level = NORMAL     # nivel según el PERCLOS (sin contar el micro-sueño)
        self.since = None               # instante en que empezó el nivel actual
        self.time_in_level = {level: 0.0 for level in LEVELS}
        self.alert_counts = {level: 0 for level in LEVELS[1:]}
        self._last_t = None
        self._last_sound = None

    def parameters(self):
        return {"precaucion_perclos_pct": self.CAUTION_PCT, "somnolencia_perclos_pct": self.DROWSY_PCT,
                "histeresis_pct": self.HYSTERESIS_PCT, "ventana_s": self.window_seconds,
                "datos_validos_min_fraccion": self.MIN_VALID_FRACTION,
                "micro_sueno": "ojos >= 80 % cerrados durante >= 1 s",
                "sonido": self.sound, "repeticion_sonido_somnolencia_s": self.DROWSY_REPEAT_S,
                "repeticion_sonido_micro_sueno_s": self.MICROSLEEP_REPEAT_S,
                "base": "Hertig-Godeschalk et al. 2020; Wierwille y Ellsworth 1994; Dinges et al. 1998 "
                        "(umbrales de PERCLOS 8-12 % en 1-3 min); PROVISIONALES"}

    def _perclos_level(self, perclos, valid_time):
        if valid_time < self.MIN_VALID_FRACTION * self.window_seconds:
            return NORMAL                       # sin un minuto (casi) completo de datos no se alerta
        current = self.perclos_level
        if perclos >= self.DROWSY_PCT:
            return SOMNOLENCIA
        if current == SOMNOLENCIA and perclos >= self.DROWSY_PCT - self.HYSTERESIS_PCT:
            return SOMNOLENCIA
        if perclos >= self.CAUTION_PCT:
            return PRECAUCION
        if current in (PRECAUCION, SOMNOLENCIA) and perclos >= self.CAUTION_PCT - self.HYSTERESIS_PCT:
            return PRECAUCION
        return NORMAL

    def update(self, now, perclos, valid_time, microsleep):
        """Devuelve el nuevo nivel si cambió (para registrarlo), o None."""
        if self._last_t is not None:
            self.time_in_level[self.level] += max(now - self._last_t, 0.0)
        self._last_t = now
        self.perclos_level = self._perclos_level(perclos, valid_time)
        level = MICRO_SUENO if microsleep else self.perclos_level
        changed = level != self.level
        rising = LEVELS.index(level) > LEVELS.index(self.level)
        previous = self.level
        if changed:
            self.level, self.since = level, now
            if rising and level != PRECAUCION:
                self.alert_counts[level] += 1
                self._last_sound = None
                if self.on_alert:
                    self.on_alert(level)
            elif rising:
                self.alert_counts[level] += 1
            # un solo aviso al entrar en PRECAUCIÓN y otro al volver a NORMAL desde un nivel de alerta; SOMNOLENCIA
            # y MICRO-SUEÑO suenan al entrar y se repiten (_maybe_sound)
            if self.sound and ((level == PRECAUCION and rising) or (level == NORMAL and previous != NORMAL)):
                play_alarm(level)
        self._maybe_sound(now)
        return level if changed else None

    def _maybe_sound(self, now):
        if not self.sound or self.level in (NORMAL, PRECAUCION):
            return
        repeat = self.MICROSLEEP_REPEAT_S if self.level == MICRO_SUENO else self.DROWSY_REPEAT_S
        if self._last_sound is None or now - self._last_sound >= repeat:
            self._last_sound = now
            play_alarm(self.level)

    def summary(self):
        return {"tiempo_por_nivel_s": {k: round(v, 2) for k, v in self.time_in_level.items()},
                "alertas": dict(self.alert_counts), "nivel_final": self.level}
