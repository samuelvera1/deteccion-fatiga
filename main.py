# main.py
"""
Uso:
    python main.py                                   # cámara 0, sujeto "anonimo"
    python main.py --sujeto S01                      # cámara 0, sujeto S01
    python main.py --sujeto S01 --fuente video.mp4   # analiza un vídeo grabado (reloj del vídeo)
    python main.py --nombre "Samuel Vera" --condicion con_gafas   # sesión guardada con el nombre
    python main.py --sujeto S01 --condicion con_gafas  # registra la condición experimental declarada
    python main.py --sin-traza                       # no guarda las métricas por frame

Cada ejecución crea sesiones/<fecha>_<sujeto>/ con metadata.json (commit, parámetros, FPS, CPU/RAM,
resumen), eventos.csv y traza.csv, y añade una fila a sesiones/resumen_sesiones.csv.
Con --nombre, la sesión se guarda con el nombre tal cual y, además, con un código anónimo (S01...)
en la columna codigo_anonimo, para poder compartir los datos sin nombres si hace falta. La carpeta
sesiones/ y participantes_privado.csv están excluidos de git: los nombres no se suben al repositorio.
"""
import argparse
import datetime

from fatigue_framework import FatigueMonitor
from session_recorder import ParticipantRegistry


def registrar_parpadeo(total_parpadeos):
    hora_actual = datetime.datetime.now().strftime("%H:%M:%S")
    print(f"[{hora_actual}] Parpadeo detectado. Total: {total_parpadeos}")


def registrar_bostezo(total_bostezos):
    hora_actual = datetime.datetime.now().strftime("%H:%M:%S")
    print(f"[{hora_actual}] ¡ALERTA! Bostezo detectado. Total: {total_bostezos}")


def parse_args():
    parser = argparse.ArgumentParser(description="Monitor de fatiga en tiempo real")
    who = parser.add_mutually_exclusive_group()
    who.add_argument("--nombre", help='nombre del participante entre comillas (ej. "Samuel Vera"); la sesión se '
                                      'guarda con el nombre y con un código anónimo (S01...) aparte')
    who.add_argument("--sujeto", default="anonimo", help="identificador libre del participante (ej. S01)")
    parser.add_argument("--condicion", default=None,
                        help="condición experimental declarada (ej. con_gafas, sin_gafas); se guarda en los metadatos")
    parser.add_argument("--fuente", default="0", help="índice de cámara (0, 1...) o ruta de un vídeo")
    parser.add_argument("--sin-traza", action="store_true", help="no guardar las métricas por frame")
    parser.add_argument("--resolucion", default="1280x720",
                        help='resolución pedida a la cámara, ej. 1280x720 o 640x480; "nativa" para no cambiarla')
    parser.add_argument("--sin-refinar", action="store_true",
                        help="desactiva refine_landmarks de MediaPipe (solo para comparar con el modo anterior)")
    args = parser.parse_args()
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


if __name__ == "__main__":
    args = parse_args()
    subject_code = None
    if args.nombre:
        subject_code, is_new = ParticipantRegistry().code_for(args.nombre)
        args.sujeto = args.nombre
        print(f"[PARTICIPANTE] {args.nombre} (código anónimo {subject_code}{', nuevo' if is_new else ''})")

    # Umbrales relativos al perfil del sujeto (calibración automática al iniciar; tecla C para recalibrar)
    monitor = FatigueMonitor(video_source=args.fuente, subject_id=args.sujeto, subject_code=subject_code,
                             condition=args.condicion, save_trace=not args.sin_traza,
                             refine_landmarks=not args.sin_refinar, capture_size=args.resolucion)
    monitor.on_blink(registrar_parpadeo)
    monitor.on_yawn(registrar_bostezo)
    monitor.start()

    # ── RESUMEN DE LA SESIÓN ────────────────────────────────────────
    meta = monitor.session.metadata
    resumen, rendimiento = meta["resumen"], meta["rendimiento"]
    print("\n" + "=" * 50)
    print(f"RESUMEN DE LA SESIÓN {meta['sesion_id']}")
    print(f"Sujeto:               {meta['sujeto']}"
          f"{' (' + meta['codigo_anonimo'] + ')' if meta['codigo_anonimo'] else ''}")
    print(f"Condición declarada:  {meta['condicion'] or '(no indicada)'}")
    print(f"Duración:             {resumen['duracion_s']:.0f} s ({meta['reloj']})")
    print(f"Parpadeos:            {resumen['parpadeos']} (prolongados: {resumen['parpadeos_prolongados']}, "
          f"duración media: {resumen['duracion_media_parpadeo_s'] or 0:.2f} s)")
    print(f"Bostezos:             {resumen['bostezos']} (micro: {resumen['micro_bostezos']})")
    print(f"PERCLOS final:        {resumen['perclos_final_pct']:.1f}%")
    gafas = resumen["gafas_final"]
    print(f"Gafas (declaradas):   {'(no declaradas)' if gafas is None else ('SÍ' if gafas else 'NO')}")
    print(f"Recalibraciones:      {resumen['recalibraciones']}")
    print(f"FPS de procesamiento: {rendimiento['fps_procesamiento_medio']}")
    print(f"CPU del proceso:      {rendimiento['cpu_proceso_pct_medio']}%")
    print(f"RAM del proceso:      {rendimiento['ram_proceso_mb_media']} MB")
    print(f"Commit:               {meta['git']['commit']}")
    print("=" * 50)
    print(f"\nDatos guardados en '{monitor.session.dir}'.")
