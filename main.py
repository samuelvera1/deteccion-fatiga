# main.py
"""
Uso:
    python main.py                                   # cámara 0, sujeto "anonimo"
    python main.py --sujeto S01                      # cámara 0, sujeto S01
    python main.py --sujeto S01 --fuente video.mp4   # analiza un vídeo grabado (reloj del vídeo)
    python main.py --nombre "Samuel Vera" --condicion con_gafas   # sesión guardada con el nombre
    python main.py --sujeto S01 --condicion con_gafas  # registra la condición experimental declarada
    python main.py --sin-traza                       # no guarda las métricas por frame
    python main.py --nombre "..." --condicion sin_gafas --grabar   # prueba EN VIVO grabada para anotarla
    python main.py --nombre "..." --condicion sin_gafas --grabar --kss   # + escala de somnolencia cada 5 min

Cada ejecución crea sesiones/<fecha>_<sujeto>/ con metadata.json (commit, parámetros, FPS, CPU/RAM,
resumen), eventos.csv y traza.csv, y añade una fila a sesiones/resumen_sesiones.csv.
Con --nombre, la sesión se guarda con el nombre tal cual y, además, con un código anónimo (S01...)
en la columna codigo_anonimo, para poder compartir los datos sin nombres si hace falta. La carpeta
sesiones/ y participantes_privado.csv están excluidos de git: los nombres no se suben al repositorio.

Para revisar una sesión de vídeo con barra de tiempo y anotar los eventos reales: ver revisar.py.
Para medir el sistema contra esas anotaciones: ver evaluar.py y docs/guia_anotacion.md.

Vídeos con calibración manual: si el vídeo tiene marcas (python revisar.py --video RUTA, teclas N/C/P),
se calibra con los tramos marcados y el conteo empieza en el inicio de la prueba. --calibracion-auto
ignora las marcas.
"""
import argparse
import datetime
import os
import sys
import traceback

import cv2

import calibration_marks
import version
from fatigue_framework import FatigueMonitor
from session_recorder import ParticipantRegistry


def registrar_parpadeo(total_parpadeos):
    hora_actual = datetime.datetime.now().strftime("%H:%M:%S")
    print(f"[{hora_actual}] Parpadeo detectado. Total: {total_parpadeos}")


def registrar_bostezo(total_bostezos):
    hora_actual = datetime.datetime.now().strftime("%H:%M:%S")
    print(f"[{hora_actual}] ¡ALERTA! Bostezo detectado. Total: {total_bostezos}")


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Monitor de fatiga en tiempo real")
    parser.add_argument("--version", action="version", version=f"Fatiga Detector {version.VERSION}")
    parser.add_argument("--ventanas", action="store_true",
                        help="abre las ventanas de inicio y de resumen en lugar de usar la consola")
    who = parser.add_mutually_exclusive_group()
    who.add_argument("--nombre", help='nombre del participante entre comillas (ej. "Samuel Vera"); la sesión se '
                                      'guarda con el nombre y con un código anónimo (S01...) aparte')
    who.add_argument("--sujeto", default="anonimo", help="identificador libre del participante (ej. S01)")
    parser.add_argument("--condicion", default=None,
                        help="condición experimental declarada (ej. con_gafas, sin_gafas); se guarda en los metadatos")
    parser.add_argument("--fuente", default="0", help="índice de cámara (0, 1...) o ruta de un vídeo")
    parser.add_argument("--sin-traza", action="store_true", help="no guardar las métricas por frame")
    parser.add_argument("--sin-sonido", action="store_true",
                        help="las alertas de fatiga se muestran y registran, pero sin sonido")
    parser.add_argument("--kss", nargs="?", const=5.0, type=float, default=None, metavar="MIN",
                        help="sesión en vivo: pregunta la escala de somnolencia de Karolinska (1-9) al empezar, cada "
                             "MIN minutos (5 si no se indica) y al terminar")
    parser.add_argument("--grabar", action="store_true",
                        help="sesión en vivo: guarda lo que ve la cámara (grabacion.mp4) para anotarlo después con "
                             "revisar.py y evaluar el sistema en tiempo real")
    parser.add_argument("--resolucion", default="1280x720",
                        help='resolución pedida a la cámara, ej. 1280x720 o 640x480; "nativa" para no cambiarla')
    parser.add_argument("--sin-refinar", action="store_true",
                        help="desactiva refine_landmarks de MediaPipe (solo para comparar con el modo anterior)")
    parser.add_argument("--calibracion-auto", action="store_true",
                        help="ignora las marcas de calibración manual del vídeo y calibra automáticamente")
    args = parser.parse_args(argv)
    args.fuente = int(args.fuente) if args.fuente.isdigit() else args.fuente
    if args.resolucion.lower() == "nativa":
        args.resolucion = None
    else:
        try:
            width, height = (int(v) for v in args.resolucion.lower().split("x"))
            args.resolucion = (width, height)
        except ValueError:
            parser.error(f'--resolucion debe ser ANCHOxALTO (ej. 1280x720) o "nativa", no "{args.resolucion}"')
    return args


