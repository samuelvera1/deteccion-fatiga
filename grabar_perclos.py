"""Graba un video del guion de PERCLOS (E9) con una guía de voz que acompaña toda la sesión.

La voz guía la calibración, arranca el guion cuando el programa empieza a medir (línea «[MONITOREO]») y anuncia
cada cierre con cuenta regresiva. Así cada minuto del guion coincide con una ventana de 60 s de PERCLOS de
evaluar.py y no hace falta una segunda persona con cronómetro. El guion dura 4 minutos (docs/guion_perclos.md).
Lo que dijo la voz, y cuándo, queda en guia_voz.csv dentro de la sesión. La voz es la síntesis de Windows
(System.Speech, con una voz en español instalada); no hay que instalar nada.

Uso (PowerShell, en la carpeta del proyecto):
    .\\venv\\Scripts\\python.exe grabar_perclos.py --probar-voz
    .\\venv\\Scripts\\python.exe grabar_perclos.py --sujeto S01 --condicion sin_gafas
    .\\venv\\Scripts\\python.exe grabar_perclos.py --sujeto S01 --condicion con_gafas
    .\\venv\\Scripts\\python.exe grabar_perclos.py --sujeto S01 --condicion lateral_30
En los videos de lado (lateral_30, lateral_45), antes de grabar la voz dice en vivo a cuántos grados queda la cara
respecto a la cámara hasta que llega al objetivo (--sin-colocar se lo salta).
Cualquier otra opción se pasa tal cual a main.py (ej. --fuente 1 para otra cámara).
"""
import argparse
import base64
import csv
import json
import os
import re
import subprocess
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
BLOCK_S = 60.0
N_BLOCKS = 4
END_CUE_S = N_BLOCKS * BLOCK_S + 2.0    # 2 s después del último minuto, para que su ventana de 60 s quede completa
VOICE_RATE = 2                          # velocidad de la voz de Windows (-10 a 10); 2 = algo más ágil que la normal
COUNTDOWN = ("Tres.", "Dos.", "Uno.")
SQUINT = ("Entrecierra los ojos, sin cerrarlos.", "Normal.")
# E9: cámara de frente, sin y con gafas. E10: cámara a un costado, a unos 30 y 45 grados de la dirección en que miras
CONDITIONS = ("sin_gafas", "con_gafas", "lateral_30", "lateral_45")
# Colocación de la cámara en los videos de lado: la voz dice el ángulo en vivo hasta que queda en el objetivo
TARGET_ANGLES = {"lateral_30": 30.0, "lateral_45": 45.0}
ANGLE_TOLERANCE = 5.0           # grados
ANGLE_HOLD_S = 3.0              # tiempo seguido dentro del objetivo para darlo por colocado
ANGLE_SPEAK_EVERY_S = 3.5


def _closure(t, seconds):
    """Cierre voluntario de `seconds` que empieza en t: «Tres, dos, uno» antes, «Cierra» en t, «Aguanta» a la mitad
    si dura 3 s o más y «Abre» en t + seconds."""
    cues = [(t - len(COUNTDOWN) + i, word) for i, word in enumerate(COUNTDOWN)] + [(t, "Cierra.")]
    if seconds >= 3.0:
        cues.append((t + seconds / 2, "Aguanta."))
    return cues + [(t + seconds, "Abre.")]


def _hold(t, seconds, start, end):
    """Acción sostenida (trampa): `start` en t y `end` en t + seconds."""
    return [(t, start), (t + seconds, end)]


def _look(t, start, blink_at=2.5, back_at=4.0):
    """Mirar a un lado (girando la cabeza o solo con los ojos), parpadear ahí y volver al frente."""
    return [(t, start), (t + blink_at, LOOK_BLINK), (t + back_at, "Al frente.")]


