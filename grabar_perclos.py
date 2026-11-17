"""Graba un video del guion de PERCLOS (E9) con una guía de voz que dice cuándo cerrar y abrir los ojos.

Abre main.py con --grabar y --sin-sonido y empieza a hablar cuando el programa termina la calibración y empieza a
medir (línea «[MONITOREO]»). Así cada minuto del guion coincide con una ventana de 60 s de PERCLOS de evaluar.py, y
no hace falta una segunda persona con cronómetro. Los tiempos siguen docs/guion_perclos.md. La voz es la síntesis
de Windows (System.Speech, con una voz en español instalada); no hay que instalar nada.

Uso (PowerShell, en la carpeta del proyecto):
    .\\venv\\Scripts\\python.exe grabar_perclos.py --probar-voz
    .\\venv\\Scripts\\python.exe grabar_perclos.py --sujeto S01 --condicion sin_gafas
    .\\venv\\Scripts\\python.exe grabar_perclos.py --sujeto S01 --condicion con_gafas
Cualquier otra opción se pasa tal cual a main.py (ej. --fuente 1 para otra cámara).
"""
import argparse
import base64
import json
import os
import re
import subprocess
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
BLOCK_S = 60.0
END_CUE_S = 362.0       # 2 s después del minuto 6, para que la última ventana de 60 s quede completa


def _closure(t, seconds):
    """Cierre voluntario: «Cierra» en t y «Abre» en t + seconds."""
    return [(t, "Cierra."), (t + seconds, "Abre.")]


def _hold(t, seconds, start, end):
    return [(t, start), (t + seconds, end)]


# (segundo desde el inicio del conteo, texto hablado), según la tabla de docs/guion_perclos.md
SCRIPT = sorted(
    [(0.0, "Minuto uno. Lee con normalidad.")]
    # 1-2: 4 parpadeos lentos y 2 cierres de 1,5 s (segundos 20 y 45)
    + [(60.0, "Minuto dos.")] + [(t, "Parpadeo lento.") for t in (68.0, 90.0, 98.0, 115.0)]
    + _closure(80.0, 1.5) + _closure(105.0, 1.5)
    # 2-3: 4 cierres de 2 s (segundos 10, 25, 40 y 55)
    + [(120.0, "Minuto tres.")] + [c for t in (130.0, 145.0, 160.0, 175.0) for c in _closure(t, 2.0)]
    # 3-4: sin cierres; trampas: celular 3 x 5 s, entrecerrar 2 x 5 s (pupila visible), giro a cada lado
    + [(180.0, "Minuto cuatro. Sin cierres.")]
    + [c for t in (184.0, 202.0, 220.0) for c in _hold(t, 5.0, "Mira el celular.", "Vuelve a la pantalla.")]
    + [c for t in (193.0, 211.0) for c in _hold(t, 5.0, "Entrecierra los ojos, sin cerrarlos.", "Normal.")]
    + _hold(229.0, 3.0, "Gira a la izquierda.", "Al frente.") + _hold(234.0, 3.0, "Gira a la derecha.", "Al frente.")
    # 4-5: 2 cierres de 4 s (segundos 10 y 35) y 1 de 2 s (segundo 50)
    + [(240.0, "Minuto cinco.")] + _closure(250.0, 4.0) + _closure(275.0, 4.0) + _closure(290.0, 2.0)
    # 5-6: normal
    + [(300.0, "Minuto seis. Normal.")]
    + [(END_CUE_S, "Fin del guion. Pulsa la tecla Q en la ventana del programa.")])

# Lee líneas por la entrada estándar y las dice con la primera voz en español instalada
_SPEAKER_PS = r"""
Add-Type -AssemblyName System.Speech
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
$v = $s.GetInstalledVoices() | Where-Object { $_.Enabled -and $_.VoiceInfo.Culture.TwoLetterISOLanguageName -eq 'es' } |
     Select-Object -First 1
if ($null -eq $v) { [Console]::Out.WriteLine('SIN_VOZ_ES'); exit 1 }
$s.SelectVoice($v.VoiceInfo.Name)
$s.Rate = 1
[Console]::InputEncoding = New-Object System.Text.UTF8Encoding $false
[Console]::Out.WriteLine('VOZ ' + $v.VoiceInfo.Name)
while ($null -ne ($l = [Console]::In.ReadLine())) {
    if ($l -eq '__FIN__') { while ($s.State -eq 'Speaking') { Start-Sleep -Milliseconds 100 }; break }
    $s.SpeakAsyncCancelAll(); [void]$s.SpeakAsync($l)
}
"""


