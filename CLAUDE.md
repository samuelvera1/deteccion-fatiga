# Fatiga Detector — contexto para Claude

Detector de somnolencia por visión computacional (MediaPipe Face Mesh + OpenCV, Python 3.11) para un **artículo
científico y una monografía** (Universidad de la Costa). Autor: S01 en los documentos (código anónimo).

## Reglas de trabajo (las pidió el autor)
- **Responder siempre en español**, en lenguaje claro y directo.
- **No preguntar de más**: decidir con criterio y listar los supuestos al final. Preguntar solo lo que de verdad le
  toca decidir al autor.
- **Rigor de investigación**: todo cambio que afecte una medida necesita hipótesis, criterio fijado ANTES de calcular
  (commit del criterio en `docs/registro_experimentos.md`), prueba en datos y registro del resultado aunque sea
  negativo. Nada ad hoc. Nunca inventar datos ni declarar validaciones que no se hicieron.
- **La anotación de referencia la hace una persona**, no Claude (si no, la máquina se valida con otra máquina).
- **Ahorrar uso**: los análisis corren en el PC con scripts que imprimen resúmenes cortos; no mirar videos ni hojas
  de imágenes salvo que sea imprescindible.
- **Uso real = en vivo, sin voz ni guion**, con comportamiento natural. Las grabaciones guiadas (`grabar_perclos.py`)
  son de validación controlada; no ajustar umbrales solo con ellas.
- Commit y push solo cuando el autor lo pide; antes de subir, revisar que no haya datos de participantes.

## Privacidad y licencias
- `sesiones/` (videos y trazas) está en `.gitignore`: nunca subirla. `participantes_privado.csv` tampoco.
- UTA-RLDD: no poner imágenes de participantes en documentos ni diapositivas. Eyeblink8: no poner caras en documentos.
- DROZY: abandonado (licencia restrictiva).

## Dónde está cada cosa
- Sistema: `main.py` (entrada), `fatigue_framework.py` (bucle), `fatigue_pose.py` (postura, E12/E14b),
  `fatigue_profile.py` (calibración), `fatigue_eyes.py`, `fatigue_perclos.py`, `fatigue_alert.py`, `fatigue_config.py`.
- Herramientas: `grabar_perclos.py` (guía de voz para E9/E10/E13), `revisar.py` (anotación; N/P saltan a eventos
  pedidos por la voz), `evaluar.py` (sistema contra anotación, incluido PERCLOS por cuadro y por minuto).
- `docs/registro_experimentos.md`: **la fuente de verdad** de todos los experimentos (E1–E14b) con criterios y
  resultados. `docs/guion_perclos.md`, `docs/guia_anotacion.md`, `docs/LEEME_ejecutable.txt`.
- `analisis/`: scripts de los experimentos recientes (E8, E12, E14, E14b, ángulos de los datasets, revisión de
  sesiones guiadas, pipeline de UTA-RLDD). Tienen rutas absolutas del PC anterior: ajustarlas.
- Fuera del repo (copiar a mano): borradores del artículo y la monografía (`articulo.md`, `mono_*.md`,
  `build_docx.js`, diapositivas) y figuras en `Entregables Fatiga Detector/fuentes/`; datasets Eyeblink8 y UTA-RLDD.
- Pruebas: `python -m unittest discover -s tests -p "test_*.py"` (108) y `python tests/golden_master.py`
  (necesita los videos de referencia de `sesiones/`).

## Estado (2026-11-16)
- Validado: estado «ojo cerrado» de PERCLOS contra Eyeblink8 (E8: sensibilidad 0,88, falsos positivos 0,06 %).
- Adoptado: E5 (parpadeos fuera de rango), E12 (cabeceo válido 15° arriba / 10° abajo), E14b (referencia de postura
  temporal: alerta disponible en UTA-RLDD del 64 % al 91 %), reintento de cámara, aviso de cámara > 40° de lado.
- Límite declarado: cámara a 45° o más de la cara no sirve (E10). A 30° los parpadeos van bien, los cierres largos no.
- Puntos débiles: reflejos en gafas; **mirar hacia abajo solo con los ojos da cierres y micro-sueños falsos** (E13).
- Pendiente:
  1. Artículo, monografía y diapositivas v4 con todo lo anterior (ruta corta: con lo que ya existe; los videos
     guiados sin anotar van como descriptivos y E4b como preliminar).
  2. Congelar versión 1.2.0 y compilar el .exe (`build.py`, `tests/verify_exe.py`).
  3. Si el autor anota: E9 (sin gafas 20261116_202655, con gafas 20261116_195327), E10 (lateral 30°
     20261116_205255), E13 (posturas 20261116_223101) con `evaluar.py`.
  4. E4b necesita 4+ personas más de UTA-RLDD (Fold1_part2 o Fold3_part1) con `analisis/rldd_pipeline.py`.
  5. Mejora futura: validar la postura por la posición vertical del iris (mirada hacia abajo).
