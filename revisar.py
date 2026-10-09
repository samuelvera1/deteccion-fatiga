# revisar.py
"""
Revisión de vídeos con barra de tiempo. Dos modos:

  1. Marcar la calibración de un vídeo ANTES de analizarlo. Protocolo de grabación: "mira a la cámara",
     "cierra los ojos", "ábrelos" y empieza la prueba.
         python revisar.py --video "C:\\...\\video.mp4"
     N marca inicio y fin del tramo neutro, C inicio y fin del tramo con ojos cerrados y P el inicio de
     la prueba. Se guardan junto al vídeo (<video>.calibracion.json) y main.py las usa al analizarlo.

  2. Revisar una sesión ya analizada y anotar los eventos reales:
         python revisar.py "sesiones/<sesion>" --ciego    # REFERENCIA -> anotaciones_ciego.csv
         python revisar.py "sesiones/<sesion>"            # revisión   -> anotaciones_revision.csv
     La referencia para la validación se anota siempre con --ciego (oculta lo detectado por el sistema),
     siguiendo docs/guia_anotacion.md. Sin --ciego es una revisión para encontrar errores, no referencia.
     B / Y / K / M anotan parpadeo / bostezo / micro-bostezo / micro-sueño como intervalo (tecla al
     inicio y otra vez al final). X marca un tramo y pide un comentario: con --ciego es NO_EVALUABLE (cara
     tapada, fuera de cuadro...; la evaluación lo excluye); sin --ciego, PROBLEMA (nota de un error).
     --anotador NOMBRE solo hace falta si anota otra persona además del anotador principal (acuerdo entre
     anotadores): sus anotaciones van a anotaciones_ciego_NOMBRE.csv.

El análisis (main.py) recorre el vídeo de principio a fin porque tiene memoria (referencia local del
parpadeo, ventana de 60 s del PERCLOS, contadores): saltar dentro del análisis falsearía los resultados.
Este revisor no analiza nada.

Carga: el vídeo se lee entero en orden, como el análisis, para que el frame N mostrado sea exactamente
el frame N de la traza aunque el vídeo tenga fps variable (la cámara de Windows graba así; saltar con
cap.set supone fps constantes). La lectura va en segundo plano (la ventana se abre al instante), la
compresión de los frames en paralelo, y el resultado se guarda en cache_revisor/ para que la siguiente
vez abra en ~1 s (en un vídeo de 33 s a 720p: ~31 s cargando frame a frame frente a ~12 s así).
"""
import argparse
import copy
import csv
import json
import os
import sys
import threading
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import cv2
import numpy as np

import calibration_marks

WINDOW = "Revision de video"
MAX_VIEW_W, MAX_VIEW_H = 900, 510   # tamaño máximo del vídeo en pantalla (y en memoria)
PANEL_W = 400                       # panel lateral derecho
TIMELINE_H = 100
JPEG_QUALITY = 85
CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache_revisor")
FONT = cv2.FONT_HERSHEY_SIMPLEX
LINE_H = 15

WHITE, GRAY, DIM = (255, 255, 255), (165, 165, 175), (110, 110, 120)
OK_COLOR, WARN_COLOR = (0, 220, 120), (0, 170, 255)
EVENT_COLORS = {
    "PARPADEO": (255, 200, 0), "PARPADEO_PROLONGADO": (255, 110, 0),
    "BOSTEZO": (0, 230, 255), "MICRO_BOSTEZO": (0, 150, 200),
    "MICRO_SUENO": (0, 0, 255), "SONRISA": (200, 0, 200),
    "PARPADEO_DESCARTADO_GIRO": (130, 130, 130),
}
STATE_COLORS = {"sin_rostro": (40, 40, 130), "calibrando": (95, 95, 95), "marcas": (150, 100, 40),
                "postura": (0, 110, 200), "midiendo": (60, 130, 60)}
NEUTRAL_COLOR, CLOSED_COLOR = (80, 200, 80), (200, 90, 170)
# X = PROBLEMA: tramo donde algo va mal (error del sistema, cara tapada, mala luz...), con comentario
# Micro-bostezo (K): bostezo contenido o con poca apertura bucal; el sistema lo separa con umbrales
# (MICRO_BOSTEZO), el anotador por apreciación visual.
ANNOTATION_KEYS = {ord("b"): "PARPADEO", ord("y"): "BOSTEZO", ord("k"): "MICRO_BOSTEZO",
                   ord("m"): "MICRO_SUENO", ord("x"): "PROBLEMA"}
