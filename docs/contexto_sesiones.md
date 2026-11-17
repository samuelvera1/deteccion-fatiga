# Contexto de las sesiones de trabajo con IA (hasta el 2026-11-16)

Resumen de lo decidido y aprendido, para que una sesión nueva (en otro PC o con otra herramienta) no empiece de
cero. Los números y criterios exactos están en `docs/registro_experimentos.md`; las reglas de trabajo en `CLAUDE.md`.

## Cómo quiere trabajar el autor
- Respuestas en español, claras y directas. Sin preguntas innecesarias: decidir y explicar los supuestos.
- Es un trabajo de investigación: hipótesis, criterio fijado antes de calcular, prueba y registro aunque salga mal.
  Nunca inventar datos ni declarar validaciones que no se hicieron (se pidió una vez decir que el autor validó una
  anotación hecha por la IA: se rechazó; la opción legítima es anotación asistida y revisada de verdad, declarada).
- Uso eficiente de recursos: los análisis corren localmente con scripts que imprimen resúmenes; la IA no mira videos.
- El producto real es en vivo, sin voz ni guion, con comportamiento natural. Lo guiado es validación controlada.

## Qué se hizo el 2026-11-16 y por qué
1. **Guía de voz para grabar** (`grabar_perclos.py`). El autor pidió un guion más corto (4 min) y una voz más activa:
   cuenta regresiva antes de cada cierre, parpadeos dirigidos en el minuto 1, parpadeos mirando a cada lado, voz en
   la calibración, aviso de luz. En los videos de lado coloca la cámara diciendo el ángulo en vivo.
2. **Cámara que deja de dar imágenes**: la app Eyeblink (de otro autor, arranca con Windows) ocupaba la cámara.
   Ahora el programa reintenta y reabre la cámara hasta 10 s y explica la causa.
3. **Ángulo de la cámara**: el resumen guarda `camara_yaw_grados` (giro de la cara respecto a la cámara en la
   calibración). Los rangos de postura son relativos a la calibración, no a la cámara.
4. **E12**: cabeceo válido hasta 15° hacia arriba y 10° hacia abajo (Eyeblink8 apoya arriba; abajo casi sin datos y
   con cierres falsos). En UTA-RLDD la alerta pasó del 64 % al 79 % del tiempo disponible.
5. **E10 (cámara de lado)**: a 30° los parpadeos se cuentan bien, los cierres largos no se sostienen; a 42-47° el ojo
   cerrado no se distingue (la apertura solo baja al 60 %). **Límite declarado: 45°**; aviso al calibrar por encima de
   40°. En los datasets ninguna persona pasa de ~30° respecto a su cámara.
6. **E14 → E14b**: si la persona se acomoda y se queda quieta 20 s fuera de rango, se crea una referencia de postura
   temporal. E14 (permanente) se adoptó y el mismo día el video de posturas mostró que sesgaba el ojo abierto al
   volver a la pantalla (+0,26); E14b (temporal, la calibración manda dentro de su rango) lo corrigió y cumple los
   cuatro criterios. Alerta disponible en UTA-RLDD: 64 % → 91 %.
7. **Revisión de los videos guiados** (sin anotar, descriptiva): de frente sin gafas funciona (10/10 cierres); con
   reflejos en gafas y a 30° los cierres largos fallan; **mirar hacia abajo solo con los ojos da cierres y un
   micro-sueño falso de 14 s** (problema principal pendiente, E13).
8. **Anotación**: debe hacerla una persona. Se añadieron atajos (N/P en `revisar.py`) y una anotación reducida (O solo
   en M y parpadeos pedidos), registrada antes de anotar.

## Sesiones grabadas (en `sesiones/`, fuera del repo)
| Sesión | Qué es | Estado |
|---|---|---|
| 20261116_195327 | con gafas, guion v2 | completa (E9); reflejos en las gafas |
| 20261116_202655 | sin gafas, guion v3 | completa (E9) |
| 20261116_205255 | lateral 30°, guion v3.1 | completa (E10) |
| 20261116_211249 / 211427 | lateral 45° | fallidas: límite del software |
| 20261116_223101 | posturas (E13) | completa; pendiente de anotar |
| 20261116_192312 / 202506 | intentos interrumpidos | descartados |

## Lo que falta (ruta corta para el artículo)
1. Escribir artículo v4 (y monografía y diapositivas) con lo que ya existe: validación principal en Eyeblink8,
   mejoras E5/E12/E14b, mapa de operación (cámara, postura, gafas), videos guiados como descriptivos, E4b preliminar.
   Borradores anteriores: `Entregables Fatiga Detector/fuentes/borradores/` (fuera del repo).
2. Congelar versión 1.2.0 y compilar el .exe en el PC donde se termine (`build.py`, `tests/verify_exe.py`).
3. Opcional: anotar los videos (E9, E10, E13), ampliar E4b con más personas de UTA-RLDD, sesiones naturales con
   `--grabar --kss`, segundo anotador, validar la mirada hacia abajo con la posición del iris.

## Herramientas de IA
- El autor pasa el proyecto a su PC personal. Opciones evaluadas: Claude Pro (todo está preparado para Claude Code),
  GitHub Copilot (gratis con el paquete de estudiante, sirve también para redactar), Gemini CLI (nivel gratuito).
- Lo que más uso consume: mirar imágenes, leer salidas largas y sesiones maratónicas. Mejor sesiones cortas con un
  objetivo claro.
- La conversación completa y la memoria de la IA están copiadas en `Entregables Fatiga Detector/contexto_claude/`
  (fuera del repo: contienen datos de la cuenta de la empresa).
