# fatigue_hud.py
"""Dibujo del panel (HUD) y de los avisos sobre el fotograma. Solo pinta: lee el estado del monitor y no lo
modifica, para que la lógica de medición de fatigue_framework.py no dependa de la interfaz."""
import cv2

import calibration_marks
from fatigue_alert import COLORS_BGR, MESSAGES, NORMAL


def draw_hud(img, monitor, perclos_val, has_glasses, is_microsleep, is_yawning):
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
    cv2.putText(img, f"{monitor.eyes.blink_count}", (30, 115), cv2.FONT_HERSHEY_DUPLEX, 0.9, (255, 200, 0), 2)
    cv2.putText(img, f"prolong. {monitor.eyes.long_blink_count}", (70, 115), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (120, 120, 130), 1)
    if monitor.eyes.blink_durations:
        # Duración del último parpadeo: prolongado si dura >= LONG_BLINK_SECONDS con cierre completo
        cv2.putText(img, f"ultimo {monitor.eyes.blink_durations[-1]:.2f} s (prolong. >= {monitor.LONG_BLINK_SECONDS:.1f} s)",
                    (30, 129), cv2.FONT_HERSHEY_SIMPLEX, 0.33, (120, 120, 130), 1)

    cv2.putText(img, "BOSTEZOS", (140, 85), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (160, 160, 170), 1)
    cv2.putText(img, f"{monitor.yawn.count}", (140, 115), cv2.FONT_HERSHEY_DUPLEX, 0.9, (0, 230, 255), 2)
    cv2.putText(img, f"micro {monitor.yawn.micro_count}", (180, 115), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (120, 120, 130), 1)

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
    reliable = monitor.closure_reliable
    if monitor.phase == monitor.FASE_MONITOREO and not reliable:
        cv2.putText(img, "NO FIABLE", (160, 230), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 140, 255), 1)
    elif monitor.perclos.total_time < monitor.perclos_min_seconds:
        cv2.putText(img, "calibrando", (160, 230), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (120, 120, 130), 1)

    color_perclos = ((0, 255, 120) if perclos_val < monitor.PERCLOS_WARN_PCT
                     else ((0, 200, 255) if perclos_val < monitor.PERCLOS_ALERT_PCT else (0, 0, 255)))
    if not reliable:
        color_perclos = (120, 120, 130)
    cv2.putText(img, f"{perclos_val:.1f}%", (30, 260), cv2.FONT_HERSHEY_DUPLEX, 0.8, color_perclos, 2)

    # Barra de 0 a PERCLOS_BAR_MAX % (en una escala de 0-100 % los valores habituales, 0-15 %, casi no se
    # veían), con rayas en los umbrales de precaución y somnolencia
    bar_x, bar_y, bar_w, bar_h = 30, 275, panel_w - 60, 10
    cv2.rectangle(img, (bar_x, bar_y), (bar_x + bar_w, bar_y + bar_h), (50, 50, 60), -1)
    fill_w = int(min(perclos_val / monitor.PERCLOS_BAR_MAX, 1.0) * bar_w)
    cv2.rectangle(img, (bar_x, bar_y), (bar_x + fill_w, bar_y + bar_h), color_perclos, -1)
    for pct in (monitor.PERCLOS_WARN_PCT, monitor.PERCLOS_ALERT_PCT):
        x = bar_x + int(pct / monitor.PERCLOS_BAR_MAX * bar_w)
        cv2.line(img, (x, bar_y - 3), (x, bar_y + bar_h + 3), (230, 230, 235), 1)
        cv2.putText(img, f"{pct:.0f}", (x - 5, bar_y + bar_h + 15), cv2.FONT_HERSHEY_SIMPLEX, 0.32, (150, 150, 160), 1)
    cv2.putText(img, f"{monitor.PERCLOS_BAR_MAX:.0f}%", (bar_x + bar_w - 20, bar_y + bar_h + 15),
                cv2.FONT_HERSHEY_SIMPLEX, 0.32, (110, 110, 120), 1)

    # Alertas de Eventos Críticos
    if is_microsleep:
        cv2.rectangle(img, (30, 310), (panel_w - 15, 350), (0, 0, 200), -1)
        cv2.putText(img, "! MICRO-SUENO !", (40, 335), cv2.FONT_HERSHEY_DUPLEX, 0.55, (255, 255, 255), 1)
    elif is_yawning:
        cv2.rectangle(img, (30, 310), (panel_w - 15, 350), (0, 150, 255), -1)
        cv2.putText(img, "BOSTEZANDO...", (45, 335), cv2.FONT_HERSHEY_DUPLEX, 0.55, (255, 255, 255), 1)

    # Nivel de fatiga (alertas en vivo)
    level = monitor.alert.level
    cv2.putText(img, "NIVEL DE FATIGA", (30, 380), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (160, 160, 170), 1)
    if level == NORMAL and monitor.phase == monitor.FASE_MONITOREO and not reliable:
        # sin cierre fiable el PERCLOS no puede subir: "normal" no significaría nada (el micro-sueño sí se muestra)
        cv2.putText(img, "SIN DATOS FIABLES", (30, 405), cv2.FONT_HERSHEY_DUPLEX, 0.6, (120, 120, 130), 1)
    else:
        cv2.putText(img, level.replace("_", "-"), (30, 405), cv2.FONT_HERSHEY_DUPLEX, 0.6, COLORS_BGR[level], 1)
    if level != NORMAL:
        draw_fatigue_banner(img, level)
    if monitor.phase == monitor.FASE_MONITOREO and not reliable:
        # Sin el nivel de ojo cerrado medido, el % de cierre no llega al 80 %: PERCLOS, micro-sueño, parpadeos
        # prolongados y alertas quedan en 0 aunque la persona cierre los ojos
        for i, text in enumerate(["OJO CERRADO NO MEDIDO:", "PERCLOS y alertas no fiables.",
                                  "Pulsa C y cierra los ojos", "hasta oir el pitido."]):
            cv2.putText(img, text, (30, 440 + 18 * i), cv2.FONT_HERSHEY_SIMPLEX, 0.42,
                        (0, 140, 255) if i == 0 else (200, 200, 210), 1)

    cv2.putText(img, "[C] recalibrar  [Q] salir", (30, h - 30), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (120, 120, 130), 1)
    if monitor.phase == monitor.FASE_MONITOREO and not monitor.head.eye_valid:
        cv2.putText(img, "POSTURA FUERA DE RANGO", (30, h - 50), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 140, 255), 1)
    fps = monitor.session.current_fps if monitor.session else None
    if fps:
        cv2.putText(img, f"{fps:.0f} FPS", (panel_w - 60, h - 30), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (120, 120, 130), 1)
    draw_clock(img, monitor._now, monitor.frames_total - 1, monitor._is_video_file())