PROBLEM_COLOR = (0, 140, 255)
# En modo ciego (referencia) la X marca un tramo NO_EVALUABLE: algo que impide ver los ojos o la boca (cara
# tapada, fuera de cuadro...). Se decide solo por lo que se ve, sin ver el sistema, y la evaluación excluye
# ese tramo. Fuera del modo ciego la X es un PROBLEMA (nota para el análisis de errores).
COMMENTED_TYPES = {"PROBLEMA", "NO_EVALUABLE"}
MAX_COMMENT = 60
# Todas las anotaciones son intervalos (tecla al inicio y otra vez al final): así la referencia humana
# tiene duración, comparable con la Duracion_s del sistema (también la del parpadeo, ~0.1-0.4 s).
INTERVAL_TYPES = set(ANNOTATION_KEYS.values()) | {"NO_EVALUABLE"}
KEY_FOR_TYPE = {**{kind: chr(key).upper() for key, kind in ANNOTATION_KEYS.items()}, "NO_EVALUABLE": "X"}
# ciego: 1 si la anotación se hizo en modo ciego (sin ver al sistema). Solo esas sirven de referencia.
ANNOTATION_HEADER = ["t_s", "frame", "tipo", "fin_t_s", "fin_frame", "comentario", "ciego", "anotador",
                     "registrado"]


def safe_name(text):
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in text)


def annotations_file(session_dir, blind, annotator=None):
    """anotaciones_ciego.csv (referencia, modo ciego) o anotaciones_revision.csv (revisión viendo el sistema).
    annotator: solo para un anotador adicional al principal (acuerdo entre anotadores) -> ..._NOMBRE.csv."""
    name = "anotaciones_" + ("ciego" if blind else "revision")
    if annotator:
        name += "_" + safe_name(annotator)
    return os.path.join(session_dir, name + ".csv")


class FrameStore:
    """Frames del vídeo en orden de lectura, comprimidos en memoria. Carga en segundo plano con caché."""

    def __init__(self, source):
        self.source = source
        cap = cv2.VideoCapture(source)
        if not cap.isOpened():
            sys.exit(f"No se pudo abrir el vídeo: {source}")
        self.fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        self.expected = max(int(cap.get(cv2.CAP_PROP_FRAME_COUNT)), 1)
        cap.release()
        self.frames = []
        self.done = False
        self.from_cache = False
        stat = os.stat(source)
        stem = safe_name(os.path.splitext(os.path.basename(source))[0])
        key = f"{stem}_{stat.st_size}_{int(stat.st_mtime)}_{MAX_VIEW_W}x{MAX_VIEW_H}_q{JPEG_QUALITY}"
        self._cache_data = os.path.join(CACHE_DIR, key + ".bin")
        self._cache_index = os.path.join(CACHE_DIR, key + ".idx.npy")
        if not self._load_cache():
            threading.Thread(target=self._load, daemon=True).start()

    @property
    def loaded(self):
        return len(self.frames)

    @property
    def total(self):
        """Frames del vídeo: el número exacto al terminar la carga; antes, el que declara el archivo."""
        return len(self.frames) if self.done else max(self.expected, len(self.frames))

    def get(self, index):
        if index >= len(self.frames):
            return None
        return cv2.imdecode(self.frames[index], cv2.IMREAD_COLOR)

    @staticmethod
    def _encode(img):
        h, w = img.shape[:2]
        scale = min(MAX_VIEW_W / w, MAX_VIEW_H / h, 1.0)
        if scale < 1.0:
            img = cv2.resize(img, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_LINEAR)
        return cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])[1].ravel()

    def _load(self):
        # Lectura en orden en este hilo; la compresión, en paralelo (OpenCV libera el GIL)
        cap = cv2.VideoCapture(self.source)
        pending = deque()
        with ThreadPoolExecutor(max(2, (os.cpu_count() or 4) - 2)) as pool:
            while True:
                ok, img = cap.read()
                if not ok:
                    break
                pending.append(pool.submit(self._encode, img))
                while pending and (pending[0].done() or len(pending) > 64):
                    self.frames.append(pending.popleft().result())
            while pending:
                self.frames.append(pending.popleft().result())
        cap.release()
        self.done = True
        self._save_cache()

    def _load_cache(self):
        if not (os.path.exists(self._cache_data) and os.path.exists(self._cache_index)):
            return False
        try:
            offsets = np.load(self._cache_index)
            data = np.fromfile(self._cache_data, dtype=np.uint8)
        except (OSError, ValueError):
            return False
        if len(offsets) < 2 or offsets[-1] != data.size:
            return False
        self.frames = [data[offsets[i]:offsets[i + 1]] for i in range(len(offsets) - 1)]
        self.done = self.from_cache = True
        return True

    def _save_cache(self):
        try:
            os.makedirs(CACHE_DIR, exist_ok=True)
            offsets = np.concatenate([[0], np.cumsum([f.size for f in self.frames])]).astype(np.int64)
            tmp = self._cache_data + ".tmp"
            with open(tmp, "wb") as f:
                for frame in self.frames:
                    f.write(frame.tobytes())
            os.replace(tmp, self._cache_data)
            np.save(self._cache_index, offsets)
        except OSError as e:
            print(f"[AVISO] No se pudo guardar la caché del vídeo: {e}")


