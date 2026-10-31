# gui.py
"""Ventanas del programa (CustomTkinter): inicio, resumen de la sesión y aviso de cámara. Solo interfaz: reciben y
devuelven datos simples, sin tocar la lógica de medición (main.py las usa para armar la sesión)."""
import os
import sys

import customtkinter as ctk

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
WIDTH, HEIGHT = 520, 660
MARGIN = 24

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


class Window(ctk.CTk):
    """Ventana de tamaño fijo, centrada, con el fondo y el icono del programa."""

    def __init__(self, title, width=WIDTH, height=HEIGHT):
        super().__init__(fg_color=BG)
        self.title(title)
        self.resizable(False, False)
        self.result = None
        x = (self.winfo_screenwidth() - width) // 2
        y = max(0, (self.winfo_screenheight() - height) // 2 - 20)
        self.geometry(f"{width}x{height}+{x}+{y}")
        icon = resource_path(os.path.join("assets", "fatiga.ico"))
        if os.path.exists(icon):
            # CustomTkinter pone su icono por defecto a los 200 ms: se cambia después
            self.after(300, lambda: self._set_icon(icon))
        self.protocol("WM_DELETE_WINDOW", self.close)

    def _set_icon(self, path):
        try:
            self.iconbitmap(path)
        except Exception:
            pass

    def close(self, result=None):
        self.result = result
        self.quit()

    def run(self):
        """Muestra la ventana hasta que se cierre y devuelve el resultado (None si se cerró sin elegir)."""
        self.lift()
        self.attributes("-topmost", True)
        self.after(200, lambda: self.attributes("-topmost", False))
        self.mainloop()
        # CustomTkinter deja programados algunos callbacks (animación de botones, escala de pantalla) que se
        # disparan ya con la ventana destruida y Tcl los muestra como "invalid command name" en la consola. Es
        # inofensivo: se silencian los errores de fondo de Tcl. NO se cancelan esos callbacks a mano: cada widget
        # los borra al destruirse y, si ya no existen, destroy() falla con "can't delete Tcl command".
        self.tk.eval("proc bgerror {args} {}")
        self.destroy()
        return self.result


# ---------------------------------------------------------------------- inicio

class StartWindow(Window):
    """Devuelve {"name": str, "condition": None | "con_gafas" | "sin_gafas", "record": bool}, o None si se sale."""

    GLASSES = {"Con gafas": "con_gafas", "Sin gafas": "sin_gafas", "Prefiero no indicarlo": None}

    def __init__(self):
        super().__init__("Fatiga Detector")
        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=MARGIN, pady=(22, 14))

        head = ctk.CTkFrame(body, fg_color="transparent")
        head.pack(anchor="w")
        label(head, "Fatiga Detector", 24, True).pack(side="left")
        label(head, f"v{version.VERSION}", 12, color=FAINT).pack(side="left", padx=(8, 0), pady=(8, 0))
        label(body, "Mide parpadeos, bostezos y cansancio con tu cámara. Todo se queda en este equipo.", 13,
              color=MUTED, wraplength=WIDTH - 2 * MARGIN, justify="left").pack(anchor="w", pady=(2, 0))

        label(body, "Nombre del participante", 14, True).pack(anchor="w", pady=(24, 6))
        self.name = ctk.CTkEntry(body, placeholder_text="Opcional", height=40, corner_radius=10, border_width=1,
                                 fg_color=CARD, border_color=BORDER, text_color=TEXT, placeholder_text_color=FAINT,
                                 font=font(13))
        self.name.pack(fill="x")
        label(body, "Si lo dejas vacío, la sesión queda como anónima.", 11, color=FAINT).pack(anchor="w", pady=(5, 0))

        label(body, "¿Llevas gafas?", 14, True).pack(anchor="w", pady=(20, 6))
        self.glasses = ctk.CTkSegmentedButton(
            body, values=list(self.GLASSES), height=36, corner_radius=10, border_width=3, font=font(13),
            fg_color=CARD, selected_color=SELECTED, selected_hover_color=SELECTED_HOVER, unselected_color=CARD,
            unselected_hover_color=BUTTON, text_color=TEXT)
        self.glasses.set("Prefiero no indicarlo")
        self.glasses.pack(fill="x")

        self.record = ctk.CTkSwitch(body, text="Grabar el video de la sesión para revisarlo después", font=font(13),
                                    text_color=TEXT, progress_color=ACCENT, fg_color=TRACK, button_color="#FFFFFF",
                                    button_hover_color="#E4E7EE", switch_width=38, switch_height=20)
        self.record.pack(anchor="w", pady=(20, 0))
        label(body, "El video se guarda solo en este equipo.", 11, color=FAINT).pack(anchor="w", padx=(48, 0))

        steps = card(body)
        steps.pack(fill="x", pady=(20, 0))
        label(steps, "Qué va a pasar", 13.5, True).pack(anchor="w", padx=18, pady=(14, 8))
        for number, text in enumerate(("Mira al frente, con los ojos abiertos, sin moverte.",
                                       "Cierra los ojos hasta oír un pitido y ábrelos.",
                                       "Listo: la pantalla te muestra tu nivel de fatiga."), 1):
            row = ctk.CTkFrame(steps, fg_color="transparent")
            row.pack(anchor="w", padx=18, pady=3)
            badge = ctk.CTkFrame(row, fg_color=BUTTON, corner_radius=12, width=24, height=24)
            badge.pack(side="left")
            badge.pack_propagate(False)
            label(badge, str(number), 12, True).pack(expand=True)
            label(row, text, 13).pack(side="left", padx=(10, 0))
        label(steps, "El nivel de fatiga completo aparece tras 1 minuto; los parpadeos y bostezos se cuentan desde el inicio.",
              11, color=MUTED, wraplength=WIDTH - 2 * MARGIN - 36, justify="left").pack(anchor="w", padx=18, pady=(8, 0))
        keys = ctk.CTkFrame(steps, fg_color="transparent")
        keys.pack(anchor="w", padx=18, pady=(6, 14))
        for text, bold in (("Para terminar pulsa ", False), ("Q", True), (". Para recalibrar pulsa ", False),
                           ("C", True), (".", False)):
            label(keys, text, 12, bold, color=TEXT if bold else MUTED).pack(side="left")

        buttons = ctk.CTkFrame(body, fg_color="transparent")
        buttons.pack(fill="x", pady=(22, 0))
        self.start_button = button(buttons, "Empezar", self.start, primary=True)
        self.start_button.pack(side="left", fill="x", expand=True)
        self.exit_button = button(buttons, "Salir", self.close, width=120)
        self.exit_button.pack(side="left", padx=(12, 0))
        label(body, "Herramienta de investigación. No es un dispositivo médico.", 11, color=FAINT).pack(pady=(14, 0))

        self.bind("<Return>", lambda event: self.start())
        self.bind("<Escape>", lambda event: self.close())

    def start(self):
        self.close({"name": self.name.get().strip(), "condition": self.GLASSES[self.glasses.get()],
                    "record": bool(self.record.get())})


