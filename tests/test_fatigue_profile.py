# tests/test_fatigue_profile.py
"""Paso de ojos cerrados: los parpadeos espontáneos no deben contar como "ojo cerrado medido"."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fatigue_config import Thresholds  # noqa: E402
from fatigue_profile import SustainedClosureFilter  # noqa: E402

FPS = 30.0


def feed(states):
    """states: secuencia de True (bajo el umbral) / False; devuelve cuántos cuadros pasan a contar."""
    f = SustainedClosureFilter(Thresholds.CLOSED_MIN_SUSTAINED_S, Thresholds.CLOSED_GAP_FRAMES)
    return sum(len(f.update(0.03, below, i / FPS)) for i, below in enumerate(states))


class SustainedClosureTest(unittest.TestCase):
    def test_parpadeos_espontaneos_no_cuentan(self):
        blinks = ([False] * 20 + [True] * 6) * 12          # 12 parpadeos de 0,2 s durante el paso
        self.assertEqual(feed(blinks), 0)

    def test_cierre_sostenido_cuenta_entero(self):
        self.assertEqual(feed([False] * 10 + [True] * 40 + [False] * 10), 40)

    def test_un_hueco_corto_no_corta_el_cierre(self):
        closure = [True] * 10 + [False] * 2 + [True] * 20   # 2 cuadros de ruido de la malla a mitad del cierre
        self.assertEqual(feed(closure), 30)

    def test_un_hueco_largo_corta_el_cierre(self):
        self.assertEqual(feed([True] * 12 + [False] * 5 + [True] * 12), 0)


if __name__ == "__main__":
    unittest.main()