class Viewer:
    """Ventana común: vídeo a la izquierda, panel lateral a la derecha, barra de tiempo abajo."""

    def __init__(self, source):
        self.store = FrameStore(source)
        self.fps = self.store.fps
        self.pos, self.playing = 0, False
        self.frame = None
        self._shown = -1                 # frame decodificado en self.frame
        self._dragging = False
        self._timeline = None
        self._timeline_key = None
        self._view_h, self._canvas_w = MAX_VIEW_H, MAX_VIEW_W + PANEL_W
        self._load_reported = False

    # ------------------------------------------------------------------ a implementar por cada modo

    def panel_items(self):
        raise NotImplementedError

    def draw_static_rows(self, bg, width):
        """Filas fijas de la barra (dependen solo de los datos)."""

    def draw_dynamic_rows(self, bar, width):
        """Filas que cambian al marcar o anotar."""

    def handle_key(self, key):
        return False

    def typing(self):
        """True mientras se escribe un texto en la ventana (las teclas no navegan)."""
        return False

    def handle_text(self, key):
        pass

    def on_loaded(self):
        """Se llama una vez al terminar de cargar el vídeo."""

    # ------------------------------------------------------------------ navegación

    def t(self, frame=None):
        return (self.pos if frame is None else frame) / self.fps

    def seek(self, frame):
        self.pos = int(np.clip(frame, 0, self.store.total - 1))

    def _refresh_frame(self):
        if self._shown != self.pos and self.pos < self.store.loaded:
            self.frame = self.store.get(self.pos)
            self._shown = self.pos

    def _advance_playback(self):
        if self.pos + 1 < self.store.loaded:
            self.pos += 1
        elif self.store.done:
            self.playing = False          # fin del vídeo

    # ------------------------------------------------------------------ barra de tiempo

    @staticmethod
    def _bar_x(width):
        return 20, width - 20

    def frame_to_x(self, frame, width):
        x0, x1 = self._bar_x(width)
        return int(x0 + (x1 - x0) * frame / max(self.store.total - 1, 1))

    def x_to_frame(self, x, width):
        x0, x1 = self._bar_x(width)
        return int(round((x - x0) / max(x1 - x0, 1) * (self.store.total - 1)))

    def _timeline_image(self, width):
        key = (width, self.store.total, self.store.done)
        if self._timeline_key != key:
            bg = np.full((TIMELINE_H, width, 3), 25, np.uint8)
            self.draw_static_rows(bg, width)
            self._timeline, self._timeline_key = bg, key
        bar = self._timeline.copy()
        x0, x1 = self._bar_x(width)
        if not self.store.done:          # parte aún sin cargar: sombreada
            xl = self.frame_to_x(self.store.loaded, width)
            bar[:, xl:x1] = (bar[:, xl:x1] * 0.35).astype(np.uint8)
        self.draw_dynamic_rows(bar, width)
        x = self.frame_to_x(self.pos, width)
        cv2.line(bar, (x, 4), (x, TIMELINE_H - 6), (0, 0, 255), 2)
        return bar

    # ------------------------------------------------------------------ dibujo

    def _common_items(self):
        minutes, seconds = divmod(self.t(), 60)
        if not self.store.done:
            state = (f"CARGANDO VIDEO {self.store.loaded * 100 // max(self.store.total, 1)}%"
                     f"  (ya puedes revisar lo cargado)", WARN_COLOR)
        elif self.playing:
            state = ("REPRODUCIENDO", OK_COLOR)
        else:
            state = ("PAUSA", WARN_COLOR)
        items = [("big", f"t = {self.t():.2f} s   ({int(minutes):02d}:{seconds:05.2f})", WHITE),
                 ("t", f"frame {self.pos} de {self.store.total - 1}", GRAY),
                 ("t",) + state]
        if self.pos >= self.store.loaded:
            items.append(("t", "este punto aun no ha cargado: espera un momento", WARN_COLOR))
        return items

    def _draw_panel(self, height):
        panel = np.full((height, PANEL_W, 3), 30, np.uint8)
        cv2.line(panel, (0, 0), (0, height), (70, 70, 80), 1)
        y = 24
        for item in self._common_items() + [("sep",)] + self.panel_items():
            kind = item[0]
            if kind == "sep":
                y += 2
                cv2.line(panel, (14, y), (PANEL_W - 14, y), (60, 60, 70), 1)
                y += 13
            elif kind == "h":
                cv2.putText(panel, item[1], (14, y), FONT, 0.44, WHITE, 1, cv2.LINE_AA)
                y += LINE_H + 1
            elif kind == "big":
                cv2.putText(panel, item[1], (14, y), FONT, 0.55, item[2], 1, cv2.LINE_AA)
                y += LINE_H + 4
            elif kind == "legend":       # palabras de colores en una línea
                x = 22
                for text, color in item[1]:
                    cv2.putText(panel, text, (x, y), FONT, 0.40, color, 1, cv2.LINE_AA)
                    x += cv2.getTextSize(text, FONT, 0.40, 1)[0][0] + 12
                y += LINE_H
            elif kind == "key":          # tecla + explicación
                cv2.putText(panel, item[1], (22, y), FONT, 0.40, WHITE, 1, cv2.LINE_AA)
                cv2.putText(panel, item[2], (92, y), FONT, 0.40, GRAY, 1, cv2.LINE_AA)
                y += LINE_H
            else:
                cv2.putText(panel, item[1], (22, y), FONT, 0.40, item[2], 1, cv2.LINE_AA)
                y += LINE_H
        return panel, y

    def render(self):
        self._refresh_frame()
        video = self.frame if self.frame is not None else np.zeros((MAX_VIEW_H, MAX_VIEW_W, 3), np.uint8)
        vh, vw = video.shape[:2]
        panel, needed = self._draw_panel(1000)
        height = max(vh, needed + 6)
        canvas = np.full((height, vw + PANEL_W, 3), 18, np.uint8)
        canvas[:vh, :vw] = video
        canvas[:, vw:] = panel[:height]
        self._view_h, self._canvas_w = height, canvas.shape[1]
        return np.vstack([canvas, self._timeline_image(canvas.shape[1])])

    # ------------------------------------------------------------------ bucle

    def _on_mouse(self, event, x, y, flags, param):
        if event == cv2.EVENT_LBUTTONDOWN and y >= self._view_h:
            self._dragging = True
        elif event == cv2.EVENT_LBUTTONUP:
            self._dragging = False
        if self._dragging and event in (cv2.EVENT_LBUTTONDOWN, cv2.EVENT_MOUSEMOVE):
            self.playing = False
            self.seek(self.x_to_frame(x, self._canvas_w))

    def run(self):
        cv2.namedWindow(WINDOW, cv2.WINDOW_AUTOSIZE)
        cv2.setMouseCallback(WINDOW, self._on_mouse)
        delay = max(1, int(1000 / self.fps) - 4)
        while True:
            if self.store.done and not self._load_reported:
                self._load_reported = True
                self.on_loaded()
            if self.playing:
                self._advance_playback()
            cv2.imshow(WINDOW, self.render())
            key = cv2.waitKey(delay if self.playing else 30) & 0xFF
            if cv2.getWindowProperty(WINDOW, cv2.WND_PROP_VISIBLE) < 1:
                break
            if key == 255:
                continue
            if self.typing():           # escribiendo un comentario: las teclas son texto, no comandos
                self.handle_text(key)
                continue
            key = ord(chr(key).lower()) if key < 128 else key
            if key == ord("q"):
                break
            if key == ord(" "):
                self.playing = not self.playing
            elif key in (ord("a"), ord("d")):
                self.playing = False
                self.seek(self.pos + (1 if key == ord("d") else -1))
            elif key in (ord("j"), ord("l")):
                self.seek(self.pos + int(round(self.fps)) * (1 if key == ord("l") else -1))
            else:
                self.handle_key(key)
        cv2.destroyAllWindows()
        self.on_exit()

    def on_exit(self):
        pass

    @staticmethod
    def navigation_items():
        return [("h", "MOVERSE POR EL VIDEO"),
                ("key", "ESPACIO", "reproducir / pausar"),
                ("key", "A  /  D", "retroceder / avanzar 1 frame"),
                ("key", "J  /  L", "retroceder / avanzar 1 segundo"),
                ("key", "clic", "en la barra de abajo: ir a ese momento")]


