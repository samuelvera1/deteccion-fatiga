# Guía de anotación y plan de evaluación

**Versión 1 — 2026-10-09 (borrador).** Si cambia alguna definición, la guía pasa a una versión nueva y se
registra en el historial de git. Las anotaciones hechas con una versión anterior solo se comparan con las
nuevas si la definición del evento no cambió.

Esta guía fija **antes de ver resultados** qué cuenta como cada evento, cómo se anota y cómo se compara
con el sistema. Las decisiones marcadas como *borrador* están pendientes de confirmar con el director.

---

## 1. Para qué sirve la anotación

La referencia para evaluar el sistema son las anotaciones humanas hechas con `revisar.py` **en modo
ciego**, es decir, sin ver lo que detectó el sistema. Si se anota viendo al sistema, la anotación se deja
influir y la evaluación queda sesgada.

| Uso | Comando | Archivo |
|---|---|---|
| **Referencia** (para la evaluación) | `python revisar.py "sesiones\<sesión>" --ciego` | `anotaciones_ciego.csv` |
| Revisión (buscar errores, ver al sistema) | `python revisar.py "sesiones\<sesión>"` | `anotaciones_revision.csv` |
| Segundo anotador (acuerdo, sección 5) | `python revisar.py "sesiones\<sesión>" --ciego --anotador "Nombre"` | `anotaciones_ciego_Nombre.csv` |

Cada anotación guarda si se hizo en modo ciego (columna `ciego`). Un mismo archivo nunca mezcla los dos
modos. **Solo `anotaciones_ciego.csv` cuenta como referencia.**

## 2. Reglas generales

1. Lee esta guía antes de anotar y tenla a mano.
2. Anota desde que la persona **abre los ojos después de la calibración** hasta el final del video. Lo
   anterior es calibración: la evaluación lo ignora.
3. Anota **todos** los eventos que veas que cumplan la definición. Si dudas, decide con la definición; no
   anotes "por si acaso".
4. Cada evento es un **intervalo**: su tecla en el inicio y otra vez en el final. Para marcar inicio y fin,
   pausa (ESPACIO) y avanza frame a frame (A / D).
5. Para corregir: **U** borra la última anotación y **E** borra la anotación del frame donde estás.
6. **No cambies la referencia después de ver qué detectó el sistema.** Para mirar errores usa la revisión
   sin `--ciego`, que va a otro archivo.
7. Anota cada video de corrido o en pocas sesiones, sin cambiar de criterio a la mitad.

## 3. Definiciones de los eventos

### B — Parpadeo
- **Qué es:** el párpado superior baja y vuelve a subir en un movimiento rápido, en los dos ojos a la vez.
  Suele durar entre 0,1 y 0,4 s (3 a 12 frames a 30 fps).
- **Se anota:** todo parpadeo en que el párpado superior baje hasta tapar al menos parte de la pupila,
  llegue o no a cerrarse del todo (parpadeos completos e incompletos). *(borrador)*
- **No se anota:**
  - el párpado que baja porque la persona **mira hacia abajo**: acompaña al ojo y se queda abajo mientras
    mira abajo;
  - guiños de un solo ojo;
  - cierres de **1 s o más**: se anotan como M.
- **Inicio:** primer frame en que el párpado superior empieza a bajar.
- **Fin:** primer frame en que el párpado vuelve a la posición abierta que tenía antes.
- **Ráfagas:** cada cierre y reapertura es un parpadeo, aunque el ojo no termine de abrirse entre uno y otro.
- **Parpadeo prolongado:** no tiene tecla. Sale de la duración anotada (corte provisional del sistema: 0,5 s;
  Caffier et al., 2003).

### M — Cierre largo (micro-sueño conductual)
- **Qué es:** ojos cerrados, con la pupila totalmente tapada, sin interrupción durante **1 s o más**. Es el
  criterio conductual de Hertig-Godeschalk et al. (2020), el mismo que usa el sistema.
- **Inicio:** primer frame con la pupila totalmente tapada.
- **Fin:** primer frame en que se vuelve a ver la pupila.
- A diferencia de B, aquí no se marca el movimiento del párpado, sino el tiempo con el ojo cerrado.
- En los videos de desarrollo estos cierres son **voluntarios**: sirven para evaluar la detección de cierres de
  1 s o más, pero no son micro-sueños reales (confirmarlos requiere EEG).

### Y — Bostezo · K — Micro-bostezo
- **Qué es:** apertura involuntaria de la boca con inspiración profunda, una pausa en la máxima apertura y un
  cierre más rápido (Provine, 1986). Suele venir con ojos entrecerrados y, a veces, la cabeza hacia atrás o
  un estiramiento.
- **Y:** la boca se abre claramente; la mandíbula baja de forma visible.
- **K:** bostezo contenido. Mismo patrón (inspiración profunda, mandíbula que intenta bajar, ojos
  entrecerrados), pero con la boca poco abierta o cerrada. *(borrador)*
- **Inicio:** primer frame en que la boca empieza a abrirse como parte del bostezo.
- **Fin:** primer frame en que los labios vuelven a la posición de reposo.
- **Un bostezo es un solo intervalo**, aunque a la mitad la boca baje un poco y se vuelva a abrir.
- **No se anota:** hablar, reír, sonreír, toser, estornudar, comer, cantar.
- Separar Y de K es una apreciación visual. El análisis principal junta los dos; la separación se evalúa
  aparte.

### X — No evaluable (en modo ciego)
- **Qué es:** un tramo en que no se ve lo necesario para anotar:
  - la cara fuera del cuadro;
  - una mano u objeto tapando los ojos o la boca;
  - reflejos de las gafas que no dejan ver los ojos;
  - la persona de perfil completo o de espaldas.
