# glasses_detector.py
import cv2
import numpy as np


class ROIGlassesDetector:
    """
    Detector de gafas post-calibración, en tres pasos:

    1. observe_anatomy(): durante la calibración facial acumula la posición de landmarks rígidos
       (puente nasal superior 168/6, comisuras 33/133/362/263, párpados inferiores 145/374) en un
       sistema canónico: origen entre los centros de los ojos, eje x a lo largo de la línea de ojos,
       unidad = distancia entre centros de los ojos (IPD).
    2. lock_roi(): con las medianas de esas posiciones fija ROIs ajustadas a la anatomía del sujeto:
         * Puente nasal: piel lisa sin gafas, puente de la montura con gafas.
         * Bajo los ojos: piel sin gafas, aro inferior / borde de la lente con gafas.
         * Mejillas (referencia): piel que las gafas nunca cubren.
    3. analyze(): en frames neutros posteriores, filtro bilateral + CLAHE + Canny + cierre morfológico.
       score = densidad de bordes del ROI de gafas - densidad de la piel de referencia (exceso de
       bordes atribuible a la montura, independiente de textura de piel, iluminación y nitidez).
       La decisión es la MEDIANA de `analysis_frames` frames estables (neutraliza reflejos
       puntuales en las lentes); discard_samples() reinicia la recogida si se pierde la estabilidad.
    4. watch(): vigilancia durante el monitoreo con histéresis estricta: el score debe quedar por
       encima de on_threshold durante switch_frames frames consecutivos para indicar CON GAFAS, o por
       debajo de off_threshold otros tantos para SIN GAFAS. break_streak() reinicia la racha cuando el
       frame no es apto (inestable o no neutro). start_recheck() repite solo el paso 3.

    Umbrales empíricos (score del HUD medido en pruebas reales): sin gafas 3.0-4.5 %, con gafas
    10.0-12.5 %. Punto medio 7.0 % para encender; 6.0 % para apagar (banda de histéresis de 1 %).
    """

    CANON_IPD = 100                          # px por IPD en la imagen normalizada
    CANON_W, CANON_H = 220, 200              # cubre x en [-1.1, 1.1] IPD, y en [-0.6, 1.4] IPD
    ORIGIN = np.array([110.0, 60.0])         # posición del punto medio entre ojos

    ANATOMY_LANDMARKS = [168, 6, 133, 362, 33, 263, 145, 374]
    # Landmarks rígidos para medir deformación (sin párpados, que se mueven al parpadear). Una mano
    # sobre la nariz o las gafas en movimiento desplazan el puente nasal respecto a los ojos.
    RIGID_ANATOMY = [168, 6, 133, 362, 33, 263]
    BRIDGE_WEIGHT = 0.6

    def __init__(self, on_threshold=7.0, off_threshold=6.0, switch_frames=10, analysis_frames=30,
                 display_smoothing=0.15, canny_low=40, canny_high=110, clahe_clip=2.0, close_kernel=(5, 3)):
        self.on_threshold = on_threshold      # score (%) por encima del cual se pasa a CON GAFAS
        self.off_threshold = off_threshold    # score (%) por debajo del cual se pasa a SIN GAFAS
        self.switch_frames = switch_frames    # frames consecutivos necesarios para cambiar de estado
        self.analysis_frames = analysis_frames
        self.display_smoothing = display_smoothing   # EMA solo para mostrar el score en el HUD
        self.canny_low = canny_low
        self.canny_high = canny_high
        # Teselas grandes (2x2): cada una incluye ojo y montura, así CLAHE no estira el contraste
        # de una tesela de piel lisa (con 4x4 amplificaba el ruido de la piel hasta saturar el ROI)
        self._clahe = cv2.createCLAHE(clipLimit=clahe_clip, tileGridSize=(2, 2))
        # Kernel más ancho que alto: une los bordes fragmentados de monturas finas/metálicas,
        # que son estructuras mayormente horizontales tras la normalización
        self._close_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, close_kernel)
        self.reset()

    def reset(self):
        self._anatomy_samples = []
        self._anatomy_ref = None              # posiciones canónicas medianas de ANATOMY_LANDMARKS
        self.regions = None                   # dict de ROIs (x0, x1, y0, y1) en unidades de IPD
        self.has_glasses = False
        self.score = None                     # exceso de densidad (%), visible en el HUD para calibrar
        self.start_recheck()

    def start_recheck(self):
        """Repite solo la decisión (paso 3) con las ROIs ya fijadas; has_glasses se mantiene hasta decidir."""
        self._scores = []
        self.is_decided = False
        self.break_streak()

    def discard_samples(self):
        """La estabilidad se rompió durante el paso 3: se descartan los frames acumulados."""
        self._scores = []

    def break_streak(self):
        """Frame no apto durante el monitoreo: la racha de frames consecutivos vuelve a cero."""
        self.switch_streak = 0

    def _hysteresis_state(self, score, current):
        """Estado que indica `score` partiendo de `current` (banda muerta entre off y on)."""
        return score >= self.off_threshold if current else score > self.on_threshold

    @property
    def progress(self):
        return min(len(self._scores) / float(self.analysis_frames), 1.0)

    # ------------------------------------------------------------------ geometría

    def _canonical_transform(self, pts):
        """Matriz afín imagen -> canónica. Ojos ordenados por x de imagen (robusto a vídeo espejado)."""
        centers = sorted([(pts[33] + pts[133]) / 2.0, (pts[362] + pts[263]) / 2.0], key=lambda c: c[0])
        left, right = centers
        v = right - left
        dist = float(np.hypot(v[0], v[1]))
        if dist < 10:
            return None
        angle = np.arctan2(v[1], v[0])
        s = self.CANON_IPD / dist
        cos_a, sin_a = np.cos(angle) * s, np.sin(angle) * s
        R = np.array([[cos_a, sin_a], [-sin_a, cos_a]])
        t = self.ORIGIN - R @ ((left + right) / 2.0)
        return np.hstack([R, t.reshape(2, 1)])

    def _canonical_anatomy(self, face):
        """Posición canónica (unidades de IPD) de ANATOMY_LANDMARKS, o None."""
        pts = np.asarray(face, dtype=np.float64)
        M = self._canonical_transform(pts)
        if M is None:
            return None
        return (pts[self.ANATOMY_LANDMARKS] @ M[:, :2].T + M[:, 2] - self.ORIGIN) / self.CANON_IPD

    def observe_anatomy(self, face):
        """Paso 1: registra la posición canónica de los landmarks anatómicos."""
        canon = self._canonical_anatomy(face)
        if canon is not None:
            self._anatomy_samples.append(canon)

    def anatomy_deviation(self, face):
        """Máxima desviación (IPD) de los landmarks rígidos respecto a la anatomía calibrada.
        Crece con oclusiones (mano sobre la nariz), gafas en movimiento o giros fuertes de cabeza."""
        if self._anatomy_ref is None:
            return 0.0
        canon = self._canonical_anatomy(face)
        if canon is None:
            return float("inf")
        rigid = [self.ANATOMY_LANDMARKS.index(i) for i in self.RIGID_ANATOMY]
        return float(np.max(np.linalg.norm(canon[rigid] - self._anatomy_ref[rigid], axis=1)))

    def lock_roi(self):
        """Paso 2: fija las ROIs a partir de la anatomía mediana del sujeto."""
        if not self._anatomy_samples:
            return False
        self._anatomy_ref = np.median(np.array(self._anatomy_samples), axis=0)
        a = dict(zip(self.ANATOMY_LANDMARKS, self._anatomy_ref))

        inner_x = min(abs(a[133][0]), abs(a[362][0]))      # media distancia entre comisuras internas
        outer_x = max(abs(a[33][0]), abs(a[263][0]))       # media distancia entre comisuras externas
        lid_y = max(a[145][1], a[374][1])                  # párpado inferior más bajo
        bridge_y0, bridge_y1 = sorted([a[168][1], a[6][1]])
        bridge_y1 = max(bridge_y1, bridge_y0 + 0.10)

        self.regions = {
            "bridge": [(-0.6 * inner_x, 0.6 * inner_x, bridge_y0, bridge_y1)],
            "rims": [(-outer_x, -inner_x, lid_y + 0.06, lid_y + 0.36),
                     (inner_x, outer_x, lid_y + 0.06, lid_y + 0.36)],
            "skin": [(-outer_x, -0.5, lid_y + 0.55, lid_y + 0.80),
                     (0.5, outer_x, lid_y + 0.55, lid_y + 0.80)],
        }
        return True

    def _region_slice(self, region):
        x0, x1, y0, y1 = region
        ox, oy = self.ORIGIN
        u = self.CANON_IPD
        return (slice(max(0, int(oy + y0 * u)), min(self.CANON_H, int(oy + y1 * u))),
                slice(max(0, int(ox + x0 * u)), min(self.CANON_W, int(ox + x1 * u))))

    @staticmethod
    def _density(edges):
        return (np.count_nonzero(edges) / float(edges.size)) * 100.0 if edges.size else 0.0

    def _mean_density(self, edges, name):
        return float(np.mean([self._density(edges[self._region_slice(r)]) for r in self.regions[name]]))

    # ------------------------------------------------------------------ análisis

    def _measure(self, frame, face, draw_debug=False):
        """Exceso de densidad de bordes (%) del ROI de gafas sobre la piel de referencia, o None."""
        if self.regions is None:
            return None
        try:
            M = self._canonical_transform(np.asarray(face, dtype=np.float64))
            if M is None:
                return None
            band = cv2.warpAffine(frame, M, (self.CANON_W, self.CANON_H),
                                  flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)

            # Filtro bilateral antes de CLAHE: elimina la textura de la piel conservando los bordes
            # fuertes de la montura, para que CLAHE no realce poros, ruido de sensor ni compresión
            gray = cv2.bilateralFilter(cv2.cvtColor(band, cv2.COLOR_BGR2GRAY), 7, 30, 7)
            gray = self._clahe.apply(gray)
            blurred = cv2.GaussianBlur(gray, (5, 5), 0)
            edges = cv2.Canny(blurred, self.canny_low, self.canny_high)
            edges = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, self._close_kernel)

            if draw_debug:
                self._draw_debug(frame, edges)

            glasses_density = (self.BRIDGE_WEIGHT * self._mean_density(edges, "bridge")
                               + (1.0 - self.BRIDGE_WEIGHT) * self._mean_density(edges, "rims"))
            return glasses_density - self._mean_density(edges, "skin")
        except Exception as e:
            print(f"[ERROR GAFAS DETECTOR] {e}")
            return None

    def analyze(self, frame, face, draw_debug=False):
        """Paso 3: analiza un frame neutro. Devuelve True en el frame en que se toma la decisión."""
        if self.is_decided:
            return False
        score = self._measure(frame, face, draw_debug)
        if score is None:
            return False
        self._scores.append(score)
        # Mediana (no media): un reflejo en la lente durante unos frames no mueve la decisión
        self.score = float(np.median(self._scores))

        if len(self._scores) < self.analysis_frames:
            return False
        # Tras reset() has_glasses es False (umbral 7.0 %); en una verificación se parte del estado
        # previo, así que un score en la banda 6-7 % mantiene la decisión anterior
        self.has_glasses = self._hysteresis_state(self.score, self.has_glasses)
        self.is_decided = True
        print(f"[GAFAS] Decisión: {'CON GAFAS' if self.has_glasses else 'SIN GAFAS'} "
              f"(mediana {self.score:.2f}% / encendido > {self.on_threshold:.1f}%, apagado < {self.off_threshold:.1f}%)")
        return True

    def watch(self, frame, face, draw_debug=False):
        """Vigilancia en un frame estable y neutro del monitoreo. True si hay que recalibrar: el score
        contradice el estado actual durante switch_frames frames consecutivos."""
        if not self.is_decided:
            return False
        score = self._measure(frame, face, draw_debug)
        if score is None:
            self.break_streak()
            return False

        self.score = score if self.score is None else self.score + self.display_smoothing * (score - self.score)
        if self._hysteresis_state(score, self.has_glasses) != self.has_glasses:
            self.switch_streak += 1
        else:
            self.switch_streak = 0
        return self.switch_streak >= self.switch_frames

    def _draw_debug(self, frame, edges):
        """Muestra la imagen canónica de bordes con las ROIs (cian: gafas, gris: piel de referencia)."""
        h, w = frame.shape[:2]
        debug = cv2.cvtColor(edges, cv2.COLOR_GRAY2BGR)
        for name, color in [("bridge", (255, 255, 0)), ("rims", (255, 255, 0)), ("skin", (150, 150, 150))]:
            for region in self.regions[name]:
                ys, xs = self._region_slice(region)
                cv2.rectangle(debug, (xs.start, ys.start), (xs.stop, ys.stop), color, 1)
        dbg_w, dbg_h = 165, 150
        if w > dbg_w + 20 and h > dbg_h + 20:
            frame[10:10 + dbg_h, w - dbg_w - 10:w - 10] = cv2.resize(debug, (dbg_w, dbg_h))
