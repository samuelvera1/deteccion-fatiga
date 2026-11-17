# fatigue_pose.py
"""Orientación de la cabeza respecto a la postura de calibración, velocidad de giro y tiempo fuera de rango."""
import statistics
from collections import deque

import numpy as np

import fatigue_geometry


def mean_rotation(axes_list):
    """Ejes medios (media de las matrices reortonormalizada con SVD), o None si falla."""
    try:
        u, _, vt = np.linalg.svd(np.mean(np.array(axes_list), axis=0))
        return u @ vt
    except np.linalg.LinAlgError:
        return None


class HeadPoseTracker:
    """Estado de la postura de la cabeza.

    max_pitch / max_yaw: rango válido para las métricas del ojo. max_pitch es un número (igual hacia arriba y hacia
    abajo) o (abajo, arriba): pitch positivo = cabeza hacia abajo. frontal_max: rango de la puerta de estabilidad.
    on_out_of_range(duración) se llama al terminar cada intervalo fuera de rango."""

    def __init__(self, max_pitch, max_yaw, frontal_max, on_out_of_range):
        down, up = max_pitch if isinstance(max_pitch, (tuple, list)) else (max_pitch, max_pitch)
        self.max_pitch_down, self.max_pitch_up = float(down), float(up)
        self.max_yaw, self.frontal_max = max_yaw, frontal_max
        self._on_out_of_range = on_out_of_range
        self.ref = None                       # ejes de la cabeza en la calibración (postura frontal)
        self.ref0 = None                      # alias de ref (la calibración original)
        self.temp_ref = None                  # E14b: referencia temporal tras un cambio de postura sostenido
        self.temp_pose = None                 # (yaw, pitch, roll) respecto a la referencia temporal
        self.samples = []                     # ejes de los frames de calibración
        self.last_axes = None
        self._last_axes_t = None
        self.speed = None                     # velocidad de giro de la cabeza (°/s) en el último frame
        self.pose = None                      # (yaw, pitch, roll) en grados respecto a la calibración
        self._out_since = None                # inicio del intervalo de postura fuera de rango en curso
        self.out_time = 0.0                   # tiempo total (s) de monitoreo con postura fuera de rango

    def reset_reference(self):
        """Descarta la referencia y las muestras (recalibración)."""
        self.ref, self.ref0, self.samples, self.pose = None, None, [], None
        self.temp_ref, self.temp_pose = None, None

    def rebase(self, ref):
        """E14b: referencia temporal (ejes ortonormales). Solo se usa mientras la postura esté fuera del rango de la
        calibración; dentro de él manda la calibración (con E14 la referencia nueva quedaba fija y sesgaba el ojo
        abierto al volver a una postura normal: video de posturas 20261116_223101)."""
        self.temp_ref = ref
        self.temp_pose = (0.0, 0.0, 0.0)

    def angles_vs_calibration(self, axes):
        """(yaw, pitch) en grados de unos ejes respecto a la referencia de la calibración original."""
        if self.ref0 is None:
            return None
        r = axes @ self.ref0.T
        return (float(np.degrees(np.arctan2(r[0, 2], r[2, 2]))),
                float(np.degrees(np.arcsin(np.clip(-r[1, 2], -1.0, 1.0)))))

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
            self.pose = self.temp_pose = None
            return
        self.pose = _relative_angles(axes, self.ref)
        self.temp_pose = None if self.temp_ref is None else _relative_angles(axes, self.temp_ref)

    def lock_reference(self):
        """Postura de referencia = ejes medios de los frames de calibración, reortonormalizados (SVD)."""
        if not self.samples:
            return
        self.ref = mean_rotation(self.samples)    # None si falla: la orientación queda vacía en la traza
        self.ref0 = self.ref

    @property
    def camera_angles(self):
        """(yaw, pitch) en grados de la postura de calibración respecto al eje de la cámara: cuánto está girada la
        cara frente a la cámara cuando la persona mira la pantalla como de costumbre (0, 0 = cámara de frente;
        el signo depende de si la imagen está espejada). Aproximado: la z de MediaPipe es estimada por la red.
        No interviene en ninguna medida: los rangos de postura son relativos a la calibración. None sin referencia."""
        if self.ref0 is None:
            return None
        r = self.ref0
        return (float(np.degrees(np.arctan2(r[0, 2], r[2, 2]))),
                float(np.degrees(np.arcsin(np.clip(-r[1, 2], -1.0, 1.0)))))

    def _within(self, max_down, max_up, max_yaw, pose=None):
        """True si la cabeza está dentro del rango (o si aún no hay orientación disponible)."""
        pose = self.pose if pose is None else pose
        if pose is None:
            return True
        yaw, pitch, _ = pose
        return -max_up <= pitch <= max_down and abs(yaw) <= max_yaw

    @property
    def in_calibration_range(self):
        return self._within(self.max_pitch_down, self.max_pitch_up, self.max_yaw)

    @property
    def using_temporary(self):
        """E14b: fuera del rango de la calibración pero dentro del de la referencia temporal."""
        return (not self.in_calibration_range and self.temp_pose is not None
                and self._within(self.max_pitch_down, self.max_pitch_up, self.max_yaw, self.temp_pose))

    @property
    def eye_valid(self):
        """La apertura 2D del ojo es fiable con esta postura (respecto a la calibración o a la referencia temporal)."""
        return self.in_calibration_range or self.using_temporary

    @property
    def frontal(self):
        return self._within(self.frontal_max, self.frontal_max, self.frontal_max)

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


