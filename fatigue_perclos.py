# fatigue_perclos.py
"""PERCLOS en una ventana deslizante ponderada por tiempo real."""
from collections import deque


class PerclosWindow:
    """PERCLOS ponderado por tiempo real (independiente de los fps) en una ventana de window_seconds.

    Cada frame pesa el tiempo transcurrido desde el anterior (máx. MAX_FRAME_WEIGHT s, para que una pausa
    del vídeo o de la cámara no pese de más). El denominador nunca baja de min_seconds: al inicio un solo
    parpadeo no puede inflar el PERCLOS."""

    MAX_FRAME_WEIGHT = 0.2

    def __init__(self, window_seconds, min_seconds):
        self.window_seconds = window_seconds
        self.min_seconds = min_seconds
        self._history = deque()               # (t, dt, cerrado) en la ventana
        self.closed_time = 0.0
        self.total_time = 0.0
        self._last_t = None
        self.value = 0.0                      # PERCLOS en %

    def update(self, is_closed, now):
        dt = 0.0 if self._last_t is None else min(max(now - self._last_t, 0.0), self.MAX_FRAME_WEIGHT)
        self._last_t = now
        self._history.append((now, dt, is_closed))
        self.total_time += dt
        self.closed_time += dt if is_closed else 0.0
        while self._history and self._history[0][0] < now - self.window_seconds:
            _, old_dt, old_closed = self._history.popleft()
            self.total_time -= old_dt
            self.closed_time -= old_dt if old_closed else 0.0

        denominator = max(self.total_time, self.min_seconds)
        self.value = max(0.0, self.closed_time / denominator * 100.0)
        return self.value

    def skip_gap(self):
        """El hueco hasta el próximo frame no pesa (p. ej. postura fuera de rango)."""
        self._last_t = None