# Parpadeos dirigidos del minuto 1: eventos conocidos para comprobar el conteo de parpadeos
BLINK_CUES = ("Haz un parpadeo.", "Otro parpadeo.", "Uno más.")
TRIPLE_BLINK = "Tres parpadeos seguidos."
# Parpadeo mirando a un lado: comprueba el conteo con la cabeza girada y con la mirada lateral (otro monitor)
LOOK_BLINK = "Parpadea."
HEAD_TURNS = ("Gira un poco a la izquierda.", "Gira un poco a la derecha.")
EYES_ONLY = ("Mira a la derecha, solo con los ojos.", "Mira a la izquierda, solo con los ojos.")

# (segundo desde el inicio del conteo, texto hablado). Las trampas que pueden sacar la postura de rango (celular,
# giros) van repartidas, como mucho 4 s por minuto, para que cada ventana conserve los 54 s válidos que exige PERCLOS.
SCRIPT = sorted(
    # Minuto 1 (~2-4 %): parpadeos dirigidos (5 sueltos y 2 series de 3), sin cierres; trampas: entrecerrar 5 s y
    # girar un poco a la izquierda 4 s, parpadeando ahí
    [(0.0, "Arrancamos. Minuto uno: parpadeos. Haz lo que te diga, con la cabeza quieta.")]
    + [(7.0, BLINK_CUES[0]), (11.0, BLINK_CUES[1]), (15.0, BLINK_CUES[2]), (19.0, TRIPLE_BLINK)]
    + [(26.0, "Ahora, una trampa.")] + _hold(28.0, 5.0, *SQUINT)
    + [(36.0, BLINK_CUES[0])]
    + _look(40.0, HEAD_TURNS[0])
    + [(46.0, TRIPLE_BLINK), (51.0, BLINK_CUES[0]), (55.0, "Bien. Se vienen los cierres.")]
    # Minuto 2 (~8-10 %): 3 cierres de 1,5 s y 3 parpadeos lentos; trampa: girar un poco a la derecha 4 s, parpadeando
    + [(60.0, "Minuto dos: cierres cortos. No bajes la cabeza.")]
    + _closure(69.0, 1.5) + _closure(84.0, 1.5) + _closure(107.0, 1.5)
    + [(t, "Parpadeo lento.") for t in (76.0, 91.0, 113.0)]
    + _look(96.0, HEAD_TURNS[1])
    + [(117.0, "Bien hecho.")]
    # Minuto 3 (~14-16 %): 4 cierres de 2 s; trampas: mirar el celular 3 s y entrecerrar 4 s; mirar a cada lado solo
    # con los ojos, parpadeando ahí
    + [(120.0, "Minuto tres: cierres de dos segundos. Cabeza quieta.")]
    + [c for t in (128.0, 141.0, 154.0, 167.0) for c in _closure(t, 2.0)]
    + _hold(132.0, 3.0, "Mira el celular.", "Vuelve a la pantalla.")
    + _look(145.0, EYES_ONLY[0], blink_at=3.0, back_at=4.5) + _look(157.0, EYES_ONLY[1], blink_at=3.5, back_at=5.0)
    + _hold(172.0, 4.0, *SQUINT)
    # Minuto 4 (~18-21 %): 2 cierres de 4 s y 1 de 3 s
    + [(180.0, "Último minuto: cierres largos. Aguanta con los ojos cerrados hasta que te diga abre.")]
    + _closure(190.0, 4.0) + _closure(205.0, 4.0) + _closure(222.0, 3.0)
    + [(197.0, "Cabeza quieta."), (214.0, "Vas muy bien."), (231.0, "Ya casi terminamos.")]
    + [(END_CUE_S, "¡Listo, terminaste! Pulsa la tecla Q en la ventana del programa.")])

# Antes de abrir el programa: en el video con gafas 20261116_195327 los reflejos de la pantalla tapaban los ojos
START_CUE = "Revisa la luz: de frente, y sin reflejos de la pantalla en las gafas."
START_CUE_S = 4.0       # lo que tarda en decirse, antes de abrir el programa (su primera frase lo cortaría)

