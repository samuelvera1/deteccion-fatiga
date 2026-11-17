# Registro de experimentos sobre el método

Cada cambio propuesto al método queda aquí con su hipótesis, el criterio fijado antes de probar, los datos, el
resultado (aunque sea negativo) y la decisión (guía de anotación, sección 7).

---

## Correcciones de implementación (sin experimento: el sistema medía algo que por definición no debía medir)

**C1 — El paso de ojos cerrados aceptaba parpadeos como "ojo cerrado medido" (2026-11-16).** Durante los 10 s del
paso, los cuadros de los parpadeos espontáneos (apertura < 0,6 × abierta, 3-8 cuadros cada uno) se acumulaban, y
con 10 o más el nivel de ojo cerrado quedaba "medido" a medio cerrar. Con ese nivel, cualquier bajada de la mirada
superaba el 80 % de cierre: alertas falsas (RLDD 05 somnoliento, 53 s de micro-sueño; el panel marcaba SOMNOLENCIA
en videos de personas alerta). Evidencia en las trazas: 7 de 21 videos sin paso de cierre (Eyeblink8 2 y 10; RLDD 04
poco alerta, 04 somnoliento, 06 alerta, 06 somnoliento, 05 somnoliento) con proporción cerrado/abierto de 0,23-0,55, y
2 sesiones en vivo en las que no hubo cierre real (20261017_131950: el ojo quedó al 70-80 %; 20261109_090009: ojos
abiertos). Corrección: solo cuentan los cuadros de un cierre sostenido de ≥ 0,5 s seguidos (huecos de hasta 2
cuadros), más largo que cualquier parpadeo normal (0,13-0,43 s). Simulada sobre las trazas: en esos 9 casos el ojo
cerrado pasa a "no medido" (el sistema lo advierte en vez de dar alertas) y en las otras 17 sesiones en vivo se sigue
midiendo. Pruebas: tests/test_fatigue_profile.py. No afecta a E4b, que se procesa con una copia congelada del código
(commit 1217023).

---

## E1 — Apertura ocular en 3D para evitar el cierre aparente al inclinar la cabeza (2026-11-16)

**Motivación.** En la validación externa con Eyeblink8 (commit edb9ec9 + cambios solo de interfaz, luego abcd056),
52 de los 62 parpadeos perdidos ocurrieron con la postura fuera de rango (|cabeceo| > 10°), donde el sistema no cuenta
parpadeos. La regla de ±10° se basó en una sola sesión (20261006_174416), en la que el ojo abierto aparentaba
cierres de 0,33 a 0,71 al inclinar la cabeza.

**Hipótesis.** El cierre aparente se debe a que la apertura se mide en el plano de la imagen y se acorta al inclinar
la cabeza. Medir las distancias verticales del párpado con las coordenadas 3D de MediaPipe (x, y, z) lo eliminaría y
permitiría ampliar el rango de postura válida.

**Criterio (fijado antes de ver los datos).**
- C1: con |cabeceo| de 10-15°, 15-20° y 20-30°, mediana del cierre aparente en 3D < 0,15 y como mucho la mitad de la
  de 2D (al menos 50 cuadros por intervalo).
- C2: en los parpadeos contados, cierre máximo mediano en 3D ≥ 90 % del de 2D.

**Datos.** 19 sesiones grabadas de desarrollo de S01 (2026-10-12 a 2026-10-31), reprocesadas con la misma
configuración de MediaPipe; 13 con niveles de ojo abierto y cerrado válidos. La apertura 2D recalculada difiere de
la registrada en la traza un 2,1 % (mediana). Scripts: exp3d_extract.py y exp3d_analyze.py (fuera del repositorio).

**Resultado.**

| \|cabeceo\| | Cuadros | Cierre aparente 2D | Cierre aparente 3D |
|---|---|---|---|
| 0-5° | 19 025 | −0,002 | −0,002 |
| 5-10° | 2 915 | +0,026 | +0,022 |
| 10-15° | 960 | −0,139 | −0,121 |
| 15-20° | 231 | −0,289 | −0,296 |
| 20-30° | 271 | −0,374 | −0,405 |

- 3D y 2D difieren en 0,03 o menos en todos los intervalos: la medida 3D no cambia la señal.
- C2: cierre máximo mediano de 312 parpadeos, 0,91 en 2D y 0,91 en 3D.
- C1 se cumple solo formalmente, porque el cierre aparente es negativo (el ojo parece *más abierto*) en ambos
  métodos; el criterio no contemplaba valores negativos. **No hay evidencia a favor de la hipótesis.**

**Hallazgo exploratorio (después de ver C1).** Con el signo del cabeceo, las sesiones grabadas dan cierre aparente
negativo a −45/−20° (−0,38 en 2D), mientras que la sesión 20261006_174416 dio +0,72 en el mismo intervalo. El efecto
de la postura no es reproducible entre sesiones; probablemente depende de hacia dónde mira la persona (el párpado
sigue a la mirada) y no solo de la geometría. Además, 20261006_174416 se ejecutó con un commit que ya no existe
(d6824a9), así que su convención de postura podría diferir.

**Decisión.** Se rechaza el cambio: el sistema sigue midiendo en 2D. La regla de postura (±10°) se mantiene, pero su
base empírica queda marcada como débil. Para revisarla hace falta un experimento controlado: inclinar la cabeza
arriba y abajo a ángulos conocidos (a) mirando la pantalla y (b) mirando al frente respecto a la cabeza, con los
ojos abiertos y con parpadeos en cada ángulo.

**Lección para los criterios.** Los criterios de reducción deben usar valores absolutos (|cierre aparente|) o
fijar el signo esperado.

---

## E2 — Profundidad mínima del parpadeo para reducir falsos positivos (2026-11-16)

**Motivación.** En Eyeblink8, los 65 falsos positivos de parpadeo tuvieron un cierre máximo mediano de 0,27 frente a
1,00 en los aciertos: en su mayoría son caídas poco profundas de la apertura.

**Hipótesis.** Exigir que la apertura baje al menos una fracción D de la referencia local (profundidad
d = 1 − mínimo / referencia ≥ D) elimina falsos positivos sin perder parpadeos reales. Hoy el umbral de entrada es
0,79 × referencia, es decir, d > 0,21 (equivale a D = 0,21, sin cambio).

**Datos.** Eyeblink8, usado desde ahora como conjunto de DESARROLLO (sus resultados ya se vieron en la validación
externa de la versión abcd056, que se mantiene como tal en los documentos). La prueba definitiva de este cambio
requiere datos nuevos.

**Criterio (fijado antes de calcular).**
- Candidatos: D ∈ {0,21 (actual), 0,25, 0,30, 0,35, 0,40, 0,45, 0,50}.
- Validación cruzada dejando un video fuera (8 pliegues): en cada pliegue se elige el D que maximiza el F1 de
  parpadeos (análisis principal) en los otros 7 videos; empates → el D más pequeño. Ese D se aplica al video
  apartado.
- Se suman VP, FP y FN de los 8 videos apartados. Se acepta el cambio si, frente a D = 0,21, los FP bajan y los FN
  no aumentan (guía, sección 7). Se informan también F1 y el análisis con postura válida.
- La profundidad se calcula con la traza de cada sesión (mínimo de la apertura durante el parpadeo y referencia
  local al inicio); el filtro se aplica a los eventos ya detectados y, si se acepta, se implementa en el detector y
  se vuelve a ejecutar el sistema para confirmar los números.

**Resultado.** Validación cruzada (8 pliegues; D elegido: 0,40 en 5 pliegues y 0,30 en 3):