class Speaker:
    """Voz de Windows en un proceso de PowerShell que queda abierto (sin la demora de arrancarlo en cada frase)."""

    def __init__(self):
        encoded = base64.b64encode(_SPEAKER_PS.encode("utf-16-le")).decode("ascii")
        self.proc = subprocess.Popen(
            ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-EncodedCommand", encoded],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        first = self.proc.stdout.readline().decode("utf-8", "replace").strip()
        if not first.startswith("VOZ "):
            self.proc.kill()
            raise RuntimeError("no hay una voz en español instalada en Windows (Configuración > Hora e idioma > Voz)"
                               if first == "SIN_VOZ_ES" else f"no arrancó la voz de Windows ({first or 'sin respuesta'})")
        self.voice = first[4:]

    def say(self, text):
        self.proc.stdin.write((text.replace("\n", " ") + "\n").encode("utf-8"))
        self.proc.stdin.flush()

    def close(self, timeout=10.0):
        """Termina de decir la última frase y cierra el proceso."""
        try:
            self.say("__FIN__")
            self.proc.stdin.close()
            self.proc.wait(timeout=timeout)
        except (OSError, subprocess.TimeoutExpired):
            self.proc.kill()


def _clock(t):
    return f"{int(t) // 60}:{t % 60:04.1f}"


def run_guide(speaker, t0, stop, log):
    """Dice el guion con t0 como inicio del conteo; devuelve el último segundo dicho (o None si se paró antes)."""
    last = None
    for t, text in SCRIPT:
        if stop.wait(max(0.0, t0 + t - time.monotonic())):
            break
        speaker.say(text)
        log(f"[GUIA {_clock(t)}] {text}")
        last = t
    return last


def main(argv=None):
    parser = argparse.ArgumentParser(description="Graba el guion de PERCLOS (E9) con guía de voz.",
                                     epilog="Las demás opciones pasan a main.py.")
    parser.add_argument("--sujeto", default="S01", help="código anónimo del participante (por defecto S01)")
    parser.add_argument("--condicion", choices=["sin_gafas", "con_gafas"], help="condición del video")
    parser.add_argument("--probar-voz", action="store_true", help="solo prueba la voz y el volumen, sin grabar")
    args, extra = parser.parse_known_args(argv)
    if not args.probar_voz and not args.condicion:
        parser.error("indica --condicion sin_gafas o --condicion con_gafas")
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
        for delay, text in ((0.0, "Prueba de voz. Cierra."), (2.0, "Abre."), (1.5, "Si me oyes bien, todo listo.")):
            time.sleep(delay)
            speaker.say(text)
        speaker.close()
        return 0

    cmd = [sys.executable, "-u", os.path.join(HERE, "main.py"), "--sujeto", args.sujeto,
           "--condicion", args.condicion, "--grabar", "--sin-sonido", *extra]
    env = dict(os.environ, PYTHONUNBUFFERED="1", PYTHONIOENCODING="utf-8")
    log("[GUIA] Abriendo el programa. Calibra como siempre: mira al frente y, cuando lo pida, cierra los ojos hasta "
        "oír el pitido. La voz empieza sola cuando el programa empiece a medir.")
    proc = subprocess.Popen(cmd, cwd=HERE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env)

    stop, guide, result = threading.Event(), None, {}
    session_dir, reserve, recalibrated = None, False, False
    for raw in proc.stdout:
        line = raw.decode("utf-8", "replace").rstrip("\r\n")
        log(line)
        if line.startswith("[PASO 2] Ojo cerrado") and "RESERVA" in line:
            reserve = True
            speaker.say("No se midió el ojo cerrado. Pulsa Q y empieza de nuevo.")
            log("[GUIA] La calibración no midió el ojo cerrado: pulsa Q y vuelve a empezar (E9 exige repetirla).")
        if "[MONITOREO]" in line:
            if guide is None:
                t0 = time.monotonic()
                guide = threading.Thread(target=lambda: result.update(last=run_guide(speaker, t0, stop, log)),
                                         daemon=True)
                guide.start()
            else:
                recalibrated = True
                log("[GUIA] Recalibraste a mitad del guion: el guion sigue su reloj; anótalo como problema si hace falta.")
        found = re.search(r"Datos guardados en '(.+)'", line)
        if found:
            session_dir = found.group(1)
    proc.wait()
    stop.set()
    if guide is not None:
        guide.join(timeout=2.0)
    speaker.close(timeout=3.0)

    print("\n" + "=" * 50)
    last = result.get("last")
    if guide is None:
        print("El programa terminó antes de empezar a medir: no hay video del guion.")
    elif last is None or last < END_CUE_S:
        print(f"[AVISO] El programa terminó en el minuto {_clock(last or 0.0)} del guion, antes del final: "
              "repite la grabación si faltó algún bloque.")
    measured = None
    if session_dir and os.path.isfile(os.path.join(session_dir, "metadata.json")):
        with open(os.path.join(session_dir, "metadata.json"), encoding="utf-8") as f:
            measured = json.load(f).get("resumen", {}).get("ojo_cerrado_medido")
    if reserve or measured is False:
        print("[AVISO] El ojo cerrado no se midió en la calibración: según E9 esta grabación no sirve; repítela.")
    if recalibrated:
        print("[AVISO] Hubo una recalibración durante el guion.")
    if session_dir:
        print(f"Sesión: {session_dir}\nSiguiente paso, anotarla en modo ciego (docs/guia_anotacion.md):\n"
              f'  .\\venv\\Scripts\\python.exe revisar.py "{session_dir}" --ciego')
    return proc.returncode


if __name__ == "__main__":
    sys.exit(main())