# Voz durante la calibración, según lo que main.py escribe en la consola (fatigue_framework.py)
CALIBRATION_CUES = (
    ("[SESION]", "Hola. Primero calibramos: mira la pantalla y quédate quieto."),
    ("[PASO 1] Perfil fijado", "Bien. Ahora cierra los ojos, del todo, y no los abras hasta oír el pitido."),
)
RETRY_CUE = "No te vi los ojos cerrados. Ábrelos; en unos segundos te pido cerrarlos otra vez."
RETRY_AGAIN_CUE = "Ciérralos otra vez, del todo, hasta oír el pitido."
MEASURED_CUE = "Listo. Abre los ojos."
RESERVE_CUE = "No se midió el ojo cerrado. Pulsa Q y empieza de nuevo."
# Cortes de la cámara (fatigue_framework._wait_for_camera): otro programa la tomó o el driver se reinició
CAMERA_CUES = (("[CAMARA] No llegan", "Se cortó la cámara. Espera un momento."),
               ("[CAMARA] La cámara volvió", "Ya volvió la cámara. Sigue."),
               ("[CAMARA] La cámara no dio", "La cámara no responde. Cierra los programas que la usen y empieza de nuevo."))

# Lee líneas en base64 (UTF-8) por la entrada estándar y las dice con la primera voz en español instalada
_SPEAKER_PS = r"""
Add-Type -AssemblyName System.Speech
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
$v = $s.GetInstalledVoices() | Where-Object { $_.Enabled -and $_.VoiceInfo.Culture.TwoLetterISOLanguageName -eq 'es' } |
     Select-Object -First 1
if ($null -eq $v) { [Console]::Out.WriteLine('SIN_VOZ_ES'); exit 1 }
$s.SelectVoice($v.VoiceInfo.Name)
$s.Rate = __RATE__
$s.Volume = 100
[Console]::Out.WriteLine('VOZ ' + $v.VoiceInfo.Name)
while ($null -ne ($l = [Console]::In.ReadLine())) {
    if ($l -eq '__FIN__') { while ($s.State -eq 'Speaking') { Start-Sleep -Milliseconds 100 }; break }
    $text = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($l))
    $s.SpeakAsyncCancelAll(); [void]$s.SpeakAsync($text)
}
"""