| | VP | FP | FN | F1 | F1 con postura válida |
|---|---|---|---|---|---|
| Actual (D = 0,21) | 316 | 64 | 62 | 0,834 | 0,899 |
| Validación cruzada | 307 | 14 | 71 | 0,878 | 0,955 |

Barrido descriptivo en los 8 videos (no decide): FP 64 → 31 → 17 → 14 → 8 → 8 → 5 y FN 62 → 63 → 64 → 67 → 71 →
75 → 80 para D = 0,21 … 0,50. (Con D = 0,21 el filtro a posteriori da 64 FP en lugar de 65: un evento con
profundidad calculada ligeramente bajo 0,21 por usar la referencia del primer cuadro del parpadeo.)

**Decisión.** NO SE ACEPTA según el criterio acordado: los FP bajan un 78 % (64 → 14), pero los FN suben de 62 a 71.
El detector no cambia. El balance es favorable (F1 0,834 → 0,878), pero cambiar la regla de aceptación después de
ver este resultado no sería válido para este experimento. Queda propuesto: (1) acordar con el director, antes del
próximo experimento, si el criterio debe permitir un aumento acotado de FN cuando el F1 mejora; y (2) si se adopta,
volver a probar la profundidad mínima (D entre 0,30 y 0,40) en datos nuevos.

**Adopción por decisión del autor (2026-11-16).** Por falta de tiempo para consultar al director, el autor decidió
adoptar el cambio pese a no cumplir el criterio acordado, por la reducción de falsos positivos y la mejora del F1.
Elección de D (posterior a ver los datos, justificada así): entre los dos valores que eligió la validación cruzada
(0,30 y 0,40, F1 en los 8 videos 0,886 y 0,886) se tomó **D = 0,30** porque pierde menos parpadeos (FN 64 frente a
71) y porque, en las sesiones propias, el 34,8 % de los parpadeos detectados con gafas tienen profundidad < 0,40
(12,4 % < 0,30; sin gafas, 10,1 % y 2,9 %): con gafas el ojo cerrado solo baja al ~54 % de la apertura. En la
evaluación piloto ciega (con gafas) los 9 aciertos tuvieron profundidad de 0,63 a 0,82 y dos de los cuatro falsos
positivos, 0,22.
- Implementación: fatigue_config.BLINK_MIN_DEPTH = 0.30; fatigue_eyes descarta el episodio y registra
  PARPADEO_DESCARTADO_PROFUNDIDAD (lo cruzan evaluar.py y el revisor); prueba tests/test_fatigue_eyes.py.
- Cómo informarlo: el F1 estimado del cambio es el de la validación cruzada (0,878; 0,955 con postura válida), no
  el de los 8 videos con D fijo (0,886), que es optimista. Eyeblink8 deja de ser un conjunto de prueba para esta
  versión; la validación externa publicada sigue siendo la de abcd056 (F1 0,83). La prueba definitiva de D = 0,30
  queda pendiente en datos nuevos.
- Confirmación con el sistema completo (Eyeblink8 reprocesado con el cambio implementado, datos de desarrollo):
  VP 314, FP 18, FN 64; sensibilidad 0,83, precisión 0,95, F1 0,88; con postura válida, F1 0,96 (VP 310, FP 16,
  FN 11). Coincide con el filtro a posteriori (FP 17) salvo un evento.
- Prueba de regresión: solo cambian los parpadeos (en los 3 videos de referencia se descartan 1, 3 y 1 caídas por
  poco profundas; sin anotaciones para saber si eran reales). Referencia regenerada a propósito.

---

## E3 — Nivel de ojo cerrado estimado con los parpadeos espontáneos (2026-11-16)

**Motivación.** Sin el paso de cerrar los ojos (videos ya grabados, como los de Eyeblink8, o una persona que no lo
hace bien) el grado de cierre no es fiable y no se pueden medir PERCLOS ni micro-sueños.

**Hipótesis.** El mínimo de la apertura en los parpadeos completos se acerca al nivel de ojo cerrado. Un percentil
bajo de los mínimos de los parpadeos del primer minuto de conteo estima la proporción ojo cerrado / ojo abierto.

**Datos.** Sesiones propias en vivo con el ojo cerrado medido en la calibración (referencia), sin recalibraciones y
con al menos 5 parpadeos (profundidad ≥ 0,30) en los primeros 60 s de conteo. Mínimo de cada parpadeo tomado de la
traza.

**Criterio (fijado antes de calcular).**
- Candidatos: percentil p ∈ {5, 10, 25, 50} de los mínimos de los parpadeos del primer minuto.
- Validación cruzada dejando una sesión fuera: en cada pliegue se elige el p con menor error absoluto mediano en las
  demás sesiones y se aplica a la apartada. Error = proporción estimada − proporción medida (cerrado / abierto).
- Se acepta si |error| ≤ 0,05 en al menos el 80 % de las sesiones apartadas.
- Si se acepta, se implementa como calibración alternativa marcada como «estimada» (no sustituye al paso de ojos
  cerrados cuando se hace).

**Resultado.** 15 sesiones válidas (S01). La validación cruzada eligió el percentil 25 en los 15 pliegues. Error de
la proporción estimada en la sesión apartada: |error| ≤ 0,05 en 10 de 15 (67 %); error absoluto mediano 0,023; los
mayores, −0,268 (sesión 20261025_101730, solo 5 parpadeos), −0,075, −0,061, −0,060 y +0,058. Errores por percentil
(todas las sesiones): P5 y P10 subestiman (el mínimo de un parpadeo suele quedar por debajo del ojo cerrado de la
calibración), P50 sobrestima.

**Decisión.** NO SE ACEPTA y no se implementa. Un error grande hace que el ojo cerrado real no llegue al P80 (por
ejemplo, con −0,27 un ojo cerrado del todo marcaría un cierre de ~0,65) y PERCLOS dejaría de detectar cierres. Vías
para un nuevo intento: exigir más parpadeos (el peor caso tenía 5) o combinar el estimador con una comprobación de
que la malla registra el cierre.

---

## E4 — Somnolencia real: duración del parpadeo en UTA-RLDD (piloto, 2026-11-16)

**Pregunta.** ¿Los indicadores del sistema cambian cuando la persona está realmente somnolienta?

**Datos.** UTA-RLDD (Ghoddoosian et al., 2019), primera parte (Fold1_part1): 6 personas, 3 videos cada una de unos
10 minutos grabados por ellas mismas con su teléfono o cámara, etiquetados por la propia persona como alerta (0),
poco alerta (5) y somnolienta (10). Versión del sistema: commit en el que se registra este criterio (profundidad
mínima D = 0,30), sin cambiar parámetros. Calibración automática; como los videos no tienen el paso de ojos
cerrados, el grado de cierre no es fiable.

**Hipótesis (Caffier et al., 2003; Ingre et al., 2006).** La duración media del parpadeo es mayor en el video
somnoliento (10) que en el alerta (0) de la misma persona. La duración la mide el sistema con la referencia local
(no depende del nivel de ojo cerrado).

**Criterio (fijado antes de procesar).**
- Medida principal: por persona, diferencia de la mediana de duración de los parpadeos contados (PARPADEO y
  PARPADEO_PROLONGADO) entre el video 10 y el 0.
- Se considera que el piloto apoya la hipótesis si la diferencia es positiva en al menos 5 de las 6 personas. Se
  informan la prueba de los signos y la de rangos con signo de Wilcoxon (unilaterales), sabiendo que con 6 personas
  la potencia es baja.