- Al cerrar el tramo, escribe el **motivo**.
- Se decide **solo por lo que se ve en el video**, nunca por lo que hizo el sistema.
- **No son "no evaluables":** cabeza girada o inclinada con la cara visible, hablar, reír o moverse. Son
  situaciones que el sistema debe manejar y se evalúan.
- Si hay un bostezo con la boca tapada, se marca el tramo como X y además se anota el bostezo (Y o K) si se
  reconoce, para saber cuántos eventos quedaron excluidos.

## 4. Plan de evaluación (`evaluar.py`)

- **Clases que se comparan:**

  | Clase | Sistema | Referencia |
  |---|---|---|
  | Parpadeo | `PARPADEO` + `PARPADEO_PROLONGADO` | B |
  | Bostezo | `BOSTEZO` + `MICRO_BOSTEZO` | Y + K |
  | Cierre largo | tramos con ojo cerrado (≥ 80 %) de 1 s o más, desde `traza.csv` | M |

- **Emparejamiento:** uno a uno entre un evento del sistema y uno anotado de la misma clase, si sus intervalos
  se solapan. Tolerancia de ±0,10 s para parpadeos, por la imprecisión de marcar a mano, y 0 para bostezos y
  cierres largos. *(borrador)*
- **Resultado de cada evento:** acierto, falso positivo (del sistema sin pareja) o falso negativo (anotado
  sin pareja).
- **Métricas:** sensibilidad, precisión y F1, con intervalos de confianza del 95 % de Wilson (1927). Se
  reportan por sesión, por persona y en conjunto.
- **Duraciones:** diferencia sistema − referencia en los pares emparejados, con el sesgo y los límites de
  acuerdo de Bland y Altman (1986). Se espera un sesgo, porque el sistema marca el inicio cuando se cruza su
  umbral y la referencia cuando empieza el movimiento.
- **Exclusiones:** los eventos que empiezan antes del inicio del conteo y los que caen en tramos X. Se
  reporta cuántos se excluyen.
- **Análisis principal:** todo el tiempo de conteo menos las exclusiones.
- **Análisis secundario (parpadeos):** solo los tramos con postura válida y la cara detectada.
- **Descartes del sistema:** los parpadeos descartados por giro rápido y los episodios descartados como
  sonrisa se comparan con la referencia. Así se estima cuántos eran eventos reales (pérdidas) y cuántos no
  (aciertos de la regla).
- **Tipo de bostezo:** acuerdo bostezo/micro-bostezo entre sistema y referencia en los pares emparejados.
- **PERCLOS:** no se valida con estas anotaciones. Haría falta anotar frame a frame cuándo el ojo está cerrado
  al menos al 80 %, y queda como tarea aparte.

## 5. Acuerdo entre anotadores

- Otra persona anota los mismos videos de forma independiente: sin ver el sistema ni las otras anotaciones,
  con `--ciego --anotador "Nombre"`.
- Al menos 2 de los videos.
- `python evaluar.py "sesiones\<sesión>" --acuerdo "Nombre"` calcula la kappa de Cohen (1960) frame a
  frame y el F1 por evento entre los dos anotadores. La kappa se interpreta con Landis y Koch (1977).

## 6. Videos de desarrollo y de prueba

- **Desarrollo:** 4 videos de unos 3 minutos con el guion fijo (2 con gafas y 2 sin gafas). Se miran, se
  analizan los errores y se corrige el método.
- **Prueba:** 2 videos (1 con gafas y 1 sin gafas). Se anotan, pero **sus resultados no se miran** hasta que
  el método esté congelado en un commit. Se evalúan una sola vez y se reporta lo que salga.
- Para videos de otras personas en el artículo: consentimiento informado y aval del comité de ética.

## 7. Criterio para aceptar cambios del método

Acordado el 2026-10-09:

- Un cambio en una regla de detección se acepta si en los videos de desarrollo **reduce los falsos positivos
  sin aumentar los falsos negativos**.
- Cada cambio queda registrado con su hipótesis, la evidencia, el criterio, el resultado (aunque sea negativo)
  y el commit.
- Los errores de implementación o de protocolo, en los que el sistema mide algo que por definición no debía
  medir, se corrigen directamente con una prueba que los reproduce y se documentan.

## 8. Decisiones pendientes de confirmar

1. Incluir los parpadeos incompletos en la referencia (sección 3, B).
2. Definición operativa del micro-bostezo (sección 3, K).
3. Tolerancia de emparejamiento de ±0,10 s para parpadeos (sección 4).

## Referencias

- Bland, J. M., y Altman, D. G. (1986). Statistical methods for assessing agreement between two methods of
  clinical measurement. *The Lancet, 327*(8476), 307–310.
- Caffier, P. P., Erdmann, U., y Ullsperger, P. (2003). Experimental evaluation of eye-blink parameters as a
  drowsiness measure. *European Journal of Applied Physiology, 89*(3–4), 319–325.
- Cohen, J. (1960). A coefficient of agreement for nominal scales. *Educational and Psychological
  Measurement, 20*(1), 37–46.
- Hertig-Godeschalk, A., Skorucak, J., Malafeev, A., Achermann, P., Mathis, J., y Schreier, D. R. (2020).
  Microsleep episodes in the borderland between wakefulness and sleep. *Sleep, 43*(1), zsz163.
- Landis, J. R., y Koch, G. G. (1977). The measurement of observer agreement for categorical data.
  *Biometrics, 33*(1), 159–174.
- Provine, R. R. (1986). Yawning as a stereotyped action pattern and releasing stimulus. *Ethology, 72*(2),
  109–122.
- Wilson, E. B. (1927). Probable inference, the law of succession, and statistical inference. *Journal of the
  American Statistical Association, 22*(158), 209–212.
