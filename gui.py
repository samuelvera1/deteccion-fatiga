# gui.py
"""Ventana única del programa (CustomTkinter). Cambia de pantalla como una página: inicio, aviso de cámara, monitor en
vivo, resumen de la sesión, cómo revisar el video y el revisor. Las pantallas de formulario solo reciben y devuelven
datos simples, sin tocar la lógica de medición (main.py las usa para armar la sesión); el monitor y el revisor se
muestran en VideoScreen, que tiene la interfaz de una ventana de OpenCV (display.py)."""
import collections
import os
import sys
import time
import tkinter

import customtkinter as ctk
import cv2
from PIL import Image, ImageTk

import fatigue_hud
import version

# ---------------------------------------------------------------------- paleta (la misma del monitor en vivo)
BG, CARD, BORDER = "#15161B", "#1F2128", "#323540"
TEXT, MUTED, FAINT = "#EAECF1", "#969BA8", "#646875"
ACCENT, ACCENT_HOVER, ON_ACCENT = "#62A6FF", "#8BBEFF", "#0E1118"
BUTTON, BUTTON_HOVER, BUTTON_BORDER = "#343844", "#3F4452", "#5A6070"
SELECTED, SELECTED_HOVER = "#2C4F85", "#345C99"
TRACK = "#2A2D37"
WARN, WARN_BG = "#F3C430", "#2A2410"
DANGER = "#FF4B4B"
LEVEL_COLORS = {"NORMAL": "#3CC970", "PRECAUCION": "#F3C430", "SOMNOLENCIA": "#FF8C3C", "MICRO_SUENO": "#FF4B4B"}
UNRELIABLE = "#4A4E5C"

FONT = "Segoe UI"
CONTENT_W = 880                  # ancho del contenido de los formularios, centrado en la ventana
GAP = 20                         # separación entre las dos columnas
COLUMN_W = (CONTENT_W - GAP) // 2

ctk.set_appearance_mode("dark")


def resource_path(relative):
    """Archivo del programa, tanto desde el código como dentro del ejecutable."""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, relative)


def shorten_path(path, limit=64):
    """Acorta una ruta larga con '…' en el medio: conserva el inicio y las últimas carpetas que quepan."""
    if len(path) <= limit:
        return path
    sep = "\\"
    parts = path.replace("/", sep).split(sep)
    head = parts[0] + sep + parts[1] if len(parts) > 3 else parts[0]
    for keep in (3, 2, 1):
        short = f"{head}{sep}…{sep}{sep.join(parts[-keep:])}"
        if len(short) <= limit:
            return short
    return short


def font(size, bold=False):
    return ctk.CTkFont(family=FONT, size=int(round(size)), weight="bold" if bold else "normal")


def label(master, text, size=14, bold=False, color=TEXT, **options):
    options.setdefault("height", 0)      # sin la altura mínima de 28 px de CustomTkinter: el diseño es más compacto
    return ctk.CTkLabel(master, text=text, font=font(size, bold), text_color=color, **options)


def card(master, **options):
    options.setdefault("corner_radius", 13)
    return ctk.CTkFrame(master, fg_color=CARD, border_width=1, border_color=BORDER, **options)


def button(master, text, command, primary=False, **options):
    if primary:
        colors = {"fg_color": ACCENT, "hover_color": ACCENT_HOVER, "text_color": ON_ACCENT}
    else:
        colors = {"fg_color": BUTTON, "hover_color": BUTTON_HOVER, "text_color": TEXT,
                  "border_width": 1, "border_color": BUTTON_BORDER}
    return ctk.CTkButton(master, text=text, command=command, height=44, corner_radius=10, font=font(15, True),
                         **colors, **options)


def columns(master, **pack):
    """Fila con dos columnas del mismo ancho (0 y 1), para llenarla con grid."""
    row = ctk.CTkFrame(master, fg_color="transparent")
    row.pack(fill="x", **pack)
    row.grid_columnconfigure((0, 1), weight=1, uniform="column")
    return row