- Calidad: se excluye un video si el rostro se detecta en menos del 50 % de los cuadros o si hay menos de 3 minutos
  de conteo con postura válida; se informa cuántos.
- Exploratorio (no decide): frecuencia de parpadeo por minuto, proporción de parpadeos de 0,5 s o más, el video
  intermedio (5) y PERCLOS (calculado con el ojo cerrado de reserva, marcado como no fiable).

**Desviación del plan (antes de ver resultados).** Por tiempo de cómputo (4 núcleos compartidos con E5) se dejaron
de procesar los videos intermedios (5): solo se completó el de la persona 04; los de 01, 02 y 03 se interrumpieron y
los de 05 y 06 no se ejecutaron. El análisis exploratorio del video intermedio queda sin hacer. La medida principal
(videos 0 y 10) no cambia.

**Resultado.** Por el criterio de calidad se excluyeron 3 videos con menos de 3 minutos de conteo con postura
válida: 02 alerta (2,7 min), 04 alerta (2,9 min) y 05 somnoliento (0,6 min). Son videos de teléfono con la cabeza
inclinada buena parte del tiempo, y el rostro se detectó en el 100 % de los cuadros. Quedaron 3 personas con el
par completo:

| Persona | Mediana alerta | Mediana somnoliento | Diferencia |
|---|---|---|---|
| 01 | 0,133 s | 0,167 s | +34 ms |
| 03 | 0,300 s | 0,433 s | +133 ms |
| 06 | 0,200 s | 0,168 s | −32 ms |

Positiva en 2 de 3 (signos p = 0,50; Wilcoxon p = 0,25). El criterio (≥ 5 de 6) **no es evaluable** tal como se
fijó: solo 3 personas válidas. Exploratorio, medias de los videos válidos, de alerta a somnoliento: mediana de
duración de 0,200 a 0,268 s; proporción de parpadeos de ≥ 0,5 s de 6 % a 15 %; frecuencia de 17,7 a 12,8 por
minuto. Va en la dirección de la literatura, pero sin poder estadístico. PERCLOS no es interpretable (ojo cerrado no
medido en 7 de 12 videos).

**Decisión.** Piloto no concluyente. La exclusión por postura deja fuera la mitad de las personas en videos de
teléfono.

### E4b — Repetición con más personas de UTA-RLDD (criterio fijado el 2026-11-16, antes de procesar)

- **Datos.** Todas las partes de UTA-RLDD que se descarguen, incluida Fold1_part1 (reprocesada). Solo los videos
  alerta (0) y somnoliento (10). Versión 1.1.0 del sistema (parpadeos también con la postura fuera de rango, E5).
- **Calidad.** Se excluye un video si el rostro se detecta en menos del 50 % de los cuadros o si hay menos de 3
  minutos de conteo (desde el inicio del conteo, con rostro), y una persona si le falta alguno de sus dos videos.
- **Medida principal.** Igual que E4: diferencia por persona de la mediana de duración del parpadeo (10 − 0).
- **Criterio.** Se considera que los datos apoyan la hipótesis si la prueba de rangos con signo de Wilcoxon unilateral
  da p < 0,05 con al menos 15 personas válidas. Se informan también la prueba de los signos, la mediana de las
  diferencias y su intervalo de confianza del 95 % (bootstrap por persona).
- **Exploratorio.** Frecuencia de parpadeo, proporción de parpadeos de ≥ 0,5 s y PERCLOS (no fiable sin ojo cerrado
  medido).
- **Resultado parcial (2026-11-16).** Procesadas Fold1_part1 (6 personas, las mismas del piloto E4) y Fold3_part2
  (6 personas nuevas). Todos los videos superan la calidad: rostro en el 100 % de los cuadros y 6,8-14,6 minutos de
  conteo. Se excluye 1 persona (Fold3_part2/32), a la que le falta el video somnoliento. Quedan **11 personas válidas**.
  - Diferencia de la mediana de duración (somnoliento − alerta), por persona: +34, +67, +133, +160, +33, −32, +80, +83,
    −27, +33 y +68 ms.
  - Mediana +67 ms (IC 95 % bootstrap +33 a +83 ms). Positivas 9 de 11 (signos p = 0,033); Wilcoxon unilateral
    W+ = 63, p = 0,002.
  - Exploratorio: 16,1 y 17,3 parpadeos/min (alerta y somnoliento); proporción de parpadeos ≥ 0,5 s 5,3 % y 14,7 %.
  - **Criterio: no evaluable todavía** (11 personas; se exigen 15).
  - Cautelas:
    - 6 de las 11 personas son las del piloto, que ya se vieron antes de formular E4b. Solo con las 5 nuevas: 4 de 5
      positivas, Wilcoxon p = 0,063 (con 5 personas el menor p posible es 0,031).
    - Tres videos alerta tienen frecuencias raras de parpadeo: Fold3_part2/31 con 53 por minuto (¿falsos positivos?) y
      Fold3_part2/33 y /34 con unos 2 por minuto (¿parpadeos perdidos?). Sus medianas salen de 20-23 parpadeos en
      los dos últimos. No se excluyen: el criterio de calidad estaba fijado y no los cubre. Conviene revisarlos a
      mano (sin cambiar el criterio).
  - Siguiente paso: Fold1_part2 y Fold3_part1 (u otras partes) para llegar a 15 o más personas, con el mismo
    análisis. Con E5 (parpadeos también fuera de rango, adoptado después), una repetición con más partes de UTA-RLDD
debería usar como criterio de calidad el tiempo de conteo con rostro, no el de postura válida, y fijarse antes de
procesar.

---

## E5 — Contar parpadeos también con la postura fuera de rango (2026-11-16)

**Motivación.** En Eyeblink8, 52 de los 62 parpadeos perdidos (84 %) ocurrieron con la postura fuera de rango, donde
hoy no se cuentan. E1 mostró que el cierre aparente por postura no se reproduce entre sesiones.

**Hipótesis.** El detector de parpadeos compara con la apertura de hace 0,3-0,9 s (referencia local), así que un
cambio lento de postura no lo dispara. Contar parpadeos también fuera de rango recupera parpadeos perdidos sin
añadir muchos falsos positivos. PERCLOS mantiene la exclusión (un cierre aparente sí lo falsearía).

**Cambio probado.** En EyeEventDetector.update, con la postura fuera de rango se sigue ejecutando el detector de
parpadeos; PERCLOS se sigue saltando (skip_gap). El micro-sueño no cambia. Código: el del commit de este registro
más ese cambio, en una copia fuera del repositorio (para no alterar E4, que se estaba procesando).

**Datos.** Eyeblink8 (desarrollo, 8 videos) y la sesión piloto propia con anotación ciega (20261009_101139, con
gafas), comparando contra la versión actual (profundidad mínima D = 0,30).

**Criterio (fijado antes de ejecutar).**
- Regla del proyecto aplicada a un cambio que busca reducir FN: se acepta si, en Eyeblink8, los FN bajan y los FP
  no suben.
- Se informan también el F1 y el resultado de la sesión piloto, que no deciden.

**Resultado.**

| | VP | FP | FN | F1 | F1 con postura válida |
|---|---|---|---|---|---|
| Eyeblink8, versión actual (D = 0,30) | 314 | 18 | 64 | 0,88 | 0,96 |
| Eyeblink8, con E5 | 361 | 17 | 17 | 0,95 | 0,96 |
| Piloto propio (gafas), versión actual | 9 | 2 | 2 | 0,82 | 0,82 |
| Piloto propio (gafas), con E5 | 9 | 5 | 2 | 0,72 | 0,82 |

