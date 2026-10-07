# fatigue_framework.py
import cv2
import numpy as np
import csv
import time
from datetime import datetime
from collections import deque
from fatigue_core import FaceMeshDetector
from glasses_detector import ROIGlassesDetector


class SubjectProfile:
    """Perfil facial neutro del sujeto: medianas de apertura ocular, bucal e IPD durante la calibración."""

    def __init__(self, calibration_frames=90):
        self.calibration_frames = calibration_frames
        self.reset()

    def reset(self):
        self._ear_samples = []
        self._mouth_samples = []
        self._ipd_samples = []
        self.open_ear_baseline = None
        self.neutral_mouth_ratio = None
        self.ipd_baseline = None

    @property
    def is_calibrated(self):
        return self.open_ear_baseline is not None

    @property
    def progress(self):
        return min(len(self._ear_samples) / float(self.calibration_frames), 1.0)

    def add_sample(self, ear, mouth_ratio, ipd):
        """Acumula un frame neutro; devuelve True en el frame en que se fija el perfil."""
        self._ear_samples.append(ear)
        self._mouth_samples.append(mouth_ratio)
        self._ipd_samples.append(ipd)
        if len(self._ear_samples) < self.calibration_frames:
            return False
        # La mediana descarta los parpadeos y gestos puntuales ocurridos durante la calibración
        self.open_ear_baseline = float(np.median(self._ear_samples))
        self.neutral_mouth_ratio = float(np.median(self._mouth_samples))
        self.ipd_baseline = float(np.median(self._ipd_samples))
        return True