# ---------------------------------------------------------------------- resumen

class SummaryWindow(Window):
    """Resumen al terminar (datos de session_view.summary_view). Devuelve "new", "review" o None."""

    def __init__(self, view):
        super().__init__("Resumen de la sesión")
        self.view = view
        ok = view["reliable"] and view["counted"]      # sin datos fiables se atenúa todo
        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=MARGIN, pady=(18, 18))

        buttons = ctk.CTkFrame(body, fg_color="transparent")
        buttons.pack(side="bottom", fill="x", pady=(14, 0))
        self.review_button = button(buttons, "Revisar el video", lambda: self.close("review"), primary=True)
        self.review_button.pack(side="left", fill="x", expand=True)
        self.new_button = button(buttons, "Nueva sesión", lambda: self.close("new"), width=130)
        self.new_button.pack(side="left", padx=(10, 0))
        self.close_button = button(buttons, "Cerrar", self.close, width=100)
        self.close_button.pack(side="left", padx=(10, 0))
        label(body, "Resumen de la sesión", 24, True).pack(anchor="w")
        who = ctk.CTkFrame(body, fg_color="transparent")
        who.pack(anchor="w", pady=(3, 0))
        label(who, view["participant"], 14).pack(side="left")
        label(who, f" · {view['glasses']}", 14, color=MUTED).pack(side="left")
        when = ctk.CTkFrame(body, fg_color="transparent")
        when.pack(anchor="w")
        label(when, f"{view['when']} · Duración ", 13, color=MUTED).pack(side="left")
        label(when, view["duration"], 13, True).pack(side="left")

        if view["warning"]:
            warning = ctk.CTkFrame(body, fg_color=WARN_BG, border_width=1, border_color=WARN, corner_radius=10)
            warning.pack(fill="x", pady=(14, 0))
            label(warning, f"⚠ {view['warning']}", 13, color=WARN, wraplength=WIDTH - 2 * MARGIN - 28,
                  justify="left").pack(anchor="w", padx=14, pady=10)

        stats = ctk.CTkFrame(body, fg_color="transparent")
        stats.pack(fill="x", pady=(14, 0))
        for column, (title, value, subs, dim) in enumerate((
                ("PARPADEOS", view["blinks"], view["blinks_sub"], False),
                ("BOSTEZOS", view["yawns"], view["yawns_sub"], False),
                ("PERCLOS FINAL", view["perclos"], [view["perclos_sub"]], not ok))):
            stats.grid_columnconfigure(column, weight=1, uniform="stat")
            tile = card(stats, corner_radius=12)
            tile.grid(row=0, column=column, sticky="nsew", padx=(0 if column == 0 else 5, 0 if column == 2 else 5))
            label(tile, title, 11, True, color=MUTED).pack(anchor="w", padx=14, pady=(12, 0))
            label(tile, value, 28, True, color=FAINT if dim else TEXT).pack(anchor="w", padx=14)
            for sub in subs:
                label(tile, sub, 11.5, color=FAINT if dim else MUTED).pack(anchor="w", padx=14)
            label(tile, "", 2).pack(pady=(0, 3))

        levels = card(body)
        levels.pack(fill="x", pady=(12, 0))
        top = ctk.CTkFrame(levels, fg_color="transparent")
        top.pack(fill="x", padx=16, pady=(10, 6))
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
        table.pack(fill="x", padx=16, pady=(8, 8))
        table.grid_columnconfigure(1, weight=1)
        for row, level in enumerate(view["levels"]):
            dim = FAINT if not ok else None
            ctk.CTkLabel(table, text="●", font=font(11), text_color=UNRELIABLE if not ok else LEVEL_COLORS[level["key"]],
                         width=18).grid(row=row, column=0, sticky="w", pady=1)
            label(table, level["name"], 14, color=dim or TEXT).grid(row=row, column=1, sticky="w", padx=(4, 0))
            label(table, level["time"], 13, color=dim or TEXT).grid(row=row, column=2, sticky="e", padx=(8, 0))
            label(table, level["percent"], 13, color=dim or MUTED, width=64, anchor="e").grid(row=row, column=3, sticky="e")
            label(table, level["alerts"], 13, True, color=dim or TEXT, width=44, anchor="e").grid(row=row, column=4,
                                                                                                  sticky="e")

        info = card(body)
        info.pack(fill="x", pady=(12, 0))
        facts = ctk.CTkFrame(info, fg_color="transparent")
        facts.pack(fill="x", padx=16, pady=(12, 0))
        for text, value, side in (("Recalibraciones ", view["recalibrations"], "left"), ("FPS medio ", view["fps"], "right")):
            pair = ctk.CTkFrame(facts, fg_color="transparent")
            pair.pack(side=side, padx=(0, 28) if side == "left" else 0)
            label(pair, text, 13, color=MUTED).pack(side="left")
            label(pair, value, 13, True).pack(side="left")
        path = ctk.CTkFrame(info, fg_color="transparent")
        path.pack(fill="x", padx=16, pady=(10, 0))
        label(path, "Guardado en", 12, color=MUTED).pack(side="left")
        label(path, view["build"], 11.5, color=FAINT).pack(side="right")
        where = ctk.CTkFrame(info, fg_color="transparent")
        where.pack(fill="x", padx=16, pady=(2, 12))
        label(where, shorten_path(view["folder"], 50), 11, wraplength=WIDTH - 2 * MARGIN - 160, justify="left").pack(
            side="left")
        self.open_button = ctk.CTkButton(where, text="Abrir carpeta", command=self.open_folder, width=104, height=28,
                                         corner_radius=8, font=font(12, True), fg_color=BUTTON, hover_color=BUTTON_HOVER,
                                         text_color=TEXT, border_width=1, border_color=BUTTON_BORDER)
        self.open_button.pack(side="right")

        self.bind("<Escape>", lambda event: self.close())

    def open_folder(self):
        try:
            os.startfile(self.view["folder"])
        except (AttributeError, OSError):
            pass