- Eyeblink8: fuera de rango el sistema contó 47 parpadeos normales (45 aciertos, 2 FP) y 8 prolongados (7 aciertos,
  1 FP). Sensibilidad de 0,83 a 0,95 sin perder precisión (0,95).
- Piloto propio: los 3 FP nuevos son PARPADEO_PROLONGADO de 0,9-1,1 s durante inclinaciones deliberadas de la cabeza
  con giros de 120-143 °/s y cierre aparente de 0,83-0,98: el artefacto de postura que motivó la regla, que además
  infla un indicador de somnolencia (proporción de parpadeos prolongados).

**Decisión.** SE ACEPTA según el criterio (FN 64 → 17, FP 18 → 17). Advertencia registrada: con gafas y movimientos
de cabeza deliberados aparecen parpadeos prolongados falsos fuera de rango. Hipótesis para un experimento posterior
(E5b), que necesita más datos propios con inclinaciones controladas: fuera de rango, contar solo parpadeos de menos
de 0,5 s (en Eyeblink8 perdería 7 aciertos y quitaría 1 FP; en el piloto quitaría los 3 FP). La implementación en el
repositorio se hace al terminar E4, que se estaba procesando con el código anterior.

---

## E6 — Búsqueda de parámetros del detector de parpadeos con validación cruzada (2026-11-16)

**Motivación.** El autor pidió iterar de forma autónoma para acercarse al máximo de aciertos. Para que el resultado
no sea memorizar los videos, la búsqueda se hace con validación cruzada y la regla se fija antes de ejecutarla.

**Herramienta.** Simulador (fuera del repositorio) que ejecuta el EyeEventDetector real sobre las trazas ya
guardadas, sin MediaPipe. Verificado: reproduce el sistema completo en Eyeblink8 (versión actual: 314/18/64 idéntico;
con E5: 361/16/17 frente a 361/17/17).

**Datos.** 9 grabaciones con parpadeos anotados: los 8 videos de Eyeblink8 y la sesión piloto propia (gafas).

**Espacio de búsqueda (72 configuraciones).** Postura: excluir (actual) o contar (E5); profundidad mínima D ∈ {0,25,
0,30, 0,35, 0,40}; factor de la referencia local ∈ {0,75, 0,79, 0,83}; periodo refractario ∈ {2, 3, 5} cuadros.

**Regla (fijada antes de ejecutar).**
- Validación cruzada dejando una grabación fuera (9 pliegues): en cada pliegue se elige la configuración con mayor F1
  de parpadeos sumando las otras 8 (empates → la más cercana a la actual) y se aplica a la apartada.
- Estimación honesta = VP, FP y FN sumados de las 9 grabaciones apartadas.
- Referencia de comparación: la configuración con E5 y los demás parámetros actuales (sin selección).
- Se adopta la configuración elegida en la mayoría de pliegues si el F1 de la validación cruzada supera al de la
  referencia en al menos 0,01 y los FN no aumentan más del 10 %; si no, se mantiene la configuración con E5.
- Todo lo obtenido aquí es de desarrollo; la prueba definitiva requiere datos nuevos.

**Resultado.**

| | VP | FP | FN | F1 |
|---|---|---|---|---|
| Versión del repositorio (excluir postura) | 323 | 20 | 66 | 0,883 |
| Referencia E5 (contar fuera de rango) | 370 | 21 | 19 | 0,949 |
| Validación cruzada de la búsqueda | 369 | 15 | 20 | 0,955 |

- La configuración más elegida (8 de 9 pliegues) fue contar fuera de rango, D = 0,40 y factor 0,75; el periodo
  refractario no cambia nada en estos datos.
- Mejor F1 descriptivo en las 9 grabaciones: 0,958 (optimista).
- La sesión piloto propia queda en 9/5/2 con cualquier configuración: sus 3 FP por inclinación de la cabeza no se
  corrigen con estos parámetros.

**Decisión.** NO se adopta (mejora de 0,006 < 0,01). Se mantiene E5 con los demás parámetros actuales. Conclusión: con
los datos anotados disponibles, el detector de parpadeos está cerca de su techo por ajuste de parámetros (F1 ≈ 0,95 en
validación cruzada). Los errores restantes requieren datos nuevos (inclinaciones controladas propias, un segundo
anotador, otro conjunto público), no más búsqueda. E5b (fuera de rango, solo parpadeos cortos) se estimó a partir de
los recuentos de E5: perdería 7 aciertos y quitaría 4 FP (F1 ≈ 0,944 < 0,949), así que no se ejecuta.

---

## E7 — Apertura del ojo normalizada por el diámetro vertical del iris (2026-11-16)

**Motivación.** La apertura actual divide la distancia vertical entre párpados por la IPD, que es horizontal: al
inclinar la cabeza la apertura se acorta en la imagen y la IPD no, de modo que el ojo parece cerrarse (E1, sesión
piloto con 3 parpadeos prolongados falsos). Además, PERCLOS se definió como la cobertura de la pupila por el párpado.

**Hipótesis.** El diámetro vertical del iris (puntos de iris del modelo refinado de MediaPipe, ya calculados y sin
usar) está en el mismo plano que la abertura del párpado y se acorta igual con el cabeceo. La razón abertura / diámetro
vertical del iris es más estable con la postura y mide directamente cuánto del iris tapa el párpado.

**Datos.** Desarrollo: 19 sesiones grabadas propias (postura) y las 9 grabaciones con parpadeos anotados (8 de
Eyeblink8 y la piloto propia). Señales reextraídas con la misma configuración de MediaPipe.

**Criterio (fijado antes de extraer).**
- C1 (postura, sesiones propias): mediana del |cierre aparente| en los tramos de |cabeceo| de 10-15°, 15-20° y
  20-30° al menos un 50 % menor que con la apertura actual (normalizada por la IPD), en el total de cuadros de esos
  tramos.
- C2 (parpadeos, simulador con la configuración E5): F1 en las 9 grabaciones anotadas no menor que el actual menos
  0,01. Se informa la sesión piloto por separado.
- Se adopta si cumple C1 y C2. El grado de cierre (PERCLOS, micro-sueño) se recalibraría con la nueva señal; su
  validación queda para DROZY.

Detalles fijados antes de ver los resultados: el diámetro vertical del iris es el par de puntos con mayor componente
vertical (mediana de la sesión) y se suaviza por ojo con la misma media móvil que la IPD (0,2).

**Resultado.** Control: la apertura/IPD recalculada difiere un 2,1 % (mediana) de la traza.
- C1: mediana del |cierre aparente| con cabeceo de 10-30° (1 462 cuadros, sesiones propias): IPD 0,258; iris 0,307.
  **No cumple**: el iris no corrige el efecto de la postura, incluso lo aumenta. Es coherente con E1: en estas
  sesiones el efecto parece deberse al párpado que acompaña a la mirada, no a la proyección.
- C2: F1 de parpadeos en las 9 grabaciones (configuración E5): IPD 0,950 (371/21/18); iris 0,956 (372/17/17).
  Cumple.
- Piloto propio (no decide): FP de 5 a 2. Desaparecen los 3 parpadeos prolongados falsos al inclinar la cabeza.

**Decisión.** NO SE ADOPTA (no cumple C1). Hipótesis nueva, posterior a ver estos datos (E7b): usar la señal del iris
solo para detectar parpadeos, manteniendo la de la IPD para el grado de cierre. Debe probarse en datos no vistos
(DROZY u otro conjunto), no en estos.

---

## E8 — Estado «ojo cerrado» de PERCLOS contra la anotación cuadro a cuadro de Eyeblink8 (criterio fijado el 2026-11-16, antes de calcular)