def _relative_angles(axes, ref):
    """(yaw, pitch, roll) en grados de unos ejes respecto a una referencia (convención de HeadPoseTracker.update)."""
    r = axes @ ref.T
    return (float(np.degrees(np.arctan2(r[0, 2], r[2, 2]))),
            float(np.degrees(np.arcsin(np.clip(-r[1, 2], -1.0, 1.0)))),
            float(np.degrees(np.arctan2(r[1, 0], r[1, 1]))))


class SustainedPostureRebaser:
    """E14/E14b: si la postura sale de rango y se queda quieta `hold_s` s en la nueva posición (desviación típica del giro y
    del cabeceo <= `max_std`°), rehace la referencia de postura con los ejes medios de ese tramo, siempre que la nueva
    postura quede dentro de `cap_pitch`/`cap_yaw` respecto a la calibración original (más allá la malla no es fiable,
    E10). Devuelve la nueva apertura de ojo abierto: mediana del tramo sin parpadeos (cuadros >= `blink_floor` x su
    percentil 90). La referencia es temporal (HeadPoseTracker.rebase): al volver al rango de la calibración manda la
    calibración. Simulado en UTA-RLDD, Eyeblink8 y el video de posturas antes de implementarlo (E14 y E14b)."""

    def __init__(self, hold_s=20.0, max_std=4.0, cap_pitch=30.0, cap_yaw=40.0, blink_floor=0.75):
        self.hold_s, self.max_std = hold_s, max_std
        self.cap_pitch, self.cap_yaw, self.blink_floor = cap_pitch, cap_yaw, blink_floor
        self._window = deque()               # (t, yaw, pitch, ejes, apertura) de los cuadros seguidos fuera de rango
        self.count = 0

    def reset(self):
        self._window.clear()

    def update(self, head, now, valid, ear):
        """Cuadro de monitoreo con rostro. Devuelve la nueva apertura de ojo abierto si rehízo la referencia."""
        if valid or head.pose is None or head.last_axes is None or ear is None or head.ref0 is None:
            self._window.clear()
            return None
        self._window.append((now, head.pose[0], head.pose[1], head.last_axes, ear))
        while self._window and self._window[0][0] < now - self.hold_s:
            self._window.popleft()
        if self._window[-1][0] - self._window[0][0] < self.hold_s - 0.5:
            return None
        yaws = [w[1] for w in self._window]
        pitches = [w[2] for w in self._window]
        if statistics.pstdev(yaws) > self.max_std or statistics.pstdev(pitches) > self.max_std:
            return None
        ref = mean_rotation([w[3] for w in self._window])
        if ref is None:
            return None
        yaw0, pitch0 = head.angles_vs_calibration(ref)
        if abs(pitch0) > self.cap_pitch or abs(yaw0) > self.cap_yaw:
            return None
        ears = sorted(w[4] for w in self._window)
        p90 = ears[int(0.9 * (len(ears) - 1))]
        open_ear = float(np.median([e for e in ears if e >= self.blink_floor * p90]))
        head.rebase(ref)
        self._window.clear()
        self.count += 1
        return open_ear
