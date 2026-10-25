# tests/test_fatigue_yawn.py
"""Pruebas del detector de bostezos: bostezo, boca abierta breve y sonrisa descartada."""
import os
import sys
import unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fatigue_yawn import YawnDetector  # noqa: E402

TIERS = [(1.65, 0.25, 0.5), (1.30, 0.15, 0.35)]    # exagerado, micro (valores por defecto del monitor)
FPS = 30


def make_detector():
    profile = SimpleNamespace(neutral_mouth_ratio=0.0, neutral_mouth_width=1.0, neutral_jaw=1.0, neutral_corner_lift=0.0)
    events = []
    detector = YawnDetector(profile, TIERS, lambda *args: events.append(args[0]))
    return detector, events


def run(detector, mouth_per_frame, shape=(0.9, 1.2, 0.0), start=0.0):
    for i, mouth in enumerate(mouth_per_frame):
        detector.update(mouth, start + i / FPS, 0.1, shape)
    return start + len(mouth_per_frame) / FPS


class YawnDetectorTest(unittest.TestCase):
    def test_boca_cerrada_no_cuenta(self):
        detector, events = make_detector()
        run(detector, [0.0] * 90)
        self.assertEqual((detector.count, events), (0, []))

    def test_bostezo_exagerado(self):
        detector, events = make_detector()
        t = run(detector, [0.6] * 30)                  # 1 s con la boca muy abierta, mandíbula caída
        run(detector, [0.0] * 10, start=t)
        self.assertEqual(detector.count, 1)
        self.assertEqual(events, ["BOSTEZO"])

    def test_apertura_breve_no_cuenta(self):
        detector, events = make_detector()
        t = run(detector, [0.6] * 5)                   # 0.17 s: menos que el mínimo de ambos niveles
        run(detector, [0.0] * 10, start=t)
        self.assertEqual(detector.count, 0)

    def test_sonrisa_se_descarta_y_se_registra(self):
        detector, events = make_detector()
        smile = (1.4, 1.05, 0.0)                       # boca 40 % más ancha, sin caída de mandíbula
        t = run(detector, [0.6] * 30, shape=smile)
        run(detector, [0.0] * 10, shape=smile, start=t)
        self.assertEqual(detector.count, 0)
        self.assertEqual(detector.smile_count, 1)
        self.assertEqual(events, ["SONRISA"])

    def test_callback_al_contar(self):
        detector, _ = make_detector()
        totals = []
        detector.on_yawn = totals.append
        run(detector, [0.6] * 30)
        self.assertEqual(totals, [1])


if __name__ == "__main__":
    unittest.main()