**Motivación.** PERCLOS no se había validado: DROZY no se pudo descargar. Eyeblink8 marca, en cada cuadro y para cada
ojo, si está totalmente cerrado (columnas LE_FC y RE_FC, valor «C»). Es una referencia humana del mismo estado que
cuenta PERCLOS, aunque en personas alertas (solo parpadeos).

**Hipótesis.** El estado por cuadro que suma PERCLOS (grado de cierre ≥ 0,80) coincide con la anotación humana:
detecta los cuadros con los dos ojos totalmente cerrados y no marca cuadros con el ojo abierto. En consecuencia, el
PERCLOS por minuto del sistema queda entre el de los cuadros totalmente cerrados y el de todos los cuadros de parpadeo.

**Datos.** Las 8 sesiones de Eyeblink8 ya procesadas (traza por cuadro, versión 1.0.0 con E2; la apertura y el ojo
abierto de la calibración no cambian con E5 ni con C1). Cuadros de la fase de monitoreo con postura válida (los que
cuenta PERCLOS), anotados y con los dos ojos visibles. Sin volver a pasar MediaPipe.

**Nivel de ojo cerrado.** Eyeblink8 no tiene el paso de cerrar los ojos de la calibración, así que se fija así:
- Principal (decide): validación dejando un video fuera. Proporción ojo cerrado / ojo abierto = mediana, en los otros 7
  videos, de (mediana de la apertura en sus cuadros con los dos ojos cerrados) / (ojo abierto de su calibración). Se
  aplica al ojo abierto de la calibración del video apartado. No usa la anotación del video que se evalúa.
- Secundario (no decide): valor de reserva del sistema, 0,25 × ojo abierto.
- Techo (no decide, circular): la misma proporción medida en el propio video.

**Referencia por cuadro.** Positivo: los dos ojos «C». Negativo: fuera de todo parpadeo anotado y a más de 2 cuadros de
uno. Intermedio (no entra en sensibilidad ni en falsos positivos): cuadros de parpadeo sin los dos ojos «C» y los 2
cuadros alrededor de cada parpadeo, porque un cierre ≥ 80 % sin llegar al 100 % es correcto o no según el párpado.

**Criterio (con el nivel principal).**
- C1: sensibilidad (positivos con cierre ≥ 0,80) ≥ 0,80, sumando los 8 videos.
- C2: falsos positivos (negativos con cierre ≥ 0,80) ≤ 1 %, sumando los 8 videos.
- C3: ventanas de 60 s sin solapamiento desde el inicio del monitoreo, con ≥ 54 s de cuadros evaluables (la misma
  exigencia que la alerta): el PERCLOS del sistema queda dentro de [PERCLOS de los cuadros totalmente cerrados − 1 punto,
  PERCLOS de todos los cuadros de parpadeo + 1 punto] en al menos el 90 % de las ventanas.
- Se considera validado el estado por cuadro si cumple C1, C2 y C3. Se informan además el sesgo y los límites de
  acuerdo de Bland-Altman del PERCLOS por ventana frente a la referencia de ojos totalmente cerrados, y (solo como
  diagnóstico) la sensibilidad con desfases de −3 a +3 cuadros.

**Alcance.** Valida la medida de cierre por cuadro y su suma en personas alertas (PERCLOS bajos, del orden de pocos
puntos). No valida el PERCLOS con somnolencia real (cierres lentos, párpado caído) ni los umbrales de 8 % y 12 %.

**Resultado.** 62 179 cuadros evaluables: 1 440 positivos, 57 830 negativos y 2 909 intermedios. La sensibilidad por
desfase es máxima en 0 cuadros (0,88 frente a 0,75 con ±1), así que traza y anotación están alineadas.
- Nivel principal (proporción de los otros 7 videos: 0,285 o 0,304):
  - C1: sensibilidad 0,878 (IC 95 % 0,861-0,894; 1 265/1 440). **Cumple.**
  - C2: falsos positivos 0,06 % (IC 95 % 0,04-0,09 %; 36/57 830). **Cumple.**
  - C3: 24 de 24 ventanas dentro del intervalo. **Cumple.** Bland-Altman frente a los cuadros totalmente cerrados: sesgo
    +0,08 puntos, límites de acuerdo −0,87 a +1,03 puntos. PERCLOS de referencia por ventana entre 0,06 % y 6,48 %
    (mediana 1,68 %). Las 24 ventanas vienen de 7 videos: el 3 no tiene ninguna con 54 s evaluables y el 11 aporta una.
  - Intermedios con cierre ≥ 0,80: 116 de 2 909.
- Por video, la sensibilidad baja en el 11 (con gafas): 0,45. Su proporción propia es 0,435, frente a 0,23-0,34 en los
  demás. Con su propia proporción (techo) sube a 0,94. Los videos 3 y 4 quedan cerca de 0,7 incluso con el techo: en
  algunos cuadros que la persona anotó como cerrados la malla no llega al cierre completo.
- Reserva 0,25 (no decide): sensibilidad 0,835, falsos positivos 0,04 %, 23/24 ventanas, sesgo −0,07 puntos. En el
  video 11 la sensibilidad es 0,23.
- Techo circular (no decide): sensibilidad 0,913, falsos positivos 0,07 %, 24/24 ventanas, límites −0,51 a +0,82 puntos.

**Decisión.** SE VALIDA el estado por cuadro de PERCLOS en personas alertas: con un nivel de ojo cerrado razonable,
detecta casi 9 de cada 10 cuadros con los ojos totalmente cerrados, casi no marca cuadros abiertos y el PERCLOS por
minuto difiere de la referencia en menos de ±1 punto. Dos límites:
- C3 resultó poco exigente con PERCLOS tan bajos: si la referencia es menor de 1 %, el límite inferior es negativo. El
  dato informativo es el de Bland-Altman.
- El caso con gafas muestra que una proporción general no sirve para todas las personas. Respalda C1 y que el sistema
  avise «ojo cerrado no medido» en lugar de usar la reserva.

Queda por validar PERCLOS en somnolencia real y alrededor de los umbrales: videos propios con cierres largos anotados
o un conjunto con PERCLOS alto.

**Comprobación de la implementación.** `evaluar.py` incorpora esta comparación (tramos O de la guía, versión 2). Con
los tramos O sacados de Eyeblink8 y el cierre de la traza tal como se grabó, da los mismos conteos que un cálculo
independiente en los 8 videos: 1 440 positivos, 57 830 negativos, 2 909 intermedios; 1 214, 21 y 97 de ellos con
cierre ≥ 0,80.

---

## E9 — PERCLOS con cierres voluntarios largos y trampas, en videos propios (criterio fijado el 2026-11-16, antes de grabar)

**Motivación.** E8 valida el estado por cuadro con PERCLOS bajos (personas alertas, solo parpadeos). Falta probarlo
cerca de los umbrales de alerta (8 % y 12 %), con cierres largos y con situaciones que pueden engañarlo: mirar hacia
abajo, entrecerrar los ojos y girar la cabeza.

**Hipótesis.** Con el nivel de ojo cerrado medido en la calibración, el estado por cuadro (cierre ≥ 0,80) y el
PERCLOS por minuto coinciden con la anotación O también con cierres largos y con las trampas.

**Datos.** Dos videos de la misma persona con el guion `docs/guion_perclos.md` (sin gafas y con gafas), grabados con
`--grabar` y la versión del sistema del commit en que se graben. Referencia: anotación en modo ciego con B, M, X y O
(guía, versión 2). Si la calibración de un video no mide el ojo cerrado (`ojo_cerrado_medido` falso), se repite la
grabación: es un fallo de protocolo, no un resultado. La guía de voz (`grabar_perclos.py`) se añadió antes de grabar.
Sincroniza el guion con el inicio del conteo y no cambia ni el guion ni el criterio.

