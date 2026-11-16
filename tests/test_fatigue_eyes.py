# tests/test_fatigue_eyes.py
"""Profundidad mínima del parpadeo (experimento E2): una caída poco profunda de la apertura no es un parpadeo."""
import os
import sys
import unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fatigue_eyes import EyeEventDetector  # noqa: E402
from fatigue_perclos import PerclosWindow  # noqa: E402
from fatigue_profile import SubjectProfile  # noqa: E402

FPS = 30.0
OPEN = 0.12


def run(depth, frames=4):
    """Ojo abierto 1,5 s, una caída de la apertura de la profundidad dada durante `frames` cuadros y 1 s abierto."""
    profile = SubjectProfile()
    profile.open_ear_baseline, profile.closed_ear_level, profile.closed_level_measured = OPEN, 0.04, True
    events = []
    eyes = EyeEventDetector(profile, PerclosWindow(60, 15), SimpleNamespace(speed=0.0),
                            lambda kind, *args, **kwargs: events.append(kind))
    signal = [OPEN] * 45 + [OPEN * (1 - depth)] * frames + [OPEN] * 30
    for i, ear in enumerate(signal):
        eyes.update(ear, False, i / FPS)
    return eyes, events


class BlinkDepthTest(unittest.TestCase):
    def test_caida_poco_profunda_no_cuenta(self):
        eyes, events = run(0.25)                     # entra por debajo de 0,79 x referencia, pero no llega al 30 %
        self.assertEqual(eyes.blink_count, 0)
        self.assertEqual(eyes.shallow_rejected, 1)
        self.assertIn("PARPADEO_DESCARTADO_PROFUNDIDAD", events)

    def test_parpadeo_profundo_cuenta(self):
        eyes, events = run(0.5)
        self.assertEqual(eyes.blink_count, 1)
        self.assertEqual(eyes.shallow_rejected, 0)
        self.assertIn("PARPADEO", events)

    def test_algo_por_encima_del_umbral_cuenta(self):
        eyes, _ = run(EyeEventDetector.BLINK_MIN_DEPTH + 0.01)
        self.assertEqual(eyes.blink_count, 1)


if __name__ == "__main__":
    unittest.main()
