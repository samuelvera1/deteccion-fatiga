# revisar_ui.py
"""
Dibujo de la interfaz de revisar.py con Pillow: fuentes TrueType (Segoe UI en Windows; DejaVu Sans, que
trae matplotlib, en otros sistemas) con tildes y eñes, tarjetas, teclas dibujadas como botones, medidores
y barra de tiempo con escala. Los colores van en RGB (Pillow); Canvas.to_bgr() convierte para OpenCV.
"""
import os

import numpy as np
from PIL import Image, ImageDraw, ImageFont

# ---------------------------------------------------------------------- paleta (RGB)
BG = (21, 22, 27)
CARD = (31, 33, 40)
CARD_BORDER = (50, 53, 64)
TRACK = (42, 45, 55)
TEXT = (234, 236, 241)
MUTED = (150, 155, 168)
FAINT = (100, 104, 117)
ACCENT = (98, 166, 255)
OK = (82, 200, 126)
WARN = (255, 182, 72)
DANGER = (238, 88, 88)
KEY_BG = (52, 56, 68)
KEY_BORDER = (90, 96, 112)
PLAYHEAD = (255, 92, 92)

# Mismo color para el evento del sistema y para la anotación del mismo tipo (se comparan de un vistazo)
EVENT_COLORS = {
    "PARPADEO": (70, 190, 255), "PARPADEO_PROLONGADO": (52, 112, 255),
    "BOSTEZO": (255, 210, 70), "MICRO_BOSTEZO": (226, 150, 52),
    "MICRO_SUENO": (238, 88, 88), "SONRISA": (206, 116, 255),
    "PARPADEO_DESCARTADO_GIRO": (118, 122, 134),
    "NO_EVALUABLE": (118, 122, 134), "PROBLEMA": (255, 128, 60),
}
SYSTEM_LABELS = {"PARPADEO": "Parpadeo", "PARPADEO_PROLONGADO": "Parpadeo prolongado", "BOSTEZO": "Bostezo",
                 "MICRO_BOSTEZO": "Micro-bostezo", "MICRO_SUENO": "Micro-sueño", "SONRISA": "Sonrisa (descartada)",
                 "PARPADEO_DESCARTADO_GIRO": "Descartado por giro"}
ANNOTATION_LABELS = {"PARPADEO": "Parpadeo", "BOSTEZO": "Bostezo", "MICRO_BOSTEZO": "Micro-bostezo",
                     "MICRO_SUENO": "Cierre largo", "NO_EVALUABLE": "No evaluable", "PROBLEMA": "Problema"}
STATE_COLORS = {"midiendo": (64, 150, 96), "calibrando": (88, 92, 104), "marcas": (70, 112, 170),
                "postura": (226, 140, 46), "sin_rostro": (170, 64, 64)}
PHASE_LABELS = {"monitoreo": "midiendo", "calibracion_manual": "calibración manual",
                "reapertura": "esperando que abra los ojos", "rostro": "calibrando (rostro)",
                "cierre": "calibrando (ojos cerrados)"}
NEUTRAL_COLOR, CLOSED_COLOR, START_COLOR = (82, 200, 126), (186, 116, 232), (234, 236, 241)


def bgr(color):
    return color[2], color[1], color[0]


# ---------------------------------------------------------------------- fuentes

