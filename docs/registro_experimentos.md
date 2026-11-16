# Registro de experimentos sobre el método

Cada cambio propuesto al método queda aquí con su hipótesis, el criterio fijado antes de probar, los datos, el
resultado (aunque sea negativo) y la decisión (guía de anotación, sección 7).

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
