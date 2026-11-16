# fatigue_report.py
"""Lo que el monitor escribe en disco: columnas y filas de traza.csv, parámetros del método y resumen de
la sesión (metadata.json). Solo lee el estado del monitor."""
import numpy as np

TRACE_HEADER = ["t", "ipd", "ear_left", "ear_right", "ear", "ear_baseline", "ear_cerrado", "cierre",
                "p80", "eyes_closed", "mouth", "mouth_neutral", "yawn_thr", "micro_yawn_thr",
                "gafas_declaradas", "fase", "estable", "movimiento",
                "parpadeos", "bostezos", "micro_bostezos", "blink_ref", "blink_closed",
                "boca_ancho_rel", "comisuras_elev", "mandibula_caida", "sonrisa",
                "cabeza_yaw", "cabeza_pitch", "cabeza_roll", "postura_valida",
                "frame",   # índice del frame en la fuente (0 = primero); los frames sin rostro no tienen fila
                "cabeza_vel"]   # velocidad de giro de la cabeza (°/s)


def session_parameters(monitor):
    """Todos los parámetros del método, para los metadatos de la sesión (sección de métodos)."""
    return {
        "camara": {"resolucion_pedida": list(monitor.capture_size) if monitor.capture_size else "nativa"},
        "facemesh": {"min_detection_confidence": monitor.detector.minDetectionCon,
                     "min_tracking_confidence": monitor.detector.minTrackCon,
                     "refine_landmarks": monitor.detector.refineLandmarks},
        "calibracion": {"frames_perfil": monitor.profile.calibration_frames,
                        "frames_ojo_cerrado": monitor.profile.closed_frames,
                        "captura_ojo_cerrado_factor": monitor.CLOSED_CAPTURE_FACTOR,
                        "timeout_ojo_cerrado_s": monitor.CLOSED_CALIBRATION_TIMEOUT,
                        "intentos_ojo_cerrado_en_vivo": monitor.CLOSED_MAX_ATTEMPTS,
                        "pausa_entre_intentos_s": monitor.CLOSED_RETRY_PAUSE,
                        "reserva_ojo_cerrado_ratio": monitor.CLOSED_FALLBACK_RATIO,
                        "cierre_visible_max_ratio": monitor.CLOSURE_VISIBLE_MAX_RATIO,
                        "reapertura_cierre_max": monitor.REOPEN_MAX_CLOSURE,
                        "reapertura_frames": monitor.REOPEN_FRAMES,
                        "modo": "manual (marcas del vídeo)" if monitor.manual_marks else "automatica",
                        "marcas_manuales": monitor.manual_marks,
                        "frames_estables_requeridos": monitor.stability.required_frames,
                        "max_movimiento_ipd": monitor.stability.max_motion,
                        "suavizado_ipd": monitor.IPD_SMOOTHING},
        "ojos": {"parpadeo_factor_ref_local": monitor.BLINK_LOCAL_FACTOR,
                 "parpadeo_margen_reapertura": monitor.BLINK_REOPEN_MARGIN,
                 "parpadeo_margen_1_frame": monitor.BLINK_DEEP_MARGIN,
                 "parpadeo_ventana_ref_s": monitor.BLINK_REF_WINDOW,
                 "parpadeo_percentil_ref": monitor.BLINK_REF_PERCENTILE,
                 "parpadeo_profundidad_min": monitor.BLINK_MIN_DEPTH,
                 "parpadeo_min_frames": monitor.MIN_BLINK_FRAMES,
                 "parpadeo_prolongado_min_s": monitor.LONG_BLINK_SECONDS,
                 "parpadeo_prolongado_cierre_min": monitor.LONG_BLINK_MIN_CLOSURE,
                 "rafaga_cierre_pico": monitor.BURST_PEAK_CLOSURE,
                 "rafaga_reapertura_parcial": monitor.BURST_REOPEN_CLOSURE,
                 "refractario_parpadeo_frames": monitor.BLINK_REFRACTORY_FRAMES,
                 "giro_rapido_cabeza_gs": monitor.FAST_HEAD_SPEED,
                 "giro_rapido_cierre_min": monitor.P80_CLOSURE,
                 "microsueno_cierre_min": monitor.P80_CLOSURE, "microsueno_min_s": monitor.MICROSLEEP_SECONDS,
                 "microsueno_cierre_salida": monitor.MICROSLEEP_EXIT_CLOSURE},
        "bostezo": {"exagerado_factor_delta_seg": monitor.yawn.tiers[monitor.yawn.TIER_EXAGGERATED],
                    "micro_factor_delta_seg": monitor.yawn.tiers[monitor.yawn.TIER_MICRO],
                    "hueco_tolerado_frames": monitor.YAWN_GAP_FRAMES,
                    "sonrisa_ancho_min_ratio": monitor.SMILE_MIN_WIDTH_RATIO,
                    "sonrisa_mandibula_max_ipd": monitor.SMILE_MAX_JAW_DROP,
                    "enfriamiento_s": monitor.YAWN_COOLDOWN_SECONDS},
        "perclos": {"definicion": "P80", "cierre_min": monitor.P80_CLOSURE, "incluye_parpadeos": True,
                    "ventana_s": monitor.window_seconds, "denominador_minimo_s": monitor.perclos_min_seconds,
                    "ponderado_por_tiempo": True,
                    "hud_precaucion_pct": monitor.PERCLOS_WARN_PCT, "hud_alerta_pct": monitor.PERCLOS_ALERT_PCT},
        "kss": monitor.kss.parameters() if monitor.kss else {"activa": False},
        "alertas_fatiga": monitor.alert.parameters(),
        "gafas": {"origen": "condición declarada por el investigador (--condicion)",
                  "declaradas": monitor.has_glasses,
                  "cambio_a_mitad_de_sesion": "recalibrar con la tecla C"},
        "postura": {"referencia": "postura media de la calibración (mirando al frente)",
                    "max_pitch_metricas_ojo": monitor.POSE_MAX_PITCH, "max_yaw_metricas_ojo": monitor.POSE_MAX_YAW,
                    "max_giro_estabilidad": monitor.POSE_STABLE_MAX,
                    "fuera_de_rango": "no se cuentan parpadeos ni PERCLOS; micro-sueño sí (marcado)"},
    }


