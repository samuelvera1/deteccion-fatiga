# assets/make_sounds.py
"""Genera las melodías de advertencia (assets/sounds/*.wav) con síntesis simple: son propias, sin derechos de autor.
    python assets/make_sounds.py
  somnolencia.wav  arpegio ascendente y suave (do-mi-sol-do), para un aviso que invita a descansar.
  microsueno.wav   dos tonos alternados y más fuertes, para un aviso urgente."""
import os
import wave

import numpy as np

RATE = 44100


def tone(freq, seconds, volume=1.0, harmonics=(1.0, 0.35, 0.15), decay=4.0, attack=0.01):
    t = np.arange(int(RATE * seconds)) / RATE
    wave_ = sum(amp * np.sin(2 * np.pi * freq * (i + 1) * t) for i, amp in enumerate(harmonics))
    envelope = np.minimum(t / attack, 1.0) * np.exp(-decay * t / seconds)
    return volume * wave_ * envelope


def silence(seconds):
    return np.zeros(int(RATE * seconds))


def save(path, samples):
    samples = samples / np.max(np.abs(samples)) * 0.85
    with wave.open(path, "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(RATE)
        f.writeframes((samples * 32767).astype(np.int16).tobytes())


def drowsiness():
    notes = [523.25, 659.25, 783.99, 1046.50]                   # do5, mi5, sol5, do6
    parts = [tone(f, 0.45, decay=3.0) for f in notes[:-1]] + [tone(notes[-1], 1.1, decay=2.5)]
    mixed = np.zeros(sum(len(p) for p in parts) - 3 * int(RATE * 0.1))
    pos = 0
    for part in parts:                                           # las notas se solapan un poco (más musical)
        mixed[pos:pos + len(part)] += part[:len(mixed) - pos]
        pos += len(part) - int(RATE * 0.1)
    return mixed


def microsleep():
    pulse = [tone(f, 0.26, harmonics=(1.0, 0.6, 0.4), decay=0.8, attack=0.004) for f in (880.0, 660.0)]
    return np.concatenate([np.concatenate([pulse[i % 2], silence(0.07)]) for i in range(6)])


if __name__ == "__main__":
    folder = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sounds")
    os.makedirs(folder, exist_ok=True)
    save(os.path.join(folder, "somnolencia.wav"), drowsiness())
    save(os.path.join(folder, "microsueno.wav"), microsleep())
    print("assets/sounds generado")
