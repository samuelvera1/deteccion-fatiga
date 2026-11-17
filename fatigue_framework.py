# fatigue_framework.py
"""Monitor de fatiga: orquesta la captura, la calibración y los detectores (ojos, bostezos, postura)."""
import time

import cv2
import numpy as np

import calibration_marks
import display
import fatigue_audio
import fatigue_geometry
import fatigue_hud
import fatigue_report
from fatigue_alert import FatigueAlert, MESSAGES, NORMAL
from fatigue_config import Thresholds
from fatigue_core import FaceMeshDetector
from fatigue_eyes import EyeEventDetector
from fatigue_perclos import PerclosWindow
from fatigue_pose import HeadPoseTracker
from fatigue_profile import LandmarkStabilityGate, SubjectProfile, SustainedClosureFilter
from fatigue_yawn import YawnDetector
from kss import KSSPrompter
from session_recorder import FrameRecorder, SessionRecorder


class FatigueMonitor(Thresholds):
    """
    Framework con interfaz UI/HUD profesional moderna y registro de telemetría.

    Pipeline secuencial (se repite completo con la tecla 'c'):
      1. FASE_ROSTRO: perfil neutro del sujeto (apertura ocular, boca, IPD 3D, postura frontal), solo con
         frames estables y de frente.
      2. FASE_CIERRE: el sujeto cierra los ojos hasta oír un pitido -> nivel de ojo cerrado (para el P80).
      2b. FASE_REAPERTURA: espera a que abra los ojos antes de empezar a contar.
      3. FASE_MONITOREO: parpadeos (referencia local), PERCLOS P80 y micro-sueño (cierre >= 80 %),
         bostezos; métricas normalizadas por IPD 3D.

    Calibración manual (vídeos con marcas de revisar.py --video, ver calibration_marks.py): en lugar de
    los pasos 1-2b, el perfil se calcula con los tramos neutro y de ojos cerrados que marcó el
    investigador (FASE_MARCAS) y el monitoreo empieza exactamente en el frame de inicio de la prueba.

    Gafas: la condición (con/sin gafas) la DECLARA el investigador (--condicion). El detector automático
    por bordes se retiró: su score dependía de la distancia a la cámara (con gafas ~5 a 50-70 px de IPD
    frente a 8-17 a >= 80 px) y de la persona (sujetos sin gafas de hasta 11.5), y las métricas ya no
    dependen de las gafas porque el ojo cerrado se calibra en cada sesión. Si el participante se pone o
    se quita las gafas a mitad de sesión, hay que recalibrar con la tecla C (el ojo cerrado cambia: 19 %
    frente a 54 % del abierto en S01).
    """

    FASE_ROSTRO, FASE_CIERRE, FASE_REAPERTURA, FASE_MONITOREO = "rostro", "cierre", "reapertura", "monitoreo"
    FASE_MARCAS = "calibracion_manual"
    # En vivo, una lectura fallida de la cámara suele ser pasajera: otro programa la tomó un momento (sesión
    # 20261116_194404, la app Eyeblink) o el driver se reinició. Se reintenta, reabriéndola cada CAMERA_REOPEN_S, hasta
    # CAMERA_STALL_S antes de terminar. El hueco no falsea PERCLOS: cada cuadro pesa como mucho 0,2 s (fatigue_perclos).
    CAMERA_STALL_S = 10.0
    CAMERA_REOPEN_S = 2.5

    def __init__(self, video_source=0, subject_id="anonimo", condition=None, save_trace=True, sessions_dir="sesiones",
                 subject_code=None, manual_marks=None, record=False, kss_interval_min=None, alert_sound=True,
                 refine_landmarks=True, capture_size=(1280, 720), headless=False,
                 yawn_factor=1.65, yawn_min_delta=0.25, yawn_min_seconds=0.5,
                 micro_yawn_factor=1.30, micro_yawn_min_delta=0.15, micro_yawn_min_seconds=0.35,
                 calibration_frames=90, window_seconds=60, perclos_min_seconds=15):
        self.video_source = video_source
        self.headless = headless              # sin ventana ni panel (análisis por lotes): mismas mediciones
        # Cada ejecución de start() crea una sesión en sessions_dir con metadatos reproducibles
        self.subject_id = subject_id
        self.condition = condition            # condición experimental declarada (p. ej. con_gafas)
        self.subject_code = subject_code      # código anónimo (S01...) guardado junto al nombre
        # Marcas de calibración manual del vídeo (calibration_marks), ya validadas; None = automática
        self.manual_marks = manual_marks
        # Sesión en vivo con grabación (--grabar): para anotarla después y evaluar el sistema en tiempo real
        self.record = record
        self.recorder = None
        # Escala de somnolencia de Karolinska durante la sesión en vivo (referencia para validar la fatiga)
        self.kss = KSSPrompter(kss_interval_min) if kss_interval_min else None
        # Nivel de fatiga y alertas en vivo (fatigue_alert.py); el sonido se desactiva al analizar vídeos
        self.alert = FatigueAlert(window_seconds, sound=alert_sound)
        self._manual_pending = manual_marks is not None
        self.test_start_s = None              # inicio del monitoreo (s), para el resumen
        self.save_trace = save_trace
        # Resolución pedida a la cámara (None = la nativa). A 640x480 la cara lejana ocupa pocos píxeles: con
        # IPD de 50-70 px la montura de las gafas casi no deja bordes (sesión 20261006_212220). Si la cámara
        # no la soporta se usa la que entregue; la real queda registrada en metadata.json.
        self.capture_size = capture_size
        self.sessions_dir = sessions_dir
        self.session = None
        self.window_seconds = window_seconds
        self.perclos_min_seconds = perclos_min_seconds

        # refine_landmarks=True por defecto: sin él, la malla apenas registra el cierre del párpado (sesiones
        # 20261006_001819 / _002122: ojos cerrados de verdad medidos al 67-77 % sin gafas y 80-88 % con gafas)
        self.detector = FaceMeshDetector(maxFaces=1, minDetectionCon=0.6, minTrackCon=0.6,
                                         refineLandmarks=refine_landmarks)
        self.profile = SubjectProfile(calibration_frames)
        self.stability = LandmarkStabilityGate(required_frames=15)
        self.yawn = YawnDetector(self.profile,
                                 [(yawn_factor, yawn_min_delta, yawn_min_seconds),                    # exagerado
                                  (micro_yawn_factor, micro_yawn_min_delta, micro_yawn_min_seconds)],  # micro/sutil
                                 self._log_detector_event)

        self._last_shape = None
        self.head = HeadPoseTracker((self.POSE_MAX_PITCH_DOWN, self.POSE_MAX_PITCH_UP), self.POSE_MAX_YAW,
                                    self.POSE_STABLE_MAX, self._log_pose_out_of_range)

        self.fps_estimate = 30                # solo para los parámetros de parpadeo, aún en frames
        # PERCLOS ponderado por tiempo real (independiente de los fps): (t, dt, cerrado) en la ventana.
        # Denominador mínimo perclos_min_seconds: al inicio un solo parpadeo no puede inflar el PERCLOS.
        self.perclos = PerclosWindow(window_seconds, perclos_min_seconds)
        self.hud = fatigue_hud.HudRenderer()
        self.eyes = EyeEventDetector(self.profile, self.perclos, self.head, self._log_detector_event)

        self.ipd = None
        # Gafas según la condición declarada: True / False, o None si no se declaró
        self.has_glasses = self._declared_glasses(condition)
        self._closed_run = SustainedClosureFilter(self.CLOSED_MIN_SUSTAINED_S, self.CLOSED_GAP_FRAMES)
        self._reset_tracking_state()

        self.recalibration_count = 0
        self.frames_total = 0
        self.frames_with_face = 0
        self._now = 0.0                       # tiempo de la sesión (s): reloj del vídeo o del sistema

    # ------------------------------------------------------------------ registro

    def parameters(self):
        """Todos los parámetros del método, para los metadatos de la sesión (sección de métodos)."""
        return fatigue_report.session_parameters(self)

    def _log_event(self, event_type, perclos_val, has_glasses, ear_val, duration=None, end_time=None, value=None):
        """end_time: instante en que terminó el evento si no es el frame actual (t_s = fin del evento)."""
        if self.session:
            self.session.log_event(self._now if end_time is None else end_time, event_type, self.phase,
                                   perclos_val, has_glasses, ear_val, duration, value)

    def _write_trace(self, now, left_ear, right_ear, ear, mouth):
        if self.session and self.session.save_trace:
            self.session.trace(fatigue_report.trace_row(self, now, left_ear, right_ear, ear, mouth))

    @property
    def perclos_val(self):
        return self.perclos.value

    def _log_pose_out_of_range(self, duration):
        self._log_event("POSTURA_FUERA_DE_RANGO", self.perclos_val, self.has_glasses, 0.0, duration)

    def on_blink(self, callback_function):
        self.eyes.on_blink = callback_function

    def on_yawn(self, callback_function):
        self.yawn.on_yawn = callback_function

    def _log_detector_event(self, event_type, ear, duration, end_time=None):
        self._log_event(event_type, self.perclos_val, self.has_glasses, ear, duration, end_time=end_time)

    # ------------------------------------------------------------------ calibración

    def _reset_tracking_state(self):
        self.eyes.reset()
        self.yawn.reset()
        self._closed_run.reset()
        self._closed_phase_started = None
        self._closed_attempt = 1              # intento actual del paso de ojos cerrados
        self._closed_retry_until = None       # fin de la pausa antes del siguiente intento
        self._reopen_streak = 0
        self._monitoring_started = False

    @property
    def phase(self):
        if self._manual_pending:
            return self.FASE_MARCAS
        if not self.profile.is_calibrated:
            return self.FASE_ROSTRO
        if not self.profile.is_closed_calibrated:
            return self.FASE_CIERRE
        if not self._monitoring_started:
            return self.FASE_REAPERTURA
        return self.FASE_MONITOREO

    @property
    def closure_reliable(self):
        """El % de cierre (y con él PERCLOS, micro-sueño, parpadeos prolongados y alertas) solo es fiable si el
        nivel de ojo cerrado se midió y la malla registró el cierre del párpado. Con el valor de reserva, el
        ojo cerrado real queda muy por encima del supuesto y el cierre no llega al 80 % (sesión
        20261017_111619: ojos casi abiertos durante el paso de cierre, cierre máximo 0.56, PERCLOS 0)."""
        p = self.profile
        if not p.closed_level_measured:
            return False
        lowest = p.closed_phase_min_ratio
        return lowest is None or lowest <= self.CLOSURE_VISIBLE_MAX_RATIO

    def recalibrate(self, reason, full=False):
        """Descarta el perfil y reinicia el pipeline desde el paso 1.
        full=True (manual, tecla C): repite también el paso de ojos cerrados (necesario si el participante se
        pone o se quita las gafas). full=False conserva la proporción de ojo cerrado medida."""
        self.profile.reset(keep_closed_ratio=not full)
        self._manual_pending = False          # tras recalibrar se usa la calibración automática
        self.head.close_interval(self._now)
        self.head.reset_reference()
        self._reset_tracking_state()
        self.recalibration_count += 1
        print(f"[CALIBRACION] Recalibrando perfil facial ({reason})")
        self._log_event("RECALIBRACION", self.perclos_val, self.has_glasses, 0.0)

    def _ask_kss(self, moment):
        self.kss.ask(moment, self._now)
        self._log_event("KSS_PREGUNTA", self.perclos_val, self.has_glasses, 0.0)

    def _answer_kss(self, value):
        response = self.kss.answer(value, self._now)
        # Duracion_s = latencia de la respuesta; Valor = puntaje KSS (1-9)
        self._log_event("KSS", self.perclos_val, self.has_glasses, 0.0, response["latencia_s"], value=value)
        print(f"[KSS] {value} ({response['momento']}, t = {response['t_respuesta']:.1f} s)")

    def _start_monitoring(self, now):
        self._monitoring_started = True
        if self.test_start_s is None:
            self.test_start_s = now
        print(f"[MONITOREO] Empieza el conteo en t = {now:.2f} s")

    def _finish_manual_calibration(self, now):
        """Al llegar al frame de inicio de la prueba: fija el perfil con los tramos marcados. Si en algún
        tramo no se detectó el rostro en suficientes frames, se pasa a la calibración automática."""
        self._manual_pending = False
        p = self.profile
        if (p.n_open_samples < calibration_marks.MIN_NEUTRAL_FRAMES
                or p.n_closed_samples < calibration_marks.MIN_CLOSED_FRAMES):
            print(f"[AVISO] Calibración manual inválida: rostro detectado en {p.n_open_samples} frames del tramo "
                  f"neutro y {p.n_closed_samples} del de ojos cerrados (mínimo {calibration_marks.MIN_NEUTRAL_FRAMES}"
                  f" y {calibration_marks.MIN_CLOSED_FRAMES}). Se calibra automáticamente desde aquí.")
            self.profile.reset()
            self.head.samples = []
            self._log_event("CALIBRACION_MANUAL_FALLIDA", self.perclos_val, self.has_glasses, 0.0)
            return
        p.finish_profile()
        p.finish_manual_closed()
        self.head.lock_reference()
        print(f"[CALIBRACION MANUAL] Ojo abierto={p.open_ear_baseline:.4f} ({p.n_open_samples} frames), "
              f"ojo cerrado={p.closed_ear_level:.4f} ({p.closed_ratio:.0%} del abierto, {p.n_closed_samples} frames), "
              f"boca neutra={p.neutral_mouth_ratio:.4f}")
        self._log_event("CALIBRACION_MANUAL", self.perclos_val, self.has_glasses, p.open_ear_baseline)
        self._warn_if_closure_not_visible()
        self._start_monitoring(now)

    def _warn_if_closure_not_visible(self):
        lowest = self.profile.closed_phase_min_ratio
        if lowest is not None and lowest > self.CLOSURE_VISIBLE_MAX_RATIO:
            print(f"[AVISO] Con los ojos cerrados la malla solo bajó al {lowest:.0%} de la apertura normal: "
                  f"el cierre del párpado apenas se registra. PERCLOS y micro-sueño NO serán fiables en "
                  f"esta sesión (revisa luz, distancia, gafas o refine_landmarks).")

    @staticmethod
    def _declared_glasses(condition):
        """Interpreta la condición declarada: 'con_gafas' -> True, 'sin_gafas' -> False, otra -> None."""
        text = (condition or "").lower().replace(" ", "_")
        if "sin" in text and "gafas" in text:
            return False
        if "con" in text and "gafas" in text:
            return True
        return None

    def _update_ipd(self, face3d):
        """IPD 3D entre los centros de los ojos (punto medio de las comisuras de cada ojo), suavizada."""
        left_center = (face3d[33] + face3d[133]) / 2.0
        right_center = (face3d[362] + face3d[263]) / 2.0
        raw_ipd = float(np.linalg.norm(left_center - right_center))
        self.ipd = raw_ipd if self.ipd is None else self.ipd + self.IPD_SMOOTHING * (raw_ipd - self.ipd)
        return self.ipd

    # ------------------------------------------------------------------ detección de eventos

    def _process_face(self, face, face3d, frame, now):
        """Procesa un rostro detectado. Devuelve (micro-sueño activo, bostezo en curso)."""
        ipd = self._update_ipd(face3d)
        self.head.update(face3d, now)
        left_ear = fatigue_geometry.eye_opening(face, self.LEFT_EYE, ipd)
        right_ear = fatigue_geometry.eye_opening(face, self.RIGHT_EYE, ipd)
        # Promedio de ambos ojos: con max(), un reflejo en una lente enmascaraba el parpadeo del otro
        ear = (left_ear + right_ear) / 2.0
        mouth = fatigue_geometry.mouth_opening(face, ipd)
        self._last_shape = shape = fatigue_geometry.mouth_shape(face, ipd)

        phase = self.phase
        # Puerta de estabilidad: cabeza quieta y, si ya hay orientación, de frente
        is_stable = self.stability.update(face, 0.0 if self.head.frontal else float("inf"))

        if phase == self.FASE_MARCAS:
            # Calibración manual: se acumulan los frames de los tramos marcados por el investigador
            # (sin puerta de estabilidad: el tramo lo eligió una persona; la mediana absorbe frames sueltos)
            n0, n1, c0, c1, _ = calibration_marks.frame_ranges(self.manual_marks)
            index = self.frames_total - 1
            if n0 <= index <= n1:
                self.profile.add_sample(ear, mouth, ipd, shape, auto_finish=False)
                self.head.add_calibration_sample()
            elif c0 <= index <= c1:
                self.profile.add_manual_closed_sample(ear)
            self._write_trace(now, left_ear, right_ear, ear, mouth)
            return False, False

        if phase == self.FASE_ROSTRO:
            # Paso 1: perfil neutro y postura de referencia, solo con frames estables
            # (manos en la cara o cabeza en movimiento falsearían la línea base)
            if not is_stable:
                self._write_trace(now, left_ear, right_ear, ear, mouth)
                return False, False
            self.head.add_calibration_sample()
            if self.profile.add_sample(ear, mouth, ipd, shape):
                self.head.lock_reference()
                print(f"[PASO 1] Perfil fijado: apertura ocular={self.profile.open_ear_baseline:.4f}, "
                      f"boca neutra={self.profile.neutral_mouth_ratio:.4f}, IPD 3D={self.profile.ipd_baseline:.1f}px")
                if self.profile.closed_level_reused:
                    print(f"[PASO 2] Ojo cerrado reutilizado de la calibración inicial: "
                          f"{self.profile.closed_ratio:.0%} del ojo abierto (sin repetir el pitido)")
                self._log_event("CALIBRACION", self.perclos_val, self.has_glasses, self.profile.open_ear_baseline)
            self._write_trace(now, left_ear, right_ear, ear, mouth)
            return False, False

        if phase == self.FASE_CIERRE:
            # Paso 2: nivel de ojo cerrado del sujeto (cierra los ojos hasta oír el pitido)
            if self._closed_retry_until is not None:
                # pausa entre intentos: la persona abre los ojos, lee el aviso y se prepara
                if now < self._closed_retry_until:
                    self._write_trace(now, left_ear, right_ear, ear, mouth)
                    return False, False
                self._closed_retry_until, self._closed_phase_started = None, now
            if self._closed_phase_started is None:
                self._closed_phase_started = now
            self.profile.observe_closed_phase(ear)
            below = ear < self.profile.open_ear_baseline * self.CLOSED_CAPTURE_FACTOR
            done = False
            for sample in self._closed_run.update(ear, below, now):
                done = self.profile.add_closed_sample(sample)
                if done:
                    break
            timed_out = not done and now - self._closed_phase_started > self.CLOSED_CALIBRATION_TIMEOUT
            if (timed_out and not self.profile.closed_samples_enough() and not self._is_video_file()
                    and self._closed_attempt < self.CLOSED_MAX_ATTEMPTS):
                # En vivo, sin ojos cerrados detectados: se repite el paso en vez de usar el valor de reserva
                # (con la reserva, PERCLOS, micro-sueño y alertas no funcionan; sesión 20261017_111619)
                self._closed_attempt += 1
                self.profile.restart_closed_phase()
                self._closed_run.reset()
                self._closed_retry_until = now + self.CLOSED_RETRY_PAUSE
                fatigue_audio.retry_beep()
                print(f"[PASO 2] No se detectaron los ojos cerrados: intento {self._closed_attempt} de "
                      f"{self.CLOSED_MAX_ATTEMPTS} en {self.CLOSED_RETRY_PAUSE:.0f} s")
                self._log_event("CALIBRACION_CIERRE_REINTENTO", self.perclos_val, self.has_glasses, 0.0,
                                value=self._closed_attempt)
                self._write_trace(now, left_ear, right_ear, ear, mouth)
                return False, False
            if timed_out:
                self.profile.finish_closed_on_timeout(self.CLOSED_FALLBACK_RATIO)
                done = True
                if not self.profile.closed_level_measured:
                    print(f"[AVISO] No se detectaron los ojos cerrados en {self.CLOSED_CALIBRATION_TIMEOUT:.0f} s: se usa "
                          f"el nivel de reserva ({self.CLOSED_FALLBACK_RATIO} x ojo abierto), NO medido. "
                          f"Pulsa C para repetir la calibración.")
            if done:
                fatigue_audio.beep()
                measured = "medido" if self.profile.closed_level_measured else "RESERVA (no medido)"
                print(f"[PASO 2] Ojo cerrado: {self.profile.closed_ear_level:.4f} "
                      f"({self.profile.closed_ear_level / self.profile.open_ear_baseline:.0%} del ojo abierto, {measured})")
                self._log_event("CALIBRACION_CIERRE" if self.profile.closed_level_measured else "CALIBRACION_CIERRE_RESERVA",
                                self.perclos_val, self.has_glasses, self.profile.closed_ear_level)
                self._warn_if_closure_not_visible()
            self._write_trace(now, left_ear, right_ear, ear, mouth)
            return False, False

        if phase == self.FASE_REAPERTURA:
            # Paso 2b: no se cuenta nada hasta que el sujeto abre los ojos tras el paso de ojos cerrados
            opened = self.profile.closure(ear) < self.REOPEN_MAX_CLOSURE
            self._reopen_streak = self._reopen_streak + 1 if opened else 0
            if self._reopen_streak >= self.REOPEN_FRAMES:
                self._start_monitoring(now)
            self._write_trace(now, left_ear, right_ear, ear, mouth)
            return False, False

        # Paso 3: monitoreo adaptativo
        is_yawning, yawn_blocks_blinks = self.yawn.update(mouth, now, ear, shape)
        pose_valid = self.head.track_range(now)
        is_microsleep = self.eyes.update(ear, yawn_blocks_blinks, now, pose_valid)
        level = self.alert.update(now, self.perclos_val, self.perclos.total_time, is_microsleep)
        if level is not None:
            self._log_event("NIVEL_FATIGA", self.perclos_val, self.has_glasses, ear, value=level)
            if level != NORMAL:
                print(f"[FATIGA] {MESSAGES[level]} (PERCLOS {self.perclos_val:.1f} %, t = {now:.1f} s)")
        self._write_trace(now, left_ear, right_ear, ear, mouth)
        return is_microsleep, is_yawning

    # ------------------------------------------------------------------ bucle principal

    def _is_video_file(self):
        source = self.video_source
        return isinstance(source, str) and not source.isdigit() and "://" not in source

    def _configure_camera(self, cap):
        """Pide la resolución configurada a una cámara en vivo (MJPG primero: muchas webcams solo dan 720p a
        30 fps comprimido). Devuelve el tamaño realmente obtenido."""
        if self.capture_size and not self._is_video_file():
            width, height = self.capture_size
            cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        actual = (int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)))
        if self.capture_size and not self._is_video_file():
            note = "" if actual == tuple(self.capture_size) else "  (la cámara no admite la pedida: se usa la suya)"
            print(f"[CAMARA] Resolución pedida {self.capture_size[0]}x{self.capture_size[1]} -> "
                  f"obtenida {actual[0]}x{actual[1]}{note}")
        return actual

    def _wait_for_camera(self, cap, window, open_capture=cv2.VideoCapture):
        """La cámara en vivo dejó de dar imágenes: reintenta hasta CAMERA_STALL_S, reabriéndola cada CAMERA_REOPEN_S.
        Devuelve (imagen, cap) si vuelve, o (None, cap) si no."""
        print("[CAMARA] No llegan imágenes de la cámara: reintentando...")
        start = last_open = time.time()
        while window.is_open() and time.time() - start < self.CAMERA_STALL_S:
            if time.time() - last_open >= self.CAMERA_REOPEN_S:
                cap.release()
                cap = open_capture(self.video_source)
                self._configure_camera(cap)
                last_open = time.time()
            success, img = cap.read()
            if success:
                print(f"[CAMARA] La cámara volvió tras {time.time() - start:.1f} s sin imágenes.")
                return img, cap
            time.sleep(0.1)
        print(f"[CAMARA] La cámara no dio imágenes en {self.CAMERA_STALL_S:.0f} s. Suele pasar cuando otro programa la "
              "está usando (navegador, Teams, Zoom, la app Cámara, Eyeblink...): ciérralo y vuelve a empezar.")
        return None, cap

    def start(self):
        if self.kss and self._is_video_file():
            print("[AVISO] --kss es para sesiones en vivo (la persona responde en el momento). Se ignora.")
            self.kss = None
        if self._is_video_file():
            self.alert.sound = False      # analizando un vídeo: alertas registradas, sin sonido
        # Antes de abrir la cámara (tarda unos segundos): así se ve enseguida que la sesión está empezando
        window = (display.NullWindow() if self.headless
                  else display.open_window(fatigue_hud.WINDOW_NAME, fatigue_hud.window_size()))
        cap = cv2.VideoCapture(self.video_source)
        frame_size = self._configure_camera(cap)
        native_fps = cap.get(cv2.CAP_PROP_FPS) or None

        # Reloj de la sesión. Con un archivo de vídeo se usa el tiempo del propio vídeo (frame / fps del
        # archivo): así el mismo vídeo da siempre el mismo resultado, sin depender de la velocidad del PC.
        # Con cámara en vivo, el reloj del sistema.
        use_video_clock = self._is_video_file() and native_fps
        clock = "video (frame / fps del archivo)" if use_video_clock else "sistema (tiempo real)"
        wall_start = time.time()

        self.session = SessionRecorder(self.subject_id, self.sessions_dir, self.save_trace, self.condition,
                                       self.subject_code)
        source_type = ("video" if self._is_video_file()
                       else "stream" if "://" in str(self.video_source) else "camara")
        self.session.begin(self.video_source, source_type, clock, frame_size, native_fps, self.parameters())
        self.session.open_trace(fatigue_report.TRACE_HEADER)
        if self.record and self._is_video_file():
            print("[AVISO] --grabar es para sesiones en vivo: el vídeo analizado ya es la grabación. Se ignora.")
        elif self.record:
            self.recorder = FrameRecorder(self.session.dir, frame_size, native_fps)
            print(f"[GRABACION] Se guarda lo que ve la cámara en {self.session.dir} (para anotarlo después)")

        while True:
            if not window.is_open():         # cerrada con la X
                break
            success, img = cap.read()
            if not success and not self._is_video_file():
                img, cap = self._wait_for_camera(cap, window)
                success = img is not None
            if not success:
                break

            self._now =self.frames_total / native_fps if use_video_clock else time.time() - wall_start
            self.frames_total += 1
            self.session.tick()
            if self._manual_pending and self.frames_total - 1 >= calibration_marks.frame_ranges(self.manual_marks)[4]:
                self._finish_manual_calibration(self._now)

            clean_frame = img.copy()
            if self.recorder:
                self.recorder.write(clean_frame, self._now)   # clean_frame no se modifica después
            img, faces = self.detector.findFaceMesh(img, draw=False)

            is_microsleep_active, is_yawning_active = False, False
            if faces:
                self.frames_with_face += 1
                is_microsleep_active, is_yawning_active = self._process_face(
                    faces[0], self.detector.faces3d[0], clean_frame, self._now)
            else:
                self.stability.reset()   # al volver el rostro se exigen de nuevo 15 frames estables

            if self.kss and self._monitoring_started and self.kss.due(self._now):
                self._ask_kss("inicio" if not self.kss.responses else "periodica")

            if not self.headless:
                img = self.hud.present(self.hud.render(img, self, is_microsleep_active, is_yawning_active), window)
                window.show(img)
            key = window.wait_key(1)
            if key == ord(' ') and self._is_video_file():
                # Pausa (solo vídeos: el reloj es el del archivo, así que pausar no altera las mediciones)
                key = 0
                while key not in (ord(' '), ord('q')):
                    key = window.wait_key(50)
                    if not window.is_open():
                        key = ord('q')       # ventana cerrada durante la pausa
                self.session.reset_tick()    # el tiempo en pausa no cuenta en los FPS de procesamiento
            if self.kss and self.kss.prompt and ord('1') <= key <= ord('9'):
                self._answer_kss(key - ord('0'))
                if self.kss.quit_after:
                    break                   # respondida la pregunta final: termina la sesión
                continue
            if key == ord('q'):
                if self.kss and self._monitoring_started and not self.kss.final_done and not self.kss.quit_after:
                    self._ask_kss("final")  # antes de salir, la última respuesta (Q otra vez: salir sin ella)
                    self.kss.quit_after = True
                    continue
                break
            if key == ord('c'):
                self.recalibrate("manual", full=True)

        cap.release()
        window.close()
        if self.recorder:
            print("[GRABACION] Terminando de guardar el vídeo...")
            self.session.metadata["grabacion"] = self.recorder.close()
        self._finish_session(native_fps, use_video_clock)

    def _finish_session(self, native_fps, use_video_clock):
        self.head.close_interval(self._now)
        metadata = self.session.finish(fatigue_report.session_summary(self))

        # Duraciones (parpadeo, micro-sueño, PERCLOS) van en segundos; solo el mínimo de frames de un parpadeo
        # y el periodo refractario siguen en frames y suponen fps_estimate
        effective_fps = native_fps if use_video_clock else metadata["rendimiento"]["fps_procesamiento_medio"]
        if effective_fps and abs(effective_fps - self.fps_estimate) > 0.15 * self.fps_estimate:
            print(f"[AVISO] La sesión fue a {effective_fps:.1f} fps, pero el periodo refractario del parpadeo "
                  f"({self.BLINK_REFRACTORY_FRAMES} frames) supone {self.fps_estimate} fps: equivale a "
                  f"{self.BLINK_REFRACTORY_FRAMES / effective_fps:.2f} s en vez de "
                  f"{self.BLINK_REFRACTORY_FRAMES / self.fps_estimate:.2f} s.")
