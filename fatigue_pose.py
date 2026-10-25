# fatigue_pose.py
"""Orientación de la cabeza respecto a la postura de calibración, velocidad de giro y tiempo fuera de rango."""
import numpy as np

import fatigue_geometry


class HeadPoseTracker:
    """Estado de la postura de la cabeza.

    max_pitch / max_yaw: rango válido para las métricas del ojo; frontal_max: rango de la puerta de
    estabilidad. on_out_of_range(duración) se llama al terminar cada intervalo fuera de rango."""

    def __init__(self, max_pitch, max_yaw, frontal_max, on_out_of_range):
        self.max_pitch, self.max_yaw, self.frontal_max = max_pitch, max_yaw, frontal_max
        self._on_out_of_range = on_out_of_range
        self.ref = None                       # ejes de la cabeza en la calibración (postura frontal)
        self.samples = []                     # ejes de los frames de calibración
        self.last_axes = None
        self._last_axes_t = None
        self.speed = None                     # velocidad de giro de la cabeza (°/s) en el último frame
        self.pose = None                      # (yaw, pitch, roll) en grados respecto a la calibración
        self._out_since = None                # inicio del intervalo de postura fuera de rango en curso
        self.out_time = 0.0                   # tiempo total (s) de monitoreo con postura fuera de rango

    def reset_reference(self):
        """Descarta la referencia y las muestras (recalibración)."""
        self.ref, self.samples, self.pose = None, [], None

    def add_calibration_sample(self):
        """Guarda los ejes del último frame como muestra de la postura de referencia."""
        if self.last_axes is not None:
            self.samples.append(self.last_axes)

    def update(self, face3d, now):
        """Orientación de la cabeza (yaw, pitch, roll en grados) RELATIVA a la postura media de la
        calibración (mirando al frente). Convención R = Ry(yaw)·Rx(pitch)·Rz(roll) en ejes de cámara:
        yaw = giro a los lados, pitch = arriba/abajo, roll = inclinación hacia el hombro.
        Además, velocidad de giro (°/s): ángulo de la rotación entre este frame y el anterior / tiempo."""
        axes = fatigue_geometry.face_axes(face3d)
        prev, prev_t = self.last_axes, self._last_axes_t
        self.speed = None
        if axes is not None and prev is not None and prev_t is not None and now > prev_t:
            cos_angle = np.clip((np.trace(axes @ prev.T) - 1.0) / 2.0, -1.0, 1.0)
            self.speed = float(np.degrees(np.arccos(cos_angle)) / (now - prev_t))
        self.last_axes, self._last_axes_t = axes, now
        if axes is None or self.ref is None:
            self.pose = None
            return
        r = axes @ self.ref.T
        yaw = np.degrees(np.arctan2(r[0, 2], r[2, 2]))
        pitch = np.degrees(np.arcsin(np.clip(-r[1, 2], -1.0, 1.0)))
        roll = np.degrees(np.arctan2(r[1, 0], r[1, 1]))
        self.pose = (float(yaw), float(pitch), float(roll))

    def lock_reference(self):
        """Postura de referencia = ejes medios de los frames de calibración, reortonormalizados (SVD)."""
        if not self.samples:
            return
        try:
            u, _, vt = np.linalg.svd(np.mean(np.array(self.samples), axis=0))
            self.ref = u @ vt
        except np.linalg.LinAlgError:
            self.ref = None                   # sin referencia: la orientación queda vacía en la traza

    def _within(self, max_pitch, max_yaw):
        """True si la cabeza está dentro del rango (o si aún no hay orientación disponible)."""
        if self.pose is None:
            return True
        yaw, pitch, _ = self.pose
        return abs(pitch) <= max_pitch and abs(yaw) <= max_yaw

    @property
    def eye_valid(self):
        """La apertura 2D del ojo es fiable con esta postura."""
        return self._within(self.max_pitch, self.max_yaw)

    @property
    def frontal(self):
        return self._within(self.frontal_max, self.frontal_max)

    def track_range(self, now):
        """Registra cada intervalo de postura fuera de rango (con su duración). Devuelve si es válida."""
        valid = self.eye_valid
        if not valid and self._out_since is None:
            self._out_since = now
        elif valid and self._out_since is not None:
            self.close_interval(now)
        return valid

    def close_interval(self, now):
        """Cierra el intervalo fuera de rango en curso (vuelta al rango, fin de sesión o recalibración)."""
        if self._out_since is not None:
            duration = now - self._out_since
            self.out_time += duration
            self._on_out_of_range(duration)
            self._out_since = None