**Criterio (sumando los dos videos, con `evaluar.py`).**
- C1: sensibilidad por cuadro ≥ 0,80.
- C2: falsos positivos por cuadro ≤ 1 %.
- C3: al menos el 90 % de las ventanas de 60 s válidas dentro de [O − 1, B/M/O + 1] puntos.
- C4: límites de acuerdo de Bland-Altman del PERCLOS por ventana (sistema − O) dentro de ±2 puntos, la histéresis de
  la alerta (`HYSTERESIS_PCT`): con ese error un minuto no salta más de un nivel cerca de los umbrales.
- Se valida si cumple C1 a C4.
- Se informan sin que decidan: el nivel de alerta de cada ventana según el sistema y según O (normal < 8 %,
  precaución 8-12 %, somnolencia ≥ 12 %); el PERCLOS del minuto de trampas (3-4); los resultados por video; y la
  kappa por cuadro de O si hay un segundo anotador.

**Alcance.** Cierres voluntarios de una persona y unas 10 ventanas: valida la medida de PERCLOS cerca de los
umbrales, no que esos umbrales detecten la somnolencia real.

**Cambio de protocolo antes de grabar (2026-11-16).** La persona que graba pidió videos más cortos: 6 minutos era
demasiado. Pidió también una voz más activa. Todavía no se había grabado nada.
- El guion pasa a 4 minutos, uno por nivel de alerta: normal con trampas (~1-3 %), precaución (~8-10 %),
  somnolencia (~14-16 %) y somnolencia alta (~18-21 %).
- Las trampas que pueden sacar la postura de rango (mirar el celular, girar) se reparten, como mucho 3 s por
  minuto, para que todas las ventanas conserven los 54 s válidos.
- La voz guía también la calibración, anuncia cada cierre con cuenta regresiva y guarda lo que dijo en
  `guia_voz.csv`.
- C1 a C4 no cambian. Con dos videos quedan 8 ventanas: el 90 % de C3 exige entonces las 8.
- En lugar del «PERCLOS del minuto de trampas» se informan los falsos positivos por cuadro durante las trampas
  (tramos de `guia_voz.csv`).
- Hubo una grabación de prueba con el guion de 6 minutos (`sin_gafas`, sesión 20261116_192312, commit e26c380),
  detenida a los 3 minutos. Fue la que motivó el cambio. Se descarta: no se anota ni se analiza.
- Un intento con gafas no llegó a grabar (0 cuadros). La aplicación Eyeblink, que arranca con Windows, tenía la
  cámara. Se borró esa sesión vacía. Desde ahí, con la cámara en vivo, una lectura fallida ya no termina la
  sesión: se reintenta hasta 10 s (`CAMERA_STALL_S`). Eso no cambia ninguna medida: el golden master sigue
  idéntico.

## E10 — Cámara a un costado (criterio fijado el 2026-11-16, antes de grabar)

**Motivación.** En un PC la cámara no siempre está de frente: una cámara USB al lado del monitor, o un portátil
puesto de lado. El rango de postura válida (10° arriba o abajo, 40° a los lados) se mide respecto a la postura de
la calibración, no respecto a la cámara (`fatigue_pose.py`; lo comprueba `tests/test_fatigue_pose.py`). Por eso un
ángulo fijo de la cámara no invalida la postura. Lo que no se ha medido es si la apertura del ojo sigue siendo
fiable con la cara vista de lado:
- el ojo lejano se ve oblicuo;
- la malla de MediaPipe es menos precisa;
- la apertura es la media de los dos ojos.

**Hipótesis.** Con la calibración hecha en la postura de trabajo, el estado de ojo cerrado y el PERCLOS por minuto
cumplen los criterios de E9 con la cámara a unos 30° y a unos 45° de la dirección en que mira la persona.

**Datos.**
- Dos videos de la misma persona, sin gafas, con el guion de 4 minutos (`grabar_perclos.py`):
  - `lateral_30`: cámara a un costado;
  - `lateral_45`: cámara al otro costado.
- Referencia de cámara de frente: el video `sin_gafas` de E9.
- Ángulo real: `camara_yaw_grados` del resumen de la sesión. Es el giro de la cara respecto a la cámara en la
  calibración. Es aproximado, porque la profundidad de MediaPipe es estimada. En tres videos propios con la cámara
  de frente dio entre −1 y −4°.
- Anotación ciega igual que en E9.
- Si la calibración no mide el ojo cerrado, se repite una vez. Si vuelve a fallar, es un resultado: el sistema no
  es utilizable a ese ángulo.

**Criterio (por video, con `evaluar.py`).**
- Un ángulo es utilizable si su video cumple C1 a C4 de E9: sensibilidad ≥ 0,80; falsos positivos ≤ 1 %; las 4
  ventanas dentro de [O − 1, B/M/O + 1]; límites de Bland-Altman dentro de ±2 puntos.
- Se informan sin que decidan, junto al video de frente:
  - el ángulo medido;
  - el porcentaje de tiempo con postura válida;
  - sensibilidad y precisión de parpadeos;
  - la proporción de ojo cerrado de la calibración;
  - la apertura de cada ojo por separado (traza), para ver si el ojo lejano se degrada.

**Variante, solo si un ángulo no cumple.** Usar solo el ojo cercano a la cámara cuando |`camara_yaw_grados`| ≥ 20°.
El ojo cercano es el de mayor ancho aparente en la calibración.
- Se compara en el mismo video, reanalizando `grabacion.mp4` sin conexión con las mismas marcas de calibración, la
  versión actual contra la variante.
- Se adopta si con ella ese video cumple C1 a C4.
- Con la cámara de frente no se activa, así que E9 no cambia.

**Alcance.** Una persona y un video por ángulo, con cierres voluntarios. Indica hasta qué ángulo se puede confiar en
la medida; no lo demuestra para cualquier persona, cámara o luz.

**Guion v3 (2026-11-16, después del video con gafas).**
- Por qué cambia: a la persona que grabó, el comienzo le pareció poco claro.
- Qué cambia en el minuto 1: pasa a parpadeos dirigidos, 5 sueltos y 2 series de 3. Son eventos conocidos para
  comprobar el conteo de parpadeos.
- Qué se añade a la voz:
  - recordatorios de cabeza quieta;
  - un aviso de luz antes de abrir el programa.
- Los minutos 2 a 4 no cambian.

**El video con gafas se queda en E9 tal como se grabó** (20261116_195327, guion v2, commit 2923ece).
- Cumplió el protocolo: ojo cerrado medido al tercer intento y guion completo.
- Excluirlo después de ver sus problemas sesgaría el resultado.
- Condiciones que se anotan:
  - luz tenue de frente;
  - reflejos de la pantalla en las gafas que tapaban parte de los ojos;
  - la cabeza bajó entre 10,6 y 12,3° durante 5,6 s (segundos 165-171 del guion), justo al cerrar los ojos.
- Ese hueco dejó la ventana deslizante con 52,4 s válidos (por debajo de 54) entre los segundos 171 y 230. En ese
  tiempo la alerta no podía actuar, aunque el PERCLOS iba del 15 al 18 %.

## E11 — Fracción mínima de datos válidos para la alerta (criterio fijado el 2026-11-16, antes de anotar E9 y E10)