class LandmarkStabilityGate:
    """
    Puerta de estabilidad de landmarks: el rostro debe estar quieto y sin deformaciones durante
    `required_frames` frames consecutivos antes de calibrar o analizar gafas.
    - Movimiento: máximo desplazamiento entre frames de landmarks rígidos, en unidades de la
      distancia entre ojos (independiente de la distancia a la cámara).
    - Deformación: desviación del puente nasal/comisuras respecto a la anatomía calibrada
      (ROIGlassesDetector.anatomy_deviation). FaceMesh deforma la malla cuando una mano tapa
      parcialmente la cara o las gafas se están colocando, aunque la cabeza no se mueva.
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


class FatigueMonitor:
    """
    Framework con interfaz UI/HUD profesional moderna y registro de telemetría.

    Pipeline secuencial (se repite completo con la tecla 'c' o automáticamente al cambiar de gafas):
      1. FASE_ROSTRO: perfil neutro del sujeto (apertura ocular, boca, IPD 3D) y anatomía para el ROI,
         solo con frames estables.
      2. FASE_GAFAS: tras 15 frames estables consecutivos, mediana del score de gafas en 30 frames
         estables y neutros; si la estabilidad se rompe, la recogida empieza de nuevo.
      3. FASE_MONITOREO: umbrales relativos al perfil del sujeto, métricas normalizadas por IPD 3D
         (invariantes a la distancia a la cámara y al giro lateral de la cabeza), con vigilancia del
         score de gafas en frames estables para recalibrar al ponerse/quitarse las gafas.
    """

    FASE_ROSTRO, FASE_GAFAS, FASE_MONITOREO = "rostro", "gafas", "monitoreo"

    # Frame "neutro" para analizar gafas: ojos abiertos y boca en reposo (sin pliegues de expresión)
    NEUTRAL_EAR_FACTOR = 0.85

    # Recalibración automática por cambio de gafas:
    # - Si el rostro se pierde > FACE_LOST_RECHECK_SECONDS (la mano tapa la cara al ponerse/quitarse
    #   las gafas), al recuperarlo se repite solo el paso 2; si la decisión cambia, se recalibra todo.
    # - Si la verificación no reúne frames neutros en GLASSES_RECHECK_TIMEOUT, se recalibra todo.
    FACE_LOST_RECHECK_SECONDS = 1.0
    GLASSES_RECHECK_TIMEOUT = 6.0   # incluye esperar 15 frames estables + 30 de análisis
    PERSISTENT_DEFORMATION_SECONDS = 5.0

    LEFT_EYE = [33, 160, 158, 133, 153, 144]
    RIGHT_EYE = [362, 385, 387, 263, 373, 380]

    MIN_BLINK_FRAMES = 2
    EYES_CLOSED_LIMIT = 20
    MICROSLEEP_FRAMES = 35
    BLINK_REFRACTORY_FRAMES = 8

    # Umbrales de apertura ocular relativos a open_ear_baseline: (cierre, reapertura, cierre profundo).
    # Con gafas FaceMesh localiza peor el párpado y la caída durante un parpadeo es menor. El
    # "cierre profundo" permite contar parpadeos rápidos que solo quedan 1 frame bajo el umbral.
    EAR_FACTORS = {False: (0.75, 0.81, 0.65),
                   True:  (0.82, 0.87, 0.72)}

    # Bostezo de dos niveles. Cada nivel exige que la boca supere su umbral de forma sostenida
    # (huecos de hasta YAWN_GAP_FRAMES frames no cortan la racha: tics de labios). Un episodio
    # dura mientras siga activa la racha del nivel 2 (el umbral más bajo).
    YAWN_TIER_EXAGGERATED, YAWN_TIER_MICRO = 0, 1
    YAWN_GAP_FRAMES = 2
    YAWN_COOLDOWN_SECONDS = 1.0

    # PERCLOS desacoplado de la boca: con la boca activa (habla, gesto, mini-bostezo) el estiramiento
    # facial baja la apertura ocular sin que los ojos se cierren; esos frames no entran en PERCLOS,
    # ni durante MOUTH_PERCLOS_HOLD_SECONDS después (los ojos tardan en relajarse)
    MOUTH_ACTIVE_DELTA = 0.08          # IPD sobre la boca neutra (~5 mm de separación de labios)
    MOUTH_PERCLOS_HOLD_SECONDS = 0.5

    IPD_SMOOTHING = 0.2       # EMA: la IPD es rígida, solo cambia con la distancia a la cámara

    def __init__(self, video_source=0,
                 yawn_factor=1.65, yawn_min_delta=0.25, yawn_min_seconds=0.5,
                 micro_yawn_factor=1.30, micro_yawn_min_delta=0.15, micro_yawn_min_seconds=0.35,
                 calibration_frames=90, window_seconds=60, perclos_min_seconds=15, trace_path=None):
        self.video_source = video_source
        # Umbral de cada nivel = max(factor * boca neutra, boca neutra + min_delta) en unidades de IPD.
        # El margen mínimo es necesario porque con labios cerrados la boca neutra es ~0 y
        # 1.3x de ~0 lo superaría cualquier sílaba.
        self.yawn_tiers = [(yawn_factor, yawn_min_delta, yawn_min_seconds),                    # exagerado
                           (micro_yawn_factor, micro_yawn_min_delta, micro_yawn_min_seconds)]  # micro/sutil
        self.yawn_min_delta = yawn_min_delta
        # CSV opcional con métricas por frame, para calibrar umbrales sobre los vídeos de validación
        self.trace_path = trace_path
        self._trace_file = None
        self._trace_writer = None

        self.detector = FaceMeshDetector(maxFaces=1, minDetectionCon=0.6, minTrackCon=0.6)
        # Umbrales empíricos: sin gafas 3.0-4.5 %, con gafas 10.0-12.5 % -> 7.0 % / 6.0 %, 10 frames
        self.glasses_detector = ROIGlassesDetector(on_threshold=7.0, off_threshold=6.0, switch_frames=10,
                                                   analysis_frames=30)
        self.profile = SubjectProfile(calibration_frames)
        self.stability = LandmarkStabilityGate(required_frames=15)

        self._on_blink = None
        self._on_yawn = None

        self.blink_count = 0
        self.yawn_count = 0                   # total (exagerados + micro)
        self.micro_yawn_count = 0

        self.fps_estimate = 30
        self.perclos_window_size = window_seconds * self.fps_estimate
        self.eye_closure_history = deque(maxlen=self.perclos_window_size)
        self.closed_frames_in_window = 0
        # Denominador mínimo: con pocos frames un solo parpadeo no puede inflar el PERCLOS
        self.perclos_min_samples = perclos_min_seconds * self.fps_estimate
        self.perclos_val = 0.0

        self.ipd = None
        self.has_glasses = False
        self._last_face_time = None
        self._recheck_prev_glasses = None     # decisión previa mientras se verifica tras perder el rostro
        self._recheck_deadline = 0.0
        self._last_microsleep_log = 0.0
        self._reset_tracking_state()

        self.log_filename = "fatigue_log.csv"
        self._init_csv_log()

    # ------------------------------------------------------------------ registro

    def _init_csv_log(self):
        try:
            with open(self.log_filename, mode='a', newline='') as f:
                writer = csv.writer(f)
                if f.tell() == 0:
                    writer.writerow(["Timestamp", "Evento", "PERCLOS_Pct", "Modo_Gafas", "EAR_Actual"])
        except Exception as e:
            print(f"[LOG ERROR] No se pudo crear CSV: {e}")

    def _log_event(self, event_type, perclos_val, has_glasses, ear_val):
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        modo_gafas = "ACTIVO" if has_glasses else "INACTIVO"
        try:
            with open(self.log_filename, mode='a', newline='') as f:
                writer = csv.writer(f)
                writer.writerow([timestamp, event_type, f"{perclos_val:.2f}", modo_gafas, f"{ear_val:.3f}"])
        except Exception as e:
            print(f"[LOG ERROR] Fallo al escribir evento: {e}")

    def _open_trace(self):
        if not self.trace_path:
            return
        self._trace_file = open(self.trace_path, mode='w', newline='')
        self._trace_writer = csv.writer(self._trace_file)
        self._trace_writer.writerow(["t", "ipd", "ear_left", "ear_right", "ear", "ear_baseline", "ear_close_thr",
                                     "eyes_closed", "mouth", "mouth_neutral", "yawn_thr", "micro_yawn_thr",
                                     "boca_activa", "gafas", "gafas_score", "fase", "estable", "movimiento",
                                     "deformacion", "parpadeos", "bostezos", "micro_bostezos"])

    def _write_trace(self, now, left_ear, right_ear, ear, mouth):
        if not self._trace_writer:
            return
        fmt = lambda v: "" if v is None else f"{v:.4f}"
        calibrated = self.profile.is_calibrated
        close_thr = self.profile.open_ear_baseline * self.EAR_FACTORS[self.has_glasses][0] if calibrated else None
        yawn_thr, micro_thr = self._yawn_thresholds() if calibrated else (None, None)
        self._trace_writer.writerow([f"{now:.3f}", fmt(self.ipd), fmt(left_ear), fmt(right_ear), fmt(ear),
                                     fmt(self.profile.open_ear_baseline), fmt(close_thr), int(self.eyes_closed),
                                     fmt(mouth), fmt(self.profile.neutral_mouth_ratio), fmt(yawn_thr), fmt(micro_thr),
                                     int(now < self.mouth_active_until), int(self.has_glasses),
                                     fmt(self.glasses_detector.score), self.phase,
                                     self.stability.stable_frames, fmt(self.stability.motion),
                                     fmt(self.stability.deformation), self.blink_count, self.yawn_count,
                                     self.micro_yawn_count])

    def on_blink(self, callback_function):
        self._on_blink = callback_function

    def on_yawn(self, callback_function):
        self._on_yawn = callback_function

    # ------------------------------------------------------------------ calibración

    def _reset_tracking_state(self):
        self.eyes_closed = False
        self.eyes_closed_frames = 0
        self.dip_min_ear = 0.0
        self.blink_refractory = 0
        self.yawn_run_start = [None, None]    # inicio de la racha sostenida de cada nivel
        self.yawn_run_gap = [0, 0]            # frames consecutivos por debajo del umbral de cada nivel
        self.yawn_counted = False
        self.yawn_exaggerated = False         # el episodio actual alcanzó el nivel 1
        self.yawn_cooldown_until = 0.0
        self.mouth_active_until = 0.0
        self._deformed_since = None

    @property
    def phase(self):
        if not self.profile.is_calibrated:
            return self.FASE_ROSTRO
        if not self.glasses_detector.is_decided:
            return self.FASE_GAFAS
        return self.FASE_MONITOREO

    def recalibrate(self, reason):
        """Descarta perfil y decisión de gafas y reinicia el pipeline desde el paso 1."""
        self.profile.reset()
        self.glasses_detector.reset()
        self.has_glasses = False
        self._recheck_prev_glasses = None
        self._reset_tracking_state()
        print(f"[CALIBRACION] Recalibrando perfil facial ({reason})")
        self._log_event("RECALIBRACION", self.perclos_val, self.has_glasses, 0.0)

    def _start_glasses_recheck(self, now, reason="rostro recuperado"):
        """Repite solo el paso 2 conservando el perfil; la decisión anterior sigue vigente mientras tanto."""
        self._recheck_prev_glasses = self.has_glasses
        self._recheck_deadline = now + self.GLASSES_RECHECK_TIMEOUT
        self.glasses_detector.start_recheck()
        self._reset_tracking_state()
        print(f"[GAFAS] Verificando gafas ({reason})")

    def _persistent_deformation(self, now):
        """True si el rostro lleva PERSISTENT_DEFORMATION_SECONDS deformado respecto a la anatomía
        calibrada, quieto y con los ojos abiertos. Con ojos cerrados nunca dispara: un cabeceo de
        sueño no debe interrumpir la alarma de micro-sueño."""
        gate = self.stability
        deformed = (gate.deformation is not None and gate.deformation > gate.max_deformation
                    and gate.motion <= gate.max_motion and not self.eyes_closed)
        if not deformed:
            self._deformed_since = None
            return False
        if self._deformed_since is None:
            self._deformed_since = now
        return now - self._deformed_since > self.PERSISTENT_DEFORMATION_SECONDS

    @property
    def is_rechecking_glasses(self):
        return self._recheck_prev_glasses is not None

    # ------------------------------------------------------------------ métricas normalizadas

    def _update_ipd(self, face3d):
        """IPD 3D entre los centros de los ojos (punto medio de las comisuras de cada ojo), suavizada."""
        left_center = (face3d[33] + face3d[133]) / 2.0
        right_center = (face3d[362] + face3d[263]) / 2.0
        raw_ipd = float(np.linalg.norm(left_center - right_center))
        self.ipd = raw_ipd if self.ipd is None else self.ipd + self.IPD_SMOOTHING * (raw_ipd - self.ipd)
        return self.ipd

    def _eye_opening(self, face, eye_indices, ipd):
        """EAR normalizado por IPD: apertura vertical media del ojo / IPD."""
        _, p2, p3, _, p5, p6 = [face[idx] for idx in eye_indices]
        vertical = (self.detector.findDistance(p2, p6) + self.detector.findDistance(p3, p5)) / 2.0
        return vertical / ipd if ipd > 0 else 0.0

    def _mouth_opening(self, face, ipd):
        """Apertura interna de los labios / IPD (el ancho de la boca cambia al bostezar; la IPD no)."""
        return self.detector.findDistance(face[13], face[14]) / ipd if ipd > 0 else 0.0

    def _is_neutral_frame(self, ear, mouth, ear_factor=None):
        """Ojos abiertos y boca en reposo. Tras un cambio de gafas el perfil puede estar desfasado,
        por eso verificación y vigilancia usan un criterio de ojo más laxo (solo 'no cerrado')."""
        ear_factor = self.NEUTRAL_EAR_FACTOR if ear_factor is None else ear_factor
        return (ear >= self.profile.open_ear_baseline * ear_factor
                and mouth <= self.profile.neutral_mouth_ratio + 0.5 * self.yawn_min_delta)

    def _yawn_thresholds(self):
        """Umbral de apertura bucal de cada nivel: [exagerado, micro]."""
        neutral = self.profile.neutral_mouth_ratio
        return [max(neutral * factor, neutral + min_delta) for factor, min_delta, _ in self.yawn_tiers]

    def _is_mouth_active(self, mouth, now):
        """Boca por encima del reposo (habla, gesto, mini-bostezo), con retención tras cerrarse."""
        if (mouth > self.profile.neutral_mouth_ratio + self.MOUTH_ACTIVE_DELTA
                or self.yawn_run_start[self.YAWN_TIER_MICRO] is not None):
            self.mouth_active_until = now + self.MOUTH_PERCLOS_HOLD_SECONDS
        return now < self.mouth_active_until

    # ------------------------------------------------------------------ detección de eventos

    def _update_perclos(self, is_closed):
        """Ventana deslizante con suma acumulada; el denominador nunca baja de perclos_min_samples."""
        if len(self.eye_closure_history) == self.eye_closure_history.maxlen:
            self.closed_frames_in_window -= self.eye_closure_history[0]
        self.eye_closure_history.append(1 if is_closed else 0)
        self.closed_frames_in_window += 1 if is_closed else 0

        denominator = max(len(self.eye_closure_history), self.perclos_min_samples)
        self.perclos_val = (self.closed_frames_in_window / float(denominator)) * 100.0
        return self.perclos_val

    def _update_yawn(self, mouth, now, ear):
        """Bostezo de dos niveles. Devuelve (bostezo_en_curso, bloquea_parpadeos).
        Se cuenta en cuanto se cumple cualquier nivel (aviso inmediato); el tipo (BOSTEZO o
        MICRO_BOSTEZO) se registra al terminar el episodio, porque un bostezo exagerado siempre
        cumple antes el nivel micro (umbral más bajo y duración más corta)."""
        if now < self.yawn_cooldown_until and self.yawn_run_start[self.YAWN_TIER_MICRO] is None:
            return False, True

        for tier, threshold in enumerate(self._yawn_thresholds()):
            if mouth > threshold:
                if self.yawn_run_start[tier] is None:
                    self.yawn_run_start[tier] = now
                self.yawn_run_gap[tier] = 0
            elif self.yawn_run_start[tier] is not None:
                self.yawn_run_gap[tier] += 1
                if self.yawn_run_gap[tier] > self.YAWN_GAP_FRAMES:
                    self.yawn_run_start[tier] = None

        sustained = [start is not None and now - start >= min_seconds
                     for start, (_, _, min_seconds) in zip(self.yawn_run_start, self.yawn_tiers)]
        if sustained[self.YAWN_TIER_EXAGGERATED]:
            self.yawn_exaggerated = True
        if any(sustained) and not self.yawn_counted:
            self.yawn_counted = True
            self.yawn_count += 1
            if self._on_yawn:
                self._on_yawn(self.yawn_count)

        if self.yawn_run_start[self.YAWN_TIER_MICRO] is None:      # fin del episodio
            if self.yawn_counted:
                if not self.yawn_exaggerated:
                    self.micro_yawn_count += 1
                self._log_event("BOSTEZO" if self.yawn_exaggerated else "MICRO_BOSTEZO",
                                self.perclos_val, self.has_glasses, ear)
                self.yawn_cooldown_until = now + self.YAWN_COOLDOWN_SECONDS
            self.yawn_run_start[self.YAWN_TIER_EXAGGERATED] = None
            self.yawn_counted = False
            self.yawn_exaggerated = False

        is_yawning = self.yawn_counted
        # Solo un bostezo confirmado bloquea parpadeos (hablar no debe bloquearlos)
        return is_yawning, is_yawning or now < self.yawn_cooldown_until

    def _update_eyes(self, ear, yawn_blocks_blinks, mouth_active, now):
        """Cierre ocular con histéresis, parpadeos, micro-sueño y PERCLOS. Devuelve micro-sueño activo.
        Con la boca activa el frame no entra en PERCLOS; el micro-sueño se sigue evaluando siempre
        (alguien puede dormirse con la boca abierta)."""
        baseline = self.profile.open_ear_baseline
        close_f, open_f, deep_f = self.EAR_FACTORS[self.has_glasses]
        if self.eyes_closed:
            self.eyes_closed = ear < baseline * open_f
        else:
            self.eyes_closed = ear < baseline * close_f

        if not mouth_active:
            self._update_perclos(self.eyes_closed)
        is_microsleep = False

        if self.eyes_closed:
            self.dip_min_ear = ear if self.eyes_closed_frames == 0 else min(self.dip_min_ear, ear)
            self.eyes_closed_frames += 1
            if self.eyes_closed_frames > self.MICROSLEEP_FRAMES:
                is_microsleep = True
                if now - self._last_microsleep_log > 1.0:
                    self._log_event("MICRO_SUENO", self.perclos_val, self.has_glasses, ear)
                    self._last_microsleep_log = now
        else:
            is_fast_blink = self.eyes_closed_frames == 1 and self.dip_min_ear < baseline * deep_f
            is_blink = ((self.eyes_closed_frames >= self.MIN_BLINK_FRAMES or is_fast_blink)
                        and self.eyes_closed_frames <= self.EYES_CLOSED_LIMIT)
            if is_blink and self.blink_refractory == 0 and not yawn_blocks_blinks:
                self.blink_count += 1
                self.blink_refractory = self.BLINK_REFRACTORY_FRAMES
                self._log_event("PARPADEO", self.perclos_val, self.has_glasses, ear)
                if self._on_blink:
                    self._on_blink(self.blink_count)
            self.eyes_closed_frames = 0

        if self.blink_refractory > 0:
            self.blink_refractory -= 1
        return is_microsleep

    def _process_face(self, face, face3d, frame, now):
        """Procesa un rostro detectado. Devuelve (micro-sueño activo, bostezo en curso)."""
        ipd = self._update_ipd(face3d)
        left_ear = self._eye_opening(face, self.LEFT_EYE, ipd)
        right_ear = self._eye_opening(face, self.RIGHT_EYE, ipd)
        # Promedio de ambos ojos: con max(), un reflejo en una lente enmascaraba el parpadeo del otro
        ear = (left_ear + right_ear) / 2.0
        mouth = self._mouth_opening(face, ipd)

        face_was_lost = (self._last_face_time is not None
                         and now - self._last_face_time > self.FACE_LOST_RECHECK_SECONDS)
        self._last_face_time = now
        if face_was_lost and self.phase == self.FASE_MONITOREO:
            self._start_glasses_recheck(now, "rostro recuperado")

        phase = self.phase
        not_closed_factor = self.EAR_FACTORS[self.has_glasses][0]
        is_stable = self.stability.update(face, self.glasses_detector.anatomy_deviation(face))

        if phase == self.FASE_ROSTRO:
            # Paso 1: perfil neutro + anatomía de puente nasal y comisuras, solo con frames estables
            # (manos en la cara o cabeza en movimiento falsearían la línea base y las ROIs)
            if not is_stable:
                self._write_trace(now, left_ear, right_ear, ear, mouth)
                return False, False
            self.glasses_detector.observe_anatomy(face)
            if self.profile.add_sample(ear, mouth, ipd):
                self.glasses_detector.lock_roi()
                print(f"[PASO 1] Perfil fijado: apertura ocular={self.profile.open_ear_baseline:.4f}, "
                      f"boca neutra={self.profile.neutral_mouth_ratio:.4f}, IPD 3D={self.profile.ipd_baseline:.1f}px")
                self._log_event("CALIBRACION", self.perclos_val, self.has_glasses, self.profile.open_ear_baseline)
            self._write_trace(now, left_ear, right_ear, ear, mouth)
            return False, False

        if phase == self.FASE_GAFAS:
            # Paso 2: tras 15 frames estables consecutivos, solo frames estables y neutros (sin parpadeo
            # ni boca abierta). Si la estabilidad se rompe (manos, gafas recolocándose), se descarta
            # lo acumulado: ningún frame de la transición entra en la mediana.
            ear_factor = not_closed_factor if self.is_rechecking_glasses else None
            if not is_stable:
                self.glasses_detector.discard_samples()
            elif (self.stability.is_ready and self._is_neutral_frame(ear, mouth, ear_factor)
                  and self.glasses_detector.analyze(frame, face)):
                if not self.is_rechecking_glasses:
                    self.has_glasses = self.glasses_detector.has_glasses
                    self._log_event("GAFAS_DETECTADAS" if self.has_glasses else "SIN_GAFAS",
                                    self.perclos_val, self.has_glasses, ear)
                elif self.glasses_detector.has_glasses != self._recheck_prev_glasses:
                    self.recalibrate("cambio de gafas detectado al recuperar el rostro")
                else:
                    self._recheck_prev_glasses = None
                    print("[GAFAS] Verificación: sin cambios, se mantiene el perfil")
            if self.is_rechecking_glasses and self.phase == self.FASE_GAFAS and now > self._recheck_deadline:
                self.recalibrate("verificación de gafas sin frames estables y neutros")
            self._write_trace(now, left_ear, right_ear, ear, mouth)
            return False, False

        # Paso 3: monitoreo adaptativo, con vigilancia de gafas en frames estables y neutros
        is_neutral = (is_stable and not self.eyes_closed
                      and self.yawn_run_start[self.YAWN_TIER_MICRO] is None
                      and now >= self.yawn_cooldown_until
                      and self._is_neutral_frame(ear, mouth, not_closed_factor))
        if self._persistent_deformation(now):
            # La anatomía cambió de forma estable (p. ej. gafas que desplazan el puente nasal en la malla):
            # sin frames estables la vigilancia no correría nunca, y el ROI fijado ya no corresponde a la
            # cara, así que se recalibra todo (una verificación tampoco reuniría frames estables)
            self.recalibrate("deformación persistente del rostro")
            self._write_trace(now, left_ear, right_ear, ear, mouth)
            return False, False
        if not is_neutral:
            self.glasses_detector.break_streak()   # "consecutivos" = frames estables y neutros seguidos
        elif self.glasses_detector.watch(frame, face):
            self.recalibrate("cambio de gafas detectado")
            self._write_trace(now, left_ear, right_ear, ear, mouth)
            return False, False

        is_yawning, yawn_blocks_blinks = self._update_yawn(mouth, now, ear)
        mouth_active = self._is_mouth_active(mouth, now)
        is_microsleep = self._update_eyes(ear, yawn_blocks_blinks, mouth_active, now)
        self._write_trace(now, left_ear, right_ear, ear, mouth)
        return is_microsleep, is_yawning

    # ------------------------------------------------------------------ interfaz

    def _draw_hud(self, img, perclos_val, has_glasses, is_microsleep, is_yawning):
        """Renderiza un panel lateral moderno con transparencias (HUD)."""
        overlay = img.copy()
        h, w, _ = img.shape

        # Panel lateral semi-transparente
        panel_w = 260
        cv2.rectangle(overlay, (15, 15), (panel_w, h - 15), (20, 20, 25), -1)

        # Mezclar transparencia (alpha = 0.75)
        cv2.addWeighted(overlay, 0.75, img, 0.25, 0, img)

        # Borde estético del panel
        cv2.rectangle(img, (15, 15), (panel_w, h - 15), (60, 60, 70), 1)

        # Título
        cv2.putText(img, "MONITOR DE FATIGA", (30, 45), cv2.FONT_HERSHEY_DUPLEX, 0.55, (255, 255, 255), 1)
        cv2.line(img, (30, 55), (panel_w - 15, 55), (100, 100, 110), 1)

        # Tarjeta 1: Parpadeos y Bostezos
        cv2.putText(img, "PARPADEOS", (30, 85), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (160, 160, 170), 1)
        cv2.putText(img, f"{self.blink_count}", (30, 115), cv2.FONT_HERSHEY_DUPLEX, 0.9, (255, 200, 0), 2)

        cv2.putText(img, "BOSTEZOS", (140, 85), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (160, 160, 170), 1)
        cv2.putText(img, f"{self.yawn_count}", (140, 115), cv2.FONT_HERSHEY_DUPLEX, 0.9, (0, 230, 255), 2)
        cv2.putText(img, f"micro {self.micro_yawn_count}", (180, 115), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (120, 120, 130), 1)

        cv2.line(img, (30, 135), (panel_w - 15, 135), (50, 50, 60), 1)

        # Tarjeta 2: Modo Gafas
        cv2.putText(img, "DETECTOR DE GAFAS", (30, 160), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (160, 160, 170), 1)
        if not self.glasses_detector.is_decided:
            status_gafas, color_gafas = "ANALIZANDO...", (0, 200, 255)
        else:
            status_gafas = "CON GAFAS" if has_glasses else "SIN GAFAS"
            color_gafas = (0, 255, 200) if has_glasses else (180, 180, 180)
        cv2.putText(img, status_gafas, (30, 185), cv2.FONT_HERSHEY_DUPLEX, 0.6, color_gafas, 1)
        if self.glasses_detector.score is not None:
            cv2.putText(img, f"score {self.glasses_detector.score:.1f}%", (160, 185), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (120, 120, 130), 1)

        cv2.line(img, (30, 205), (panel_w - 15, 205), (50, 50, 60), 1)

        # Tarjeta 3: Indicador PERCLOS con Barra de Progreso
        cv2.putText(img, "PERCLOS (FATIGA)", (30, 230), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (160, 160, 170), 1)
        if len(self.eye_closure_history) < self.perclos_min_samples:
            cv2.putText(img, "calibrando", (160, 230), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (120, 120, 130), 1)

        color_perclos = (0, 255, 120) if perclos_val < 15.0 else ((0, 200, 255) if perclos_val < 22.0 else (0, 0, 255))
        cv2.putText(img, f"{perclos_val:.1f}%", (30, 260), cv2.FONT_HERSHEY_DUPLEX, 0.8, color_perclos, 2)

        # Barra de progreso
        bar_x, bar_y, bar_w, bar_h = 30, 275, panel_w - 60, 10
        cv2.rectangle(img, (bar_x, bar_y), (bar_x + bar_w, bar_y + bar_h), (50, 50, 60), -1)
        fill_w = int((min(perclos_val, 100.0) / 100.0) * bar_w)
        cv2.rectangle(img, (bar_x, bar_y), (bar_x + fill_w, bar_y + bar_h), color_perclos, -1)

        # Alertas de Eventos Críticos
        if is_microsleep:
            cv2.rectangle(img, (30, 310), (panel_w - 15, 350), (0, 0, 200), -1)
            cv2.putText(img, "! MICRO-SUENO !", (40, 335), cv2.FONT_HERSHEY_DUPLEX, 0.55, (255, 255, 255), 1)
        elif is_yawning:
            cv2.rectangle(img, (30, 310), (panel_w - 15, 350), (0, 150, 255), -1)
            cv2.putText(img, "BOSTEZANDO...", (45, 335), cv2.FONT_HERSHEY_DUPLEX, 0.55, (255, 255, 255), 1)

        cv2.putText(img, "[C] recalibrar  [Q] salir", (30, h - 30), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (120, 120, 130), 1)

    def _draw_calibration_overlay(self, img, title, progress):
        """Banner de la fase de calibración con barra de progreso, a la derecha del panel lateral."""
        h, w, _ = img.shape
        x0, x1, y0, y1 = 275, w - 15, h - 100, h - 15
        if x1 - x0 < 250:
            x0 = 15

        overlay = img.copy()
        cv2.rectangle(overlay, (x0, y0), (x1, y1), (20, 20, 25), -1)
        cv2.addWeighted(overlay, 0.8, img, 0.2, 0, img)
        cv2.rectangle(img, (x0, y0), (x1, y1), (0, 200, 255), 1)

        for text, y, scale in [(title, y0 + 28, 0.55), ("MIRA AL FRENTE", y0 + 52, 0.5)]:
            (text_w, _), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_DUPLEX, scale, 1)
            cv2.putText(img, text, (x0 + (x1 - x0 - text_w) // 2, y), cv2.FONT_HERSHEY_DUPLEX, scale, (255, 255, 255), 1)

        bar_x0, bar_x1, bar_y = x0 + 20, x1 - 20, y1 - 22
        cv2.rectangle(img, (bar_x0, bar_y), (bar_x1, bar_y + 8), (50, 50, 60), -1)
        cv2.rectangle(img, (bar_x0, bar_y), (bar_x0 + int((bar_x1 - bar_x0) * progress), bar_y + 8), (0, 200, 255), -1)

    # ------------------------------------------------------------------ bucle principal

    def start(self):
        cap = cv2.VideoCapture(self.video_source)
        self._open_trace()

        print(f"Framework Iniciado con HUD. Telemetria guardandose en '{self.log_filename}'.")

        while True:
            success, img = cap.read()
            if not success:
                break

            clean_frame = img.copy()
            img, faces = self.detector.findFaceMesh(img, draw=False)

            is_microsleep_active, is_yawning_active = False, False
            if faces:
                is_microsleep_active, is_yawning_active = self._process_face(
                    faces[0], self.detector.faces3d[0], clean_frame, time.time())
            else:
                self.stability.reset()   # al volver el rostro se exigen de nuevo 15 frames estables

            # Renderizado del HUD Limpio
            self._draw_hud(img, self.perclos_val, self.has_glasses, is_microsleep_active, is_yawning_active)
            phase = self.phase
            if phase == self.FASE_ROSTRO:
                self._draw_calibration_overlay(img, "PASO 1/2: ANALIZANDO ROSTRO...", self.profile.progress)
            elif phase == self.FASE_GAFAS:
                if not self.stability.is_ready:
                    title = "QUIETO: ESTABILIZANDO ROSTRO..."
                    progress = self.stability.stable_frames / float(self.stability.required_frames)
                else:
                    title = "VERIFICANDO GAFAS..." if self.is_rechecking_glasses else "PASO 2/2: DETECTANDO GAFAS..."
                    progress = self.glasses_detector.progress
                self._draw_calibration_overlay(img, title, progress)

            cv2.imshow("Fatigue Framework Monitor", img)
            key = cv2.waitKey(1) & 0xFF
            if key == ord('q'):
                break
            if key == ord('c'):
                self.recalibrate("manual")

        if self._trace_file:
            self._trace_file.close()
        cap.release()
        cv2.destroyAllWindows()
