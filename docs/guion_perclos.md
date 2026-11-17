# Guion de grabación para validar PERCLOS (E9)

Sirve para grabar videos con PERCLOS de 0 % a ~20 % por minuto. Así se prueba el sistema cerca de los umbrales
de alerta (8 % y 12 %) y en situaciones que pueden engañarlo. Los cierres son **voluntarios**: validan la
medida del cierre, no la somnolencia real.

## Antes de grabar

- Dos videos de la misma persona: uno **sin gafas** y otro **con gafas** (en E8, las gafas cambiaron mucho el
  nivel de ojo cerrado).
- Luz normal de oficina, cara de frente a la cámara, a la distancia habitual.
- Al lado de la ventana del programa, un texto abierto para leer (los minutos «normales») y el celular a mano
  (minuto de trampas).
- **Guía de voz** (`grabar_perclos.py`): abre el programa y, cuando termina la calibración y empieza a medir, una
  voz de Windows dice cada paso del guion («Cierra», «Abre», «Mira el celular»…). Así cada minuto del guion coincide
  con una ventana de 60 s de PERCLOS y no hace falta una segunda persona con cronómetro. Comandos (PowerShell, en la
  carpeta del proyecto):

  ```
  .\venv\Scripts\python.exe grabar_perclos.py --probar-voz
  .\venv\Scripts\python.exe grabar_perclos.py --sujeto S01 --condicion sin_gafas
  .\venv\Scripts\python.exe grabar_perclos.py --sujeto S01 --condicion con_gafas
  ```

  El primero solo prueba la voz y el volumen. Los otros graban cada video con `--grabar --sin-sonido`.
  `--sin-sonido` silencia las alertas de fatiga, para que su pitido no provoque parpadeos ni sustos. El pitido de la
  calibración sí suena: cuando el programa pida cerrar los ojos, mantenlos cerrados hasta oírlo.
- Si la consola dice que el ojo cerrado se tomó de la **RESERVA (no medido)**, pulsa Q y vuelve a empezar: E9 no
  acepta esa grabación. Al oír «Fin del guion», pulsa Q en la ventana del programa.
- Sin voz en español instalada, una segunda persona lee el guion en voz alta con un cronómetro, que arranca cuando
  el programa empieza a medir.

## Guion (6 bloques de 1 minuto)

| Minuto | Qué hace la persona | PERCLOS esperado |
|---|---|---|
| 0-1 | Normal: mira la pantalla y lee un texto, parpadea como siempre. | ~1-3 % |
| 1-2 | Normal, más 4 parpadeos lentos (~0,5 s) y 2 cierres de 1,5 s (en los segundos 20 y 45). | ~7-10 % |
| 2-3 | 4 cierres de 2 s (en los segundos 10, 25, 40 y 55). | ~14-16 % |
| 3-4 | Sin cierres. Trampas: mira el teclado o el celular 3 veces 5 s, entrecierra los ojos (pupila visible) 2 veces 5 s y gira la cabeza a cada lado. | ~1-3 % |
| 4-5 | 2 cierres de 4 s (segundos 10 y 35) y 1 de 2 s (segundo 50). | ~17-20 % |
| 5-6 | Normal otra vez. | ~1-3 % |

La voz (o la persona que lee) dice «cierra» y «abre». Los segundos exactos de cada paso están en `SCRIPT`, en
`grabar_perclos.py`. No hace falta exactitud al segundo: lo que cuenta es lo que se anota después, no el guion.

## Después de grabar

1. **Anotar** cada video en modo ciego (`docs/guia_anotacion.md`):

   ```
   .\venv\Scripts\python.exe revisar.py "sesiones\<sesión>" --ciego
   ```

   - Primera pasada: B (parpadeos), M (cierres de 1 s o más), Y/K si hay bostezos y X si algo tapa los ojos.
   - Segunda pasada: O (los dos ojos con la pupila totalmente tapada) dentro de cada B y M, cuadro a cuadro.
   - Tiempo aproximado: 1 a 1,5 horas por video de 6 minutos.
   - Si se puede, otra persona anota uno de los dos videos con `--anotador "Nombre"` (acuerdo entre anotadores).
2. **Evaluar**:

   ```
   .\venv\Scripts\python.exe evaluar.py "sesiones\<sesión 1>" "sesiones\<sesión 2>"
   ```

   Muestra los parpadeos, los cierres largos y el bloque de PERCLOS (sensibilidad, falsos positivos y acuerdo por
   minuto). El criterio para dar PERCLOS por validado está fijado en E9 (`docs/registro_experimentos.md`) antes de
   grabar.
