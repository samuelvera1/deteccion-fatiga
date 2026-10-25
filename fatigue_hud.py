# fatigue_hud.py
"""Pantalla del monitor en vivo, dibujada con Pillow (Segoe UI, con tildes y eñes): imagen de la cámara a la
izquierda y panel a la derecha con el nivel de fatiga, el PERCLOS y los contadores. Solo pinta: lee el estado
del monitor y no lo modifica, para que la lógica de medición no dependa de la interfaz.

El panel se redibuja solo cuando cambia algún valor mostrado (el PERCLOS se muestra con un decimal), y la
franja del reloj cada frame; así dibujar la interfaz no baja los fps de procesamiento."""
import cv2
import numpy as np
from PIL import Image, ImageDraw

import calibration_marks
import revisar_ui as ui
from fatigue_alert import MICRO_SUENO, NORMAL, PRECAUCION, SOMNOLENCIA

WINDOW_NAME = "Fatigue Framework Monitor"
WIDTH, HEIGHT = 1280, 720
CAMERA_BOX = (16, 16, 864, 652)             # x0, y0, x1, y1 (relación 4:3; una cámara 16:9 queda con franjas)
PANEL_X0, PANEL_X1 = 880, 1264
PANEL_HEIGHT = 678                         # alto del panel (desde y = 16)
RADIUS = 10

LEVEL_COLORS = {NORMAL: (60, 201, 112), PRECAUCION: (243, 196, 48), SOMNOLENCIA: (255, 140, 60),
                MICRO_SUENO: (255, 75, 75)}
LEVEL_NAMES = {NORMAL: "NORMAL", PRECAUCION: "PRECAUCIÓN", SOMNOLENCIA: "SOMNOLENCIA", MICRO_SUENO: "MICRO-SUEÑO"}
LEVEL_ORDER = [NORMAL, PRECAUCION, SOMNOLENCIA, MICRO_SUENO]
CALIBRATING_COLOR = (98, 166, 255)
DIM = (92, 96, 108)
PHASES_CALIBRATING = ("rostro", "cierre", "reapertura", "calibracion_manual")


def window_size():
    """Tamaño inicial de la ventana: el del lienzo, reducido si la pantalla no lo admite (se deja sitio a la barra
    de título y a la de tareas). La ventana se puede redimensionar: la imagen se escala."""
    try:
        import ctypes
        screen_w, screen_h = (ctypes.windll.user32.GetSystemMetrics(i) for i in (0, 1))
    except (AttributeError, OSError):
        return WIDTH, HEIGHT
    scale = min(1.0, (screen_w - 20) / WIDTH, (screen_h - 120) / HEIGHT)
    return int(WIDTH * scale), int(HEIGHT * scale)


def _tint(color, amount=0.14):
    """Fondo oscuro con un matiz del color (tarjeta del nivel)."""
    return tuple(int(ui.BG[i] * (1 - amount) + color[i] * amount) for i in range(3))


def _fit_font(draw, text, bold, size, max_width):
    """Mayor tamaño (hasta `size`) con el que el texto cabe en max_width: el nivel nunca se desborda."""
    while size > 10 and draw.textlength(text, font=ui.load_font(size, bold)) > max_width:
        size -= 1
    return ui.load_font(size, bold)