**Motivación.** La alerta exige 54 de los últimos 60 s con postura válida (`MIN_VALID_FRACTION` = 0,90). En el video
con gafas de E9, un cabeceo de 5,6 s la bloqueó durante un minuto entero. En un detector de somnolencia eso es grave:
cabecear es un signo de sueño, y el sistema se queda sin decir nada justo entonces.

**Hipótesis.** Con 45 s válidos (0,75), el PERCLOS de la ventana coincide con la anotación tan bien como con 54 s.

**Datos.**
- Los videos anotados de E9 y E10.
- Ventanas deslizantes de 60 s cada 5 s, con PERCLOS del sistema contra O, como en `evaluar.py`.
- Las ventanas se solapan, así que no son independientes: los límites de acuerdo son descriptivos.

**Criterio.**
- Se baja a 0,75 si:
  - (a) en las ventanas con 45 a 54 s válidos, los límites de Bland-Altman (sistema − O) quedan dentro de ±2 puntos;
  - (b) hay al menos 10 de esas ventanas, de al menos 2 tramos sin postura válida distintos.
- Con menos datos no se decide.
- Se informa además el tiempo de monitoreo sin alerta posible con 0,90 y con 0,75.

**Relación con E1.** Sigue pendiente el experimento controlado que pidió E1: cabeza inclinada a ángulos conocidos.
Solo ese experimento puede decir si el límite de ±10° se puede ampliar.

## E12 — Rango de cabeceo válido para PERCLOS (criterio fijado el 2026-11-16, antes de calcular)

**Motivación.**
- Al revisar UTA-RLDD, la persona que dirige el proyecto vio a muchos participantes «fuera de rango» en posturas
  naturales.
- La regla de ±10° de cabeceo se basó en una sola sesión, y E1 dejó su base marcada como débil.
- En el video con gafas de E9, un cabeceo de 11° bloqueó la alerta un minuto.
- El riesgo de ampliar el rango es el contrario: al mirar hacia abajo, el párpado baja con la mirada y el ojo puede
  parecer cerrado (falso positivo).

**Hipótesis.** Entre 10° y 20-30° de cabeceo, el estado de ojo cerrado (cierre ≥ 0,80) es tan fiable como dentro de
±10°, así que el rango se puede ampliar sin falsear PERCLOS.

**Datos que deciden.**
- Eyeblink8: los 8 videos procesados para E8 (`eval_eyeblink8_v2`), con la anotación por cuadro.
- Las mismas clases que en E8:
  - positivo: los dos ojos totalmente cerrados;
  - negativo: a más de 2 cuadros de un parpadeo;
  - intermedio: excluido.
- El mismo nivel de ojo cerrado que en E8 (principal: la mediana de los otros videos).
- Esta vez entran también los cuadros con la postura fuera de rango.
- Los cuadros se agrupan por |cabeceo| respecto a la calibración: 0-10° (referencia), 10-15°, 15-20°, 20-25° y
  25-30°.
- Solo entran cuadros con |giro| ≤ 40°, el límite actual, para aislar el cabeceo.
- Se excluyen los cuadros con algún ojo no visible.

**Criterio.**
- Se amplía `POSE_MAX_PITCH` al mayor límite L ∈ {15°, 20°, 25°, 30°} tal que cada intervalo entre 10° y L cumpla:
  - falsos positivos por cuadro ≤ 1 %, con al menos 500 negativos;
  - el mismo ≤ 1 % en cada sentido (cabeza arriba y cabeza abajo) que tenga al menos 500 negativos;
  - sensibilidad ≥ 0,80, con al menos 30 positivos.
- Un intervalo sin datos suficientes corta la ampliación ahí.
- Si 10-15° no cumple, se mantiene ±10°.

**Se informan sin que decidan.**
- En UTA-RLDD (24 videos de E4b, posturas naturales de unos 10 minutos):
  - el porcentaje de tiempo fuera de rango, por eje;
  - el porcentaje de tiempo sin alerta posible (ventana con menos de 54 s válidos), con el límite actual y con el
    que resulte.
- La mediana del cabeceo de cada video, para ver si la referencia de la calibración quedó atípica (persona que se
  acomoda después de calibrar).

**Alcance.**
- Eyeblink8 son 4 personas alertas frente a un portátil.
- Dice si la medida del ojo cerrado aguanta esos ángulos, no cómo se comporta un cabeceo de sueño real.

**Resultado (2026-11-16).** Script `e12_cabeceo.py`, fuera del repositorio. El intervalo de 0-10° reproduce E8:
sensibilidad 0,878 y falsos positivos 0,06 %.

| \|Cabeceo\| | Sentido | Positivos | Sensibilidad | Negativos | Falsos positivos |
|---|---|---|---|---|---|
| 0-10° | ambos | 1440 | 0,878 | 57 830 | 0,06 % |
| 10-15° | ambos | 126 | 0,873 | 3940 | 0,48 % |
| 10-15° | arriba | 126 | 0,873 | 3912 | 0,08 % |
| 10-15° | abajo | 0 | — | 28 | 57 % (16 de 28) |
| 15-20° | ambos | 33 | 0,788 | 661 | 2,12 % |
| 15-20° | arriba | 28 | 0,750 | 655 | 1,22 % |
| 15-20° | abajo | 5 | — | 6 | 6 de 6 |
| 20-25° | arriba | 29 | 0,897 | 294 | 0 % |
| 25-30° | arriba | 0 | — | 45 | 6,7 % |

- Pitch positivo = cabeza hacia abajo. Se comprobó con la geometría de `face_axes` y con el cabeceo del video con
  gafas de E9 (+12°).
- Criterio: 10-15° cumple (falsos positivos 0,48 %, sensibilidad 0,873). 15-20° no (2,12 % y 0,788). **El límite
  que da el criterio es ±15°.**
- Pero la salvaguarda por sentido solo se aplicaba con 500 negativos o más, y hacia abajo hay 28. En esos 28, el
  57 % son cierres falsos. Es el riesgo que se temía: el párpado baja con la mirada. Apunta en el mismo sentido que
  la sesión que motivó la regla (E1) y que los parpadeos prolongados falsos al inclinar la cabeza en el piloto de E5.
- UTA-RLDD (23 videos): alerta disponible (ventana con ≥ 54 s válidos) según el límite.

  | Límite | Media | Mediana | Videos con menos del 50 % |
  |---|---|---|---|
  | ±10° (antes) | 64,0 % | 75,2 % | 9 de 23 |
  | abajo 10°, arriba 15° | 79,2 % | 100 % | 5 de 23 |
  | ±15° | 88,7 % | 100 % | 3 de 23 |

  El giro casi nunca saca de rango: 0 % en 22 videos y 2 % en uno. Lo que saca de rango es el cabeceo.
- En siete videos, toda la sesión queda desplazada entre 10° y 14° respecto a la calibración (mediana del cabeceo):
  la persona se acomodó después de calibrar. Son las «posturas naturales fuera de rango» que se vieron al revisar:
  - hacia abajo: 02_0 (+12,8°), 02_10 (+10,7°), 04_10 (+10,0°);
  - hacia arriba: 04_0 (−11,8°), 05_10 (−14,1°), 31_10 (−9,5°), 35_10 (−10,8°).

**Decisión.** Se amplía solo hacia arriba: `POSE_MAX_PITCH_UP` = 15° y `POSE_MAX_PITCH_DOWN` = 10°.
- Es una desviación conservadora del criterio, decidida después de ver los datos. Adopta la parte con evidencia
  (3912 cuadros) y no la que tiene evidencia en contra, aunque sea escasa.
