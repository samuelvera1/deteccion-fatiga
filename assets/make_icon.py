# assets/make_icon.py
"""Genera assets/fatiga.ico (un ojo sobre fondo oscuro, con la paleta de la interfaz). Se ejecuta una sola vez:
    python assets/make_icon.py
El .ico resultante se guarda en el repositorio; lo usan las ventanas y el ejecutable."""
import os

from PIL import Image, ImageChops, ImageDraw

BG, ACCENT, WHITE = (21, 22, 27), (98, 166, 255), (234, 236, 241)
S = 1024                                   # se dibuja grande y se reduce: bordes suaves


def circle(cx, cy, r):
    mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(mask).ellipse((cx - r, cy - r, cx + r, cy + r), fill=255)
    return mask


def draw():
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((24, 24, S - 24, S - 24), radius=220, fill=BG, outline=(50, 53, 64), width=14)
    cx = cy = S // 2
    # el ojo es una almendra: intersección de dos círculos grandes, uno desplazado hacia arriba y otro hacia abajo
    almond = ImageChops.multiply(circle(cx, cy + 330, 600), circle(cx, cy - 330, 600))
    shrunk = almond.resize((S - 90, S - 90))
    hole = Image.new("L", (S, S), 0)
    hole.paste(shrunk, (45, 45))
    ring = ImageChops.subtract(almond, hole)           # solo el contorno de la almendra
    img.paste(Image.new("RGBA", (S, S), ACCENT + (255,)), (0, 0), ring)
    d = ImageDraw.Draw(img)
    d.ellipse((cx - 150, cy - 150, cx + 150, cy + 150), fill=ACCENT)    # iris
    d.ellipse((cx - 70, cy - 70, cx + 70, cy + 70), fill=BG)            # pupila
    d.ellipse((cx - 30, cy - 90, cx + 20, cy - 40), fill=WHITE)         # brillo
    return img


if __name__ == "__main__":
    here = os.path.dirname(os.path.abspath(__file__))
    icon = draw().resize((256, 256), Image.LANCZOS)
    icon.save(os.path.join(here, "fatiga.ico"), sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print("assets/fatiga.ico generado")