def phase_info(monitor):
    """(título, subtítulo, progreso 0-1) de la fase de calibración en curso; None durante el monitoreo."""
    phase = monitor.phase
    if phase == monitor.FASE_ROSTRO:
        return "Paso 1/2 · Analizando rostro", "Mira al frente", monitor.profile.progress
    if phase == monitor.FASE_CIERRE and monitor._closed_retry_until is not None:
        remaining = max(0.0, monitor._closed_retry_until - monitor._now)
        return ("No se detectaron los ojos cerrados",
                f"Ciérralos del todo en {remaining:.0f} s  (intento {monitor._closed_attempt}/{monitor.CLOSED_MAX_ATTEMPTS})",
                1.0 - remaining / monitor.CLOSED_RETRY_PAUSE)
    if phase == monitor.FASE_CIERRE:
        attempt = f" (intento {monitor._closed_attempt}/{monitor.CLOSED_MAX_ATTEMPTS})" if monitor._closed_attempt > 1 else ""
        return "Paso 2/2 · Cierra los ojos" + attempt, "Ábrelos al oír el pitido", monitor.profile.closed_progress
    if phase == monitor.FASE_REAPERTURA:
        return "Abre los ojos", "El conteo empieza al abrirlos", 1.0
    if phase == monitor.FASE_MARCAS:
        start_frame = calibration_marks.frame_ranges(monitor.manual_marks)[4]
        return ("Calibración manual (marcas del vídeo)",
                f"La prueba empieza en t = {monitor.manual_marks['inicio_prueba']['s']:.2f} s",
                (monitor.frames_total - 1) / max(start_frame, 1))
    return None