SPECIAL_KEYS = {"Return": 13, "KP_Enter": 13, "Escape": 27, "BackSpace": 8}


def key_code(event):
    """Tecla de Tk -> código como el de cv2.waitKey (0-254), o None si no tiene."""
    if event.keysym in SPECIAL_KEYS:
        return SPECIAL_KEYS[event.keysym]
    if len(event.char) == 1 and 32 <= ord(event.char) < 255:
        return ord(event.char)
    return None


# ---------------------------------------------------------------------- la ventana

class App(ctk.CTk):
    """La ventana del programa, del tamaño del monitor en vivo (la pantalla más grande) y centrada. Muestra una pantalla
    a la vez (set_screen). Cerrarla con la X termina el programa (durante el monitor, tras confirmarlo); la sesión en
    curso se guarda igual."""

    def __init__(self):
        super().__init__(fg_color=BG)
        self.title("Fatiga Detector")
        self.closed = False
        self.result = None
        self.screen = None
        # CustomTkinter deja programados callbacks (animación de botones, escala de pantalla) que se disparan con el
        # widget ya destruido al cambiar de pantalla, y Tcl los muestra como "invalid command name". Es inofensivo: se
        # silencian los errores de fondo de Tcl. NO se cancelan esos callbacks a mano: cada widget los borra al
        # destruirse y, si ya no existen, destroy() falla con "can't delete Tcl command".
        self.tk.eval("proc bgerror {args} {}")
        # geometry() de CustomTkinter multiplica ancho y alto por la escala de Windows, pero no la posición
        scaling = ctk.ScalingTracker.get_window_scaling(self)
        screen_w, screen_h = self.winfo_screenwidth(), self.winfo_screenheight()
        fit = min(1.0, (screen_w / scaling - 20) / fatigue_hud.WIDTH, (screen_h / scaling - 120) / fatigue_hud.HEIGHT)
        width, height = int(fatigue_hud.WIDTH * fit), int(fatigue_hud.HEIGHT * fit)
        x = max(0, int(screen_w - width * scaling) // 2)
        y = max(0, int(screen_h - height * scaling) // 2 - 20)
        self.geometry(f"{width}x{height}+{x}+{y}")
        self.minsize(min(width, CONTENT_W + 40), min(height, 560))
        icon = resource_path(os.path.join("assets", "fatiga.ico"))
        if os.path.exists(icon):
            # CustomTkinter pone su icono por defecto a los 200 ms: se cambia después
            self.after(300, lambda: self._set_icon(icon))
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.bind("<Key>", self._on_key)
        self.lift()
        self.attributes("-topmost", True)
        self.after(200, lambda: self.attributes("-topmost", False))

    def _set_icon(self, path):
        try:
            self.iconbitmap(path)
        except Exception:
            pass

    def _on_close(self):
        if self.screen is not None and not self.screen.can_close():
            return
        self.close_now()

    def close_now(self):
        self.closed = True
        self.withdraw()                  # desaparece al instante aunque la sesión tarde en terminar de guardarse
        self.quit()

    def _on_key(self, event):
        if self.screen is not None:
            self.screen.on_key(event)

    def set_screen(self, screen):
        if screen is self.screen:
            return
        if self.screen is not None:
            self.screen.destroy()
        self.screen = screen
        screen.pack(fill="both", expand=True)
        self.focus_set()

    def run(self, screen):
        """Muestra una pantalla de formulario hasta que se elige algo (Screen.close) o se cierra la ventana. Devuelve lo
        elegido (None si se cerró). La pantalla sigue a la vista hasta que la reemplace la siguiente."""
        self.set_screen(screen)
        self.result = None
        if not self.closed:
            self.mainloop()
        return None if self.closed else self.result

    def finish(self, result):
        self.result = result
        self.quit()

    def loading(self, text):
        """Pantalla de espera mientras el programa hace algo que tarda (abrir la cámara, guardar la sesión...)."""
        self.set_screen(MessageScreen(self, text))
        self.update()


class Screen(ctk.CTkFrame):
    """Pantalla de formulario: el contenido (self.body) va centrado en la ventana, con el ancho indicado."""

    def __init__(self, app, width=CONTENT_W):
        super().__init__(app, fg_color=BG, corner_radius=0)
        self.app = app
        self.body = ctk.CTkFrame(self, fg_color="transparent")
        self.body.place(relx=0.5, rely=0.5, anchor="center")
        # fija el ancho del contenido: sin esto, el marco toma el ancho de lo que lleva dentro
        ctk.CTkFrame(self.body, fg_color="transparent", width=width, height=1).pack()

    def on_key(self, event):
        if event.keysym == "Escape":
            self.close()

    def can_close(self):
        return True

    def close(self, result=None):
        self.app.finish(result)


class MessageScreen(Screen):
    def __init__(self, app, text):
        super().__init__(app, width=400)
        label(self.body, text, 16, color=MUTED).pack()

    def on_key(self, event):
        pass


# ---------------------------------------------------------------------- inicio

class StartScreen(Screen):
    """Devuelve {"name": str, "condition": None | "con_gafas" | "sin_gafas", "record": bool}, o None si se sale."""

    GLASSES = {"Con gafas": "con_gafas", "Sin gafas": "sin_gafas", "Prefiero no indicarlo": None}

    def __init__(self, app):
        super().__init__(app)
        body = self.body
        head = ctk.CTkFrame(body, fg_color="transparent")
        head.pack(anchor="w")
        label(head, "Fatiga Detector", 26, True).pack(side="left")
        label(head, f"v{version.VERSION}", 12, color=FAINT).pack(side="left", padx=(8, 0), pady=(10, 0))
        label(body, "Mide parpadeos, bostezos y cansancio con tu cámara. Todo se queda en este equipo.", 13.5,
              color=MUTED).pack(anchor="w", pady=(2, 0))

        row = columns(body, pady=(24, 0))
        form = ctk.CTkFrame(row, fg_color="transparent")
        form.grid(row=0, column=0, sticky="nsew", padx=(0, GAP // 2))
        label(form, "Nombre del participante", 14, True).pack(anchor="w", pady=(0, 6))
        self.name = ctk.CTkEntry(form, placeholder_text="Opcional", height=40, corner_radius=10, border_width=1,
                                 fg_color=CARD, border_color=BORDER, text_color=TEXT, placeholder_text_color=FAINT,
                                 font=font(13))
        self.name.pack(fill="x")
        label(form, "Si lo dejas vacío, la sesión queda como anónima.", 11, color=FAINT).pack(anchor="w", pady=(5, 0))

        label(form, "¿Llevas gafas?", 14, True).pack(anchor="w", pady=(20, 6))
        self.glasses = ctk.CTkSegmentedButton(
            form, values=list(self.GLASSES), height=36, corner_radius=10, border_width=3, font=font(13),
            fg_color=CARD, selected_color=SELECTED, selected_hover_color=SELECTED_HOVER, unselected_color=CARD,
            unselected_hover_color=BUTTON, text_color=TEXT)
        self.glasses.set("Prefiero no indicarlo")
        self.glasses.pack(fill="x")

        self.record = ctk.CTkSwitch(form, text="Grabar el video de la sesión para revisarlo después", font=font(13),
                                    text_color=TEXT, progress_color=ACCENT, fg_color=TRACK, button_color="#FFFFFF",
                                    button_hover_color="#E4E7EE", switch_width=38, switch_height=20)
        self.record.pack(anchor="w", pady=(22, 0))
        label(form, "El video se guarda solo en este equipo.", 11, color=FAINT).pack(anchor="w", padx=(48, 0))

        steps = card(row)
        steps.grid(row=0, column=1, sticky="nsew", padx=(GAP // 2, 0))
        label(steps, "Qué va a pasar", 14, True).pack(anchor="w", padx=18, pady=(16, 8))
        for number, text in enumerate(("Mira al frente, con los ojos abiertos, sin moverte.",
                                       "Cierra los ojos hasta oír un pitido y ábrelos.",
                                       "Listo: la pantalla te muestra tu nivel de fatiga."), 1):
            step = ctk.CTkFrame(steps, fg_color="transparent")
            step.pack(anchor="w", padx=18, pady=3)
            badge = ctk.CTkFrame(step, fg_color=BUTTON, corner_radius=12, width=24, height=24)
            badge.pack(side="left")
            badge.pack_propagate(False)
            label(badge, str(number), 12, True).pack(expand=True)
            label(step, text, 13).pack(side="left", padx=(10, 0))
        label(steps, "El nivel de fatiga completo aparece tras 1 minuto; los parpadeos y bostezos se cuentan desde el "
                     "inicio.", 11.5, color=MUTED, wraplength=COLUMN_W - 36, justify="left").pack(anchor="w", padx=18,
                                                                                                 pady=(10, 0))
        keys = ctk.CTkFrame(steps, fg_color="transparent")
        keys.pack(anchor="w", padx=18, pady=(8, 16))
        for text, bold in (("Para terminar pulsa ", False), ("Q", True), (". Para recalibrar pulsa ", False),
                           ("C", True), (".", False)):
            label(keys, text, 12, bold, color=TEXT if bold else MUTED).pack(side="left")

        buttons = ctk.CTkFrame(body, fg_color="transparent")
        buttons.pack(fill="x", pady=(28, 0))
        self.start_button = button(buttons, "Empezar", self.start, primary=True)
        self.start_button.pack(side="left", fill="x", expand=True)
        self.exit_button = button(buttons, "Salir", self.close, width=140)
        self.exit_button.pack(side="left", padx=(12, 0))
        label(body, "Herramienta de investigación. No es un dispositivo médico.", 11, color=FAINT).pack(pady=(14, 0))

    def on_key(self, event):
        if event.keysym in ("Return", "KP_Enter"):
            self.start()
        else:
            super().on_key(event)

    def start(self):
        self.close({"name": self.name.get().strip(), "condition": self.GLASSES[self.glasses.get()],
                    "record": bool(self.record.get())})


# ---------------------------------------------------------------------- resumen

class SummaryScreen(Screen):
    """Resumen al terminar (datos de session_view.summary_view). Devuelve "new", "review" o None."""

    def __init__(self, app, view):
        super().__init__(app)
        self.view = view
        ok = view["reliable"] and view["counted"]      # sin datos fiables se atenúa todo
        body = self.body

        label(body, "Resumen de la sesión", 24, True).pack(anchor="w")
        who = ctk.CTkFrame(body, fg_color="transparent")
        who.pack(anchor="w", pady=(3, 0))
        label(who, view["participant"], 14).pack(side="left")
        label(who, f" · {view['glasses']}", 14, color=MUTED).pack(side="left")
        label(who, f"   {view['when']} · Duración ", 13, color=MUTED).pack(side="left")
        label(who, view["duration"], 13, True).pack(side="left")

        if view["warning"]:
            warning = ctk.CTkFrame(body, fg_color=WARN_BG, border_width=1, border_color=WARN, corner_radius=10)
            warning.pack(fill="x", pady=(14, 0))
            label(warning, f"⚠ {view['warning']}", 13, color=WARN, wraplength=CONTENT_W - 28,
                  justify="left").pack(anchor="w", padx=14, pady=10)

        stats = ctk.CTkFrame(body, fg_color="transparent")
        stats.pack(fill="x", pady=(14, 0))
        for column, (title, value, subs, dim) in enumerate((
                ("PARPADEOS", view["blinks"], view["blinks_sub"], False),
                ("BOSTEZOS", view["yawns"], view["yawns_sub"], False),
                ("PERCLOS FINAL", view["perclos"], [view["perclos_sub"]], not ok))):
            stats.grid_columnconfigure(column, weight=1, uniform="stat")
            tile = card(stats, corner_radius=12)
            tile.grid(row=0, column=column, sticky="nsew", padx=(0 if column == 0 else 6, 0 if column == 2 else 6))
            label(tile, title, 11, True, color=MUTED).pack(anchor="w", padx=16, pady=(12, 0))
            label(tile, value, 28, True, color=FAINT if dim else TEXT).pack(anchor="w", padx=16)
            for sub in subs:
                label(tile, sub, 11.5, color=FAINT if dim else MUTED).pack(anchor="w", padx=16)
            label(tile, "", 2).pack(pady=(0, 5))

        row = columns(body, pady=(12, 0))
        levels = card(row)
        levels.grid(row=0, column=0, sticky="nsew", padx=(0, GAP // 2))
        top = ctk.CTkFrame(levels, fg_color="transparent")
        top.pack(fill="x", padx=16, pady=(12, 6))
        label(top, "Tiempo en cada nivel", 14, True, color=FAINT if not ok else TEXT).pack(side="left")
        label(top, "alertas", 12, color=FAINT if not ok else MUTED).pack(side="right")
        bar = ctk.CTkFrame(levels, fg_color=TRACK, corner_radius=3, height=14)
        bar.pack(fill="x", padx=16)
        bar.pack_propagate(False)
        offset = 0.0
        for level in view["levels"]:
            if level["share"] > 0:
                segment = ctk.CTkFrame(bar, fg_color=UNRELIABLE if not ok else LEVEL_COLORS[level["key"]],
                                       corner_radius=0)
                width = max(level["share"], 0.008)          # un tramo muy corto sigue viéndose
                segment.place(relx=offset, rely=0, relheight=1, relwidth=width)
                offset += width
        table = ctk.CTkFrame(levels, fg_color="transparent")
        table.pack(fill="x", padx=16, pady=(8, 10))
        table.grid_columnconfigure(1, weight=1)
        for row_index, level in enumerate(view["levels"]):
            dim = FAINT if not ok else None
            ctk.CTkLabel(table, text="●", font=font(11), text_color=UNRELIABLE if not ok else LEVEL_COLORS[level["key"]],
                         width=18).grid(row=row_index, column=0, sticky="w", pady=1)
            label(table, level["name"], 14, color=dim or TEXT).grid(row=row_index, column=1, sticky="w", padx=(4, 0))
            label(table, level["time"], 13, color=dim or TEXT).grid(row=row_index, column=2, sticky="e", padx=(8, 0))
            label(table, level["percent"], 13, color=dim or MUTED, width=64, anchor="e").grid(row=row_index, column=3,
                                                                                              sticky="e")
            label(table, level["alerts"], 13, True, color=dim or TEXT, width=44, anchor="e").grid(row=row_index,
                                                                                                  column=4, sticky="e")

        info = card(row)
        info.grid(row=0, column=1, sticky="nsew", padx=(GAP // 2, 0))
        label(info, "Detalles", 14, True).pack(anchor="w", padx=16, pady=(12, 6))
        for text, value in (("Recalibraciones", view["recalibrations"]), ("FPS medio", view["fps"]),
                            ("Versión", view["build"])):
            pair = ctk.CTkFrame(info, fg_color="transparent")
            pair.pack(fill="x", padx=16, pady=1)
            label(pair, text, 13, color=MUTED).pack(side="left")
            label(pair, value, 13, True).pack(side="right")
        label(info, "Guardado en", 12, color=MUTED).pack(anchor="w", padx=16, pady=(10, 0))
        where = ctk.CTkFrame(info, fg_color="transparent")
        where.pack(fill="x", padx=16, pady=(2, 12))
        self.open_button = ctk.CTkButton(where, text="Abrir carpeta", command=self.open_folder, width=104, height=28,
                                         corner_radius=8, font=font(12, True), fg_color=BUTTON, hover_color=BUTTON_HOVER,
                                         text_color=TEXT, border_width=1, border_color=BUTTON_BORDER)
        self.open_button.pack(side="right", anchor="n")
        label(where, shorten_path(view["folder"], 50), 11, wraplength=COLUMN_W - 32 - 116, justify="left").pack(
            side="left", anchor="n")

        buttons = ctk.CTkFrame(body, fg_color="transparent")
        buttons.pack(fill="x", pady=(18, 0))
        self.review_button = button(buttons, "Revisar el video", lambda: self.close("review"), primary=True)
        self.review_button.pack(side="left", fill="x", expand=True)
        self.new_button = button(buttons, "Nueva sesión", lambda: self.close("new"), width=150)
        self.new_button.pack(side="left", padx=(12, 0))
        self.close_button = button(buttons, "Cerrar", self.close, width=120)
        self.close_button.pack(side="left", padx=(12, 0))

    def open_folder(self):
        try:
            os.startfile(self.view["folder"])
        except (AttributeError, OSError):
            pass


# ---------------------------------------------------------------------- revisar el video

class ReviewScreen(Screen):
    """Elige cómo revisar el video de la sesión. Devuelve "blind", "review" o None (volver al resumen).
    view: datos de session_view.summary_view (recorded, annotations)."""

    def __init__(self, app, view):
        super().__init__(app)
        body = self.body
        label(body, "Revisar el video", 24, True).pack(anchor="w")
        if not view["recorded"]:
            label(body, "Esta sesión no se grabó, así que no hay video que revisar. La próxima vez activa «Grabar el "
                        "video de la sesión» en la pantalla de inicio.", 13.5, color=MUTED, wraplength=CONTENT_W,
                  justify="left").pack(anchor="w", pady=(10, 0))
            self.cancel_button = button(body, "Volver al resumen", self.close, primary=True, width=220)
            self.cancel_button.pack(anchor="e", pady=(24, 0))
            return
        label(body, "Marca sobre el video dónde hubo cada evento (parpadeo, bostezo, cierre largo...).", 13.5,
              color=MUTED).pack(anchor="w", pady=(4, 0))
        row = columns(body, pady=(16, 0))
        self.blind_button = self._option(
            row, 0, "Anotar eventos",
            "No ves lo que detectó el sistema, así tu anotación no se deja influir. Es la que sirve como "
            "referencia para medir su precisión.", "blind", True)
        self.review_button = self._option(
            row, 1, "Revisar detecciones",
            "Ves lo que detectó el sistema y marcas dónde se equivocó (por ejemplo: «aquí no hubo bostezo»). "
            "Sirve para encontrar errores, no como referencia.", "review", False)
        counts = view["annotations"]
        if counts["blind"] or counts["review"]:
            parts = []
            if counts["blind"]:
                parts.append(f"{counts['blind']} anotadas en modo ciego")
            if counts["review"]:
                parts.append(f"{counts['review']} de revisión")
            label(body, "Ya guardadas: " + " · ".join(parts), 12, color=MUTED).pack(anchor="w", pady=(12, 0))
        self.cancel_button = button(body, "Volver al resumen", self.close, width=220)
        self.cancel_button.pack(anchor="e", pady=(24, 0))

    def on_key(self, event):
        if event.keysym in ("Return", "KP_Enter") and not hasattr(self, "blind_button"):
            self.close()
        else:
            super().on_key(event)

    def _option(self, row, column, title, description, result, primary):
        frame = card(row)
        frame.grid(row=0, column=column, sticky="nsew", padx=(0, GAP // 2) if column == 0 else (GAP // 2, 0))
        chosen = button(frame, title, lambda: self.close(result), primary=primary)
        chosen.configure(height=38)
        chosen.pack(side="bottom", fill="x", padx=16, pady=(0, 16))
        label(frame, title, 15, True).pack(anchor="w", padx=16, pady=(14, 0))
        label(frame, description, 12.5, color=MUTED, wraplength=COLUMN_W - 32, justify="left").pack(
            anchor="w", padx=16, pady=(4, 14))
        return chosen


# ---------------------------------------------------------------------- cámara

class CameraErrorScreen(Screen):
    """Aviso de cámara no disponible. Devuelve "retry" o None (salir)."""

    def __init__(self, app):
        super().__init__(app, width=480)
        body = self.body
        head = ctk.CTkFrame(body, fg_color="transparent")
        head.pack(anchor="w")
        label(head, "●", 14, color=DANGER).pack(side="left")
        label(head, "No encontramos la cámara", 22, True).pack(side="left", padx=(10, 0))
        label(body, "Revisa que esté conectada y que ningún otro programa la esté usando (Zoom, Teams...). "
                    "Luego vuelve a intentarlo.", 13.5, color=MUTED, wraplength=480, justify="left").pack(
            anchor="w", pady=(10, 0))
        buttons = ctk.CTkFrame(body, fg_color="transparent")
        buttons.pack(anchor="e", pady=(24, 0))
        self.retry_button = button(buttons, "Reintentar", lambda: self.close("retry"), primary=True, width=130)
        self.retry_button.pack(side="right")
        self.exit_button = button(buttons, "Salir", self.close, width=100)
        self.exit_button.pack(side="right", padx=(0, 10))

    def on_key(self, event):
        if event.keysym in ("Return", "KP_Enter"):
            self.close("retry")
        else:
            super().on_key(event)


# ---------------------------------------------------------------------- monitor y revisor

class VideoScreen(tkinter.Frame):
    """Pantalla del monitor en vivo o del revisor, con la interfaz de display.OpenCvWindow: la imagen ocupa toda la
    ventana, escalada sin deformarla, y las teclas y el ratón le llegan como a una ventana de OpenCV. El bucle del
    monitor sigue siendo el suyo: wait_key() atiende la ventana mientras espera."""

    MOUSE = (("<ButtonPress-1>", cv2.EVENT_LBUTTONDOWN), ("<B1-Motion>", cv2.EVENT_MOUSEMOVE),
             ("<ButtonRelease-1>", cv2.EVENT_LBUTTONUP))

    def __init__(self, name, size=None):
        app = get_app()
        super().__init__(app, bg=BG, bd=0, highlightthickness=0)
        self.app = app
        self._keys = collections.deque()
        self._mouse = None
        self._photo = None
        self._buffer = None
        self._layout = (1.0, 0, 0)           # escala y posición de la imagen dentro de la pantalla
        self._confirm_close = name == fatigue_hud.WINDOW_NAME
        self._prompt = None
        self.image = tkinter.Label(self, bg=BG, bd=0, highlightthickness=0, text="Un momento…", fg=MUTED,
                                   font=(FONT, 14))
        self.image.place(x=0, y=0, relwidth=1, relheight=1)    # place: la imagen no agranda la ventana
        for sequence, event in self.MOUSE:
            self.image.bind(sequence, lambda e, kind=event: self._on_mouse(kind, e))
        app.set_screen(self)
        app.update()

    def on_key(self, event):
        code = key_code(event)
        if code is not None:
            self._keys.append(code)

    def can_close(self):
        if not self._confirm_close:
            return True
        if self._prompt is None:
            self._prompt = self._close_prompt()
        return False

    def _close_prompt(self):
        # sobre la imagen y no un cuadro modal: el modal pararía la cámara y dejaría un hueco en las mediciones
        prompt = card(self, corner_radius=14)
        prompt.place(relx=0.5, rely=0.5, anchor="center")
        label(prompt, "¿Cerrar Fatiga Detector?", 18, True).pack(anchor="w", padx=22, pady=(18, 0))
        label(prompt, "La sesión termina aquí y se guarda lo medido hasta ahora, pero no verás el resumen.\n"
                      "Para terminar y ver el resumen, pulsa Q.", 13, color=MUTED, justify="left").pack(
            anchor="w", padx=22, pady=(6, 0))
        buttons = ctk.CTkFrame(prompt, fg_color="transparent")
        buttons.pack(anchor="e", padx=22, pady=(18, 18))
        self.keep_button = button(buttons, "Seguir con la sesión", self._dismiss_prompt, primary=True, width=200)
        self.keep_button.pack(side="right")
        self.close_button = button(buttons, "Cerrar", self.app.close_now, width=110)
        self.close_button.pack(side="right", padx=(0, 10))
        return prompt

    def _dismiss_prompt(self):
        self._prompt.destroy()
        self._prompt = None

    def _on_mouse(self, kind, event):
        if self._mouse is not None:
            scale, x0, y0 = self._layout
            self._mouse(kind, int((event.x - x0) / scale), int((event.y - y0) / scale), 0, None)

    def size(self):
        width, height = self.winfo_width(), self.winfo_height()
        return (width, height) if width > 1 and height > 1 else None

    def show(self, img):
        width, height = self.size() or (img.shape[1], img.shape[0])
        out = fatigue_hud.fit_to_window(img, (width, height), self._buffer)
        h, w = img.shape[:2]
        if out is img:                       # ya era del tamaño de la pantalla
            scale, shown_w, shown_h = 1.0, w, h
        else:
            self._buffer = out
            scale = min(width / w, height / h)
            shown_w, shown_h = max(1, int(w * scale)), max(1, int(h * scale))
        # la etiqueta centra la imagen; dentro de ella, fit_to_window centra el fotograma
        out_h, out_w = out.shape[:2]
        self._layout = (scale, (width - out_w) // 2 + (out_w - shown_w) // 2, (height - out_h) // 2 + (out_h - shown_h) // 2)
        rgb = Image.fromarray(cv2.cvtColor(out, cv2.COLOR_BGR2RGB))
        if self._photo is None or (self._photo.width(), self._photo.height()) != rgb.size:
            self._photo = ImageTk.PhotoImage(rgb)
            self.image.configure(image=self._photo, text="")
        else:
            self._photo.paste(rgb)

    def wait_key(self, ms):
        deadline = time.perf_counter() + ms / 1000
        while True:
            self.app.update()
            if self._keys or self.app.closed or time.perf_counter() >= deadline:
                break
            time.sleep(0.005)
        return self._keys.popleft() if self._keys else 255

    def is_open(self):
        return not self.app.closed

    def on_mouse(self, callback):
        self._mouse = callback

    def close(self):
        self.app.loading("Un momento…")      # hasta que aparezca la pantalla siguiente (guardar la sesión tarda)


# ---------------------------------------------------------------------- uso desde main.py

_app = None


def get_app():
    global _app
    if _app is None:
        _app = App()
    return _app


def closed():
    """True si se cerró la ventana con la X (atiende antes los clics pendientes)."""
    if _app is None:
        return False
    if not _app.closed:
        _app.update()
    return _app.closed


def close():
    global _app
    if _app is not None:
        _app.destroy()
        _app = None


def show_error(text):
    """Cuadro de error sencillo (si algo falla sin pantalla propia)."""
    from tkinter import messagebox
    if _app is not None and not _app.closed:
        messagebox.showerror("Fatiga Detector", text, parent=_app)
        return
    root = tkinter.Tk()
    root.withdraw()
    messagebox.showerror("Fatiga Detector", text)
    root.destroy()


def ask_start():
    app = get_app()
    choice = app.run(StartScreen(app))
    if choice is not None:
        app.loading("Abriendo la cámara…")
    return choice


def show_summary(view):
    app = get_app()
    return app.run(SummaryScreen(app, view))


def ask_review(view):
    app = get_app()
    mode = app.run(ReviewScreen(app, view))
    if mode:
        app.loading("Abriendo el video…")
    return mode


def camera_error():
    app = get_app()
    choice = app.run(CameraErrorScreen(app))
    if choice == "retry":
        app.loading("Buscando la cámara…")
    return choice