def manual_marks_for(source, ignore):
    """Marcas de calibración manual del vídeo, validadas; None si no hay (o se ignoran)."""
    if ignore or not isinstance(source, str) or not os.path.exists(source):
        return None
    marks = calibration_marks.load_marks(source)
    if marks is None:
        print("[CALIBRACION] El vídeo no tiene marcas: calibración automática "
              "(para marcarlo: python revisar.py --video RUTA)")
        return None
    issues = calibration_marks.problems(marks)
    if issues:
        sys.exit("Las marcas de calibración del vídeo están incompletas: " + "; ".join(issues) +
                 ".\nCorrígelas con revisar.py --video, o analiza con --calibracion-auto.")
    n, c, p = marks["neutro"], marks["cerrado"], marks["inicio_prueba"]
    print(f"[CALIBRACION] Marcas manuales: neutro {n['inicio_s']:.2f}-{n['fin_s']:.2f} s, "
          f"ojos cerrados {c['inicio_s']:.2f}-{c['fin_s']:.2f} s, prueba desde {p['s']:.2f} s")
    return marks


def run_session(args):
    """Una sesión completa (registro del participante, calibración y monitor). Devuelve el monitor ya terminado."""
    subject_code = None
    if args.nombre:
        subject_code, is_new = ParticipantRegistry().code_for(args.nombre)
        args.sujeto = args.nombre
        print(f"[PARTICIPANTE] {args.nombre} (código anónimo {subject_code}{', nuevo' if is_new else ''})")

    # Umbrales relativos al perfil del sujeto (calibración automática al iniciar, o manual con las marcas del
    # vídeo; tecla C para recalibrar)
    marks = manual_marks_for(args.fuente, args.calibracion_auto)
    monitor = FatigueMonitor(video_source=args.fuente, subject_id=args.sujeto, subject_code=subject_code,
                             manual_marks=marks, condition=args.condicion, save_trace=not args.sin_traza,
                             refine_landmarks=not args.sin_refinar, capture_size=args.resolucion,
                             record=args.grabar, kss_interval_min=args.kss, alert_sound=not args.sin_sonido)
    monitor.on_blink(registrar_parpadeo)
    monitor.on_yawn(registrar_bostezo)
    monitor.start()
    return monitor


def print_summary(monitor):
    """Resumen de la sesión en la consola."""
    meta = monitor.session.metadata
    resumen, rendimiento = meta["resumen"], meta["rendimiento"]
    print("\n" + "=" * 50)
    print(f"RESUMEN DE LA SESIÓN {meta['sesion_id']}")
    print(f"Sujeto:               {meta['sujeto']}"
          f"{' (' + meta['codigo_anonimo'] + ')' if meta['codigo_anonimo'] else ''}")
    print(f"Condición declarada:  {meta['condicion'] or '(no indicada)'}")
    print(f"Fuente:               {meta['tipo_fuente']} ({meta['fuente']})")
    print(f"Duración:             {resumen['duracion_s']:.0f} s ({meta['reloj']})")
    start = resumen["inicio_monitoreo_s"]
    print(f"Calibración:          {resumen['calibracion_modo']}"
          f"{f', conteo desde t = {start:.2f} s' if start is not None else ', el conteo no llegó a empezar'}")
    print(f"Parpadeos:            {resumen['parpadeos']} (prolongados: {resumen['parpadeos_prolongados']}, "
          f"duración media: {resumen['duracion_media_parpadeo_s'] or 0:.2f} s)")
    print(f"Bostezos:             {resumen['bostezos']} (micro: {resumen['micro_bostezos']}, duración media "
          f"de la apertura: {resumen['duracion_media_bostezo_s'] or 0:.2f} s)")
    if resumen["parpadeos_descartados_giro"]:
        print(f"Descartados por giro: {resumen['parpadeos_descartados_giro']} (caídas de apertura al girar "
              f"rápido la cabeza, sin cierre del párpado)")
    print(f"PERCLOS final:        {resumen['perclos_final_pct']:.1f}%")
    gafas = resumen["gafas_final"]
    print(f"Gafas (declaradas):   {'(no declaradas)' if gafas is None else ('SÍ' if gafas else 'NO')}")
    print(f"Recalibraciones:      {resumen['recalibraciones']}")
    if resumen.get("kss"):
        print("Somnolencia (KSS):    " + ", ".join(f"{r['valor']} ({r['momento']}, {r['t_respuesta']:.0f} s)"
                                                    for r in resumen["kss"]))
    fatiga = resumen.get("fatiga")
    if fatiga:
        niveles = ", ".join(f"{k.lower().replace('_', '-')} {v:.0f} s"
                            for k, v in fatiga["tiempo_por_nivel_s"].items() if v > 0)
        alertas = ", ".join(f"{k.lower().replace('_', '-')} {v}" for k, v in fatiga["alertas"].items() if v)
        print(f"Nivel de fatiga:      {niveles or '-'}")
        print(f"Alertas:              {alertas or 'ninguna'}")
    print(f"FPS de procesamiento: {rendimiento['fps_procesamiento_medio']}")
    print(f"CPU del proceso:      {rendimiento['cpu_proceso_pct_medio']}%")
    print(f"RAM del proceso:      {rendimiento['ram_proceso_mb_media']} MB")
    print(f"Versión:              {version.VERSION} ({'ejecutable' if version.is_frozen() else 'código fuente'})")
    print(f"Commit:               {meta['git']['commit']}")
    print("=" * 50)
    print(f"\nDatos guardados en '{monitor.session.dir}'.")
    if meta.get("grabacion"):
        print(f"Grabación: {meta['grabacion']['frames']} frames. Para anotarla:\n"
              f'  python revisar.py "{monitor.session.dir}" --ciego')


