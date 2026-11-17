# Guion de grabación para validar PERCLOS (E9) y la cámara de lado (E10)

Sirve para grabar videos de 4 minutos con PERCLOS de 0 % a ~20 % por minuto. Así se prueba el sistema en los tres
niveles de alerta (normal < 8 %, precaución 8-12 %, somnolencia ≥ 12 %) y en situaciones que pueden engañarlo. Los
cierres son **voluntarios**: validan la medida del cierre, no la somnolencia real.

## Qué videos grabar

Los cuatro con la misma persona, el mismo día y la misma luz:

| Video | `--condicion` | Cámara | Experimento |
|---|---|---|---|
| 1 | `sin_gafas` | de frente | E9 (y referencia de E10) |
| 2 | `con_gafas` | de frente | E9 (ya grabado con el guion v2: sesión 20261116_195327) |
| 3 | `lateral_30` | a un costado, a unos 30° | E10 |
| 4 | `lateral_45` | al otro costado, a unos 45° | E10 |

**Cámara de lado (videos 3 y 4).** Tú miras de frente, como cuando trabajas, y la cámara queda a un costado
apuntando a tu cara. Para poner el ángulo sin transportador, con la cámara a la misma distancia de ti que el punto
al que miras:
- 30°: la cámara corrida hacia el lado algo más de la mitad de esa distancia (a 60 cm, unos 35 cm al lado).
- 45°: la cámara corrida hacia el lado lo mismo que esa distancia (a 60 cm, unos 60 cm al lado).

Con un portátil, ponlo de lado mirando hacia ti y mira de frente a otra pantalla o a un punto fijo, por ejemplo un
papel pegado a la pared a la altura de los ojos. Con una cámara USB o el celular como cámara, muévela tú
(`--fuente 1` si no es la cámara 0). No hace falta exactitud: el
programa mide el ángulo real de la cara respecto a la cámara (`camara_yaw_grados` en el resumen de la sesión).

## Antes de grabar

- Luz normal de oficina, **de frente** (no detrás de ti), a la distancia habitual. Con gafas, baja el brillo de la
  pantalla o inclínala hasta que no se refleje en los lentes: en el video con gafas los reflejos tapaban los ojos.
- No hace falta leer nada. Entre una indicación y otra, mira la pantalla como cuando la usas: la ventana del
  programa o un video sin sonido (el sonido taparía la voz). Parpadea normal, sin forzar ni aguantar.
- El celular a mano, para cuando la voz diga «Mira el celular».
- Con los ojos cerrados, **la cabeza quieta**: bajarla más de 10° deja esos segundos sin datos válidos, y con más
  de 6 s así el minuto se queda sin los 54 s que exige la alerta («Reuniendo datos 52 de 54 s»).
- **Guía de voz** (`grabar_perclos.py`). La voz te guía la calibración y, cuando el programa empieza a medir, cada
  paso del guion. Antes de cada cierre hace una cuenta regresiva («Tres, dos, uno, cierra») y en los cierres largos
  dice «Aguanta». Así cada minuto del guion coincide con una ventana de 60 s de PERCLOS y no hace falta una segunda
  persona con cronómetro. Comandos (PowerShell, en la carpeta del proyecto):

  ```
  .\venv\Scripts\python.exe grabar_perclos.py --probar-voz
  .\venv\Scripts\python.exe grabar_perclos.py --sujeto S01 --condicion sin_gafas
  ```

  El primero solo prueba la voz y el volumen. El segundo graba un video; cambia `--condicion` en cada uno.
  - La guía usa `--grabar --sin-sonido`. `--sin-sonido` silencia las alertas de fatiga, para que su pitido no
    provoque parpadeos ni sustos.
  - El pitido de la calibración sí suena: cuando pida cerrar los ojos, mantenlos cerrados hasta oírlo.
  - Lo que dijo la voz, y en qué segundo, queda en `guia_voz.csv` dentro de la sesión.
- Si la voz o la consola dicen que **no se midió el ojo cerrado** (RESERVA), pulsa Q y vuelve a empezar:
  - E9 no acepta esa grabación.
  - En E10 se repite una vez. Si vuelve a pasar, ese es el resultado: a ese ángulo no se puede usar.
- Al oír «¡Listo, terminaste!», pulsa Q en la ventana del programa.
- Sin voz en español instalada, una segunda persona lee el guion en voz alta con un cronómetro, que arranca cuando
  el programa empieza a medir.

## Guion (4 bloques de 1 minuto)

| Minuto | Qué hace la persona | PERCLOS esperado |
|---|---|---|
| 0-1 | Parpadeos dirigidos: «Haz un parpadeo» (5 veces) y «Tres parpadeos seguidos» (2 veces). Trampas: entrecerrar los ojos 5 s (con la pupila visible) y girar un poco a la izquierda 3 s. | ~2-4 % (normal) |
| 1-2 | 3 cierres de 1,5 s, 3 parpadeos lentos y girar un poco a la derecha 3 s. | ~8-10 % (precaución) |
| 2-3 | 4 cierres de 2 s. Trampas: mirar el celular 3 s y entrecerrar los ojos 4 s. | ~14-16 % (somnolencia) |
| 3-4 | 2 cierres de 4 s y 1 de 3 s. | ~18-21 % (somnolencia) |

- Mirar el celular y los giros pueden sacar la postura de rango. Por eso van repartidos, como mucho 3 s por minuto:
  cada ventana conserva los 54 s válidos que exige PERCLOS.
- Los segundos exactos de cada paso están en `SCRIPT`, en `grabar_perclos.py`.
- No hace falta exactitud al segundo: lo que cuenta es lo que se anota después, no el guion.

## Después de grabar

1. **Anotar** cada video en modo ciego (`docs/guia_anotacion.md`):

   ```
   .\venv\Scripts\python.exe revisar.py "sesiones\<sesión>" --ciego
   ```

   - Primera pasada: B (parpadeos), M (cierres de 1 s o más), Y/K si hay bostezos y X si algo tapa los ojos.
   - Segunda pasada: O (los dos ojos con la pupila totalmente tapada) dentro de cada B y M, cuadro a cuadro.
   - Tiempo aproximado: 40 a 60 minutos por video de 4 minutos.
   - Si se puede, otra persona anota uno de los videos con `--anotador "Nombre"` (acuerdo entre anotadores).
2. **Evaluar**:

   ```
   .\venv\Scripts\python.exe evaluar.py "sesiones\<sesión 1>" "sesiones\<sesión 2>"
   ```

   Muestra los parpadeos, los cierres largos y el bloque de PERCLOS: sensibilidad, falsos positivos y acuerdo por
   minuto. Los criterios de E9 y E10 están fijados en `docs/registro_experimentos.md` antes de grabar.