- Golden master: en un video de referencia, el tiempo fuera de rango baja de 1,47 a 0,53 s y el PERCLOS final pasa
  de 2,67 a 2,60 %. Las pruebas cubren el límite asimétrico.

**Pendiente.**
- (1) Hacia abajo: hace falta el experimento controlado que pidió E1, con la cabeza inclinada hacia abajo a ángulos
  conocidos, ojos abiertos, parpadeos y cierres.
- (2) Los videos desplazados hacia abajo (02_0, 02_10, 04_10) siguen casi sin alerta. Lo de fondo no es el ancho del
  rango, sino que la referencia de la calibración deja de representar la postura de trabajo. Hipótesis para E13:
  rehacer la referencia, y la apertura del ojo abierto, cuando la postura cambia de forma sostenida.
- Versiones dentro de E9 y E10: el video con gafas se grabó con la regla anterior (commit 2923ece). Los que faltan se
  graban con esta. El commit queda en los metadatos de cada sesión y los resultados se informan por video.

**Guion v3.1 (2026-11-16, antes de grabar los videos que faltan).** A propuesta de la persona que graba, se añade un
parpadeo pedido («Parpadea») en cuatro momentos: con la cabeza girada a cada lado (minutos 1 y 2; el giro pasa de
3 a 4 s) y mirando a cada lado solo con los ojos (minuto 3). Son eventos conocidos para comprobar el conteo de
parpadeos con la cabeza girada y con la mirada lateral (otro monitor). Se informa cuántos de esos parpadeos cuenta
el sistema (tramos de `guia_voz.csv`); no decide nada. Lo que puede sacar la postura de rango sigue por debajo de 6 s
por minuto: como mucho 4 s.

**Grabaciones de E9 y E10 (2026-11-16).**

| Sesión | Condición | Commit | Guion | Estado |
|---|---|---|---|---|
| 20261116_195327 | con gafas | 2923ece | v2 | completa (E9) |
| 20261116_202506 | sin gafas | 9ce8076 | v3 | interrumpida a los 82 s del guion: se descarta por incompleta |
| 20261116_202655 | sin gafas | 9ce8076 | v3 (sin los parpadeos mirando a los lados de v3.1) | completa (E9) |
| 20261116_205255 | lateral 30° | e1cc6f3 | v3.1 | completa (E10); cámara colocada a 30,7° |

Observación del video lateral de 30°, después del guion: al mirar directo a la cámara (giro de unos 32°), la cabeza
salió 10-13° «hacia abajo» y quedó fuera de rango por el límite de 10° hacia abajo. El cierre medido fue de unos 0,
sin cierres falsos. Para la persona que grabó, que eso salga fuera de rango es un error.

Diagnóstico, que no decide nada:
- Se reprocesó el video calculando los ángulos en el marco de la cabeza en lugar del de la cámara. El acoplamiento
  entre cabeceo y giro no cambió (pendiente −0,22 en los dos marcos), así que no es un error del marco de
  referencia.
- Con la cámara de frente también aparece: en los videos sin gafas y con gafas, girar unos 35° a la derecha da 7-9°
  de cabeceo «hacia arriba».
- No se puede saber si es movimiento real de la cabeza o un sesgo de la estimación de MediaPipe en giros grandes.

## E13 — Cabeza hacia abajo y mirada hacia abajo con verdad de terreno (criterio fijado el 2026-11-16, antes de grabar)

**Motivación.**
- E12 no pudo decidir el límite hacia abajo: había 28 cuadros en Eyeblink8.
- Mirar directo a una cámara de costado dio 10-13° hacia abajo y quedó fuera de rango (lateral de 30°).
- El riesgo conocido sigue: al bajar la mirada el párpado baja y el ojo parece cerrado.

**Hipótesis.**
- (a) Con la cabeza 10-20° hacia abajo, el estado de ojo cerrado sigue siendo fiable, y el límite de 10° se puede
  ampliar.
- (b) Si hay cierres falsos, se deben a la mirada hacia abajo y no a la inclinación de la cabeza. Se ve en el bloque
  «solo los ojos hacia abajo».

**Datos.**
- Un video guiado de S01 (`grabar_perclos.py --condicion postura`, 3 minutos), con la cámara de frente y sin gafas.
- Seis posturas de 30 s; en cada una, unos 20 s con los ojos abiertos, 2 parpadeos pedidos y un cierre de 2 s:
  - pantalla (referencia);
  - cabeza un poco abajo (teclado);
  - cabeza más abajo (celular en la mesa);
  - solo los ojos abajo;
  - cabeza un poco arriba;
  - directo a la cámara.
- Anotación ciega con B, M, O y X (guía v2).
- Mismas clases que en E8 y E12:
  - positivo: O;
  - negativo: a más de 2 cuadros de cualquier B, M u O;
  - X: excluido.
- Los cuadros se agrupan por el cabeceo que mide el sistema respecto a la calibración, sumados a los cuadros de
  Eyeblink8 de esos intervalos (E12).

**Criterio.**
- `POSE_MAX_PITCH_DOWN` pasa al mayor L ∈ {15°, 20°, 25°, 30°} tal que cada intervalo hacia abajo entre 10° y L
  cumpla:
  - falsos positivos por cuadro ≤ 1 %, con al menos 500 negativos;
  - sensibilidad ≥ 0,80, con al menos 30 positivos.
- Lo mismo hacia arriba por encima de 15° (`POSE_MAX_PITCH_UP`).
- Un intervalo sin datos suficientes corta la ampliación ahí.

**Se informan sin que decidan.**
- Falsos positivos, sensibilidad y cabeceo mediano de cada bloque.
- Los parpadeos contados por bloque.
- Si el bloque «solo los ojos abajo» (cabeza a unos 0°) da más del 1 % de falsos positivos. En ese caso, la causa
  es la mirada y un límite de cabeceo no la evita. Quedaría motivado otro experimento: validar la postura por la
  posición vertical del iris.

**Alcance.** Una persona, posturas voluntarias y ángulos medidos por el propio sistema (aproximados).

**Renumeración.** La idea de rehacer la referencia cuando la postura cambia de forma sostenida (pendiente de E12)
pasa a llamarse E14.

**E10, intentos a 45° (2026-11-16).**

| Sesión | Cámara colocada | Qué pasó |
|---|---|---|
| 20261116_211249 | 49,2° | El paso 1 (postura estable) no terminó en 25 s y la persona lo detuvo. La malla tiembla a ese ángulo y la puerta de estabilidad casi nunca llega a 15 cuadros seguidos. |
| 20261116_211427 | 47,0° (−41,9° en la calibración) | El ojo cerrado no se midió en los 3 intentos del programa y usó la reserva. Detenida a los 49 s. |

Con los ojos cerrados, la apertura medida baja menos cuanto más de lado está la cámara. Valor mínimo durante el paso
de ojos cerrados, sobre la apertura normal:

| Video | Ángulo | Mínimo |
|---|---|---|
| sin gafas | −1,6° | 0,11 |
| lateral | 30,7° | 0,41 |
| con gafas | 2,4° | 0,53 |
| lateral | −41,9° | 0,60 |

La captura exige bajar de 0,6 durante 0,5 s: a 45° el cierre casi no se distingue de un ojo abierto en la malla.

Según el criterio de E10, la grabación a 45° se repite una vez. Si vuelve a fallar, el resultado es que a 45° el
sistema no es utilizable. Para esa repetición, la guía ya no pide pulsar Q cuando falla la medida del ojo cerrado en
los videos de lado: pide seguir con el guion. Así queda el video completo para probar sin conexión la variante
pre-registrada en E10 (usar solo el ojo cercano), con calibración manual por marcas.