class CalibrationMarker(Viewer):
    """Modo --video: marcar tramo neutro, tramo de ojos cerrados e inicio de la prueba."""

    def __init__(self, video_path):
        super().__init__(video_path)
        self.video_path = video_path
        self.marks = (calibration_marks.load_marks(video_path)
                      or calibration_marks.empty_marks(video_path, self.fps, self.store.expected))
        self._history = []

    def _set_segment(self, key):
        segment = self.marks.get(key)
        if segment is None or segment.get("fin_frame") is not None:
            self.marks[key] = {"inicio_frame": self.pos, "fin_frame": None}
        else:
            start = segment["inicio_frame"]
            segment["inicio_frame"], segment["fin_frame"] = min(start, self.pos), max(start, self.pos)

    def handle_key(self, key):
        if key not in (ord("n"), ord("c"), ord("p"), ord("u")):
            return False
        if key == ord("u"):
            if not self._history:
                return True
            self.marks = self._history.pop()
        else:
            self._history.append(copy.deepcopy(self.marks))
            if key == ord("n"):
                self._set_segment("neutro")
            elif key == ord("c"):
                self._set_segment("cerrado")
            else:
                self.marks["inicio_prueba"] = {"frame": self.pos}
        calibration_marks.save_marks(self.video_path, self.marks)
        return True

    def on_loaded(self):
        self.marks["frames_video"] = self.store.total
        if any(self.marks.get(k) for k in ("neutro", "cerrado", "inicio_prueba")):
            calibration_marks.save_marks(self.video_path, self.marks)

    def _segment_text(self, name, key, letter):
        segment = self.marks.get(key)
        if not segment:
            return (f"{name}: sin marcar (pulsa {letter} al inicio)", DIM)
        start = self.t(segment["inicio_frame"])
        if segment.get("fin_frame") is None:
            return (f"{name}: desde {start:.2f} s - falta el fin ({letter})", WARN_COLOR)
        end = self.t(segment["fin_frame"])
        return (f"{name}: {start:.2f} - {end:.2f} s  ({end - start:.1f} s)", OK_COLOR)

    def _in_segment(self, key):
        segment = self.marks.get(key)
        if not segment:
            return False
        end = segment["fin_frame"] if segment.get("fin_frame") is not None else segment["inicio_frame"]
        return segment["inicio_frame"] <= self.pos <= end

    def panel_items(self):
        neutral = self._segment_text("Neutro", "neutro", "N")
        closed = self._segment_text("Ojos cerrados", "cerrado", "C")
        start = self.marks.get("inicio_prueba")
        start_item = ((f"Inicio de la prueba: {self.t(start['frame']):.2f} s", OK_COLOR) if start
                      else ("Inicio de la prueba: sin marcar (P)", DIM))
        items = [("h", "MARCAS DE CALIBRACION"), ("t",) + neutral, ("t",) + closed, ("t",) + start_item]
        issues = calibration_marks.problems(self.marks)
        if not issues:
            items.append(("t", "LISTO: ya puedes analizarlo con main.py", OK_COLOR))
        else:
            items += [("t", issue, WARN_COLOR) for issue in issues[:2]]
        here = ("tramo NEUTRO" if self._in_segment("neutro") else
                "tramo OJOS CERRADOS" if self._in_segment("cerrado") else "-")
        items += [("t", f"este frame: {here}", GRAY), ("sep",),
                  ("h", "COLORES DE LA BARRA"),
                  ("legend", [("neutro", NEUTRAL_COLOR), ("ojos cerrados", CLOSED_COLOR),
                              ("inicio prueba", WHITE)]),
                  ("legend", [("sombreado = aun cargando", DIM)]),
                  ("sep",)] + self.navigation_items() + [
                  ("sep",), ("h", "MARCAR (en el frame actual)"),
                  ("key", "N", "inicio / fin del tramo NEUTRO"),
                  ("t", "          (mira a la camara, ojos abiertos, quieto)", DIM),
                  ("key", "C", "inicio / fin del tramo OJOS CERRADOS"),
                  ("key", "P", "momento en que EMPIEZA LA PRUEBA"),
                  ("key", "U", "deshacer la ultima marca"),
                  ("key", "Q", "salir (las marcas se guardan solas)")]
        return items

    def draw_dynamic_rows(self, bar, width):
        x0, x1 = self._bar_x(width)
        cv2.putText(bar, "calibracion", (x0, 24), FONT, 0.4, GRAY, 1, cv2.LINE_AA)
        cv2.rectangle(bar, (x0, 30), (x1, 56), (45, 45, 50), -1)
        for key, color in (("neutro", NEUTRAL_COLOR), ("cerrado", CLOSED_COLOR)):
            segment = self.marks.get(key)
            if not segment:
                continue
            end = segment["fin_frame"] if segment.get("fin_frame") is not None else self.pos
            xs, xe = sorted((self.frame_to_x(segment["inicio_frame"], width), self.frame_to_x(end, width)))
            if segment.get("fin_frame") is None:   # tramo a medio marcar: contorno hasta el cursor
                cv2.rectangle(bar, (xs, 30), (max(xe, xs + 1), 56), color, 1)
            else:
                cv2.rectangle(bar, (xs, 30), (max(xe, xs + 2), 56), color, -1)
        start = self.marks.get("inicio_prueba")
        if start:
            x = self.frame_to_x(start["frame"], width)
            cv2.line(bar, (x, 26), (x, 62), WHITE, 3)
            cv2.putText(bar, "prueba", (min(x + 5, x1 - 50), 76), FONT, 0.4, WHITE, 1, cv2.LINE_AA)

    def on_exit(self):
        issues = calibration_marks.problems(self.marks)
        print(f"Marcas en {calibration_marks.marks_path(self.video_path)}")
        if issues:
            print("Faltan: " + "; ".join(issues))
        else:
            print(f'Listo para analizar:\n  python main.py --nombre "..." --condicion ... --fuente "{self.video_path}"')


