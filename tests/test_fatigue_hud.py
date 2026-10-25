# tests/test_fatigue_hud.py
"""Prueba de humo del dibujo del HUD: cada fase se pinta sin errores y modifica el fotograma."""
import os
import sys
import unittest
from unittest import mock

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import calibration_marks  # noqa: E402
import fatigue_hud  # noqa: E402
from fatigue_framework import FatigueMonitor  # noqa: E402


class FatigueHudTest(unittest.TestCase):
    def setUp(self):
        self.monitor = FatigueMonitor(video_source="x.mp4", save_trace=False, alert_sound=False)

    def render(self, phase):
        """Pinta con la fase forzada (phase es una propiedad de solo lectura del monitor)."""
        img = np.zeros((720, 1280, 3), np.uint8)
        with mock.patch.object(FatigueMonitor, "phase", new_callable=mock.PropertyMock, return_value=phase):
            fatigue_hud.draw_hud(img, self.monitor, 12.0, None, False, False)
            fatigue_hud.draw_phase_overlay(img, self.monitor)
        return img

    def test_todas_las_fases(self):
        self.monitor.manual_marks = {"inicio_prueba": {"s": 3.0}}
        for phase in (FatigueMonitor.FASE_ROSTRO, FatigueMonitor.FASE_CIERRE, FatigueMonitor.FASE_REAPERTURA,
                      FatigueMonitor.FASE_MONITOREO):
            with self.subTest(phase=phase):
                self.assertGreater(int(self.render(phase).sum()), 0)

    def test_aviso_de_reintento_de_ojos_cerrados(self):
        self.monitor._closed_retry_until, self.monitor._closed_attempt = 5.0, 2
        self.assertGreater(int(self.render(FatigueMonitor.FASE_CIERRE).sum()), 0)

    def test_fase_marcas_manuales(self):
        marks = {"neutro": {"inicio_s": 0, "fin_s": 1}, "cerrado": {"inicio_s": 1, "fin_s": 2},
                 "inicio_prueba": {"s": 3.0}}
        with mock.patch.object(calibration_marks, "frame_ranges", return_value=(0, 10, 10, 20, 30)):
            self.monitor.manual_marks = marks
            self.assertGreater(int(self.render(FatigueMonitor.FASE_MARCAS).sum()), 0)

    def test_microsueno_y_bostezo(self):
        img = np.zeros((720, 1280, 3), np.uint8)
        fatigue_hud.draw_hud(img, self.monitor, 40.0, True, True, False)
        fatigue_hud.draw_hud(img, self.monitor, 40.0, False, False, True)
        self.assertGreater(int(img.sum()), 0)


if __name__ == "__main__":
    unittest.main()
