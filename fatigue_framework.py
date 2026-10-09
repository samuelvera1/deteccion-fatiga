# fatigue_framework.py
import cv2
import numpy as np
import time
from collections import deque
import calibration_marks
from fatigue_core import FaceMeshDetector
from session_recorder import SessionRecorder


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


class FatigueMonitor:
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

    # Calibración de ojo cerrado: cuentan los frames con apertura < CLOSED_CAPTURE_FACTOR x ojo abierto.
    # Si en CLOSED_CALIBRATION_TIMEOUT s no se completa, se usa CLOSED_FALLBACK_RATIO x ojo abierto
    # (valor de reserva, NO medido: queda marcado en metadata.json como cierre_medido = false).
    # 0.25 es el mínimo del único parpadeo completo observado en la sesión 20261005_231802.
    CLOSED_CAPTURE_FACTOR = 0.6
    CLOSED_CALIBRATION_TIMEOUT = 10.0
    CLOSED_FALLBACK_RATIO = 0.25
    # Si con los ojos cerrados la apertura no baja de este nivel, el cierre apenas es visible en la malla
    CLOSURE_VISIBLE_MAX_RATIO = 0.6
    # Reapertura tras el paso de ojos cerrados: el monitoreo empieza cuando el cierre baja de
    # REOPEN_MAX_CLOSURE durante REOPEN_FRAMES frames seguidos. Sin esto, el tiempo que el sujeto tarda
    # en abrir los ojos tras el pitido (o en un vídeo, donde no hay pitido) contaba como micro-sueño y
    # PERCLOS (sesión 20261008_143243: micro-sueño falso de 1.02 s nada más terminar la calibración).
    REOPEN_MAX_CLOSURE = 0.5
    REOPEN_FRAMES = 3

    # PERCLOS P80 (Wierwille et al., 1994; Dinges y Grace, 1998): proporción del tiempo, en una
    # ventana de 1 min, con el párpado >= 80 % cerrado. Incluye los parpadeos (variante elegida;
    # algunas definiciones los excluyen).
    P80_CLOSURE = 0.80
    # Micro-sueño (Hertig-Godeschalk et al., 2020): párpados >= 80 % cerrados durante >= 1 s
    # (en ese trabajo, 1-15 s y confirmado con EEG; aquí es solo el criterio conductual).
    # Se sale del estado de cierre por debajo de MICROSLEEP_EXIT_CLOSURE para no partir un episodio.
    MICROSLEEP_SECONDS = 1.0
    MICROSLEEP_EXIT_CLOSURE = 0.70

    LEFT_EYE = [33, 160, 158, 133, 153, 144]
    RIGHT_EYE = [362, 385, 387, 263, 373, 380]

    MIN_BLINK_FRAMES = 2
    # PARPADEO PROLONGADO (long closure duration blink): la duración del parpadeo y la proporción de
    # parpadeos de cierre largo aumentan con la somnolencia (Caffier et al., 2003; Ingre et al., 2006).
    # Corte de 0.5 s PROVISIONAL: no verificado en la literatura; en los datos del sujeto los parpadeos
    # normales duraron 0.13-0.43 s (sesiones 20261005_232441, 20261006_003914 y _004113). Se guarda la
    # duración de cada parpadeo en eventos.csv para poder reclasificar con otro corte sin regrabar.
    LONG_BLINK_SECONDS = 0.5
    # Un parpadeo prolongado debe llegar a cierre >= 80 % (excluye entrecerrar los ojos)
    LONG_BLINK_MIN_CLOSURE = 0.80
    # RÁFAGAS de parpadeos: un nuevo cierre >= 80 % tras una reapertura parcial < 60 % es un parpadeo nuevo.
    # Valores PROVISIONALES derivados de la sesión 20261006_114449 (S02): en sus ráfagas los cierres
    # llegaron a 0.86-1.04 y las reaperturas parciales entre parpadeos a 0.19-0.58.
    BURST_PEAK_CLOSURE = 0.80
    BURST_REOPEN_CLOSURE = 0.60

    # SONRISA vs BOSTEZO (FACS, Ekman y Friesen, 1978): la sonrisa (AU12) estira las comisuras hacia los
    # lados; el bostezo abre la boca con caída de mandíbula. Un episodio de boca abierta se descarta como
    # bostezo si la boca está claramente más ancha que en reposo SIN gran caída de mandíbula.
    # Ajustado con datos (sin etiquetas por evento, PROVISIONAL): sonrisas de S01 (sesiones 20261006_155916
    # y _212220) -> ancho 1.33-1.44 y mandíbula 0.05-0.13; bostezos de S01 -> ancho 0.83-1.00 y mandíbula
    # 0.17-0.27; bostezos de otro sujeto (20261006_160134) -> mandíbula 0.17-0.61 (algunos con ancho hasta
    # 1.25, por eso la mandíbula decide). Se retiró la condición de elevación de comisuras: medida respecto
    # al labio superior no capta la sonrisa con dientes (el labio superior sube con las comisuras; ~0 en S01).
    SMILE_MIN_WIDTH_RATIO = 1.15    # boca >= 15 % más ancha que la neutra
    SMILE_MAX_JAW_DROP = 0.15       # mandíbula < 0.15 IPD (~9.5 mm) más abajo que en reposo

    # RANGO DE POSTURA VÁLIDO para las métricas del ojo (orientación relativa a la calibración frontal).
    # La apertura del ojo se mide en 2D: al inclinar la cabeza arriba/abajo se acorta en la imagen y parece
    # cierre. Sesión 20261006_174416 (S01, con gafas): con |pitch| <= 10° cierre aparente ~0 (mediana -0.04);
    # 10-15° -> 0.33; 30-45° -> 0.71 (hasta 0.93, por encima del P80). El giro lateral (yaw) hasta ~44° no
    # produjo cierre aparente. PROVISIONAL (1 sujeto). Fuera de rango no se cuentan parpadeos ni PERCLOS;
    # el micro-sueño se sigue evaluando por seguridad (dormirse suele ir con cabeceo) y el intervalo se
    # registra como POSTURA_FUERA_DE_RANGO para poder filtrar esos eventos.
    POSE_MAX_PITCH = 10.0
    POSE_MAX_YAW = 40.0
    # Postura "frontal" exigida por la puerta de estabilidad (calibración y análisis de gafas): la medida de
    # deformación de la malla reacciona sobre todo a los giros de cabeza (0.25-0.31 con 33-43° de yaw)
    POSE_STABLE_MAX = 10.0
    # Periodo refractario tras contar un parpadeo (evita contar dos veces el mismo). Era 8 frames (~0.27 s)
    # y bloqueaba parpadeos reales de ráfagas (separados ~0.25 s). Con 3 frames (~0.1 s): S02 pasa de 24 a
    # 28 parpadeos en la sesión 20261006_114449 (29 cierres en la señal) y las sesiones de S01 con recuento
    # manual no cambian. PROVISIONAL: falta validar con ráfagas contadas a mano.
    BLINK_REFRACTORY_FRAMES = 3
    # GIRO RÁPIDO DE CABEZA: al girar rápido, la apertura medida por la malla cae un poco sin que el
    # párpado se mueva, y al pasar por la postura frontal se contaba como parpadeo (sesión
    # 20261008_154526: giro de 208 °/s con cierre máximo 0.08, frente a parpadeos reales con cierre
    # 1.00-1.13 y cabeza a 27-41 °/s). Si durante el episodio la cabeza gira a más de FAST_HEAD_SPEED,
    # solo cuenta como parpadeo si el cierre llega al P80. No se descartan todos: los giros de mirada
    # con la cabeza suelen ir acompañados de parpadeos reales (Evinger et al., 1994), que cierran del
    # todo. Umbral PROVISIONAL (1 sesión; en ella el percentil 99 del giro normal fue 114 °/s).
    FAST_HEAD_SPEED = 120.0

    # PARPADEO = evento transitorio: caída brusca de la apertura respecto a la apertura de justo antes
    # (referencia local = percentil 90 de la apertura entre 0.9 s y 0.3 s antes del frame actual), en la
    # línea de tratar el parpadeo como un patrón temporal de la señal EAR (Soukupová y Čech, 2016).
    # Es independiente de la mirada, la postura y las gafas, que cambian el nivel de apertura "normal".
    # Ajustado con la sesión 20261005_232441 (1 sujeto, 10 parpadeos con gafas + 10 sin gafas,
    # recuento manual): factores 0.78-0.80 dieron 10/10 en ambos tramos y 0 micro-sueños falsos;
    # el umbral relativo a la calibración (0.82 con gafas) daba 15/10. PENDIENTE validar con más sujetos.
    BLINK_LOCAL_FACTOR = 0.79       # parpadeo si apertura < 0.79 x referencia local (igual con y sin gafas)
    BLINK_REOPEN_MARGIN = 0.06      # se reabre por encima de (0.79 + 0.06) x referencia local
    BLINK_DEEP_MARGIN = 0.10        # 1 solo frame cuenta si baja de (0.79 - 0.10) x referencia local
    BLINK_REF_WINDOW = (0.9, 0.3)   # s antes del frame actual que forman la referencia local
    BLINK_REF_PERCENTILE = 90

    # Bostezo de dos niveles. Cada nivel exige que la boca supere su umbral de forma sostenida
    # (huecos de hasta YAWN_GAP_FRAMES frames no cortan la racha: tics de labios). Un episodio
    # dura mientras siga activa la racha del nivel 2 (el umbral más bajo).
    YAWN_TIER_EXAGGERATED, YAWN_TIER_MICRO = 0, 1
    YAWN_GAP_FRAMES = 2
    YAWN_COOLDOWN_SECONDS = 1.0
    # Duración del bostezo = tiempo con la boca por encima del umbral micro (fase de boca abierta), del
    # primer al último frame sobre el umbral. No es la duración completa del bostezo (Provine, 1986:
    # ~6 s de media incluyendo inspiración y cierre), sino la parte visible como apertura bucal.

    IPD_SMOOTHING = 0.2       # EMA: la IPD es rígida, solo cambia con la distancia a la cámara

    # Colores del HUD para PERCLOS: SIN respaldo en la literatura encontrada (solo visualización)
    PERCLOS_WARN_PCT = 15.0
    PERCLOS_ALERT_PCT = 22.0

    def __init__(self, video_source=0, subject_id="anonimo", condition=None, save_trace=True, sessions_dir="sesiones",
                 subject_code=None, manual_marks=None,
                 refine_landmarks=True, capture_size=(1280, 720),
                 yawn_factor=1.65, yawn_min_delta=0.25, yawn_min_seconds=0.5,
                 micro_yawn_factor=1.30, micro_yawn_min_delta=0.15, micro_yawn_min_seconds=0.35,
                 calibration_frames=90, window_seconds=60, perclos_min_seconds=15):
        self.video_source = video_source
        # Cada ejecución de start() crea una sesión en sessions_dir con metadatos reproducibles
        self.subject_id = subject_id
        self.condition = condition            # condición experimental declarada (p. ej. con_gafas)
        self.subject_code = subject_code      # código anónimo (S01...) guardado junto al nombre
        # Marcas de calibración manual del vídeo (calibration_marks), ya validadas; None = automática
        self.manual_marks = manual_marks
        self._manual_pending = manual_marks is not None
        self.test_start_s = None              # inicio del monitoreo (s), para el resumen
        self.save_trace = save_trace
        # Resolución pedida a la cámara (None = la nativa). A 640x480 la cara lejana ocupa pocos píxeles: con
        # IPD de 50-70 px la montura de las gafas casi no deja bordes (sesión 20261006_212220). Si la cámara
        # no la soporta se usa la que entregue; la real queda registrada en metadata.json.
        self.capture_size = capture_size
        self.sessions_dir = sessions_dir
        self.session = None
        # Umbral de cada nivel = max(factor * boca neutra, boca neutra + min_delta) en unidades de IPD.
        # El margen mínimo es necesario porque con labios cerrados la boca neutra es ~0 y
        # 1.3x de ~0 lo superaría cualquier sílaba.
        self.yawn_tiers = [(yawn_factor, yawn_min_delta, yawn_min_seconds),                    # exagerado
                           (micro_yawn_factor, micro_yawn_min_delta, micro_yawn_min_seconds)]  # micro/sutil
        self.yawn_min_delta = yawn_min_delta
        self.window_seconds = window_seconds
        self.perclos_min_seconds = perclos_min_seconds

        # refine_landmarks=True por defecto: sin él, la malla apenas registra el cierre del párpado (sesiones
        # 20261006_001819 / _002122: ojos cerrados de verdad medidos al 67-77 % sin gafas y 80-88 % con gafas)
        self.detector = FaceMeshDetector(maxFaces=1, minDetectionCon=0.6, minTrackCon=0.6,
                                         refineLandmarks=refine_landmarks)
        self.profile = SubjectProfile(calibration_frames)
        self.stability = LandmarkStabilityGate(required_frames=15)

        self._on_blink = None
        self._on_yawn = None

        self.blink_count = 0
        self.long_blink_count = 0             # parpadeos prolongados (>= LONG_BLINK_SECONDS, sin micro-sueño)
        self.blink_durations = []             # duración (s) de cada parpadeo normal y prolongado
        self.yawn_count = 0                   # total (exagerados + micro)
        self.micro_yawn_count = 0
        self.smile_count = 0                  # episodios de boca abierta descartados como sonrisa
        self._last_shape = None
        self.pose_ref = None                  # ejes de la cabeza en la calibración (postura frontal)
        self._pose_samples = []
        self._last_axes = None
        self._last_axes_t = None
        self.head_speed = None                # velocidad de giro de la cabeza (°/s) en el último frame
        self.head_pose = None                 # (yaw, pitch, roll) en grados respecto a la calibración
        self.yawn_durations = []              # duración (s) de la apertura bucal de cada bostezo contado
        self.fast_turn_rejected = 0           # caídas de apertura descartadas por giro rápido de cabeza
        self._pose_out_since = None           # inicio del intervalo de postura fuera de rango en curso
        self.pose_out_time = 0.0              # tiempo total (s) de monitoreo con postura fuera de rango

        self.fps_estimate = 30                # solo para los parámetros de parpadeo, aún en frames
        # PERCLOS ponderado por tiempo real (independiente de los fps): (t, dt, cerrado) en la ventana.
        # Denominador mínimo perclos_min_seconds: al inicio un solo parpadeo no puede inflar el PERCLOS.
        self.perclos_history = deque()
        self.perclos_closed_time = 0.0
        self.perclos_total_time = 0.0
        self._perclos_last_t = None
        self.perclos_val = 0.0

        self.ipd = None
        # Gafas según la condición declarada: True / False, o None si no se declaró
        self.has_glasses = self._declared_glasses(condition)
        self._last_microsleep_log = 0.0
        self._reset_tracking_state()

        self.recalibration_count = 0
        self.frames_total = 0
        self.frames_with_face = 0
        self._now = 0.0                       # tiempo de la sesión (s): reloj del vídeo o del sistema

    # ------------------------------------------------------------------ registro

    TRACE_HEADER = ["t", "ipd", "ear_left", "ear_right", "ear", "ear_baseline", "ear_cerrado", "cierre",
                    "p80", "eyes_closed", "mouth", "mouth_neutral", "yawn_thr", "micro_yawn_thr",
                    "gafas_declaradas", "fase", "estable", "movimiento",
                    "parpadeos", "bostezos", "micro_bostezos", "blink_ref", "blink_closed",
                    "boca_ancho_rel", "comisuras_elev", "mandibula_caida", "sonrisa",
                    "cabeza_yaw", "cabeza_pitch", "cabeza_roll", "postura_valida",
                    "frame",   # índice del frame en la fuente (0 = primero); los frames sin rostro no tienen fila
                    "cabeza_vel"]   # velocidad de giro de la cabeza (°/s)

    def parameters(self):
        """Todos los parámetros del método, para los metadatos de la sesión (sección de métodos)."""
        return {
            "camara": {"resolucion_pedida": list(self.capture_size) if self.capture_size else "nativa"},
            "facemesh": {"min_detection_confidence": self.detector.minDetectionCon,
                         "min_tracking_confidence": self.detector.minTrackCon,
                         "refine_landmarks": self.detector.refineLandmarks},
            "calibracion": {"frames_perfil": self.profile.calibration_frames,
                            "frames_ojo_cerrado": self.profile.closed_frames,
                            "captura_ojo_cerrado_factor": self.CLOSED_CAPTURE_FACTOR,
                            "timeout_ojo_cerrado_s": self.CLOSED_CALIBRATION_TIMEOUT,
                            "reserva_ojo_cerrado_ratio": self.CLOSED_FALLBACK_RATIO,
                            "cierre_visible_max_ratio": self.CLOSURE_VISIBLE_MAX_RATIO,
                            "reapertura_cierre_max": self.REOPEN_MAX_CLOSURE,
                            "reapertura_frames": self.REOPEN_FRAMES,
                            "modo": "manual (marcas del vídeo)" if self.manual_marks else "automatica",
                            "marcas_manuales": self.manual_marks,
                            "frames_estables_requeridos": self.stability.required_frames,
                            "max_movimiento_ipd": self.stability.max_motion,
                            "suavizado_ipd": self.IPD_SMOOTHING},
            "ojos": {"parpadeo_factor_ref_local": self.BLINK_LOCAL_FACTOR,
                     "parpadeo_margen_reapertura": self.BLINK_REOPEN_MARGIN,
                     "parpadeo_margen_1_frame": self.BLINK_DEEP_MARGIN,
                     "parpadeo_ventana_ref_s": self.BLINK_REF_WINDOW,
                     "parpadeo_percentil_ref": self.BLINK_REF_PERCENTILE,
                     "parpadeo_min_frames": self.MIN_BLINK_FRAMES,
                     "parpadeo_prolongado_min_s": self.LONG_BLINK_SECONDS,
                     "parpadeo_prolongado_cierre_min": self.LONG_BLINK_MIN_CLOSURE,
                     "rafaga_cierre_pico": self.BURST_PEAK_CLOSURE,
                     "rafaga_reapertura_parcial": self.BURST_REOPEN_CLOSURE,
                     "refractario_parpadeo_frames": self.BLINK_REFRACTORY_FRAMES,
                     "giro_rapido_cabeza_gs": self.FAST_HEAD_SPEED,
                     "giro_rapido_cierre_min": self.P80_CLOSURE,
                     "microsueno_cierre_min": self.P80_CLOSURE, "microsueno_min_s": self.MICROSLEEP_SECONDS,
                     "microsueno_cierre_salida": self.MICROSLEEP_EXIT_CLOSURE},
            "bostezo": {"exagerado_factor_delta_seg": self.yawn_tiers[self.YAWN_TIER_EXAGGERATED],
                        "micro_factor_delta_seg": self.yawn_tiers[self.YAWN_TIER_MICRO],
                        "hueco_tolerado_frames": self.YAWN_GAP_FRAMES,
                        "sonrisa_ancho_min_ratio": self.SMILE_MIN_WIDTH_RATIO,
                        "sonrisa_mandibula_max_ipd": self.SMILE_MAX_JAW_DROP,
                        "enfriamiento_s": self.YAWN_COOLDOWN_SECONDS},
            "perclos": {"definicion": "P80", "cierre_min": self.P80_CLOSURE, "incluye_parpadeos": True,
                        "ventana_s": self.window_seconds, "denominador_minimo_s": self.perclos_min_seconds,
                        "ponderado_por_tiempo": True,
                        "hud_precaucion_pct": self.PERCLOS_WARN_PCT, "hud_alerta_pct": self.PERCLOS_ALERT_PCT},
            "gafas": {"origen": "condición declarada por el investigador (--condicion)",
                      "declaradas": self.has_glasses,
                      "cambio_a_mitad_de_sesion": "recalibrar con la tecla C"},
            "postura": {"referencia": "postura media de la calibración (mirando al frente)",
                        "max_pitch_metricas_ojo": self.POSE_MAX_PITCH, "max_yaw_metricas_ojo": self.POSE_MAX_YAW,
                        "max_giro_estabilidad": self.POSE_STABLE_MAX,
                        "fuera_de_rango": "no se cuentan parpadeos ni PERCLOS; micro-sueño sí (marcado)"},
        }

    def _log_event(self, event_type, perclos_val, has_glasses, ear_val, duration=None, end_time=None):
        """end_time: instante en que terminó el evento si no es el frame actual (t_s = fin del evento)."""
        if self.session:
            self.session.log_event(self._now if end_time is None else end_time, event_type, self.phase,
                                   perclos_val, has_glasses, ear_val, duration)

    def _write_trace(self, now, left_ear, right_ear, ear, mouth):
        if not (self.session and self.session.save_trace):
            return
        fmt = lambda v: "" if v is None else f"{v:.4f}"
        calibrated = self.profile.is_calibrated
        closure = self.profile.closure(ear) if self.profile.is_closed_calibrated else None
        yawn_thr, micro_thr = self._yawn_thresholds() if calibrated else (None, None)
        p, shape = self.profile, self._last_shape
        if shape is not None and p.neutral_mouth_width:
            width_rel = shape[0] / p.neutral_mouth_width
            lift_delta, jaw_delta = shape[2] - p.neutral_corner_lift, shape[1] - p.neutral_jaw
        else:
            width_rel = lift_delta = jaw_delta = None
        self.session.trace([f"{now:.3f}", fmt(self.ipd), fmt(left_ear), fmt(right_ear), fmt(ear),
                                     fmt(self.profile.open_ear_baseline), fmt(self.profile.closed_ear_level),
                                     fmt(closure), int(closure is not None and closure >= self.P80_CLOSURE),
                                     int(self.eyes_closed),
                                     fmt(mouth), fmt(self.profile.neutral_mouth_ratio), fmt(yawn_thr), fmt(micro_thr),
                                     "" if self.has_glasses is None else int(self.has_glasses), self.phase,
                                     self.stability.stable_frames, fmt(self.stability.motion),
                                     self.blink_count, self.yawn_count,
                                     self.micro_yawn_count, fmt(self.blink_ref), int(self.blink_closed),
                                     fmt(width_rel), fmt(lift_delta), fmt(jaw_delta), int(self._is_smile(shape)),
                                     *(fmt(a) for a in (self.head_pose or (None, None, None))),
                                     int(self.eye_pose_valid), self.frames_total - 1, fmt(self.head_speed)])

    def on_blink(self, callback_function):
        self._on_blink = callback_function

    def on_yawn(self, callback_function):
        self._on_yawn = callback_function

    # ------------------------------------------------------------------ calibración

    def _reset_tracking_state(self):
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
        self.blink_ref = None
        self._ear_history = deque()           # (t, apertura) del último segundo, para la referencia local
        self._last_blink_ref = None
        self.yawn_run_start = [None, None]    # inicio de la racha sostenida de cada nivel
        self.yawn_run_gap = [0, 0]            # frames consecutivos por debajo del umbral de cada nivel
        self.yawn_counted = False
        self.yawn_exaggerated = False         # el episodio actual alcanzó el nivel 1
        self.yawn_cooldown_until = 0.0
        self.yawn_episode_start = None        # inicio del episodio de boca abierta en curso
        self.yawn_last_open = None            # último instante con la boca sobre el umbral micro
        self.blink_max_head_speed = 0.0       # giro de cabeza máximo (°/s) durante el cierre en curso
        self.yawn_smile_seen = False          # el episodio en curso tuvo forma de sonrisa
        self._closed_phase_started = None
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

    def recalibrate(self, reason, full=False):
        """Descarta el perfil y reinicia el pipeline desde el paso 1.
        full=True (manual, tecla C): repite también el paso de ojos cerrados (necesario si el participante se
        pone o se quita las gafas). full=False conserva la proporción de ojo cerrado medida."""
        self.profile.reset(keep_closed_ratio=not full)
        self._manual_pending = False          # tras recalibrar se usa la calibración automática
        self._close_pose_interval()
        self.pose_ref, self._pose_samples, self.head_pose = None, [], None
        self._reset_tracking_state()
        self.recalibration_count += 1
        print(f"[CALIBRACION] Recalibrando perfil facial ({reason})")
        self._log_event("RECALIBRACION", self.perclos_val, self.has_glasses, 0.0)

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
            self._pose_samples = []
            self._log_event("CALIBRACION_MANUAL_FALLIDA", self.perclos_val, self.has_glasses, 0.0)
            return
        p.finish_profile()
        p.finish_manual_closed()
        self._lock_pose_reference()
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

    @staticmethod
    def _beep():
        """Aviso sonoro (el sujeto tiene los ojos cerrados y no ve la pantalla)."""
        try:
            import winsound
            winsound.Beep(1200, 250)
        except Exception:
            print("\a", end="", flush=True)

    def _pose_within(self, max_pitch, max_yaw):
        """True si la cabeza está dentro del rango (o si aún no hay orientación disponible)."""
        if self.head_pose is None:
            return True
        yaw, pitch, _ = self.head_pose
        return abs(pitch) <= max_pitch and abs(yaw) <= max_yaw

    @property
    def eye_pose_valid(self):
        return self._pose_within(self.POSE_MAX_PITCH, self.POSE_MAX_YAW)

    @property
    def pose_frontal(self):
        return self._pose_within(self.POSE_STABLE_MAX, self.POSE_STABLE_MAX)

    def _track_pose_range(self, now):
        """Registra cada intervalo de postura fuera de rango como POSTURA_FUERA_DE_RANGO (con su duración)."""
        valid = self.eye_pose_valid
        if not valid and self._pose_out_since is None:
            self._pose_out_since = now
        elif valid and self._pose_out_since is not None:
            duration = now - self._pose_out_since
            self.pose_out_time += duration
            self._log_event("POSTURA_FUERA_DE_RANGO", self.perclos_val, self.has_glasses, 0.0, duration)
            self._pose_out_since = None
        return valid

    def _close_pose_interval(self):
        """Cierra el intervalo fuera de rango en curso (fin de sesión o recalibración)."""
        if self._pose_out_since is not None:
            duration = self._now - self._pose_out_since
            self.pose_out_time += duration
            self._log_event("POSTURA_FUERA_DE_RANGO", self.perclos_val, self.has_glasses, 0.0, duration)
            self._pose_out_since = None

    # ------------------------------------------------------------------ métricas normalizadas

    @staticmethod
    def _face_axes(face3d):
        """Ejes de la cabeza (columnas: derecha, abajo, adelante) a partir de landmarks 3D: línea entre los
        centros de los ojos y eje frente (10) -> mentón (152), ortonormalizados. Coordenadas de MediaPipe:
        x a la derecha, y hacia abajo, z alejándose de la cámara (z estimada por la red, no medida)."""
        p = np.asarray(face3d, dtype=np.float64)
        across = (p[362] + p[263]) / 2.0 - (p[33] + p[133]) / 2.0
        down = p[152] - p[10]
        if np.linalg.norm(across) < 1e-6:
            return None
        x = across / np.linalg.norm(across)
        y = down - np.dot(down, x) * x
        if np.linalg.norm(y) < 1e-6:
            return None                       # malla degenerada: frente y mentón alineados con los ojos
        y /= np.linalg.norm(y)
        axes = np.column_stack([x, y, np.cross(x, y)])
        return axes if np.all(np.isfinite(axes)) else None

    def _update_head_pose(self, face3d, now):
        """Orientación de la cabeza (yaw, pitch, roll en grados) RELATIVA a la postura media de la
        calibración (mirando al frente). Convención R = Ry(yaw)·Rx(pitch)·Rz(roll) en ejes de cámara:
        yaw = giro a los lados, pitch = arriba/abajo, roll = inclinación hacia el hombro.
        Además, velocidad de giro (°/s): ángulo de la rotación entre este frame y el anterior / tiempo."""
        axes = self._face_axes(face3d)
        prev, prev_t = self._last_axes, self._last_axes_t
        self.head_speed = None
        if axes is not None and prev is not None and prev_t is not None and now > prev_t:
            cos_angle = np.clip((np.trace(axes @ prev.T) - 1.0) / 2.0, -1.0, 1.0)
            self.head_speed = float(np.degrees(np.arccos(cos_angle)) / (now - prev_t))
        self._last_axes, self._last_axes_t = axes, now
        if axes is None or self.pose_ref is None:
            self.head_pose = None
            return
        r = axes @ self.pose_ref.T
        yaw = np.degrees(np.arctan2(r[0, 2], r[2, 2]))
        pitch = np.degrees(np.arcsin(np.clip(-r[1, 2], -1.0, 1.0)))
        roll = np.degrees(np.arctan2(r[1, 0], r[1, 1]))
        self.head_pose = (float(yaw), float(pitch), float(roll))

    def _lock_pose_reference(self):
        """Postura de referencia = ejes medios de los frames de calibración, reortonormalizados (SVD)."""
        if not self._pose_samples:
            return
        try:
            u, _, vt = np.linalg.svd(np.mean(np.array(self._pose_samples), axis=0))
            self.pose_ref = u @ vt
        except np.linalg.LinAlgError:
            self.pose_ref = None              # sin referencia: la orientación queda vacía en la traza

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

    def _mouth_shape(self, face, ipd):
        """(ancho de boca, distancia nariz-mentón, elevación de comisuras) en unidades de IPD.
        La elevación se mide sobre el eje vertical de la cara (perpendicular a la línea de los ojos, hacia
        el mentón): positiva si las comisuras (61, 291) quedan por encima del labio superior interno (13)."""
        if ipd <= 0:
            return None
        pts = np.asarray(face, dtype=np.float64)
        across = (pts[362] + pts[263]) / 2.0 - (pts[33] + pts[133]) / 2.0
        norm = float(np.linalg.norm(across))
        if norm == 0:
            return None
        down = np.array([-across[1], across[0]]) / norm
        if np.dot(pts[152] - pts[1], down) < 0:          # vídeo espejado: el eje debe apuntar al mentón
            down = -down
        corners = (pts[61] + pts[291]) / 2.0
        width = float(np.linalg.norm(pts[61] - pts[291])) / ipd
        jaw = float(np.linalg.norm(pts[152] - pts[1])) / ipd
        lift = float(np.dot(pts[13] - corners, down)) / ipd
        return width, jaw, lift

    def _is_smile(self, shape):
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

    def _yawn_thresholds(self):
        """Umbral de apertura bucal de cada nivel: [exagerado, micro]."""
        neutral = self.profile.neutral_mouth_ratio
        return [max(neutral * factor, neutral + min_delta) for factor, min_delta, _ in self.yawn_tiers]

    # ------------------------------------------------------------------ detección de eventos

    def _update_perclos(self, is_closed, now):
        """PERCLOS ponderado por tiempo real en una ventana de window_seconds; el denominador nunca baja
        de perclos_min_seconds. Cada frame pesa el tiempo transcurrido desde el anterior (máx. 0.2 s,
        para que una pausa del vídeo o de la cámara no pese de más)."""
        dt = 0.0 if self._perclos_last_t is None else min(max(now - self._perclos_last_t, 0.0), 0.2)
        self._perclos_last_t = now
        self.perclos_history.append((now, dt, is_closed))
        self.perclos_total_time += dt
        self.perclos_closed_time += dt if is_closed else 0.0
        while self.perclos_history and self.perclos_history[0][0] < now - self.window_seconds:
            _, old_dt, old_closed = self.perclos_history.popleft()
            self.perclos_total_time -= old_dt
            self.perclos_closed_time -= old_dt if old_closed else 0.0

        denominator = max(self.perclos_total_time, self.perclos_min_seconds)
        self.perclos_val = max(0.0, self.perclos_closed_time / denominator * 100.0)
        return self.perclos_val

    def _update_yawn(self, mouth, now, ear, shape=None):
        """Bostezo de dos niveles. Devuelve (bostezo_en_curso, bloquea_parpadeos).
        Se cuenta en cuanto se cumple cualquier nivel (aviso inmediato); el tipo (BOSTEZO o
        MICRO_BOSTEZO) se registra al terminar el episodio, porque un bostezo exagerado siempre
        cumple antes el nivel micro (umbral más bajo y duración más corta).
        Mientras la forma de la boca sea de sonrisa (_is_smile) el episodio no se cuenta; si termina sin
        contarse y hubo sonrisa, se registra un evento SONRISA (para poder revisar los descartes)."""
        if now < self.yawn_cooldown_until and self.yawn_run_start[self.YAWN_TIER_MICRO] is None:
            return False, True

        for tier, threshold in enumerate(self._yawn_thresholds()):
            if mouth > threshold:
                if self.yawn_run_start[tier] is None:
                    self.yawn_run_start[tier] = now
                    if tier == self.YAWN_TIER_MICRO:
                        self.yawn_episode_start, self.yawn_smile_seen = now, False
                if tier == self.YAWN_TIER_MICRO:
                    self.yawn_last_open = now     # último frame con la boca sobre el umbral (fin del episodio)
                self.yawn_run_gap[tier] = 0
            elif self.yawn_run_start[tier] is not None:
                self.yawn_run_gap[tier] += 1
                if self.yawn_run_gap[tier] > self.YAWN_GAP_FRAMES:
                    self.yawn_run_start[tier] = None

        smiling = self.yawn_run_start[self.YAWN_TIER_MICRO] is not None and self._is_smile(shape)
        self.yawn_smile_seen = self.yawn_smile_seen or smiling
        # Un episodio que mostró forma de sonrisa solo puede contarse como bostezo si aparece después la
        # señal propia del bostezo (caída de mandíbula); si no, al cerrar la boca (frames de tolerancia) la
        # forma deja de ser de sonrisa y el episodio se colaba como bostezo.
        jaw_drop = (shape[1] - self.profile.neutral_jaw
                    if shape is not None and self.profile.neutral_jaw is not None else None)
        vetoed = smiling or (self.yawn_smile_seen and not (jaw_drop is not None and jaw_drop >= self.SMILE_MAX_JAW_DROP))
        sustained = [start is not None and now - start >= min_seconds
                     for start, (_, _, min_seconds) in zip(self.yawn_run_start, self.yawn_tiers)]
        if sustained[self.YAWN_TIER_EXAGGERATED] and not vetoed:
            self.yawn_exaggerated = True
        if any(sustained) and not self.yawn_counted and not vetoed:
            self.yawn_counted = True
            self.yawn_count += 1
            if self._on_yawn:
                self._on_yawn(self.yawn_count)

        if self.yawn_run_start[self.YAWN_TIER_MICRO] is None:      # fin del episodio
            # El episodio se cierra YAWN_GAP_FRAMES frames después de que la boca baje del umbral:
            # el evento se registra en el último frame con la boca abierta, con la duración de la apertura
            start, end = self.yawn_episode_start, self.yawn_last_open
            duration = end - start if start is not None and end is not None else None
            if self.yawn_counted:
                if not self.yawn_exaggerated:
                    self.micro_yawn_count += 1
                if duration is not None:
                    self.yawn_durations.append(duration)
                self._log_event("BOSTEZO" if self.yawn_exaggerated else "MICRO_BOSTEZO",
                                self.perclos_val, self.has_glasses, ear, duration, end_time=end)
                self.yawn_cooldown_until = now + self.YAWN_COOLDOWN_SECONDS
            elif self.yawn_smile_seen and start is not None:
                self.smile_count += 1
                self._log_event("SONRISA", self.perclos_val, self.has_glasses, ear, duration, end_time=end)
            self.yawn_run_start[self.YAWN_TIER_EXAGGERATED] = None
            self.yawn_counted = False
            self.yawn_exaggerated = False
            self.yawn_episode_start, self.yawn_smile_seen, self.yawn_last_open = None, False, None

        is_yawning = self.yawn_counted
        # Solo un bostezo confirmado bloquea parpadeos (hablar no debe bloquearlos)
        return is_yawning, is_yawning or now < self.yawn_cooldown_until

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

    def _update_blinks(self, ear, yawn_blocks_blinks, occluded, eye_shut, now):
        """Parpadeo como caída transitoria respecto a la referencia local, con histéresis.
        `occluded` NO se usa para descartar parpadeos: el umbral de deformación (0.08 IPD) se estimó con un
        solo sujeto y en otro (S02, sesiones 20261006_114449 / _114612) marcaba como ocluido el 15-37 % de
        los frames sin manos en la cara (giros de cabeza), descartando parpadeos reales."""
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
                self.blink_peak_seen, self.blink_split = False, None
                self.blink_max_head_speed = 0.0
            self.blink_dip = min(self.blink_dip, ear)
            self.blink_max_head_speed = max(self.blink_max_head_speed, self.head_speed or 0.0)
            self.blink_closed_frames += 1
            if self.profile.closed_level_measured:
                self._split_burst(ear, ref, yawn_blocks_blinks, now)
        elif self.blink_closed_frames > 0:
            self._classify_closure_episode(ear, ref, yawn_blocks_blinks, now, self.blink_closed_frames, self.blink_dip)
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
            self._log_event("PARPADEO_DESCARTADO_GIRO", self.perclos_val, self.has_glasses, ear, duration,
                            end_time=end_time)
            return
        if duration < self.LONG_BLINK_SECONDS:
            self.blink_count += 1
            self.blink_durations.append(duration)
            self._log_event("PARPADEO", self.perclos_val, self.has_glasses, ear, duration)
            if self._on_blink:
                self._on_blink(self.blink_count)
        elif self.profile.closure(dip) >= self.LONG_BLINK_MIN_CLOSURE:
            self.long_blink_count += 1
            self.blink_durations.append(duration)
            self._log_event("PARPADEO_PROLONGADO", self.perclos_val, self.has_glasses, ear, duration)
        else:
            return                            # entrecerrar los ojos: ni parpadeo ni cierre
        self.blink_refractory = self.BLINK_REFRACTORY_FRAMES

    def _update_eyes(self, ear, yawn_blocks_blinks, occluded, now, pose_valid=True):
        """Parpadeos (referencia local), PERCLOS P80 y micro-sueño. Devuelve micro-sueño activo.
        El % de cierre se mide entre los niveles abierto y cerrado calibrados del sujeto: entrecerrar
        los ojos (al bostezar, hablar o mirar abajo) no llega al 80 % y no cuenta como cierre.
        Con la postura fuera de rango (pose_valid=False) no se cuentan parpadeos ni PERCLOS (la apertura 2D
        del ojo no es fiable); el micro-sueño se sigue evaluando por seguridad."""
        closure = self.profile.closure(ear)
        if pose_valid:
            self._update_blinks(ear, yawn_blocks_blinks, occluded, closure >= self.MICROSLEEP_EXIT_CLOSURE, now)
            self._update_perclos(closure >= self.P80_CLOSURE, now)
        else:
            self.blink_closed, self.blink_closed_frames = False, 0   # se descarta el episodio en curso
            self._perclos_last_t = None                               # el hueco no pesa en el PERCLOS

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
            self._log_event("MICRO_SUENO", self.perclos_val, self.has_glasses, ear, now - self.closed_since)
            self._last_microsleep_log = now
        return True

    def _process_face(self, face, face3d, frame, now):
        """Procesa un rostro detectado. Devuelve (micro-sueño activo, bostezo en curso)."""
        ipd = self._update_ipd(face3d)
        self._update_head_pose(face3d, now)
        left_ear = self._eye_opening(face, self.LEFT_EYE, ipd)
        right_ear = self._eye_opening(face, self.RIGHT_EYE, ipd)
        # Promedio de ambos ojos: con max(), un reflejo en una lente enmascaraba el parpadeo del otro
        ear = (left_ear + right_ear) / 2.0
        mouth = self._mouth_opening(face, ipd)
        self._last_shape = shape = self._mouth_shape(face, ipd)

        phase = self.phase
        # Puerta de estabilidad: cabeza quieta y, si ya hay orientación, de frente
        is_stable = self.stability.update(face, 0.0 if self.pose_frontal else float("inf"))

        if phase == self.FASE_MARCAS:
            # Calibración manual: se acumulan los frames de los tramos marcados por el investigador
            # (sin puerta de estabilidad: el tramo lo eligió una persona; la mediana absorbe frames sueltos)
            n0, n1, c0, c1, _ = calibration_marks.frame_ranges(self.manual_marks)
            index = self.frames_total - 1
            if n0 <= index <= n1:
                self.profile.add_sample(ear, mouth, ipd, shape, auto_finish=False)
                if self._last_axes is not None:
                    self._pose_samples.append(self._last_axes)
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
            if self._last_axes is not None:
                self._pose_samples.append(self._last_axes)
            if self.profile.add_sample(ear, mouth, ipd, shape):
                self._lock_pose_reference()
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
            if self._closed_phase_started is None:
                self._closed_phase_started = now
            self.profile.observe_closed_phase(ear)
            done = False
            if ear < self.profile.open_ear_baseline * self.CLOSED_CAPTURE_FACTOR:
                done = self.profile.add_closed_sample(ear)
            if not done and now - self._closed_phase_started > self.CLOSED_CALIBRATION_TIMEOUT:
                self.profile.finish_closed_on_timeout(self.CLOSED_FALLBACK_RATIO)
                done = True
                if not self.profile.closed_level_measured:
                    print(f"[AVISO] No se detectaron los ojos cerrados en {self.CLOSED_CALIBRATION_TIMEOUT:.0f} s: se usa "
                          f"el nivel de reserva ({self.CLOSED_FALLBACK_RATIO} x ojo abierto), NO medido. "
                          f"Pulsa C para repetir la calibración.")
            if done:
                self._beep()
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
        is_yawning, yawn_blocks_blinks = self._update_yawn(mouth, now, ear, shape)
        pose_valid = self._track_pose_range(now)
        is_microsleep = self._update_eyes(ear, yawn_blocks_blinks, False, now, pose_valid)
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
        cv2.putText(img, f"prolong. {self.long_blink_count}", (70, 115), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (120, 120, 130), 1)

        cv2.putText(img, "BOSTEZOS", (140, 85), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (160, 160, 170), 1)
        cv2.putText(img, f"{self.yawn_count}", (140, 115), cv2.FONT_HERSHEY_DUPLEX, 0.9, (0, 230, 255), 2)
        cv2.putText(img, f"micro {self.micro_yawn_count}", (180, 115), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (120, 120, 130), 1)

        cv2.line(img, (30, 135), (panel_w - 15, 135), (50, 50, 60), 1)

        # Tarjeta 2: gafas según la condición declarada (--condicion)
        cv2.putText(img, "GAFAS (DECLARADAS)", (30, 160), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (160, 160, 170), 1)
        if has_glasses is None:
            status_gafas, color_gafas = "NO DECLARADO", (120, 120, 130)
        else:
            status_gafas = "CON GAFAS" if has_glasses else "SIN GAFAS"
            color_gafas = (0, 255, 200) if has_glasses else (180, 180, 180)
        cv2.putText(img, status_gafas, (30, 185), cv2.FONT_HERSHEY_DUPLEX, 0.6, color_gafas, 1)

        cv2.line(img, (30, 205), (panel_w - 15, 205), (50, 50, 60), 1)

        # Tarjeta 3: Indicador PERCLOS con Barra de Progreso
        cv2.putText(img, "PERCLOS (FATIGA)", (30, 230), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (160, 160, 170), 1)
        if self.perclos_total_time < self.perclos_min_seconds:
            cv2.putText(img, "calibrando", (160, 230), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (120, 120, 130), 1)

        color_perclos = ((0, 255, 120) if perclos_val < self.PERCLOS_WARN_PCT
                         else ((0, 200, 255) if perclos_val < self.PERCLOS_ALERT_PCT else (0, 0, 255)))
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
        if self.phase == self.FASE_MONITOREO and not self.eye_pose_valid:
            cv2.putText(img, "POSTURA FUERA DE RANGO", (30, h - 50), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 140, 255), 1)
        fps = self.session.current_fps if self.session else None
        if fps:
            cv2.putText(img, f"{fps:.0f} FPS", (panel_w - 60, h - 30), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (120, 120, 130), 1)
        self._draw_clock(img)

    def _draw_clock(self, img):
        """Tiempo de la sesión (= columna t de traza.csv y t_s de eventos.csv; en un vídeo, el segundo de
        la grabación) y número de frame, para anotar a mano el momento de un evento y buscarlo en la traza."""
        h, w, _ = img.shape
        minutes, seconds = divmod(self._now, 60)
        lines = [f"t = {self._now:.2f} s  ({int(minutes):02d}:{seconds:05.2f})", f"frame {self.frames_total - 1}"]
        if self._is_video_file():
            lines.append("[ESPACIO] pausa")
        x0, y0 = w - 265, 15
        cv2.rectangle(img, (x0, y0), (w - 15, y0 + 22 * len(lines) + 12), (20, 20, 25), -1)
        for i, text in enumerate(lines):
            cv2.putText(img, text, (x0 + 12, y0 + 27 + 22 * i), cv2.FONT_HERSHEY_SIMPLEX, 0.5 if i == 0 else 0.42,
                        (255, 255, 255) if i == 0 else (160, 160, 170), 1)

    def _draw_calibration_overlay(self, img, title, progress, subtitle="MIRA AL FRENTE"):
        """Banner de la fase de calibración con barra de progreso, a la derecha del panel lateral."""
        h, w, _ = img.shape
        x0, x1, y0, y1 = 275, w - 15, h - 100, h - 15
        if x1 - x0 < 250:
            x0 = 15

        overlay = img.copy()
        cv2.rectangle(overlay, (x0, y0), (x1, y1), (20, 20, 25), -1)
        cv2.addWeighted(overlay, 0.8, img, 0.2, 0, img)
        cv2.rectangle(img, (x0, y0), (x1, y1), (0, 200, 255), 1)

        for text, y, scale in [(title, y0 + 28, 0.55), (subtitle, y0 + 52, 0.5)]:
            (text_w, _), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_DUPLEX, scale, 1)
            cv2.putText(img, text, (x0 + (x1 - x0 - text_w) // 2, y), cv2.FONT_HERSHEY_DUPLEX, scale, (255, 255, 255), 1)

        bar_x0, bar_x1, bar_y = x0 + 20, x1 - 20, y1 - 22
        cv2.rectangle(img, (bar_x0, bar_y), (bar_x1, bar_y + 8), (50, 50, 60), -1)
        cv2.rectangle(img, (bar_x0, bar_y), (bar_x0 + int((bar_x1 - bar_x0) * progress), bar_y + 8), (0, 200, 255), -1)

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

    def start(self):
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
        self.session.open_trace(self.TRACE_HEADER)

        while True:
            success, img = cap.read()
            if not success:
                break

            self._now = self.frames_total / native_fps if use_video_clock else time.time() - wall_start
            self.frames_total += 1
            self.session.tick()
            if self._manual_pending and self.frames_total - 1 >= calibration_marks.frame_ranges(self.manual_marks)[4]:
                self._finish_manual_calibration(self._now)

            clean_frame = img.copy()
            img, faces = self.detector.findFaceMesh(img, draw=False)

            is_microsleep_active, is_yawning_active = False, False
            if faces:
                self.frames_with_face += 1
                is_microsleep_active, is_yawning_active = self._process_face(
                    faces[0], self.detector.faces3d[0], clean_frame, self._now)
            else:
                self.stability.reset()   # al volver el rostro se exigen de nuevo 15 frames estables

            # Renderizado del HUD Limpio
            self._draw_hud(img, self.perclos_val, self.has_glasses, is_microsleep_active, is_yawning_active)
            phase = self.phase
            if phase == self.FASE_ROSTRO:
                self._draw_calibration_overlay(img, "PASO 1/2: ANALIZANDO ROSTRO...", self.profile.progress)
            elif phase == self.FASE_CIERRE:
                self._draw_calibration_overlay(img, "PASO 2/2: CIERRA LOS OJOS...", self.profile.closed_progress,
                                               subtitle="ABRELOS AL OIR EL PITIDO")
            elif phase == self.FASE_REAPERTURA:
                self._draw_calibration_overlay(img, "ABRE LOS OJOS", 1.0, subtitle="EL CONTEO EMPIEZA AL ABRIRLOS")
            elif phase == self.FASE_MARCAS:
                start_frame = calibration_marks.frame_ranges(self.manual_marks)[4]
                self._draw_calibration_overlay(img, "CALIBRACION MANUAL (MARCAS DEL VIDEO)",
                                               (self.frames_total - 1) / max(start_frame, 1),
                                               subtitle=f"LA PRUEBA EMPIEZA EN t = {self.manual_marks['inicio_prueba']['s']:.2f} s")

            cv2.imshow("Fatigue Framework Monitor", img)
            key = cv2.waitKey(1) & 0xFF
            if key == ord(' ') and self._is_video_file():
                # Pausa (solo vídeos: el reloj es el del archivo, así que pausar no altera las mediciones)
                key = 0
                while key not in (ord(' '), ord('q')):
                    key = cv2.waitKey(50) & 0xFF
                    if cv2.getWindowProperty("Fatigue Framework Monitor", cv2.WND_PROP_VISIBLE) < 1:
                        key = ord('q')       # ventana cerrada durante la pausa
                self.session.reset_tick()    # el tiempo en pausa no cuenta en los FPS de procesamiento
            if key == ord('q'):
                break
            if key == ord('c'):
                self.recalibrate("manual", full=True)

        cap.release()
        cv2.destroyAllWindows()
        self._finish_session(native_fps, use_video_clock)

    def _finish_session(self, native_fps, use_video_clock):
        self._close_pose_interval()
        metadata = self.session.finish({
            "duracion_s": round(self._now, 2),
            "calibracion_modo": "manual" if self.manual_marks else "automatica",
            "inicio_monitoreo_s": None if self.test_start_s is None else round(self.test_start_s, 3),
            "frames": self.frames_total,
            "frames_con_rostro": self.frames_with_face,
            "gafas_final": self.has_glasses,
            "parpadeos": self.blink_count,
            "parpadeos_prolongados": self.long_blink_count,
            # Proporción de parpadeos de cierre largo (Caffier et al., 2003) y duración media del parpadeo
            # (Ingre et al., 2006); incluyen parpadeos normales y prolongados, no micro-sueños
            "proporcion_parpadeos_prolongados": (round(self.long_blink_count / len(self.blink_durations), 4)
                                                 if self.blink_durations else None),
            "duracion_media_parpadeo_s": (round(float(np.mean(self.blink_durations)), 4)
                                          if self.blink_durations else None),
            "bostezos": self.yawn_count,
            "micro_bostezos": self.micro_yawn_count,
            "duracion_media_bostezo_s": (round(float(np.mean(self.yawn_durations)), 4)
                                         if self.yawn_durations else None),
            "parpadeos_descartados_giro": self.fast_turn_rejected,
            "sonrisas_descartadas": self.smile_count,
            "tiempo_postura_fuera_de_rango_s": round(self.pose_out_time, 2),
            "perclos_final_pct": round(self.perclos_val, 2),
            "recalibraciones": self.recalibration_count,
            "ojo_abierto_ref": self.profile.open_ear_baseline,
            "ojo_cerrado_ref": self.profile.closed_ear_level,
            "ojo_cerrado_medido": self.profile.closed_level_measured,
            "ojo_cerrado_proporcion": self.profile.closed_ratio,
            "ojo_cerrado_reutilizado_en_recalibracion": self.profile.closed_level_reused,
            "paso_ojos_cerrados_apertura_min_ratio": self.profile.closed_phase_min_ratio,
        })

        # Duraciones (parpadeo, micro-sueño, PERCLOS) van en segundos; solo el mínimo de frames de un parpadeo
        # y el periodo refractario siguen en frames y suponen fps_estimate
        effective_fps = native_fps if use_video_clock else metadata["rendimiento"]["fps_procesamiento_medio"]
        if effective_fps and abs(effective_fps - self.fps_estimate) > 0.15 * self.fps_estimate:
            print(f"[AVISO] La sesión fue a {effective_fps:.1f} fps, pero el periodo refractario del parpadeo "
                  f"({self.BLINK_REFRACTORY_FRAMES} frames) supone {self.fps_estimate} fps: equivale a "
                  f"{self.BLINK_REFRACTORY_FRAMES / effective_fps:.2f} s en vez de "
                  f"{self.BLINK_REFRACTORY_FRAMES / self.fps_estimate:.2f} s.")
