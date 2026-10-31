# assets/make_sounds.py
"""Genera las melodías de los estados (assets/sounds/*.wav) con síntesis simple: son propias, sin derechos de autor.
    python assets/make_sounds.py
Cuanto más grave el estado, más grave y fuerte el sonido:
  normal.wav       dos notas agudas y suaves que suben (vuelta a la normalidad).
  precaucion.wav   dos notas agudas y suaves que bajan (atención, sin alarma).
  somnolencia.wav  tres notas medias en tono menor, que bajan (advertencia).
  microsueno.wav   pulsos graves y ásperos, los más fuertes (alarma)."""
import os
import wave

import numpy as np

RATE = 44100


def tone(freq, seconds, harmonics=(1.0, 0.35, 0.15), decay=4.0, attack=0.01):
    t = np.arange(int(RATE * seconds)) / RATE
    wave_ = sum(amp * np.sin(2 * np.pi * freq * (i + 1) * t) for i, amp in enumerate(harmonics))
    return wave_ * np.minimum(t / attack, 1.0) * np.exp(-decay * t / seconds)


def silence(seconds):
    return np.zeros(int(RATE * seconds))


def melody(notes, overlap=0.08):
    """Notas (frecuencia, duración, parámetros de tone) puestas una tras otra, un poco solapadas."""
    parts = [tone(f, d, **kw) for f, d, kw in notes]
    step = int(RATE * overlap)
    mixed = np.zeros(sum(len(p) for p in parts) - step * (len(parts) - 1))
    pos = 0
    for part in parts:
        mixed[pos:pos + len(part)] += part
        pos += len(part) - step
    return mixed


def save(path, samples, peak):
    """peak: volumen máximo (0-1). Los estados más graves suenan más fuerte."""
    samples = samples / np.max(np.abs(samples)) * peak
    with wave.open(path, "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(RATE)
        f.writeframes((samples * 32767).astype(np.int16).tobytes())


def normal():
    return melody([(784.0, 0.30, {"decay": 3.5}), (1046.5, 0.70, {"decay": 3.0})])                 # sol5 -> do6 (sube)


def caution():
    return melody([(987.8, 0.35, {"decay": 3.0}), (783.99, 0.75, {"decay": 3.0})])                 # si5 -> sol5 (baja)


def drowsiness():
    soft = {"decay": 3.0}
    return melody([(659.25, 0.40, soft), (523.25, 0.40, soft), (440.0, 1.10, {"decay": 2.5})])     # mi5 do5 la4 (menor)


def microsleep():
    harsh = {"harmonics": (1.0, 0.8, 0.65, 0.5, 0.4), "decay": 0.7, "attack": 0.004}
    pulses = [tone(f, 0.30, **harsh) for f in (196.0, 146.83)]                                      # sol3 / re3: graves
    return np.concatenate([np.concatenate([pulses[i % 2], silence(0.07)]) for i in range(6)])


if __name__ == "__main__":
    folder = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sounds")
    os.makedirs(folder, exist_ok=True)
    for name, samples, peak in (("normal", normal(), 0.35), ("precaucion", caution(), 0.5),
                                ("somnolencia", drowsiness(), 0.7), ("microsueno", microsleep(), 0.95)):
        save(os.path.join(folder, name + ".wav"), samples, peak)
    print("assets/sounds generado")
