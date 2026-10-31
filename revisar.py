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
     B / Y / K / M anotan parpadeo / bostezo / micro-bostezo / cierre largo como intervalo (tecla al
     inicio y otra vez al final). X marca un tramo y pide un comentario: con --ciego es NO_EVALUABLE (cara
     tapada, fuera de cuadro...; la evaluación lo excluye); sin --ciego, PROBLEMA (nota de un error).
     U deshace la última anotación, E borra la del cursor y Q guarda y sale.
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

Interfaz: se dibuja con Pillow y fuentes TrueType (revisar_ui.py).
"""
import argparse
import bisect
import copy
import csv
import json
import os
import sys
import threading
import time
from collections import Counter, deque
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import cv2
import numpy as np

import calibration_marks
import paths
import revisar_ui as ui

WINDOW = "Revision de video"
MAX_VIEW_W, MAX_VIEW_H = 900, 510   # tamaño máximo del vídeo en pantalla (y en memoria)
PANEL_W = 420                       # panel lateral derecho
PAD, GAP = 14, 8                    # margen del panel y separación entre tarjetas
GUTTER = 92                         # columna con los nombres de las filas en la barra de tiempo
JPEG_QUALITY = 85
# En la carpeta de datos del programa (paths.py)
CACHE_DIR = os.path.join(paths.data_dir(), "cache_revisor")

# Micro-bostezo (K): bostezo contenido o con poca apertura bucal; el sistema lo separa con umbrales
# (MICRO_BOSTEZO), el anotador por apreciación visual. M = cierre largo (micro-sueño conductual, >= 1 s).
ANNOTATION_KEYS = {ord("b"): "PARPADEO", ord("y"): "BOSTEZO", ord("k"): "MICRO_BOSTEZO",
                   ord("m"): "MICRO_SUENO", ord("x"): "PROBLEMA"}
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
LONG_BLINK_NOTICE_S = 1.0         # guía: con los ojos cerrados 1 s o más es un cierre largo (M), no un parpadeo
NAVIGATION_KEYS = ("Moverse", [(["Espacio"], "Reproducir / pausar"), (["A", "D"], "± 1 frame"),
                               (["J", "L"], "± 1 segundo"), (["Clic"], "Saltar (en la barra)")])


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
        self._timeline = None            # (clave, imagen fija, filas, y del eje)
        self._keys_card = None
        self._card_cache = {}            # tarjetas que no cambian en cada cuadro: id -> (clave, imagen)
        self._buffer = None              # imagen de la ventana, reutilizada entre cuadros
        self._rendered_key = None        # estado con el que se dibujó el último cuadro
        self.ui_version = 0              # sube con cada tecla: obliga a redibujar
        self._view_h, self._canvas_w = MAX_VIEW_H, MAX_VIEW_W + PANEL_W
        self._load_reported = False

    # ------------------------------------------------------------------ a implementar por cada modo

    def header_info(self):
        """(título del panel, etiqueta del modo, color de la etiqueta)."""
        raise NotImplementedError

    def draw_panel_body(self, c, y):
        """Tarjetas propias del modo, desde y; devuelve la y siguiente."""
        return y

    def key_sections(self):
        """[(título, [(teclas, explicación), ...]), ...] para la tarjeta de teclas."""
        return [NAVIGATION_KEYS]

    def draw_input_card(self, c, y):
        """Tarjeta para escribir un texto (sustituye a la de teclas mientras typing() es True)."""
        return y

    def timeline_rows(self):
        """[(clave, nombre, alto)] de las filas de la barra de tiempo."""
        return []

    def draw_static_rows(self, c, rows, width):
        """Contenido fijo de las filas (depende solo de los datos)."""

    def draw_dynamic_rows(self, c, rows, width):
        """Contenido que cambia al marcar o anotar."""

    def legend_items(self):
        """[(texto, color)] de la leyenda bajo la barra de tiempo."""
        return []

    def handle_key(self, key):
        return False

    def typing(self):
        """True mientras se escribe un texto en la ventana (las teclas no navegan)."""
        return False

    def handle_text(self, key):
        pass

    def on_loaded(self):
        """Se llama una vez al terminar de cargar el vídeo."""

    def on_exit(self):
        pass

    # ------------------------------------------------------------------ navegación

    def t(self, frame=None):
        """Instante (s) de un frame. En un vídeo, frame / fps; en una sesión en vivo grabada, el reloj real."""
        return (self.pos if frame is None else frame) / self.fps

    def frame_at(self, seconds):
        """Frame correspondiente a un instante (inversa de t)."""
        return seconds * self.fps

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
    def _track_x(width):
        return GUTTER, width - 16

    def frame_to_x(self, frame, width):
        x0, x1 = self._track_x(width)
        return int(x0 + (x1 - x0) * frame / max(self.store.total - 1, 1))

    def x_to_frame(self, x, width):
        x0, x1 = self._track_x(width)
        return int(round((x - x0) / max(x1 - x0, 1) * (self.store.total - 1)))

    def _legend_lines(self, width):
        """Reparte la leyenda en líneas que quepan en el ancho de la barra."""
        x0, x1 = self._track_x(width)
        items = self.legend_items() + ([("Zona oscura: aún cargando", ui.TRACK)] if not self.store.done else [])
        lines, line, used = [], [], 0
        for label, color in items:
            item_w = 15 + ui.fonts().small.getlength(label) + 16
            if line and x0 + used + item_w > x1:
                lines.append(line)
                line, used = [], 0
            line.append((label, color))
            used += item_w
        return lines + ([line] if line else [])

    def _timeline_static(self, width):
        definition = self.timeline_rows()
        y, rows = 10, {}
        for key, _, height in definition:
            rows[key] = (y, y + height)
            y += height + 6
        axis_y = y
        legend = self._legend_lines(width)
        height = axis_y + 22 + 17 * len(legend) + 6
        c = ui.Canvas(width, height)
        x0, x1 = self._track_x(width)
        for key, name, _ in definition:
            top, bottom = rows[key]
            c.draw.rounded_rectangle((x0, top, x1, bottom), radius=3, fill=ui.TRACK)
            c.text(x0 - 12, (top + bottom) / 2, name, c.fonts.small, ui.MUTED, anchor="rm")
        self.draw_static_rows(c, rows, width)
        # Escala de tiempo: una marca cada 1, 2, 5, 10... s, con al menos 56 px entre etiquetas
        duration = self.t(self.store.total - 1)
        px_per_s = (x1 - x0) / max(duration, 1e-6)
        step = next((s for s in (1, 2, 5, 10, 15, 30, 60, 120, 300) if s * px_per_s >= 56), 600)
        second = 0
        while second <= duration + 1e-6:
            x = self.frame_to_x(self.frame_at(second), width)
            c.draw.line((x, axis_y, x, axis_y + 4), fill=ui.FAINT)
            c.text(x, axis_y + 6, f"{second // 60}:{second % 60:02d}", c.fonts.small, ui.FAINT, anchor="ma")
            second += step
        for i, line in enumerate(legend):
            lx, ly = x0, axis_y + 24 + 17 * i
            for label, color in line:
                lx += c.swatch(lx, ly, color, label) + 16
        return c.img, rows, axis_y

    def _timeline_image(self, width):
        key = (width, self.store.total, self.store.done)
        if self._timeline is None or self._timeline[0] != key:
            self._timeline = (key,) + self._timeline_static(width)
        _, static, rows, axis_y = self._timeline
        c = ui.Canvas(0, 0, image=static.copy())
        self.draw_dynamic_rows(c, rows, width)
        bar = c.to_bgr()
        x0, x1 = self._track_x(width)
        if not self.store.done:          # parte aún sin cargar: sombreada
            xl = self.frame_to_x(self.store.loaded, width)
            bar[6:axis_y, xl:x1 + 1] = (bar[6:axis_y, xl:x1 + 1] * 0.35).astype(np.uint8)
        x = self.frame_to_x(self.pos, width)
        cv2.line(bar, (x, 6), (x, axis_y + 2), ui.bgr(ui.PLAYHEAD), 2)
        cv2.circle(bar, (x, 6), 4, ui.bgr(ui.PLAYHEAD), -1, cv2.LINE_AA)
        return bar

    # ------------------------------------------------------------------ panel

    def card(self, c, y, title, rows, cache_id=None, cache_key=None):
        """Tarjeta del panel. rows: [(alto, función(lienzo, x, y, ancho))]. Devuelve la y siguiente.
        Con cache_id y cache_key, la tarjeta se reutiliza mientras cache_key no cambie (el texto con fuentes
        TrueType es lo más costoso de dibujar)."""
        w = PANEL_W - 2 * PAD
        top = 30 if title else 12
        h = top + sum(height for height, _ in rows) + 6
        cached = self._card_cache.get(cache_id) if cache_id else None
        if cached is None or cached[0] != cache_key:
            card = ui.Canvas(w + 1, h + 1)
            card.card(0, 0, w, h, title)
            cy = top
            for height, draw in rows:
                draw(card, 12, cy, w - 24)
                cy += height
            cached = (cache_key, card.img)
            if cache_id:
                self._card_cache[cache_id] = cached
        c.img.paste(cached[1], (PAD, int(y)))
        return y + cached[1].height - 1 + GAP

    def _header(self, c, y):
        """Reloj, número de frame, modo y estado de la reproducción, en una sola franja."""
        _, badge, badge_color = self.header_info()
        minutes, seconds = divmod(self.t(), 60)
        clock_w = c.text(PAD, y - 2, f"{int(minutes):02d}:{seconds:05.2f}", c.fonts.clock)
        c.text(PAD + clock_w + 10, y + 12, f"frame {self.pos} de {self.store.total - 1}", c.fonts.small, ui.MUTED)
        c.pill(PANEL_W - PAD, y, badge, badge_color, align="right")
        if not self.store.done:
            state, color = f"Cargando video · {self.store.loaded * 100 // max(self.store.total, 1)} %", ui.WARN
        elif self.playing:
            state, color = "Reproduciendo", ui.OK
        else:
            state, color = "En pausa", ui.MUTED
        c.text(PANEL_W - PAD, y + 25, state, c.fonts.bold, color, anchor="ra")
        y += 46
        if self.pos >= self.store.loaded:
            c.text(PAD, y, "Este punto aún no ha cargado: espera un momento.", c.fonts.small, ui.WARN)
            y += 17
        return y

    def _keys_card_image(self):
        """Tarjeta de teclas (fija: se dibuja una vez). Dos columnas: tecla(s) + qué hace."""
        if self._keys_card is None:
            sections = self.key_sections()
            w = PANEL_W - 2 * PAD
            h = 30 + sum(16 + 22 * ((len(items) + 1) // 2) for _, items in sections) + 4
            c = ui.Canvas(w + 1, h + 1)
            c.card(0, 0, w, h, "Teclas")
            col_w = (w - 24 - 12) / 2
            y = 30
            for title, items in sections:
                c.text(12, y, title, c.fonts.small, ui.FAINT)
                y += 16
                for i, (keys, label) in enumerate(items):
                    column_x = 12 + (i % 2) * (col_w + 12)
                    x, row_y = column_x, y + 22 * (i // 2)
                    for key in keys:
                        x += c.keycap(x, row_y, key) + 4
                    c.text(x + 3, row_y + 10, c.fit(label, c.fonts.body, column_x + col_w - x - 3), c.fonts.body,
                           ui.TEXT, anchor="lm")
                y += 22 * ((len(items) + 1) // 2)
            self._keys_card = c.img
        return self._keys_card

    def _render_panel(self):
        c = ui.Canvas(PANEL_W, 760)
        y = self._header(c, PAD)
        y = self.draw_panel_body(c, y)
        if self.typing():
            y = self.draw_input_card(c, y)
        else:
            keys = self._keys_card_image()
            c.img.paste(keys, (PAD, int(y)))
            y += keys.height + GAP
        return c.to_bgr()[:int(y - GAP + PAD)]

    def render(self):
        """Compone vídeo + panel + barra de tiempo. Si nada cambió desde el cuadro anterior (vídeo en pausa,
        sin teclas), devuelve la misma imagen sin redibujar."""
        state = (self.pos, self.playing, self.store.loaded, self.store.done, self.ui_version)
        if state == self._rendered_key and self._buffer is not None:
            return self._buffer
        self._refresh_frame()
        video = self.frame if self.frame is not None else np.zeros((MAX_VIEW_H, MAX_VIEW_W, 3), np.uint8)
        vh, vw = video.shape[:2]
        panel = self._render_panel()
        timeline = self._timeline_image(vw + PANEL_W)
        height = max(vh, panel.shape[0])
        shape = (height + timeline.shape[0], vw + PANEL_W, 3)
        if self._buffer is None or self._buffer.shape != shape:
            self._buffer = np.empty(shape, np.uint8)
            self._buffer[:] = ui.bgr(ui.BG)
        out = self._buffer
        out[:vh, :vw] = video
        out[vh:height, :vw] = ui.bgr(ui.BG)
        out[:panel.shape[0], vw:] = panel
        out[panel.shape[0]:height, vw:] = ui.bgr(ui.BG)
        out[:height, vw] = ui.bgr(ui.CARD_BORDER)
        out[height:] = timeline
        self._view_h, self._canvas_w = height, shape[1]
        self._rendered_key = state
        return out

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
        frame_ms = 1000.0 / self.fps
        while True:
            started = time.perf_counter()
            if self.store.done and not self._load_reported:
                self._load_reported = True
                self.on_loaded()
            if self.playing:
                self._advance_playback()
            cv2.imshow(WINDOW, self.render())
            # Reproducción a velocidad real: se espera solo lo que falta para completar un frame
            elapsed_ms = (time.perf_counter() - started) * 1000
            key = cv2.waitKey(max(1, int(frame_ms - elapsed_ms)) if self.playing else 30) & 0xFF
            if cv2.getWindowProperty(WINDOW, cv2.WND_PROP_VISIBLE) < 1:
                break
            if key == 255:
                continue
            self.ui_version += 1
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


class CalibrationMarker(Viewer):
    """Modo --video: marcar tramo neutro, tramo de ojos cerrados e inicio de la prueba."""

    STEPS = [("1", "Neutro", "Mira a la cámara, ojos abiertos, quieto", "neutro", "N", ui.NEUTRAL_COLOR),
             ("2", "Ojos cerrados", "Cerrados del todo", "cerrado", "C", ui.CLOSED_COLOR),
             ("3", "Inicio de la prueba", "Cuando ya abrió los ojos", "inicio_prueba", "P", ui.START_COLOR)]

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

    def _in_segment(self, key):
        segment = self.marks.get(key)
        if not segment:
            return False
        end = segment["fin_frame"] if segment.get("fin_frame") is not None else segment["inicio_frame"]
        return segment["inicio_frame"] <= self.pos <= end

    # ------------------------------------------------------------------ dibujo

    def header_info(self):
        return "Marcar calibración", "CALIBRACIÓN", ui.OK

    def _step_status(self, key, letter, color):
        """(texto del valor, color del círculo, color del texto) de un paso."""
        if key == "inicio_prueba":
            start = self.marks.get("inicio_prueba")
            if start:
                return f"{self.t(start['frame']):.2f} s", color, ui.TEXT
            return f"pulsa {letter}", ui.FAINT, ui.MUTED
        segment = self.marks.get(key)
        if not segment:
            return f"pulsa {letter} al inicio", ui.FAINT, ui.MUTED
        if segment.get("fin_frame") is None:
            return f"desde {self.t(segment['inicio_frame']):.2f} s · falta el fin ({letter})", ui.WARN, ui.WARN
        start, end = self.t(segment["inicio_frame"]), self.t(segment["fin_frame"])
        return f"{start:.2f} – {end:.2f} s  ({end - start:.1f} s)", color, ui.TEXT

    def draw_panel_body(self, c, y):
        rows = []
        for number, name, hint, key, letter, color in self.STEPS:
            def step(c, x, y, w, number=number, name=name, hint=hint, key=key, letter=letter, color=color):
                value, dot, value_color = self._step_status(key, letter, color)
                c.draw.ellipse((x, y + 1, x + 20, y + 21), fill=dot)
                c.text(x + 10, y + 11, number, c.fonts.key, (18, 19, 23), anchor="mm")
                c.text(x + 30, y, name, c.fonts.bold)
                c.text(x + 30, y + 17, hint, c.fonts.small, ui.FAINT)
                c.text(x + w, y + 2, value, c.fonts.body, value_color, anchor="ra")
            rows.append((38, step))

        def status(c, x, y, w):
            issues = calibration_marks.problems(self.marks)
            if not issues:
                c.text(x, y, "Listo: ya puedes analizarlo con main.py", c.fonts.bold, ui.OK)
            else:
                c.text(x, y, c.fit("Falta: " + issues[0], c.fonts.body, w), c.fonts.body, ui.WARN)

        place = ("dentro del tramo neutro" if self._in_segment("neutro") else
                 "dentro del tramo de ojos cerrados" if self._in_segment("cerrado") else "fuera de los tramos")

        def here(c, x, y, w):
            c.text(x, y, f"Este frame: {place}", c.fonts.small, ui.MUTED)

        rows += [(22, status), (17, here)]
        return self.card(c, y, "Pasos de la calibración", rows, cache_id="pasos",
                         cache_key=(json.dumps(self.marks, sort_keys=True), place))

    def key_sections(self):
        return [NAVIGATION_KEYS,
                ("Marcar en el frame actual", [(["N"], "Neutro: inicio y fin"), (["C"], "Cerrados: inicio y fin"),
                                               (["P"], "Inicio de la prueba")]),
                ("Corregir", [(["U"], "Deshacer la última"), (["Q"], "Guardar y salir")])]

    def timeline_rows(self):
        return [("calib", "Calibración", 20)]

    def legend_items(self):
        return [("Neutro", ui.NEUTRAL_COLOR), ("Ojos cerrados", ui.CLOSED_COLOR),
                ("Inicio de la prueba", ui.START_COLOR)]

    def draw_dynamic_rows(self, c, rows, width):
        top, bottom = rows["calib"]
        for key, color in (("neutro", ui.NEUTRAL_COLOR), ("cerrado", ui.CLOSED_COLOR)):
            segment = self.marks.get(key)
            if not segment:
                continue
            end = segment["fin_frame"] if segment.get("fin_frame") is not None else self.pos
            xs, xe = sorted((self.frame_to_x(segment["inicio_frame"], width), self.frame_to_x(end, width)))
            if segment.get("fin_frame") is None:   # tramo a medio marcar: contorno hasta el cursor
                c.draw.rounded_rectangle((xs, top, max(xe, xs + 2), bottom), radius=3, outline=color, width=2)
            else:
                c.draw.rounded_rectangle((xs, top, max(xe, xs + 3), bottom), radius=3, fill=color)
        start = self.marks.get("inicio_prueba")
        if start:
            x = self.frame_to_x(start["frame"], width)
            c.draw.line((x, top - 4, x, bottom + 4), fill=ui.START_COLOR, width=3)
            c.text(x + 6, (top + bottom) / 2, "Prueba", c.fonts.small, ui.START_COLOR, anchor="lm")

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
        recording = self.meta.get("grabacion")
        self.frame_times = None         # instante real de cada frame (sesiones en vivo grabadas)
        if recording:                   # sesión en vivo con --grabar: se revisa la grabación
            source = os.path.join(session_dir, recording["archivo"])
            with open(os.path.join(session_dir, recording["tiempos"]), newline="", encoding="utf-8") as f:
                self.frame_times = [float(r["t"]) for r in csv.DictReader(f)]
        elif self.meta.get("tipo_fuente") == "camara" or source.isdigit():
            sys.exit("Esta sesión fue en vivo sin grabar: no hay vídeo que revisar (usa main.py --grabar).")
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
        self.comment_for, self.comment_text = None, ""   # anotación cuyo comentario se está escribiendo
        self._edits = 0                 # cambios en las anotaciones (para redibujar su tarjeta)

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
                if r["Evento"] in ui.SYSTEM_LABELS:
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
        self._edits += 1
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

    def t(self, frame=None):
        if self.frame_times:            # sesión en vivo: los frames no llegan a intervalos exactos
            index = int(np.clip(self.pos if frame is None else frame, 0, len(self.frame_times) - 1))
            return self.frame_times[index]
        return super().t(frame)

    def frame_at(self, seconds):
        if self.frame_times:
            return bisect.bisect_left(self.frame_times, seconds)
        return super().frame_at(seconds)

    def typing(self):
        return self.comment_for is not None

    def handle_text(self, key):
        """Comentario: ENTER guarda, ESC lo deja sin comentario, RETROCESO borra una letra."""
        if key in (13, 10, 27):
            self.comment_for["comentario"] = self.comment_text.strip() if key != 27 else ""
            self.comment_for = None
            self._save_annotations()
        elif key == 8:
            self.comment_text = self.comment_text[:-1]
        elif 32 <= key < 256 and key != 127 and chr(key).isprintable() and len(self.comment_text) < MAX_COMMENT:
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

    def header_info(self):
        if self.blind:
            return "Revisión de sesión", "MODO CIEGO", ui.WARN
        return "Revisión de sesión", "REVISIÓN", ui.ACCENT

    def _describe(self, a):
        label = ui.ANNOTATION_LABELS.get(a["tipo"], a["tipo"])
        if a.get("fin_frame") is None:
            text = f"{label}  {float(a['t_s']):.2f} s"
        else:
            text = f"{label}  {float(a['t_s']):.2f} – {float(a['fin_t_s']):.2f} s"
        return text + (f"  ·  {a['comentario']}" if a.get("comentario") else "")

    def _long_blink(self, a):
        return (a["tipo"] == "PARPADEO" and a.get("fin_frame") is not None
                and self.t(a["fin_frame"]) - self.t(a["frame"]) >= LONG_BLINK_NOTICE_S)

    def _near_me(self, a):
        end = a["fin_frame"] if a.get("fin_frame") is not None else a["frame"]
        return a["frame"] - self.fps <= self.pos <= end + self.fps

    def draw_panel_body(self, c, y):
        y = self._blind_card(c, y) if self.blind else self._system_card(c, y)
        return self._annotations_card(c, y)

    def _blind_card(self, c, y):
        def info(c, x, y, w):
            text = "El sistema está oculto para que tu anotación no se deje influir."
            for i, line in enumerate(c.wrap(text, c.fonts.body, w)):
                c.text(x, y + 18 * i, line, c.fonts.body)

        def guide(c, x, y, w):
            c.text(x, y, "Definiciones de cada evento: docs/guia_anotacion.md", c.fonts.small, ui.MUTED)

        return self.card(c, y, "Modo ciego", [(38, info), (16, guide)], cache_id="ciego", cache_key="fijo")

    def _system_card(self, c, y):
        row = self.trace.get(self.pos)
        rows = []
        if row is None:
            rows.append((20, lambda c, x, y, w: c.text(x, y, "Sin rostro detectado en este frame", c.fonts.body,
                                                       ui.DANGER)))
        else:
            def value(key):
                v = row.get(key)
                return float(v) if v not in (None, "") else None

            def phase(c, x, y, w):
                x += c.text(x, y, "Fase  ", c.fonts.body, ui.MUTED)
                x += c.text(x, y, ui.PHASE_LABELS.get(row["fase"], row["fase"]), c.fonts.bold) + 16
                x += c.text(x, y, "Postura  ", c.fonts.body, ui.MUTED)
                valid = row.get("postura_valida") == "1"
                c.text(x, y, "válida" if valid else "fuera de rango", c.fonts.bold, ui.OK if valid else ui.WARN)

            def meters(c, x, y, w):
                half = (w - 18) // 2
                closure = value("cierre")
                c.text(x, y, "Cierre del ojo", c.fonts.small, ui.MUTED)
                c.text(x + half, y, "–" if closure is None else f"{closure:.2f}", c.fonts.small, ui.TEXT, anchor="ra")
                c.meter(x, y + 18, half, closure, 1.2, ui.EVENT_COLORS["PARPADEO"], marks=(0.8,))
                mouth, micro, yawn = value("mouth"), value("micro_yawn_thr"), value("yawn_thr")
                bx = x + half + 18
                c.text(bx, y, "Apertura de la boca", c.fonts.small, ui.MUTED)
                c.text(bx + half, y, "–" if mouth is None else f"{mouth:.2f}", c.fonts.small, ui.TEXT, anchor="ra")
                c.meter(bx, y + 18, half, mouth, max(0.6, (yawn or 0) * 1.4), ui.EVENT_COLORS["BOSTEZO"],
                        marks=tuple(m for m in (micro, yawn) if m))

            def head(c, x, y, w):
                pitch, yaw = value("cabeza_pitch"), value("cabeza_yaw")
                angles = "–" if pitch is None or yaw is None else f"arriba/abajo {pitch:+.1f}° · lados {yaw:+.1f}°"
                x += c.text(x, y, "Cabeza  ", c.fonts.body, ui.MUTED)
                x += c.text(x, y, angles, c.fonts.body) + 16
                x += c.text(x, y, "Sonrisa  ", c.fonts.body, ui.MUTED)
                c.text(x, y, "sí" if row.get("sonrisa") == "1" else "no", c.fonts.body)

            def counters(c, x, y, w):
                x += c.text(x, y, "Contados  ", c.fonts.body, ui.MUTED)
                c.text(x, y, f"{row['parpadeos']} parpadeos · {row['bostezos']} bostezos (micro "
                             f"{row['micro_bostezos']})", c.fonts.body)

            rows += [(21, phase), (32, meters), (21, head), (21, counters)]

        near = [e for e in self.events if e[0] - 1.0 <= self.t() <= e[1] + 1.0]

        def nearby(c, x, y, w):
            if not near:
                c.text(x, y, "Sin eventos del sistema cerca de este momento", c.fonts.small, ui.FAINT)
                return
            start, end, kind = near[-1]
            more = f"   (+{len(near) - 1} más)" if len(near) > 1 else ""
            c.swatch(x, y, ui.EVENT_COLORS[kind], c.fit(f"{ui.SYSTEM_LABELS[kind]}  {start:.2f} – {end:.2f} s{more}",
                                                        c.fonts.small, w - 15), c.fonts.small, ui.TEXT)

        rows.append((18, nearby))
        return self.card(c, y, "Lo que midió el sistema", rows)

    def _annotations_card(self, c, y):
        counts = Counter(a["tipo"] for a in self.annotations)
        order = ["PARPADEO", "BOSTEZO", "MICRO_BOSTEZO", "MICRO_SUENO", "NO_EVALUABLE" if self.blind else "PROBLEMA"]

        def chips(c, x, y, w):
            cx, cy = x, y
            for kind in order:
                label = f"{ui.ANNOTATION_LABELS[kind]}  {counts.get(kind, 0)}"
                item_w = 15 + c.length(label, c.fonts.small) + 16
                if cx > x and cx + item_w > x + w:
                    cx, cy = x, cy + 17
                c.swatch(cx, cy, ui.EVENT_COLORS[kind], label, c.fonts.small, ui.TEXT)
                cx += item_w

        mine = [a for a in self.annotations if self._near_me(a)][-2:]

        def status(c, x, y, w):
            if self.pending is not None:
                kind = self.pending["tipo"]
                text = (f"Marcando {ui.ANNOTATION_LABELS[kind].lower()} desde {self.t(self.pending['frame']):.2f} s"
                        f"  ·  pulsa {KEY_FOR_TYPE[kind]} al final")
                c.draw.rounded_rectangle((x, y, x + w, y + 28), radius=6, outline=ui.WARN, width=1)
                c.text(x + 10, y + 14, c.fit(text, c.fonts.body, w - 20), c.fonts.body, ui.WARN, anchor="lm")
                return
            if not mine:
                c.text(x, y, "Ninguna anotación cerca de este momento", c.fonts.small, ui.FAINT)
            for i, a in enumerate(mine):
                text, color = self._describe(a), ui.TEXT
                if self._long_blink(a):     # guía: cerrado 1 s o más es un cierre largo (M)
                    text, color = text + "  ·  ¿cierre largo (M)? dura 1 s o más", ui.WARN
                c.swatch(x, y + 17 * i, ui.EVENT_COLORS.get(a["tipo"], ui.TEXT),
                         c.fit(text, c.fonts.small, w - 15), c.fonts.small, color)

        pending = None if self.pending is None else (self.pending["tipo"], self.pending["frame"])
        key = (self._edits, pending, tuple(id(a) for a in mine))
        return self.card(c, y, f"Tus anotaciones  ·  {len(self.annotations)}", [(36, chips), (34, status)],
                         cache_id="anotaciones", cache_key=key)

    def draw_input_card(self, c, y):
        title = "Motivo del tramo no evaluable" if self.blind else "Describe el problema"

        def box(c, x, y, w):
            c.draw.rounded_rectangle((x, y, x + w, y + 32), radius=6, fill=ui.KEY_BG, outline=ui.ACCENT, width=2)
            shown = self.comment_text
            while shown and c.length(shown + "|", c.fonts.body) > w - 20:
                shown = shown[1:]
            c.text(x + 10, y + 16, shown + "|", c.fonts.body, anchor="lm")

        def example(c, x, y, w):
            text = ("Ej.: cara tapada, fuera de cuadro, reflejo de las gafas" if self.blind
                    else "Ej.: parpadeo falso al girar la cabeza")
            c.text(x, y, text, c.fonts.small, ui.MUTED)

        def keys(c, x, y, w):
            for label, explanation in (("Enter", "guardar"), ("Esc", "sin comentario"), ("Retroceso", "borrar")):
                x += c.keycap(x, y, label) + 5
                x += c.text(x, y + 3, explanation, c.fonts.small, ui.MUTED) + 14

        return self.card(c, y, title, [(40, box), (20, example), (24, keys)])

    def key_sections(self):
        return [NAVIGATION_KEYS,
                ("Anotar: la tecla al inicio y otra vez al final",
                 [(["B"], "Parpadeo"), (["Y"], "Bostezo"), (["K"], "Micro-bostezo"), (["M"], "Cierre largo ≥ 1 s"),
                  (["X"], "No evaluable" if self.blind else "Problema")]),
                ("Corregir", [(["U"], "Deshacer la última"), (["E"], "Borrar la del cursor"),
                              (["Q"], "Guardar y salir")])]

    def timeline_rows(self):
        if self.blind:
            return [("tu", "Tú", 18)]
        return [("estado", "Estado", 7), ("sistema", "Sistema", 14), ("tu", "Tú", 14)]

    def legend_items(self):
        mine = [(ui.ANNOTATION_LABELS[k], ui.EVENT_COLORS[k])
                for k in ("PARPADEO", "BOSTEZO", "MICRO_BOSTEZO", "MICRO_SUENO")]
        if self.blind:
            return mine + [("No evaluable", ui.EVENT_COLORS["NO_EVALUABLE"])]
        return [("Midiendo", ui.STATE_COLORS["midiendo"]), ("Calibrando", ui.STATE_COLORS["calibrando"]),
                ("Calib. manual", ui.STATE_COLORS["marcas"]), ("Postura no válida", ui.STATE_COLORS["postura"]),
                ("Sin rostro", ui.STATE_COLORS["sin_rostro"]), ("Parpadeo", ui.EVENT_COLORS["PARPADEO"]),
                ("Prolongado", ui.EVENT_COLORS["PARPADEO_PROLONGADO"]), ("Bostezo", ui.EVENT_COLORS["BOSTEZO"]),
                ("Micro-bostezo", ui.EVENT_COLORS["MICRO_BOSTEZO"]), ("Micro-sueño", ui.EVENT_COLORS["MICRO_SUENO"]),
                ("Sonrisa", ui.EVENT_COLORS["SONRISA"]), ("Giro rápido", ui.EVENT_COLORS["PARPADEO_DESCARTADO_GIRO"]),
                ("Problema", ui.EVENT_COLORS["PROBLEMA"])]

    def draw_static_rows(self, c, rows, width):
        x0, x1 = self._track_x(width)
        if "estado" in rows:
            top, bottom = rows["estado"]
            for x in range(x0, x1 + 1):
                c.draw.line((x, top, x, bottom), fill=ui.STATE_COLORS[self._state(self.x_to_frame(x, width))])
        if "sistema" in rows:
            top, bottom = rows["sistema"]
            for start, end, kind in self.events:
                xs = self.frame_to_x(self.frame_at(start), width)
                xe = max(self.frame_to_x(self.frame_at(end), width), xs + 3)
                c.draw.rounded_rectangle((xs, top, xe, bottom), radius=2, fill=ui.EVENT_COLORS[kind])

    def draw_dynamic_rows(self, c, rows, width):
        top, bottom = rows["tu"]
        for a in self.annotations:
            xs = self.frame_to_x(a["frame"], width)
            xe = xs if a.get("fin_frame") is None else self.frame_to_x(a["fin_frame"], width)
            c.draw.rounded_rectangle((xs, top, max(xe, xs + 3), bottom), radius=2,
                                     fill=ui.EVENT_COLORS.get(a["tipo"], ui.TEXT))
        if self.pending is not None:    # intervalo a medio marcar: contorno hasta el cursor
            color = ui.EVENT_COLORS.get(self.pending["tipo"], ui.TEXT)
            xs, xe = sorted((self.frame_to_x(self.pending["frame"], width), self.frame_to_x(self.pos, width)))
            c.draw.rounded_rectangle((xs, top, max(xe, xs + 2), bottom), radius=2, outline=color, width=2)

    def on_exit(self):
        if self.comment_for is not None:    # ventana cerrada mientras se escribía: se guarda lo escrito
            self.comment_for["comentario"] = self.comment_text.strip()
            self._save_annotations()
        if self.pending is not None:
            print(f"[AVISO] El {ui.ANNOTATION_LABELS[self.pending['tipo']].lower()} que empezaste en "
                  f"{self.t(self.pending['frame']):.2f} s quedó sin fin y NO se guardó.")
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


def review_session(session_dir, blind, annotator=None):
    """Abre el editor de anotación sobre una sesión y espera a que se cierre (lo usa main.py desde las ventanas).
    Devuelve un mensaje de error si no se pudo abrir (sesión sin vídeo...), o None."""
    try:
        SessionReviewer(session_dir, blind, annotator).run()
    except SystemExit as stop:
        return str(stop.code) if isinstance(stop.code, str) else None
    return None


if __name__ == "__main__":
    args = parse_args()
    if args.video:
        if not os.path.exists(args.video):
            sys.exit(f"No se encuentra el vídeo: {args.video}")
        CalibrationMarker(args.video).run()
    else:
        SessionReviewer(args.sesion, args.ciego, args.anotador).run()