class HudRenderer:
    """Compone el fotograma que se muestra. Una instancia por sesión (guarda las cachés)."""

    def __init__(self):
        self._base = self._build_base()
        self._panel_key, self._panel, self._panel_img = {}, None, None
        self._overlay_cache = {}
        self._corners = self._corner_patches()
        self._right_strip_key, self._right_strip = None, None

    # ------------------------------------------------------------------ piezas fijas

    @staticmethod
    def _build_base():
        img = Image.new("RGB", (WIDTH, HEIGHT), ui.BG)
        draw = ImageDraw.Draw(img)
        draw.rounded_rectangle(CAMERA_BOX, radius=RADIUS, fill=(4, 5, 7), outline=ui.CARD_BORDER)
        return np.asarray(img)[:, :, ::-1].copy()          # BGR

    def _corner_patches(self):
        """Esquinas redondeadas de la caja de la cámara: se restauran tras pegar la imagen."""
        x0, y0, x1, y1 = CAMERA_BOX
        r = RADIUS + 1
        return [((y, x), self._base[y:y + r, x:x + r].copy())
                for y, x in ((y0, x0), (y0, x1 - r + 1), (y1 - r + 1, x0), (y1 - r + 1, x1 - r + 1))]

    # ------------------------------------------------------------------ composición

    def render(self, camera, monitor, is_microsleep, is_yawning):
        """Devuelve el fotograma completo (BGR) con la cámara y el panel."""
        canvas = self._base.copy()
        self._paste_camera(canvas, camera, monitor, is_microsleep, is_yawning)
        panel = self._panel_image(monitor)
        canvas[16:16 + panel.shape[0], PANEL_X0:PANEL_X0 + panel.shape[1]] = panel
        self._draw_bottom_bar(canvas, monitor)
        return canvas

    def _paste_camera(self, canvas, camera, monitor, is_microsleep, is_yawning):
        """Escala la cámara dentro de la caja (sin deformarla) directamente sobre el lienzo y dibuja encima los
        avisos. Es solo para mostrar: el análisis usa el frame original."""
        x0, y0, x1, y1 = CAMERA_BOX
        box = canvas[y0 + 1:y1 - 1, x0 + 1:x1 - 1]
        bh, bw = box.shape[:2]
        h, w = camera.shape[:2]
        scale = min(bw / w, bh / h)
        nw, nh = max(1, int(w * scale)), max(1, int(h * scale))
        ox, oy = (bw - nw) // 2, (bh - nh) // 2
        cv2.resize(camera, (nw, nh), dst=box[oy:oy + nh, ox:ox + nw], interpolation=cv2.INTER_LINEAR)
        if monitor.kss and monitor.kss.prompt:
            monitor.kss.draw(box)
        self._draw_banners(box, monitor, is_microsleep, is_yawning)
        for (y, x), patch in self._corners:
            canvas[y:y + patch.shape[0], x:x + patch.shape[1]] = patch

    def _draw_banners(self, box, monitor, is_microsleep, is_yawning):
        """Avisos sobre la imagen: evento en curso arriba al centro, calibración abajo."""
        banners = []
        if is_microsleep:
            banners.append(("MICRO-SUEÑO", LEVEL_COLORS[MICRO_SUENO], (255, 255, 255)))
        elif is_yawning:
            banners.append(("BOSTEZANDO...", LEVEL_COLORS[PRECAUCION], (30, 26, 8)))
        if monitor.phase == monitor.FASE_MONITOREO and not monitor.head.eye_valid:
            banners.append(("POSTURA FUERA DE RANGO", (232, 236, 244), (24, 26, 32)))
        y = 30
        for text, fill, ink in banners:
            y += self._blend(box, self._banner(text, fill, ink), y) + 10
        info = phase_info(monitor)
        if info:
            title, subtitle, progress = info
            overlay = self._calibration_banner(title, subtitle, progress, box.shape[1] - 48)
            self._blend(box, overlay, box.shape[0] - overlay.shape[0] - 24)

    def _cached(self, key, build):
        if key not in self._overlay_cache:
            if len(self._overlay_cache) > 300:
                self._overlay_cache.clear()
            self._overlay_cache[key] = build()
        return self._overlay_cache[key]

    def _banner(self, text, fill, ink):
        def build():
            font = ui.load_font(24, True)
            probe = ImageDraw.Draw(Image.new("RGB", (1, 1)))
            w, h = int(probe.textlength(text, font=font)) + 56, 52
            img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
            d = ImageDraw.Draw(img)
            d.rounded_rectangle((0, 0, w - 1, h - 1), radius=12, fill=fill + (242,))
            d.text((w / 2, h / 2), text, font=font, fill=ink, anchor="mm")
            return np.asarray(img)
        return self._cached(("banner", text, fill, ink), build)

    def _calibration_banner(self, title, subtitle, progress, width):
        step = int(min(max(progress, 0.0), 1.0) * 100)

        def build():
            img = Image.new("RGBA", (width, 92), (0, 0, 0, 0))
            d = ImageDraw.Draw(img)
            d.rounded_rectangle((0, 0, width - 1, 91), radius=12, fill=ui.BG + (236,), outline=CALIBRATING_COLOR + (255,))
            d.text((width / 2, 24), title, font=ui.load_font(20, True), fill=ui.TEXT, anchor="mm")
            d.text((width / 2, 50), subtitle, font=ui.load_font(15), fill=ui.MUTED, anchor="mm")
            d.rounded_rectangle((20, 70, width - 20, 78), radius=4, fill=ui.TRACK + (255,))
            filled = int((width - 40) * step / 100)
            if filled > 0:
                d.rounded_rectangle((20, 70, 20 + max(filled, 8), 78), radius=4, fill=CALIBRATING_COLOR + (255,))
            return np.asarray(img)
        return self._cached(("calibration", title, subtitle, step, width), build)

    @staticmethod
    def _blend(box, rgba, top):
        """Pega una imagen RGBA sobre box (BGR), centrada en x y con su borde superior en `top`. Devuelve su alto."""
        h, w = rgba.shape[:2]
        x = (box.shape[1] - w) // 2
        region = box[top:top + h, x:x + w]
        alpha = rgba[:, :, 3:4].astype(np.float32) / 255.0
        region[:] = (region * (1 - alpha) + rgba[:, :, 2::-1] * alpha).astype(np.uint8)
        return h

    # ------------------------------------------------------------------ panel

    def _panel_image(self, monitor):
        """Panel completo en BGR. Cada tarjeta se redibuja solo si cambió algo de lo que muestra."""
        state = self._panel_state(monitor)
        if self._panel is None:
            self._panel = np.empty((PANEL_HEIGHT, PANEL_X1 - PANEL_X0, 3), np.uint8)
            self._panel[:] = ui.BG[::-1]
            self._panel_img = Image.new("RGB", (PANEL_X1 - PANEL_X0, PANEL_HEIGHT), ui.BG)
        keys = {"level": state[1:4] + state[12:14], "perclos": (state[0], state[3]) + state[4:6] + state[12:15],
                "counters": state[6:8] + state[9:11], "info": (state[8], state[11])}
        changed = [part for part, key in keys.items() if self._panel_key.get(part) != key]
        if changed:
            self._panel_key.update({part: keys[part] for part in changed})
            self._draw_panel(state, changed)
        return self._panel

    @staticmethod
    def _panel_state(monitor):
        """Todo lo que muestra el panel (si no cambia, no se redibuja)."""
        phase = monitor.phase
        calibrating = phase in PHASES_CALIBRATING
        info = phase_info(monitor) if calibrating else None
        reliable = monitor.closure_reliable
        durations = monitor.eyes.blink_durations
        glasses = monitor.has_glasses
        return (calibrating, None if info is None else (info[0], int(info[2] * 100)),
                monitor.alert.level, bool(phase == monitor.FASE_MONITOREO and not reliable),
                round(monitor.perclos_val, 1), monitor.perclos.total_time < monitor.perclos_min_seconds,
                monitor.eyes.blink_count, monitor.eyes.long_blink_count,
                round(durations[-1], 2) if durations else None,
                monitor.yawn.count, monitor.yawn.micro_count,
                None if glasses is None else bool(glasses),
                monitor.PERCLOS_WARN_PCT, monitor.PERCLOS_ALERT_PCT, monitor.PERCLOS_BAR_MAX,
                monitor.LONG_BLINK_SECONDS)

    def _draw_panel(self, state, parts):
        (calibrating, calib, level, unreliable, perclos, gathering, blinks, long_blinks, last_blink,
         yawns, micro_yawns, glasses, warn, alert, bar_max, long_seconds) = state
        width = PANEL_X1 - PANEL_X0
        img = self._panel_img
        d = ImageDraw.Draw(img)
        section, body, bold = ui.load_font(12, True), ui.load_font(15), ui.load_font(15, True)

        def card(y0, y1, fill=ui.CARD, outline=ui.CARD_BORDER, x0=0, x1=width, line=1):
            d.rounded_rectangle((x0, y0, x1 - 1, y1), radius=RADIUS, fill=fill, outline=outline, width=line)

        if "level" in parts:
            d.rectangle((0, 0, width, 217), fill=ui.BG)
            # ---- nivel de fatiga
            if calibrating:
                color, name = CALIBRATING_COLOR, "CALIBRANDO"
                subtitle = calib[0] if calib else ""
            elif unreliable and level == NORMAL:
                color, name = LEVEL_COLORS[PRECAUCION], "OJO CERRADO NO MEDIDO"
                subtitle = "PERCLOS y alertas no fiables."
            else:
                color, name = LEVEL_COLORS[level], LEVEL_NAMES[level]
                subtitle = {NORMAL: f"PERCLOS por debajo de {warn:.0f} %", PRECAUCION: f"PERCLOS ≥ {warn:.0f} %",
                            SOMNOLENCIA: f"PERCLOS ≥ {alert:.0f} %", MICRO_SUENO: "Ojos cerrados ≥ 1 s"}[level]
                if unreliable:
                    subtitle = "PERCLOS no fiable (ojo cerrado no medido)"
            card(0, 216, fill=_tint(color), outline=color, line=2)
            d.text((20, 18), "NIVEL DE FATIGA", font=section, fill=ui.MUTED)
            d.text((20, 40), name, font=_fit_font(d, name, True, 46, width - 40), fill=color)
            d.text((20, 108), subtitle, font=_fit_font(d, subtitle, False, 15, width - 40), fill=ui.TEXT)
            if unreliable and not calibrating and level == NORMAL:
                d.text((20, 140), "Pulsa", font=body, fill=ui.TEXT)
                kx = 20 + d.textlength("Pulsa ", font=body)
                kw = self._keycap(d, kx, 137, "C")
                d.text((kx + kw + 8, 140), "y cierra los ojos hasta oír el pitido", font=body, fill=ui.TEXT)
            elif not calibrating:
                seg_w = (width - 40 - 3 * 6) / 4
                for i, lv in enumerate(LEVEL_ORDER):
                    x = 20 + i * (seg_w + 6)
                    active = lv == level
                    d.rounded_rectangle((x, 156, x + seg_w, 162), radius=3, fill=LEVEL_COLORS[lv] if active else ui.TRACK)
                    label = LEVEL_NAMES[lv]
                    font = _fit_font(d, label, active, 11, seg_w + 4)
                    d.text((x, 172), label, font=font, fill=LEVEL_COLORS[lv] if active else ui.FAINT)
            else:
                progress = (calib[1] if calib else 0) / 100
                d.rounded_rectangle((20, 160, width - 20, 168), radius=4, fill=ui.TRACK)
                if progress > 0:
                    d.rounded_rectangle((20, 160, 20 + max(8, int((width - 40) * progress)), 168), radius=4, fill=color)
            self._panel[0:217] = np.asarray(img)[0:217, :, ::-1]
        if "perclos" in parts:
            d.rectangle((0, 228, width, 385), fill=ui.BG)
            # ---- PERCLOS
            dimmed = calibrating or unreliable
            p_color = DIM if dimmed else (LEVEL_COLORS[NORMAL] if perclos < warn
                                          else LEVEL_COLORS[PRECAUCION] if perclos < alert else LEVEL_COLORS[SOMNOLENCIA])
            card(228, 384)
            d.text((20, 252), "PERCLOS · 60 s", font=section, fill=ui.MUTED if not dimmed else DIM)
            if gathering and not calibrating:
                d.text((20 + d.textlength("PERCLOS · 60 s   ", font=section), 252), "reuniendo datos", font=ui.load_font(12),
                       fill=ui.FAINT)
            big = ui.load_font(36, True)
            value = f"{perclos:.1f}"
            pct_w = d.textlength(" %", font=ui.load_font(18))
            d.text((width - 20, 274), " %", font=ui.load_font(18), fill=ui.MUTED if not dimmed else DIM, anchor="rs")
            d.text((width - 20 - pct_w, 274), value, font=big, fill=p_color, anchor="rs")
            bx, bw = 20, width - 40
            d.rounded_rectangle((bx, 296, bx + bw, 308), radius=6, fill=ui.TRACK)
            filled = int(bw * min(max(perclos / bar_max, 0.0), 1.0))
            if filled > 0 and not calibrating:
                d.rounded_rectangle((bx, 296, bx + max(filled, 12), 308), radius=6, fill=p_color)
            for pct in (warn, alert):
                mx = bx + int(bw * pct / bar_max)
                d.line((mx, 291, mx, 313), fill=ui.TEXT if not dimmed else DIM, width=2)
            small = ui.load_font(12)
            d.text((bx, 324), "0", font=small, fill=ui.FAINT)
            for pct in (warn, alert):
                d.text((bx + int(bw * pct / bar_max), 324), f"{pct:.0f}", font=small, fill=ui.MUTED, anchor="ma")
            d.text((bx + bw, 324), f"{bar_max:.0f} %", font=small, fill=ui.FAINT, anchor="ra")
            self._panel[228:385] = np.asarray(img)[228:385, :, ::-1]
        if "counters" in parts:
            d.rectangle((0, 396, width, 547), fill=ui.BG)
            # ---- contadores
            half = (width - 12) / 2
            for i, (title, number, sub_label, sub_value, number_color) in enumerate((
                    ("PARPADEOS", blinks, "prolongados", long_blinks, ui.TEXT),
                    ("BOSTEZOS", yawns, "micro-bostezos", micro_yawns, ui.TEXT))):
                x0 = i * (half + 12)
                card(396, 546, x0=x0, x1=x0 + half)
                d.text((x0 + 16, 416), title, font=section, fill=ui.MUTED)
                d.text((x0 + 16, 438), str(number), font=ui.load_font(52, True), fill=number_color)
                d.text((x0 + 16, 506), f"{sub_label}: ", font=ui.load_font(14), fill=ui.MUTED)
                d.text((x0 + 16 + d.textlength(f"{sub_label}: ", font=ui.load_font(14)), 506), str(sub_value),
                       font=ui.load_font(14, True), fill=ui.TEXT)
            self._panel[396:547] = np.asarray(img)[396:547, :, ::-1]
        if "info" in parts:
            d.rectangle((0, 558, width, 679), fill=ui.BG)
            # ---- último parpadeo y gafas
            card(558, 678)
            glasses_text = {None: "No declaradas", True: "Con gafas", False: "Sin gafas"}[glasses]
            last_text = "—" if last_blink is None else f"{last_blink:.2f} s"
            for y, label, text in ((582, "Último parpadeo", last_text), (632, "Gafas (declaradas)", glasses_text)):
                d.text((20, y), label, font=body, fill=ui.MUTED)
                d.text((width - 20, y), text, font=bold, fill=ui.TEXT, anchor="ra")
            d.line((20, 618, width - 20, 618), fill=ui.CARD_BORDER)
            self._panel[558:679] = np.asarray(img)[558:679, :, ::-1]

    @staticmethod
    def _keycap(d, x, y, label):
        font = ui.load_font(12, True)
        w = max(24, d.textlength(label, font=font) + 14)
        d.rounded_rectangle((x, y, x + w, y + 22), radius=5, fill=ui.KEY_BG, outline=ui.KEY_BORDER)
        d.text((x + w / 2, y + 11), label, font=font, fill=ui.TEXT, anchor="mm")
        return w

    # ------------------------------------------------------------------ franja inferior

    def _draw_bottom_bar(self, canvas, monitor):
        """Reloj de la sesión (= columna t de traza.csv y t_s de eventos.csv; en un vídeo, el segundo de la
        grabación) y número de frame, que cambian cada frame; las teclas y los fps van en una franja en caché."""
        x0, y0, x1 = CAMERA_BOX[0], CAMERA_BOX[3] + 12, CAMERA_BOX[2]
        y1 = HEIGHT - 8
        height, width = y1 - y0, x1 - x0
        left = Image.new("RGB", (380, height), ui.BG)
        d = ImageDraw.Draw(left)
        minutes, seconds = divmod(monitor._now, 60)
        cy = height // 2
        clock, small = ui.load_font(22, True), ui.load_font(16)
        text = f"t = {monitor._now:.2f} s"
        d.text((2, cy), text, font=clock, fill=ui.TEXT, anchor="lm")
        pos = 2 + d.textlength(text, font=clock) + 12
        d.text((pos, cy), f"({int(minutes):02d}:{int(seconds):02d})", font=small, fill=ui.MUTED, anchor="lm")
        pos += d.textlength("(00:00)", font=small) + 16
        d.text((pos, cy), f"frame {monitor.frames_total - 1}", font=ui.load_font(14), fill=ui.FAINT, anchor="lm")
        canvas[y0:y1, x0:x0 + 380] = np.asarray(left)[:, :, ::-1]

        fps = monitor.session.current_fps if monitor.session else None
        keys = [("C", "Recalibrar"), ("Q", "Salir")]
        if monitor.kss:
            keys.append(("1–9", "KSS"))
        if monitor._is_video_file():
            keys.insert(0, ("Espacio", "Pausa"))
        key = (None if not fps else int(round(fps)), tuple(keys))
        if key != self._right_strip_key:
            self._right_strip_key = key
            self._right_strip = self._build_right_strip(key[0], keys, width - 380, height)
        canvas[y0:y1, x0 + 380:x1] = self._right_strip

    def _build_right_strip(self, fps, keys, width, height):
        img = Image.new("RGB", (width, height), ui.BG)
        d = ImageDraw.Draw(img)
        cy = height // 2
        right = width - 2
        if fps:
            text = f"{fps} FPS"
            right -= d.textlength(text, font=ui.load_font(14))
            d.text((right, cy), text, font=ui.load_font(14), fill=ui.FAINT, anchor="lm")
            right -= 24
        label_font = ui.load_font(15)
        for key, label in reversed(keys):
            right -= d.textlength(label, font=label_font)
            d.text((right, cy), label, font=label_font, fill=ui.MUTED, anchor="lm")
            right -= 8 + max(24, d.textlength(key, font=ui.load_font(12, True)) + 14)
            self._keycap(d, right, cy - 11, key)
            right -= 22
        return np.asarray(img)[:, :, ::-1].copy()
