# fatigue_config.py
"""Umbrales y constantes del monitor de fatiga, cada uno con su fuente (literatura o sesión de datos).
Los valores marcados PROVISIONAL se ajustaron con pocos sujetos y están pendientes de validar.
FatigueMonitor los hereda, así que siguen accesibles como self.NOMBRE y se registran en metadata.json."""
from fatigue_alert import FatigueAlert


class Thresholds:
    # Calibración de ojo cerrado: cuentan los frames con apertura < CLOSED_CAPTURE_FACTOR x ojo abierto.
    # Si en CLOSED_CALIBRATION_TIMEOUT s no se completa, se usa CLOSED_FALLBACK_RATIO x ojo abierto
    # (valor de reserva, NO medido: queda marcado en metadata.json como cierre_medido = false).
    # 0.25 es el mínimo del único parpadeo completo observado en la sesión 20261005_231802.
    CLOSED_CAPTURE_FACTOR = 0.6
    CLOSED_CALIBRATION_TIMEOUT = 10.0
    # En vivo, si en un intento no se detectan los ojos cerrados, el paso se repite solo (hasta
    # CLOSED_MAX_ATTEMPTS intentos, con CLOSED_RETRY_PAUSE s entre ellos) antes de usar la reserva
    CLOSED_MAX_ATTEMPTS = 3
    CLOSED_RETRY_PAUSE = 3.0
    CLOSED_FALLBACK_RATIO = 0.25
    # Solo cuentan los cuadros de un CIERRE SOSTENIDO: >= CLOSED_MIN_SUSTAINED_S seguidos bajo el umbral (huecos de
    # hasta CLOSED_GAP_FRAMES cuadros). Sin esto, los parpadeos espontáneos del paso (3-8 cuadros cada uno) se juntaban
    # como "ojo cerrado medido" a medio cerrar: en 7 de 21 videos sin paso de cierre (Eyeblink8, UTA-RLDD) y en 2
    # sesiones en vivo sin cierre real (20261017_131950, 20261109_090009), con alertas falsas (RLDD 05 somnoliento:
    # 53 s de micro-sueño). 0,5 s supera la duración de los parpadeos normales (0,13-0,43 s, ver LONG_BLINK_SECONDS).
    CLOSED_MIN_SUSTAINED_S = 0.5
    CLOSED_GAP_FRAMES = 2
    # Si con los ojos cerrados la apertura no baja de este nivel, el cierre apenas es visible en la malla
    CLOSURE_VISIBLE_MAX_RATIO = 0.6
    # Reapertura tras el paso de ojos cerrados: el monitoreo empieza cuando el cierre baja de
    # REOPEN_MAX_CLOSURE durante REOPEN_FRAMES frames seguidos. Sin esto, el tiempo que el sujeto tarda
    # en abrir los ojos tras el pitido (o en un vídeo, donde no hay pitido) contaba como micro-sueño y
    # PERCLOS (sesión 20261008_143243: micro-sueño falso de 1.02 s nada más terminar la calibración).
    REOPEN_MAX_CLOSURE = 0.5
    REOPEN_FRAMES = 3

    # PERCLOS P80 (Wierwille et al., 1994; Dinges y Grace, 1998): proporción del tiempo, en una
    # ventana de 1 min, con el párpado >= 80 % cerrado. Incluye los parpadeos (variante elegida;
    # algunas definiciones los excluyen).
    P80_CLOSURE = 0.80
    # Micro-sueño (Hertig-Godeschalk et al., 2020): párpados >= 80 % cerrados durante >= 1 s
    # (en ese trabajo, 1-15 s y confirmado con EEG; aquí es solo el criterio conductual).
    # Se sale del estado de cierre por debajo de MICROSLEEP_EXIT_CLOSURE para no partir un episodio.
    MICROSLEEP_SECONDS = 1.0
    MICROSLEEP_EXIT_CLOSURE = 0.70

    LEFT_EYE = [33, 160, 158, 133, 153, 144]
    RIGHT_EYE = [362, 385, 387, 263, 373, 380]

    MIN_BLINK_FRAMES = 2
    # PARPADEO PROLONGADO (long closure duration blink): la duración del parpadeo y la proporción de
    # parpadeos de cierre largo aumentan con la somnolencia (Caffier et al., 2003; Ingre et al., 2006).
    # Corte de 0.5 s PROVISIONAL: no verificado en la literatura; en los datos del sujeto los parpadeos
    # normales duraron 0.13-0.43 s (sesiones 20261005_232441, 20261006_003914 y _004113). Se guarda la
    # duración de cada parpadeo en eventos.csv para poder reclasificar con otro corte sin regrabar.
    LONG_BLINK_SECONDS = 0.5
    # Un parpadeo prolongado debe llegar a cierre >= 80 % (excluye entrecerrar los ojos)
    LONG_BLINK_MIN_CLOSURE = 0.80
    # RÁFAGAS de parpadeos: un nuevo cierre >= 80 % tras una reapertura parcial < 60 % es un parpadeo nuevo.
    # Valores PROVISIONALES derivados de la sesión 20261006_114449 (S02): en sus ráfagas los cierres
    # llegaron a 0.86-1.04 y las reaperturas parciales entre parpadeos a 0.19-0.58.
    BURST_PEAK_CLOSURE = 0.80
    BURST_REOPEN_CLOSURE = 0.60

    # SONRISA vs BOSTEZO (FACS, Ekman y Friesen, 1978): la sonrisa (AU12) estira las comisuras hacia los
    # lados; el bostezo abre la boca con caída de mandíbula. Un episodio de boca abierta se descarta como
    # bostezo si la boca está claramente más ancha que en reposo SIN gran caída de mandíbula.
    # Ajustado con datos (sin etiquetas por evento, PROVISIONAL): sonrisas de S01 (sesiones 20261006_155916
    # y _212220) -> ancho 1.33-1.44 y mandíbula 0.05-0.13; bostezos de S01 -> ancho 0.83-1.00 y mandíbula
    # 0.17-0.27; bostezos de otro sujeto (20261006_160134) -> mandíbula 0.17-0.61 (algunos con ancho hasta
    # 1.25, por eso la mandíbula decide). Se retiró la condición de elevación de comisuras: medida respecto
    # al labio superior no capta la sonrisa con dientes (el labio superior sube con las comisuras; ~0 en S01).
    SMILE_MIN_WIDTH_RATIO = 1.15    # boca >= 15 % más ancha que la neutra
    SMILE_MAX_JAW_DROP = 0.15       # mandíbula < 0.15 IPD (~9.5 mm) más abajo que en reposo

    # RANGO DE POSTURA VÁLIDO para las métricas del ojo (orientación relativa a la calibración frontal).
    # La apertura del ojo se mide en 2D: al inclinar la cabeza arriba/abajo se acorta en la imagen y parece
    # cierre. Sesión 20261006_174416 (S01, con gafas): con |pitch| <= 10° cierre aparente ~0 (mediana -0.04);
    # 10-15° -> 0.33; 30-45° -> 0.71 (hasta 0.93, por encima del P80). El giro lateral (yaw) hasta ~44° no
    # produjo cierre aparente. PROVISIONAL (1 sujeto; el efecto no se reprodujo en otras 19 sesiones, E1).
    # Fuera de rango no cuenta el PERCLOS; los parpadeos sí (E5: en Eyeblink8 FN 64 -> 17 sin subir los FP; en la
    # sesión piloto con gafas aparecieron 3 parpadeos prolongados falsos al inclinar la cabeza). El micro-sueño se
    # sigue evaluando (dormirse suele ir con cabeceo) y el intervalo se registra como POSTURA_FUERA_DE_RANGO.
    # E12 (Eyeblink8, anotación por cuadro): con la cabeza 10-15° hacia ARRIBA respecto a la calibración, el ojo
    # cerrado se mide como dentro del rango (sensibilidad 0,87, falsos positivos 0,08 % en 3912 cuadros) -> 15°.
    # Hacia ABAJO no hay datos (28 cuadros, 57 % de cierres falsos: el párpado baja con la mirada) -> se queda en 10°.
    # Pitch positivo = cabeza hacia abajo (fatigue_pose). En UTA-RLDD la alerta pasa de estar disponible el 64 % al
    # 79 % del tiempo.
    POSE_MAX_PITCH_DOWN = 10.0
    POSE_MAX_PITCH_UP = 15.0
    POSE_MAX_YAW = 40.0
    # Postura "frontal" exigida por la puerta de estabilidad (calibración y análisis de gafas): la medida de
    # deformación de la malla reacciona sobre todo a los giros de cabeza (0.25-0.31 con 33-43° de yaw)
    POSE_STABLE_MAX = 10.0
    # E14: si la postura sale de rango y se queda quieta en la nueva posición POSTURE_REBASE_HOLD_S s (desviación típica
    # <= POSTURE_REBASE_MAX_STD°), se rehace la referencia de postura y el ojo abierto (la persona se acomodó, o calibró
    # en un momento atípico). Solo dentro de ±30° de cabeceo y ±40° de giro respecto a la calibración (E10). En
    # UTA-RLDD la alerta pasa de estar disponible el 79 % al 90 % del tiempo sin más cierres en los videos alerta.
    POSTURE_REBASE_HOLD_S = 20.0
    # Límite de la cámara de lado (E10): con la cara a 30° de la cámara el ojo cerrado se distingue (la apertura baja
    # al 41 % al cerrar); a 42-47° ya no (baja solo al 60 %, la calibración no lo capta). Por encima de este ángulo
    # se avisa en la calibración. Límite declarado del software: cámara a menos de 45° de la cara.
    CAMERA_MAX_YAW_WARN = 40.0
    POSTURE_REBASE_MAX_STD = 4.0
    POSTURE_REBASE_CAP_PITCH = 30.0
    POSTURE_REBASE_CAP_YAW = 40.0
    # Periodo refractario tras contar un parpadeo (evita contar dos veces el mismo). Era 8 frames (~0.27 s)
    # y bloqueaba parpadeos reales de ráfagas (separados ~0.25 s). Con 3 frames (~0.1 s): S02 pasa de 24 a
    # 28 parpadeos en la sesión 20261006_114449 (29 cierres en la señal) y las sesiones de S01 con recuento
    # manual no cambian. PROVISIONAL: falta validar con ráfagas contadas a mano.
    BLINK_REFRACTORY_FRAMES = 3
    # GIRO RÁPIDO DE CABEZA: al girar rápido, la apertura medida por la malla cae un poco sin que el
    # párpado se mueva, y al pasar por la postura frontal se contaba como parpadeo (sesión
    # 20261008_154526: giro de 208 °/s con cierre máximo 0.08, frente a parpadeos reales con cierre
    # 1.00-1.13 y cabeza a 27-41 °/s). Si durante el episodio la cabeza gira a más de FAST_HEAD_SPEED,
    # solo cuenta como parpadeo si el cierre llega al P80. No se descartan todos: los giros de mirada
    # con la cabeza suelen ir acompañados de parpadeos reales (Evinger et al., 1994), que cierran del
    # todo. Umbral PROVISIONAL (1 sesión; en ella el percentil 99 del giro normal fue 114 °/s).
    FAST_HEAD_SPEED = 120.0

    # PARPADEO = evento transitorio: caída brusca de la apertura respecto a la apertura de justo antes
    # (referencia local = percentil 90 de la apertura entre 0.9 s y 0.3 s antes del frame actual), en la
    # línea de tratar el parpadeo como un patrón temporal de la señal EAR (Soukupová y Čech, 2016).
    # Es independiente de la mirada, la postura y las gafas, que cambian el nivel de apertura "normal".
    # Ajustado con la sesión 20261005_232441 (1 sujeto, 10 parpadeos con gafas + 10 sin gafas,
    # recuento manual): factores 0.78-0.80 dieron 10/10 en ambos tramos y 0 micro-sueños falsos;
    # el umbral relativo a la calibración (0.82 con gafas) daba 15/10. PENDIENTE validar con más sujetos.
    BLINK_LOCAL_FACTOR = 0.79       # parpadeo si apertura < 0.79 x referencia local (igual con y sin gafas)
    BLINK_REOPEN_MARGIN = 0.06      # se reabre por encima de (0.79 + 0.06) x referencia local
    BLINK_DEEP_MARGIN = 0.10        # 1 solo frame cuenta si baja de (0.79 - 0.10) x referencia local
    BLINK_REF_WINDOW = (0.9, 0.3)   # s antes del frame actual que forman la referencia local
    BLINK_REF_PERCENTILE = 90
    # PROFUNDIDAD MÍNIMA: un parpadeo cuenta si la apertura baja al menos un 30 % de la referencia local que había al
    # empezar (1 - mínimo / referencia >= 0.30). Experimento E2 (docs/registro_experimentos.md), ajustado en
    # Eyeblink8 con validación cruzada por video: FP 64 -> 14 y FN 62 -> 71 (F1 0.83 -> 0.88). NO cumplía el criterio
    # acordado (los FN subieron); se adoptó por decisión del autor. Entre los dos valores que eligió la validación
    # cruzada (0.30 y 0.40, F1 igual) se tomó 0.30 porque con gafas el 35 % de los parpadeos propios bajan menos de
    # 0.40. PROVISIONAL: pendiente de probar con datos nuevos.
    BLINK_MIN_DEPTH = 0.30

    # Bostezo de dos niveles. Cada nivel exige que la boca supere su umbral de forma sostenida
    # (huecos de hasta YAWN_GAP_FRAMES frames no cortan la racha: tics de labios). Un episodio
    # dura mientras siga activa la racha del nivel 2 (el umbral más bajo).
    YAWN_TIER_EXAGGERATED, YAWN_TIER_MICRO = 0, 1
    YAWN_GAP_FRAMES = 2
    YAWN_COOLDOWN_SECONDS = 1.0
    # Duración del bostezo = tiempo con la boca por encima del umbral micro (fase de boca abierta), del
    # primer al último frame sobre el umbral. No es la duración completa del bostezo (Provine, 1986:
    # ~6 s de media incluyendo inspiración y cierre), sino la parte visible como apertura bucal.

    IPD_SMOOTHING = 0.2       # EMA: la IPD es rígida, solo cambia con la distancia a la cámara

    # Colores del HUD para PERCLOS: los mismos umbrales que las alertas (fatigue_alert.py, de la literatura)
    PERCLOS_WARN_PCT = FatigueAlert.CAUTION_PCT
    PERCLOS_ALERT_PCT = FatigueAlert.DROWSY_PCT
    PERCLOS_BAR_MAX = 30.0    # tope de la barra del panel (solo visualización)