def trace_row(monitor, now, left_ear, right_ear, ear, mouth):
    """Una fila de traza.csv (columnas de TRACE_HEADER)."""
    def fmt(v):
        return "" if v is None else f"{v:.4f}"

    calibrated = monitor.profile.is_calibrated
    closure = monitor.profile.closure(ear) if monitor.profile.is_closed_calibrated else None
    yawn_thr, micro_thr = monitor.yawn.thresholds() if calibrated else (None, None)
    p, shape = monitor.profile, monitor._last_shape
    if shape is not None and p.neutral_mouth_width:
        width_rel = shape[0] / p.neutral_mouth_width
        lift_delta, jaw_delta = shape[2] - p.neutral_corner_lift, shape[1] - p.neutral_jaw
    else:
        width_rel = lift_delta = jaw_delta = None
    return [f"{now:.3f}", fmt(monitor.ipd), fmt(left_ear), fmt(right_ear), fmt(ear),
            fmt(p.open_ear_baseline), fmt(p.closed_ear_level),
            fmt(closure), int(closure is not None and closure >= monitor.P80_CLOSURE),
            int(monitor.eyes.eyes_closed),
            fmt(mouth), fmt(p.neutral_mouth_ratio), fmt(yawn_thr), fmt(micro_thr),
            "" if monitor.has_glasses is None else int(monitor.has_glasses), monitor.phase,
            monitor.stability.stable_frames, fmt(monitor.stability.motion),
            monitor.eyes.blink_count, monitor.yawn.count,
            monitor.yawn.micro_count, fmt(monitor.eyes.blink_ref), int(monitor.eyes.blink_closed),
            fmt(width_rel), fmt(lift_delta), fmt(jaw_delta), int(monitor.yawn.is_smile(shape)),
            *(fmt(a) for a in (monitor.head.pose or (None, None, None))),
            int(monitor.head.eye_valid), monitor.frames_total - 1, fmt(monitor.head.speed)]


def session_summary(monitor):
    """Resumen de la sesión para metadata.json."""
    return {
        "duracion_s": round(monitor._now, 2),
        "calibracion_modo": "manual" if monitor.manual_marks else "automatica",
        "kss": monitor.kss.responses if monitor.kss else None,
        "fatiga": monitor.alert.summary(),
        "inicio_monitoreo_s": None if monitor.test_start_s is None else round(monitor.test_start_s, 3),
        "frames": monitor.frames_total,
        "frames_con_rostro": monitor.frames_with_face,
        "gafas_final": monitor.has_glasses,
        "parpadeos": monitor.eyes.blink_count,
        "parpadeos_prolongados": monitor.eyes.long_blink_count,
        # Proporción de parpadeos de cierre largo (Caffier et al., 2003) y duración media del parpadeo
        # (Ingre et al., 2006); incluyen parpadeos normales y prolongados, no micro-sueños
        "proporcion_parpadeos_prolongados": (round(monitor.eyes.long_blink_count / len(monitor.eyes.blink_durations), 4)
                                             if monitor.eyes.blink_durations else None),
        "duracion_media_parpadeo_s": (round(float(np.mean(monitor.eyes.blink_durations)), 4)
                                      if monitor.eyes.blink_durations else None),
        "bostezos": monitor.yawn.count,
        "micro_bostezos": monitor.yawn.micro_count,
        "duracion_media_bostezo_s": (round(float(np.mean(monitor.yawn.durations)), 4)
                                     if monitor.yawn.durations else None),
        "parpadeos_descartados_giro": monitor.eyes.fast_turn_rejected,
        "parpadeos_descartados_profundidad": monitor.eyes.shallow_rejected,
        "sonrisas_descartadas": monitor.yawn.smile_count,
        "tiempo_postura_fuera_de_rango_s": round(monitor.head.out_time, 2),
        "perclos_final_pct": round(monitor.perclos_val, 2),
        "recalibraciones": monitor.recalibration_count,
        "ojo_abierto_ref": monitor.profile.open_ear_baseline,
        "ojo_cerrado_ref": monitor.profile.closed_ear_level,
        "ojo_cerrado_medido": monitor.profile.closed_level_measured,
        "ojo_cerrado_proporcion": monitor.profile.closed_ratio,
        "ojo_cerrado_reutilizado_en_recalibracion": monitor.profile.closed_level_reused,
        "paso_ojos_cerrados_apertura_min_ratio": monitor.profile.closed_phase_min_ratio,
    }