# ---------------------------------------------------------------------- revisar el video

class ReviewWindow(Window):
    """Elige cómo revisar el video de la sesión. Devuelve "blind", "review" o None (cancelar).
    view: datos de session_view.summary_view (recorded, annotations)."""

    def __init__(self, view):
        recorded = view["recorded"]
        super().__init__("Revisar el video", 480, 430 if recorded else 250)
        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=26, pady=(22, 18))
        label(body, "Revisar el video", 22, True).pack(anchor="w")
        if not recorded:
            label(body, "Esta sesión no se grabó, así que no hay video que revisar. La próxima vez activa «Grabar el "
                        "video de la sesión» en la ventana de inicio.", 13, color=MUTED, wraplength=428,
                  justify="left").pack(anchor="w", pady=(10, 0))
            self.cancel_button = button(body, "Entendido", self.close, primary=True)
            self.cancel_button.pack(side="bottom", fill="x")
            self.bind("<Return>", lambda event: self.close())
            self.bind("<Escape>", lambda event: self.close())
            return
        label(body, "Marca sobre el video dónde hubo cada evento (parpadeo, bostezo, cierre largo...).", 13,
              color=MUTED, wraplength=428, justify="left").pack(anchor="w", pady=(4, 0))
        self.blind_button = self._option(
            body, "Anotar eventos",
            "No ves lo que detectó el sistema, así tu anotación no se deja influir. Es la que sirve como "
            "referencia para medir su precisión.", "blind", True)
        self.review_button = self._option(
            body, "Revisar detecciones",
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
        self.cancel_button = button(body, "Cancelar", self.close)
        self.cancel_button.pack(side="bottom", fill="x")
        self.bind("<Escape>", lambda event: self.close())

    def _option(self, master, title, description, result, primary):
        frame = card(master)
        frame.pack(fill="x", pady=(12, 0))
        label(frame, title, 14, True).pack(anchor="w", padx=16, pady=(12, 0))
        label(frame, description, 12, color=MUTED, wraplength=400, justify="left").pack(anchor="w", padx=16,
                                                                                       pady=(2, 8))
        chosen = button(frame, title, lambda: self.close(result), primary=primary)
        chosen.configure(height=36)
        chosen.pack(fill="x", padx=16, pady=(0, 14))
        return chosen


# ---------------------------------------------------------------------- cámara

class CameraErrorWindow(Window):
    """Aviso de cámara no disponible. Devuelve "retry" o None (salir)."""

    def __init__(self):
        super().__init__("Fatiga Detector", 440, 222)
        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=26, pady=(24, 20))
        head = ctk.CTkFrame(body, fg_color="transparent")
        head.pack(anchor="w")
        label(head, "●", 14, color=DANGER).pack(side="left")
        label(head, "No encontramos la cámara", 20, True).pack(side="left", padx=(10, 0))
        label(body, "Revisa que esté conectada y que ningún otro programa la esté usando (Zoom, Teams...). "
                    "Luego vuelve a intentarlo.", 13.5, color=MUTED, wraplength=380, justify="left").pack(
            anchor="w", pady=(10, 0))
        buttons = ctk.CTkFrame(body, fg_color="transparent")
        buttons.pack(side="bottom", anchor="e")
        self.retry_button = button(buttons, "Reintentar", lambda: self.close("retry"), primary=True, width=130)
        self.retry_button.pack(side="right")
        self.exit_button = button(buttons, "Salir", self.close, width=100)
        self.exit_button.pack(side="right", padx=(0, 10))
        self.bind("<Return>", lambda event: self.close("retry"))
        self.bind("<Escape>", lambda event: self.close())


def show_error(text):
    """Cuadro de error sencillo (si algo falla sin ventana propia)."""
    from tkinter import Tk, messagebox
    root = Tk()
    root.withdraw()
    messagebox.showerror("Fatiga Detector", text)
    root.destroy()


def ask_start():
    return StartWindow().run()


def show_summary(view):
    return SummaryWindow(view).run()


def ask_review(view):
    return ReviewWindow(view).run()


def camera_error():
    return CameraErrorWindow().run()