def draw_fatigue_banner(img, level):
    """Aviso grande arriba al centro, a la derecha del panel."""
    h, w, _ = img.shape
    x0, x1, y0, y1 = 280, w - 290, 15, 70
    if x1 - x0 < 300:
        x0, x1 = 280, w - 15
    overlay = img.copy()
    cv2.rectangle(overlay, (x0, y0), (x1, y1), COLORS_BGR[level], -1)
    cv2.addWeighted(overlay, 0.85, img, 0.15, 0, img)
    text = MESSAGES[level]
    (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_DUPLEX, 0.7, 2)
    cv2.putText(img, text, (x0 + max(10, (x1 - x0 - tw) // 2), y0 + (y1 - y0 + th) // 2),
                cv2.FONT_HERSHEY_DUPLEX, 0.7, (255, 255, 255), 2)


def draw_clock(img, now, frame_index, is_video):
    """Tiempo de la sesión (= columna t de traza.csv y t_s de eventos.csv; en un vídeo, el segundo de
    la grabación) y número de frame, para anotar a mano el momento de un evento y buscarlo en la traza."""
    h, w, _ = img.shape
    minutes, seconds = divmod(now, 60)
    lines = [f"t = {now:.2f} s  ({int(minutes):02d}:{seconds:05.2f})", f"frame {frame_index}"]
    if is_video:
        lines.append("[ESPACIO] pausa")
    x0, y0 = w - 265, 15
    cv2.rectangle(img, (x0, y0), (w - 15, y0 + 22 * len(lines) + 12), (20, 20, 25), -1)
    for i, text in enumerate(lines):
        cv2.putText(img, text, (x0 + 12, y0 + 27 + 22 * i), cv2.FONT_HERSHEY_SIMPLEX, 0.5 if i == 0 else 0.42,
                    (255, 255, 255) if i == 0 else (160, 160, 170), 1)


def draw_calibration_overlay(img, title, progress, subtitle="MIRA AL FRENTE"):
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


def draw_phase_overlay(img, monitor):
    """Banner de la fase de calibración en curso (nada durante el monitoreo)."""
    phase = monitor.phase
    if phase == monitor.FASE_ROSTRO:
        draw_calibration_overlay(img, "PASO 1/2: ANALIZANDO ROSTRO...", monitor.profile.progress)
    elif phase == monitor.FASE_CIERRE and monitor._closed_retry_until is not None:
        remaining = max(0.0, monitor._closed_retry_until - monitor._now)
        draw_calibration_overlay(
            img, "NO SE DETECTARON LOS OJOS CERRADOS", 1.0 - remaining / monitor.CLOSED_RETRY_PAUSE,
            subtitle=f"CIERRALOS DEL TODO EN {remaining:.0f} s  (INTENTO {monitor._closed_attempt}/{monitor.CLOSED_MAX_ATTEMPTS})")
    elif phase == monitor.FASE_CIERRE:
        attempt = f" (INTENTO {monitor._closed_attempt}/{monitor.CLOSED_MAX_ATTEMPTS})" if monitor._closed_attempt > 1 else ""
        draw_calibration_overlay(img, "PASO 2/2: CIERRA LOS OJOS..." + attempt, monitor.profile.closed_progress,
                                 subtitle="ABRELOS AL OIR EL PITIDO")
    elif phase == monitor.FASE_REAPERTURA:
        draw_calibration_overlay(img, "ABRE LOS OJOS", 1.0, subtitle="EL CONTEO EMPIEZA AL ABRIRLOS")
    elif phase == monitor.FASE_MARCAS:
        start_frame = calibration_marks.frame_ranges(monitor.manual_marks)[4]
        draw_calibration_overlay(img, "CALIBRACION MANUAL (MARCAS DEL VIDEO)",
                                 (monitor.frames_total - 1) / max(start_frame, 1),
                                 subtitle=f"LA PRUEBA EMPIEZA EN t = {monitor.manual_marks['inicio_prueba']['s']:.2f} s")
