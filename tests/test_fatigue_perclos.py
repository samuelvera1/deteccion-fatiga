# tests/test_fatigue_perclos.py
"""Pruebas de la ventana de PERCLOS ponderada por tiempo."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fatigue_perclos import PerclosWindow  # noqa: E402


def feed(window, closed_pattern, dt=0.1, start=0.0):
    t = start
    for closed in closed_pattern:
        window.update(closed, t)
        t += dt
    return t


class PerclosWindowTest(unittest.TestCase):
    def test_denominador_minimo_evita_inflar_el_inicio(self):
        w = PerclosWindow(60, 15)
        feed(w, [True] * 10)                 # 1 s cerrado, pero el denominador mínimo es 15 s
        self.assertLess(w.value, 10.0)

    def test_mitad_cerrado(self):
        w = PerclosWindow(60, 15)
        feed(w, ([True] * 10 + [False] * 10) * 100)
        self.assertAlmostEqual(w.value, 50.0, delta=1.0)

    def test_ventana_olvida_lo_antiguo(self):
        w = PerclosWindow(10, 5)
        t = feed(w, [True] * 100)            # 10 s cerrado
        feed(w, [False] * 200, start=t)      # 20 s abierto: lo cerrado sale de la ventana
        self.assertAlmostEqual(w.value, 0.0, places=6)

    def test_hueco_largo_pesa_como_maximo_0_2_s(self):
        w = PerclosWindow(60, 15)
        w.update(False, 0.0)
        w.update(True, 30.0)                 # pausa de 30 s: pesa 0.2 s
        self.assertAlmostEqual(w.total_time, PerclosWindow.MAX_FRAME_WEIGHT)

    def test_skip_gap_no_pesa(self):
        w = PerclosWindow(60, 15)
        w.update(False, 0.0)
        w.skip_gap()
        w.update(True, 5.0)
        self.assertAlmostEqual(w.total_time, 0.0)


if __name__ == "__main__":
    unittest.main()