class Speaker:
    """Voz de Windows en un proceso de PowerShell que queda abierto (sin la demora de arrancarlo en cada frase).
    Cada frase corta la anterior si aún no terminó: el guion deja tiempo para que se diga entera."""

    def __init__(self, rate=VOICE_RATE):
        script = _SPEAKER_PS.replace("__RATE__", str(int(rate)))
        encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
        self.proc = subprocess.Popen(
            ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-EncodedCommand", encoded],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        first = self.proc.stdout.readline().decode("utf-8", "replace").strip()
        if not first.startswith("VOZ "):
            self.proc.kill()
            raise RuntimeError("no hay una voz en español instalada en Windows (Configuración > Hora e idioma > Voz)"
                               if first == "SIN_VOZ_ES" else f"no arrancó la voz de Windows ({first or 'sin respuesta'})")
        self.voice = first[4:]
        self.lock = threading.Lock()

    def say(self, text):
        line = base64.b64encode(text.encode("utf-8")) + b"\n"
        with self.lock:
            try:
                self.proc.stdin.write(line)
                self.proc.stdin.flush()
            except OSError:
                pass        # la voz se cerró: el guion sigue escribiéndose en la consola

    def close(self, timeout=10.0):
        """Termina de decir la última frase y cierra el proceso."""
        with self.lock:
            try:
                self.proc.stdin.write(b"__FIN__\n")
                self.proc.stdin.close()
            except OSError:
                pass
        try:
            self.proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            self.proc.kill()


def _clock(t):
    return f"{int(t) // 60}:{t % 60:04.1f}"


def run_guide(speaker, t0, stop, log, said):
    """Dice el guion con t0 (time.monotonic) como inicio del conteo; añade a `said` (t_guion, t_real, texto)."""
    for t, text in SCRIPT:
        if stop.wait(max(0.0, t0 + t - time.monotonic())):
            break
        speaker.say(text)
        said.append((t, round(time.monotonic() - t0, 3), text))
        log(f"[GUIA {_clock(t)}] {text}")


def save_cues(session_dir, said):
    """guia_voz.csv: cada frase del guion con su segundo previsto y el real, ambos desde el inicio del conteo."""
    with open(os.path.join(session_dir, "guia_voz.csv"), "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["t_guion_s", "t_real_s", "texto"])
        writer.writerows(said)


def camera_yaw(face3d):
    """Giro de la cara respecto a la cámara, en grados y sin signo (0 = de frente). Misma fórmula que
    HeadPoseTracker.camera_angles (camara_yaw_grados del resumen). Aproximado: la z de MediaPipe es estimada."""
    import numpy as np

    import fatigue_geometry
    axes = fatigue_geometry.face_axes(face3d)
    return None if axes is None else abs(float(np.degrees(np.arctan2(axes[0, 2], axes[2, 2]))))


def angle_feedback(angle, target, tolerance=ANGLE_TOLERANCE):
    """(dentro del objetivo, frase de la voz) para un ángulo medido (None = no se ve la cara)."""
    if angle is None:
        return False, "No te veo la cara. Apunta la cámara hacia ti."
    if angle < target - tolerance:
        return False, f"{angle:.0f} grados. Corre la cámara más hacia el lado."
    if angle > target + tolerance:
        return False, f"{angle:.0f} grados. Un poco menos."
    return True, f"{angle:.0f} grados. Ahí está. Quédate quieto."


def position_camera(speaker, target, source, log, max_s=None):
    """Antes de un video de lado: mide en vivo el giro de la cara respecto a la cámara y guía con la voz hasta que
    quede en target ± ANGLE_TOLERANCE durante ANGLE_HOLD_S. Enter o espacio aceptan el ángulo actual; Q cancela.
    Devuelve el ángulo aceptado, o None si se canceló."""
    import statistics
    from collections import deque

    import cv2

    from fatigue_core import FaceMeshDetector
    detector = FaceMeshDetector(maxFaces=1, minDetectionCon=0.6, minTrackCon=0.6, refineLandmarks=True)
    cap = cv2.VideoCapture(source)
    window = "Colocar la camara"
    intro = (f"Vamos a poner la cámara a {target:.0f} grados. Mira de frente a tu punto, no a la cámara, "
             "y corre la cámara hacia un lado hasta que te diga listo.")
    speaker.say(intro)
    log(f"[CAMARA] Colocando la cámara a {target:.0f}° (± {ANGLE_TOLERANCE:.0f}). Mira de frente a tu punto, no a la "
        "cámara. Enter acepta el ángulo actual; Q cancela.")
    recent, inside_since, result = deque(maxlen=15), None, None
    start = time.monotonic()
    next_say = start + 0.5 + 0.07 * len(intro)      # deja terminar la explicación (~0,07 s por carácter, medido)
    failures = 0
    try:
        while max_s is None or time.monotonic() - start < max_s:
            ok, img = cap.read()
            if not ok:
                failures += 1
                if failures > 50:
                    log("[CAMARA] La cámara no da imágenes: ciérrala en otros programas y vuelve a empezar.")
                    return None
                time.sleep(0.1)
                continue
            failures = 0
            _, faces = detector.findFaceMesh(img, draw=False)
            angle = camera_yaw(detector.faces3d[0]) if faces else None
            if angle is not None:
                recent.append(angle)
            elif recent:
                recent.popleft()
            smooth = statistics.median(recent) if len(recent) >= 5 else None
            inside, phrase = angle_feedback(smooth, target)
            now = time.monotonic()
            inside_since = (inside_since or now) if inside else None
            label = "sin cara" if smooth is None else f"{smooth:.0f} grados (objetivo {target:.0f})"
            color = (80, 200, 80) if inside else (0, 160, 255)
            cv2.rectangle(img, (0, 0), (img.shape[1], 70), (30, 30, 30), -1)
            cv2.putText(img, label, (20, 48), cv2.FONT_HERSHEY_SIMPLEX, 1.4, color, 3)
            cv2.imshow(window, img)
            key = cv2.waitKey(1) & 0xFF
            if key in (ord("q"), ord("Q"), 27):
                speaker.say("Cancelado.")
                return None
            if key in (13, 32) and smooth is not None:
                result = smooth
                break
            if inside_since is not None and now - inside_since >= ANGLE_HOLD_S:
                result = smooth
                break
            if now >= next_say:
                speaker.say(phrase)
                next_say = now + ANGLE_SPEAK_EVERY_S
    finally:
        cap.release()
        cv2.destroyWindow(window)
    if result is not None:
        speaker.say(f"Listo, {result:.0f} grados. Deja la cámara ahí.")
        log(f"[CAMARA] Cámara colocada: la cara queda a {result:.0f}° de la cámara.")
        time.sleep(3.0)
    return result


def _source_from(extra):
    """Valor de --fuente entre las opciones que pasan a main.py (0 si no se indica)."""
    if "--fuente" in extra and extra.index("--fuente") + 1 < len(extra):
        value = extra[extra.index("--fuente") + 1]
        return int(value) if value.isdigit() else value
    return 0


def test_voice(speaker):
    cues = [(0.0, "Prueba de voz.")] + _closure(4.0, 2.0) + [(7.5, "Si me oyes bien, todo listo.")]
    t0 = time.monotonic()
    for t, text in cues:
        time.sleep(max(0.0, t0 + t - time.monotonic()))
        speaker.say(text)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Graba el guion de PERCLOS (E9) con guía de voz.",
                                     epilog="Las demás opciones pasan a main.py.")
    parser.add_argument("--sujeto", default="S01", help="código anónimo del participante (por defecto S01)")
    parser.add_argument("--condicion", choices=CONDITIONS, help="condición del video (E9: gafas; E10: cámara de lado)")
    parser.add_argument("--probar-voz", action="store_true", help="solo prueba la voz y el volumen, sin grabar")
    parser.add_argument("--sin-colocar", action="store_true",
                        help="en los videos de lado, no guiar la colocación de la cámara (ya está puesta)")
    args, extra = parser.parse_known_args(argv)
    if not args.probar_voz and not args.condicion:
        parser.error("indica --condicion (" + ", ".join(CONDITIONS) + ")")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")

    print_lock = threading.Lock()

    def log(message):
        with print_lock:
            print(message, flush=True)

    try:
        speaker = Speaker()
    except (RuntimeError, OSError) as exc:
        print(f"[ERROR] {exc}. Sin voz, usa el guion con otra persona que lea (docs/guion_perclos.md).")
        return 1
    log(f"[GUIA] Voz: {speaker.voice}")

    if args.probar_voz:
        test_voice(speaker)
        speaker.close()
        return 0

    placed = None
    if args.condicion in TARGET_ANGLES and not args.sin_colocar:
        placed = position_camera(speaker, TARGET_ANGLES[args.condicion], _source_from(extra), log)
        if placed is None:
            speaker.close()
            print("[GUIA] Colocación cancelada: no se grabó nada.")
            return 1

    cmd = [sys.executable, "-u", os.path.join(HERE, "main.py"), "--sujeto", args.sujeto,
           "--condicion", args.condicion, "--grabar", "--sin-sonido", *extra]
    env = dict(os.environ, PYTHONUNBUFFERED="1", PYTHONIOENCODING="utf-8")
    log("[GUIA] Antes de empezar: luz de frente (no detrás de ti), brillo de la pantalla bajo para que no se refleje "
        "en las gafas y ningún otro programa usando la cámara.")
    speaker.say(START_CUE)
    time.sleep(START_CUE_S)
    log("[GUIA] Abriendo el programa. La voz te guía la calibración y el guion (4 minutos).")
    proc = subprocess.Popen(cmd, cwd=HERE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env)

    stop, guide, said, timers = threading.Event(), None, [], []
    session_dir, reserve, recalibrated, camera_gaps, camera_lost = None, False, False, [], False
    for raw in proc.stdout:
        line = raw.decode("utf-8", "replace").rstrip("\r\n")
        log(line)
        found = re.match(r"\[SESION\] \S+ -> (.+)$", line) or re.search(r"Datos guardados en '(.+)'", line)
        if found and session_dir is None:
            session_dir = os.path.join(HERE, found.group(1))     # main.py corre en HERE: rutas relativas a HERE
        for prefix, text in CAMERA_CUES:
            if line.startswith(prefix):
                speaker.say(text)
        gap = re.search(r"\[CAMARA\] La cámara volvió tras (\d+(?:\.\d+)?) s", line)
        if gap and guide is not None:
            camera_gaps.append((said[-1][0] if said else 0.0, float(gap.group(1))))
        camera_lost = camera_lost or line.startswith("[CAMARA] La cámara no dio")
        if guide is not None:
            if "[MONITOREO]" in line:
                recalibrated = True
                log("[GUIA] Recalibraste a mitad del guion: el guion sigue su reloj; anótalo como problema si hace falta.")
            continue
        for prefix, text in CALIBRATION_CUES:
            if line.startswith(prefix):
                speaker.say(text)
        if line.startswith("[PASO 2] No se detectaron"):
            speaker.say(RETRY_CUE)
            pause = re.search(r" en (\d+(?:\.\d+)?) s", line)
            timer = threading.Timer(float(pause.group(1)) if pause else 5.0, speaker.say, (RETRY_AGAIN_CUE,))
            timer.daemon = True
            timer.start()
            timers.append(timer)
        if line.startswith("[PASO 2] Ojo cerrado:"):
            if "RESERVA" in line:
                reserve = True
                speaker.say(RESERVE_CUE)
                log("[GUIA] La calibración no midió el ojo cerrado: pulsa Q y vuelve a empezar (E9 exige repetirla).")
            else:
                speaker.say(MEASURED_CUE)
        if "[MONITOREO]" in line:
            t0 = time.monotonic()
            guide = threading.Thread(target=run_guide, args=(speaker, t0, stop, log, said), daemon=True)
            guide.start()
    proc.wait()
    stop.set()
    for timer in timers:
        timer.cancel()
    if guide is not None:
        guide.join(timeout=2.0)
    speaker.close(timeout=3.0)

    print("\n" + "=" * 50)
    last = said[-1][0] if said else None
    if guide is None:
        print("El programa terminó antes de empezar a medir: no hay video del guion"
              + (" (la cámara no dio imágenes; mira el aviso [CAMARA] de arriba)." if camera_lost else ".")
              + " Esa sesión quedó vacía: no sirve para anotar.")
    elif last is None or last < END_CUE_S:
        print(f"[AVISO] El programa terminó en el minuto {_clock(last or 0.0)} del guion, antes del final: "
              "repite la grabación si faltó algún bloque.")
    measured = None
    if session_dir and os.path.isdir(session_dir):
        if said:
            save_cues(session_dir, said)
        if placed is not None:
            with open(os.path.join(session_dir, "posicion_camara.json"), "w", encoding="utf-8") as f:
                json.dump({"objetivo_grados": TARGET_ANGLES[args.condicion], "medido_al_colocar_grados": round(placed, 1),
                           "nota": "giro de la cara respecto a la cámara mirando de frente; aproximado (z estimada)"},
                          f, ensure_ascii=False, indent=1)
        meta_path = os.path.join(session_dir, "metadata.json")
        if os.path.isfile(meta_path):
            with open(meta_path, encoding="utf-8") as f:
                measured = json.load(f).get("resumen", {}).get("ojo_cerrado_medido")
    if reserve or measured is False:
        print("[AVISO] El ojo cerrado no se midió en la calibración: según E9 esta grabación no sirve; repítela.")
    if recalibrated:
        print("[AVISO] Hubo una recalibración durante el guion.")
    for t, seconds in camera_gaps:
        print(f"[AVISO] La cámara se cortó {seconds:.1f} s cerca del minuto {_clock(t)} del guion"
              + (": ese minuto puede quedar sin los 54 s válidos; repite la grabación." if seconds > 5.0 else "."))
    if session_dir and guide is not None:
        print(f"Sesión: {session_dir}\nSiguiente paso, anotarla en modo ciego (docs/guia_anotacion.md):\n"
              f'  .\\venv\\Scripts\\python.exe revisar.py "{session_dir}" --ciego')
    return proc.returncode


if __name__ == "__main__":
    sys.exit(main())