def options_to_argv(choice):
    """Opciones de la ventana de inicio -> argumentos de línea de comandos (así hay un solo camino de arranque)."""
    argv = []
    if choice["name"]:
        argv += ["--nombre", choice["name"]]
    if choice["condition"]:
        argv += ["--condicion", choice["condition"]]
    if choice["record"]:
        argv.append("--grabar")
    return argv


def camera_available(index=0):
    """Comprueba que la cámara abre y entrega un frame (antes de empezar la sesión)."""
    capture = cv2.VideoCapture(index)
    try:
        return bool(capture.isOpened() and capture.read()[0])
    finally:
        capture.release()


def run_with_windows():
    """Modo con ventanas: inicio -> sesión -> resumen, y de ahí a una sesión nueva o a salir."""
    import gui
    import session_view
    while True:
        choice = gui.ask_start()
        if choice is None:
            return
        while not camera_available():
            if gui.camera_error() != "retry":
                return
        monitor = run_session(parse_args(options_to_argv(choice)))
        print_summary(monitor)
        while True:
            view = session_view.summary_view(monitor.session.metadata, monitor.closure_reliable, monitor.session.dir)
            action = gui.show_summary(view)
            if action != "review":
                break
            mode = gui.ask_review(view)
            if mode:
                import revisar
                problem = revisar.review_session(monitor.session.dir, blind=(mode == "blind"))
                if problem:
                    gui.show_error(problem)
        if action != "new":
            return


def main(argv=None):
    args = parse_args(argv)
    if args.ventanas:
        run_with_windows()
        return
    print_summary(run_session(args))


def redirect_output_to_log():
    """Sin consola (ejecutable de ventanas) no hay dónde imprimir: avisos, resumen y errores van a
    fatiga_detector.log junto al .exe."""
    if sys.stdout is not None and sys.stderr is not None:
        return
    log = open(os.path.join(os.path.dirname(sys.executable), "fatiga_detector.log"), "a", encoding="utf-8",
               buffering=1)
    log.write(f"\n=== {datetime.datetime.now():%Y-%m-%d %H:%M:%S} · Fatiga Detector {version.VERSION} ===\n")
    sys.stdout = sys.stderr = log


def run_executable():
    """Ejecutable (PyInstaller): trabaja junto al .exe, así sesiones/ y participantes_privado.csv quedan en la
    misma carpeta aunque se abra con doble clic. Sin argumentos (doble clic) abre las ventanas; con argumentos
    se comporta como main.py en la consola."""
    os.chdir(os.path.dirname(sys.executable))
    redirect_output_to_log()
    windows = len(sys.argv) == 1
    try:
        main(["--ventanas"] if windows else None)
    except SystemExit as stop:
        if isinstance(stop.code, str):
            print(stop.code)
        elif stop.code not in (0, None) and not windows:
            raise
    except Exception as error:
        traceback.print_exc()
        if windows:
            import gui
            gui.show_error(f"Algo falló y el programa tuvo que cerrarse.\n\n{error}")


if __name__ == "__main__":
    if version.is_frozen():
        run_executable()
    else:
        main()