class SessionReviewer(Viewer):
    """Modo sesión: vídeo + lo que guardó el análisis + anotaciones manuales."""

    def __init__(self, session_dir, blind, annotator):
        with open(os.path.join(session_dir, "metadata.json"), encoding="utf-8") as f:
            self.meta = json.load(f)
        source = str(self.meta.get("fuente", ""))
        if self.meta.get("tipo_fuente") == "camara" or source.isdigit():
            sys.exit("Esta sesión fue con la cámara en vivo: no hay vídeo que revisar.")
        if not os.path.exists(source):
            sys.exit(f"No se encuentra el vídeo de la sesión: {source}")
        super().__init__(source)
        self.fps = self.meta.get("fps_nativo_fuente") or self.fps
        self.dir, self.blind = session_dir, blind
        self.annotator = annotator or "principal"
        self.trace = self._load_trace()
        self.events = self._load_events()
        self.annotations_path = annotations_file(session_dir, blind, annotator)
        legacy = os.path.join(session_dir, "anotaciones_revisor.csv")   # nombre por defecto de versiones anteriores
        if not blind and annotator is None and os.path.exists(legacy) and not os.path.exists(self.annotations_path):
            os.replace(legacy, self.annotations_path)
            print("[AVISO] anotaciones_revisor.csv (versión anterior, hechas viendo el sistema) se renombró a "
                  "anotaciones_revision.csv")
        self.annotations = self._load_annotations()
        mode = "1" if blind else "0"
        if any(a["ciego"] != mode for a in self.annotations):
            sys.exit(f"{os.path.basename(self.annotations_path)} contiene anotaciones hechas "
                     f"{'SIN' if blind else 'EN'} modo ciego: la referencia y la revisión no se mezclan.")
        self.pending = None             # intervalo con inicio marcado y sin fin
        self.comment_for, self.comment_text = None, ""   # PROBLEMA cuyo comentario se está escribiendo

    # ------------------------------------------------------------------ datos

    def _load_trace(self):
        """Fila de la traza por número de frame (las trazas antiguas sin columna frame usan t * fps)."""
        path = os.path.join(self.dir, "traza.csv")
        if not os.path.exists(path):
            return {}
        with open(path, newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        return {int(r["frame"]) if r.get("frame") else int(round(float(r["t"]) * self.fps)): r for r in rows}

    def _load_events(self):
        """Eventos del sistema como (inicio_s, fin_s, tipo). Se registran al terminar: inicio = t - duración."""
        events = []
        with open(os.path.join(self.dir, "eventos.csv"), newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                if r["Evento"] in EVENT_COLORS:
                    end = float(r["t_s"])
                    duration = float(r["Duracion_s"]) if r.get("Duracion_s") else 0.0
                    events.append((end - duration, end, r["Evento"]))
        return events

    def _load_annotations(self):
        if not os.path.exists(self.annotations_path):
            return []
        with open(self.annotations_path, newline="", encoding="utf-8") as f:
            # Archivos anteriores a la columna "ciego": se consideran NO ciegos (no consta que lo fueran)
            return [{**a, "frame": int(a["frame"]),
                     "fin_frame": int(a["fin_frame"]) if a.get("fin_frame") else None,
                     "ciego": a.get("ciego") or "0"}
                    for a in csv.DictReader(f)]

    def _save_annotations(self):
        # Los archivos de versiones anteriores (sin columnas fin_*) se reescriben con el formato actual
        with open(self.annotations_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=ANNOTATION_HEADER, restval="", extrasaction="ignore")
            writer.writeheader()
            writer.writerows([{**a, "fin_frame": "" if a.get("fin_frame") is None else a["fin_frame"]}
                              for a in sorted(self.annotations, key=lambda a: a["frame"])])

    def on_loaded(self):
        analyzed = (self.meta.get("resumen") or {}).get("frames")
        if analyzed and analyzed != self.store.total:
            print(f"[AVISO] El análisis procesó {analyzed} frames y el vídeo tiene {self.store.total}: "
                  f"¿es el mismo archivo, o se cortó el análisis con Q?")

    def handle_key(self, key):
        if key in ANNOTATION_KEYS:
            kind = ANNOTATION_KEYS[key]
            if kind == "PROBLEMA" and self.blind:
                kind = "NO_EVALUABLE"
            if kind in INTERVAL_TYPES and self.pending is None:
                self.pending = {"tipo": kind, "frame": self.pos}    # inicio; falta el fin
                return True
            if kind in INTERVAL_TYPES and self.pending["tipo"] == kind:
                start, end = sorted((self.pending["frame"], self.pos))
                self.pending = None
                self._add_annotation(kind, start, end)
                if kind in COMMENTED_TYPES:     # pedir el comentario en la ventana
                    self.playing = False
                    self.comment_for, self.comment_text = self.annotations[-1], ""
            elif kind in INTERVAL_TYPES:                            # otro intervalo abierto: se reemplaza
                self.pending = {"tipo": kind, "frame": self.pos}
                return True
            else:
                self._add_annotation(kind, self.pos, None)
        elif key == ord("u"):
            if self.pending is not None:
                self.pending = None                                 # cancela el intervalo a medio marcar
                return True
            if not self.annotations:
                return True
            self.annotations.pop()      # la lista está en orden de anotación (el archivo se guarda ordenado aparte)
        elif key == ord("e"):
            # borra la anotación que contiene el frame actual (si hay varias, la más reciente)
            here = [a for a in self.annotations
                    if a["frame"] <= self.pos <= (a["frame"] if a.get("fin_frame") is None else a["fin_frame"])]
            if not here:
                return True
            self.annotations.remove(here[-1])
        else:
            return False
        self._save_annotations()
        return True

    def _add_annotation(self, kind, start, end):
        self.annotations.append({"t_s": f"{self.t(start):.3f}", "frame": start, "tipo": kind,
                                 "fin_t_s": "" if end is None else f"{self.t(end):.3f}", "fin_frame": end,
                                 "comentario": "", "ciego": "1" if self.blind else "0", "anotador": self.annotator,
                                 "registrado": datetime.now().isoformat(timespec="seconds")})

    def typing(self):
        return self.comment_for is not None

    def handle_text(self, key):
        """Comentario del PROBLEMA: ENTER guarda, ESC lo deja sin comentario, BORRAR borra una letra.
        Solo letras sin tilde (OpenCV no dibuja tildes ni eñes)."""
        if key in (13, 10, 27):
            self.comment_for["comentario"] = self.comment_text.strip() if key != 27 else ""
            self.comment_for = None
            self._save_annotations()
        elif key == 8:
            self.comment_text = self.comment_text[:-1]
        elif 32 <= key < 127 and len(self.comment_text) < MAX_COMMENT:
            self.comment_text += chr(key)

    # ------------------------------------------------------------------ dibujo

    def _state(self, frame):
        row = self.trace.get(frame)
        if row is None:
            return "sin_rostro"
        if row["fase"] == "calibracion_manual":
            return "marcas"
        if row["fase"] != "monitoreo":
            return "calibrando"
        return "postura" if row.get("postura_valida") == "0" else "midiendo"

    def draw_static_rows(self, bg, width):
        x0, x1 = self._bar_x(width)
        if not self.blind:
            cv2.putText(bg, "estado", (x0, 12), FONT, 0.4, GRAY, 1, cv2.LINE_AA)
            for x in range(x0, x1):
                cv2.line(bg, (x, 16), (x, 24), STATE_COLORS[self._state(self.x_to_frame(x, width))], 1)
            cv2.putText(bg, "sistema", (x0, 39), FONT, 0.4, GRAY, 1, cv2.LINE_AA)
            for start, end, kind in self.events:
                xs = self.frame_to_x(start * self.fps, width)
                xe = max(self.frame_to_x(end * self.fps, width), xs + 2)
                cv2.rectangle(bg, (xs, 43), (xe, 57), EVENT_COLORS[kind], -1)
        cv2.putText(bg, "tus anotaciones", (x0, 73), FONT, 0.4, GRAY, 1, cv2.LINE_AA)
        cv2.rectangle(bg, (x0, 77), (x1, 92), (45, 45, 50), -1)

    def draw_dynamic_rows(self, bar, width):
        for a in self.annotations:
            color = PROBLEM_COLOR if a["tipo"] in COMMENTED_TYPES else WHITE
            xs = self.frame_to_x(a["frame"], width)
            if a.get("fin_frame") is None:
                cv2.line(bar, (xs, 77), (xs, 92), color, 2)
            else:
                cv2.rectangle(bar, (xs, 77), (max(self.frame_to_x(a["fin_frame"], width), xs + 2), 92), color, -1)
        if self.pending is not None:    # intervalo a medio marcar: contorno hasta el cursor
            color = PROBLEM_COLOR if self.pending["tipo"] in COMMENTED_TYPES else WHITE
            xs, xe = sorted((self.frame_to_x(self.pending["frame"], width), self.frame_to_x(self.pos, width)))
            cv2.rectangle(bar, (xs, 77), (max(xe, xs + 1), 92), color, 1)

    def panel_items(self):
        items = []
        if self.blind:
            items += [("h", "MODO CIEGO"), ("t", "no se muestra lo que detecto el sistema", GRAY),
                      ("t", "(para que tu anotacion no se deje influir)", DIM)]
        else:
            items.append(("h", "LO QUE MIDIO EL SISTEMA (este frame)"))
            row = self.trace.get(self.pos)
            if row is None:
                items.append(("t", "sin rostro detectado en este frame", (100, 100, 255)))
            else:
                def num(key, decimals=2):
                    value = row.get(key)
                    return f"{float(value):.{decimals}f}" if value else "-"

                valid = "si" if row.get("postura_valida") == "1" else "NO (no cuenta parpadeos)"
                items += [
                    ("t", f"fase: {row['fase']}   postura valida: {valid}", (220, 220, 220)),
                    ("t", f"cierre del ojo: {num('cierre')}  (>= 0.80 = cerrado)", EVENT_COLORS["PARPADEO"]),
                    ("t", f"boca: {num('mouth')}  (micro >= {num('micro_yawn_thr')}, bostezo >= {num('yawn_thr')})",
                     EVENT_COLORS["BOSTEZO"]),
                    ("t", f"sonrisa: {'SI' if row.get('sonrisa') == '1' else 'no'}   cabeza: pitch "
                          f"{num('cabeza_pitch', 1)}  yaw {num('cabeza_yaw', 1)} grados", (200, 200, 200)),
                    ("t", f"contadores: parpadeos {row['parpadeos']}  bostezos {row['bostezos']}"
                          f"  micro {row['micro_bostezos']}", (220, 220, 220)),
                ]
            near = [e for e in self.events if e[0] - 1.0 <= self.t() <= e[1] + 1.0][:2]
            items += [("t", f"> {kind} {start:.2f}-{end:.2f} s", EVENT_COLORS[kind]) for start, end, kind in near]
        def near_me(a):
            end = a["fin_frame"] if a.get("fin_frame") is not None else a["frame"]
            return a["frame"] - self.fps <= self.pos <= end + self.fps

        def describe(a):
            if a.get("fin_frame") is None:
                text = f"* {a['tipo']} en {float(a['t_s']):.2f} s"
            else:
                text = f"* {a['tipo']} {float(a['t_s']):.2f} - {float(a['fin_t_s']):.2f} s"
            if a.get("comentario"):
                text += f": {a['comentario']}"
            return (text[:58] + "...") if len(text) > 61 else text

        mine = [a for a in self.annotations if near_me(a)]
        items += [("sep",), ("h", f"TUS ANOTACIONES ({len(self.annotations)} en total)")]
        if self.comment_for is not None:
            prompt = "MOTIVO: cara tapada, fuera de cuadro..." if self.blind else "DESCRIBE EL PROBLEMA"
            items += [("t", f"{prompt} (sin tildes):", PROBLEM_COLOR),
                      ("big", (self.comment_text + "_")[-34:], WHITE),
                      ("t", "ENTER guardar   ESC sin comentario   BORRAR letra", GRAY)]
        if self.pending is not None:
            items.append(("t", f"{self.pending['tipo']} desde {self.t(self.pending['frame']):.2f} s: "
                               f"pulsa {KEY_FOR_TYPE[self.pending['tipo']]} en el final", WARN_COLOR))
        items += ([("t", describe(a), PROBLEM_COLOR if a["tipo"] in COMMENTED_TYPES else WHITE) for a in mine[:2]]
                  or [("t", "ninguna cerca de este momento", DIM)])
        items += [("sep",), ("h", "COLORES DE LA BARRA")]
        if not self.blind:
            items += [("legend", [("midiendo", STATE_COLORS["midiendo"]), ("calibrando", STATE_COLORS["calibrando"]),
                                  ("calib. manual", STATE_COLORS["marcas"]), ("postura", STATE_COLORS["postura"]),
                                  ("sin rostro", STATE_COLORS["sin_rostro"])]),
                      ("legend", [("parpadeo", EVENT_COLORS["PARPADEO"]), ("prolongado", EVENT_COLORS["PARPADEO_PROLONGADO"]),
                                  ("micro-sueno", EVENT_COLORS["MICRO_SUENO"])]),
                      ("legend", [("bostezo", EVENT_COLORS["BOSTEZO"]), ("micro-bostezo", EVENT_COLORS["MICRO_BOSTEZO"]),
                                  ("sonrisa", EVENT_COLORS["SONRISA"]),
                                  ("descartado (giro)", EVENT_COLORS["PARPADEO_DESCARTADO_GIRO"])])]
        items += [("legend", [("blanco = tus anotaciones", WHITE),
                              ("naranja = no evaluable" if self.blind else "naranja = problema", PROBLEM_COLOR)]),
                  ("sep",)]
        items += self.navigation_items() + [
            ("sep",), ("h", "ANOTAR LO QUE VES: tecla al INICIO y otra al FIN"),
            ("key", "B", "parpadeo: empieza a cerrar / abre (usa A/D)"),
            ("key", "Y", "bostezo: empieza a abrir la boca / la cierra"),
            ("key", "K", "micro-bostezo (contenido, boca poco abierta)"),
            ("key", "M", "micro-sueno: cierra los ojos / los abre"),
            ("key", "X", "NO EVALUABLE: cara tapada, fuera de cuadro..." if self.blind
             else "PROBLEMA en ese tramo (luego escribes que)"),
            ("key", "U / E / Q", "borra la ultima / la de aqui / salir")]
        return items

    def on_exit(self):
        if self.comment_for is not None:    # ventana cerrada mientras se escribía: se guarda lo escrito
            self.comment_for["comentario"] = self.comment_text.strip()
            self._save_annotations()
        if self.pending is not None:
            print(f"[AVISO] El {self.pending['tipo']} que empezaste en {self.t(self.pending['frame']):.2f} s quedó "
                  f"sin fin y NO se guardó.")
        print(f"{len(self.annotations)} anotaciones en {self.annotations_path}")


def parse_args():
    parser = argparse.ArgumentParser(description="Revisión de vídeos y sesiones con barra de tiempo")
    parser.add_argument("sesion", nargs="?", help="carpeta de la sesión analizada (sesiones/<fecha>_<sujeto>)")
    parser.add_argument("--video", help="vídeo sin analizar: marcar la calibración manual (N / C / P)")
    parser.add_argument("--ciego", action="store_true", help="ocultar lo detectado por el sistema")
    parser.add_argument("--anotador", default=None,
                        help="solo si anota OTRA persona además del anotador principal (para medir el acuerdo "
                             "entre anotadores); sus anotaciones van a un archivo aparte")
    args = parser.parse_args()
    if args.sesion and not args.video and os.path.isfile(args.sesion):
        args.video, args.sesion = args.sesion, None   # se pasó la ruta de un vídeo sin --video
    if bool(args.sesion) == bool(args.video):
        parser.error("indica una carpeta de sesión o --video RUTA (uno de los dos)")
    return args


if __name__ == "__main__":
    args = parse_args()
    if args.video:
        if not os.path.exists(args.video):
            sys.exit(f"No se encuentra el vídeo: {args.video}")
        CalibrationMarker(args.video).run()
    else:
        SessionReviewer(args.sesion, args.ciego, args.anotador).run()