def _font_file(bold):
    folders = [os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")]
    names = ["segoeuib.ttf" if bold else "segoeui.ttf"]
    try:
        import matplotlib
        folders.append(os.path.join(os.path.dirname(matplotlib.__file__), "mpl-data", "fonts", "ttf"))
        names.append("DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf")
    except ImportError:
        pass
    for folder in folders:
        for name in names:
            path = os.path.join(folder, name)
            if os.path.exists(path):
                return path
    return None


_FONT_CACHE = {}


def load_font(size, bold=False):
    """Fuente TrueType del tamaño pedido (la misma que usa la interfaz), cacheada."""
    key = (size, bold)
    if key not in _FONT_CACHE:
        path = _font_file(bold)
        _FONT_CACHE[key] = ImageFont.truetype(path, size) if path else ImageFont.load_default(size=size)
    return _FONT_CACHE[key]


class Fonts:
    def __init__(self):
        regular, bold = _font_file(False), _font_file(True)

        def load(path, size):
            return ImageFont.truetype(path, size) if path else ImageFont.load_default(size=size)

        self.clock = load(bold, 26)
        self.title = load(bold, 15)
        self.section = load(bold, 11)
        self.body = load(regular, 13)
        self.bold = load(bold, 13)
        self.small = load(regular, 11)
        self.key = load(bold, 11)


_FONTS = None


def fonts():
    global _FONTS
    if _FONTS is None:
        _FONTS = Fonts()
    return _FONTS


# ---------------------------------------------------------------------- lienzo

class Canvas:
    """Lienzo Pillow con las piezas de la interfaz."""

    def __init__(self, width, height, bg=BG, image=None):
        self.img = image if image is not None else Image.new("RGB", (int(width), int(height)), bg)
        self.draw = ImageDraw.Draw(self.img)
        self.fonts = fonts()

    def text(self, x, y, text, font=None, fill=TEXT, anchor="la"):
        font = font or self.fonts.body
        self.draw.text((x, y), text, font=font, fill=fill, anchor=anchor)
        return self.draw.textlength(text, font=font)

    def length(self, text, font=None):
        return self.draw.textlength(text, font=font or self.fonts.body)

    def fit(self, text, font, width):
        """Recorta el texto con '…' para que quepa en width píxeles."""
        if self.length(text, font) <= width:
            return text
        while text and self.length(text + "…", font) > width:
            text = text[:-1]
        return text + "…"

    def wrap(self, text, font, width):
        lines, line = [], ""
        for word in text.split():
            candidate = f"{line} {word}".strip()
            if line and self.length(candidate, font) > width:
                lines.append(line)
                line = word
            else:
                line = candidate
        return lines + ([line] if line else [])

    def card(self, x, y, w, h, title=None):
        self.draw.rounded_rectangle((x, y, x + w, y + h), radius=8, fill=CARD, outline=CARD_BORDER)
        if title:
            self.text(x + 12, y + 9, title.upper(), self.fonts.section, MUTED)

    def keycap(self, x, y, label):
        w = max(22, self.length(label, self.fonts.key) + 12)
        self.draw.rounded_rectangle((x, y, x + w, y + 20), radius=4, fill=KEY_BG, outline=KEY_BORDER)
        self.draw.text((x + w / 2, y + 10), label, font=self.fonts.key, fill=TEXT, anchor="mm")
        return w

    def pill(self, x, y, label, color, align="left"):
        w = self.length(label, self.fonts.key) + 18
        if align == "right":
            x -= w
        self.draw.rounded_rectangle((x, y, x + w, y + 20), radius=10, fill=color)
        self.draw.text((x + w / 2, y + 10), label, font=self.fonts.key, fill=(18, 19, 23), anchor="mm")
        return w

    def swatch(self, x, y, color, label, font=None, fill=MUTED):
        """Cuadradito de color + texto. Devuelve el ancho ocupado."""
        font = font or self.fonts.small
        self.draw.rounded_rectangle((x, y + 3, x + 10, y + 13), radius=2, fill=color)
        return 15 + self.text(x + 15, y, label, font, fill)

    def meter(self, x, y, w, value, maximum, color, marks=()):
        """Barra horizontal con el valor actual y rayas en los umbrales."""
        self.draw.rounded_rectangle((x, y, x + w, y + 6), radius=3, fill=TRACK)
        if value is not None and maximum > 0:
            filled = int(w * min(max(value / maximum, 0.0), 1.0))
            if filled > 0:
                self.draw.rounded_rectangle((x, y, x + max(filled, 6), y + 6), radius=3, fill=color)
        for mark in marks:
            mx = x + int(w * min(mark / maximum, 1.0))
            self.draw.line((mx, y - 3, mx, y + 9), fill=TEXT, width=1)

    def to_bgr(self):
        return np.ascontiguousarray(np.asarray(self.img)[:, :, ::-1])
