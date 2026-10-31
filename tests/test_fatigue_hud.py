# tests/test_fatigue_hud.py
"""Pruebas del HUD: cada estado de la pantalla se pinta sin errores, con el tamaño esperado y sin desbordes."""
import os
import sys
import unittest
from unittest import mock

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import calibration_marks  # noqa: E402
import fatigue_hud  # noqa: E402
from fatigue_alert import LEVELS, MICRO_SUENO, NORMAL  # noqa: E402
from fatigue_framework import FatigueMonitor  # noqa: E402


class FatigueHudTest(unittest.TestCase):
    def setUp(self):
        self.monitor = FatigueMonitor(video_source="x.mp4", save_trace=False, alert_sound=False)
        self.camera = np.full((720, 1280, 3), 90, np.uint8)

    def render(self, phase, level=NORMAL, reliable=True, microsleep=False, yawning=False):
        """Pinta con la fase y el nivel forzados (phase y closure_reliable son propiedades de solo lectura)."""
        self.monitor.alert.level = level
        with mock.patch.object(FatigueMonitor, "phase", new_callable=mock.PropertyMock, return_value=phase), \
                mock.patch.object(FatigueMonitor, "closure_reliable", new_callable=mock.PropertyMock,
                                  return_value=reliable):
            return self.monitor.hud.render(self.camera, self.monitor, microsleep, yawning)

    def test_tamano_de_la_pantalla(self):
        frame = self.render(FatigueMonitor.FASE_MONITOREO)
        self.assertEqual(frame.shape, (fatigue_hud.HEIGHT, fatigue_hud.WIDTH, 3))

    def test_los_cuatro_niveles(self):
        frames = {level: self.render(FatigueMonitor.FASE_MONITOREO, level) for level in LEVELS}
        for a in LEVELS:
            for b in LEVELS:
                if a < b:
                    self.assertFalse(np.array_equal(frames[a], frames[b]), f"{a} y {b} se ven igual")

    def test_todas_las_fases_de_calibracion(self):
        self.monitor.manual_marks = {"inicio_prueba": {"s": 3.0}}
        for phase in (FatigueMonitor.FASE_ROSTRO, FatigueMonitor.FASE_CIERRE, FatigueMonitor.FASE_REAPERTURA):
            with self.subTest(phase=phase):
                self.assertEqual(self.render(phase).shape[2], 3)

    def test_aviso_de_reintento_de_ojos_cerrados(self):
        self.monitor._closed_retry_until, self.monitor._closed_attempt = 5.0, 2
        retry = self.render(FatigueMonitor.FASE_CIERRE)
        self.monitor._closed_retry_until = None
        normal = self.render(FatigueMonitor.FASE_CIERRE)
        self.assertFalse(np.array_equal(retry, normal))

    def test_fase_marcas_manuales(self):
        self.monitor.manual_marks = {"neutro": {"inicio_s": 0, "fin_s": 1}, "cerrado": {"inicio_s": 1, "fin_s": 2},
                                     "inicio_prueba": {"s": 3.0}}
        with mock.patch.object(calibration_marks, "frame_ranges", return_value=(0, 10, 10, 20, 30)):
            self.assertEqual(self.render(FatigueMonitor.FASE_MARCAS).shape[2], 3)

    def test_ojo_cerrado_no_medido_cambia_el_panel(self):
        self.assertFalse(np.array_equal(self.render(FatigueMonitor.FASE_MONITOREO, reliable=True),
                                        self.render(FatigueMonitor.FASE_MONITOREO, reliable=False)))

    def test_avisos_de_microsueno_y_bostezo(self):
        base = self.render(FatigueMonitor.FASE_MONITOREO, MICRO_SUENO)
        self.assertFalse(np.array_equal(base, self.render(FatigueMonitor.FASE_MONITOREO, MICRO_SUENO, microsleep=True)))
        self.assertFalse(np.array_equal(base, self.render(FatigueMonitor.FASE_MONITOREO, MICRO_SUENO, yawning=True)))

    def test_camara_4_3_y_16_9(self):
        wide = self.render(FatigueMonitor.FASE_MONITOREO)
        self.camera = np.full((480, 640, 3), 90, np.uint8)
        self.assertEqual(self.render(FatigueMonitor.FASE_MONITOREO).shape, wide.shape)

    def test_ajuste_a_cualquier_tamano_de_ventana(self):
        frame = self.render(FatigueMonitor.FASE_MONITOREO)
        for size in ((1920, 1080), (1366, 700), (800, 600), (1280, 720), (500, 900)):
            with self.subTest(size=size):
                out = fatigue_hud.fit_to_window(frame, size)
                self.assertEqual(out.shape, (size[1], size[0], 3))

    def test_el_ajuste_no_deforma(self):
        """En una ventana más ancha, la imagen conserva su proporción y deja franjas a los lados."""
        frame = np.zeros((720, 1280, 3), np.uint8)
        frame[:] = (200, 50, 50)
        out = fatigue_hud.fit_to_window(frame, (2000, 720))
        content_cols = np.where((out == (200, 50, 50)).all(axis=2).any(axis=0))[0]
        self.assertEqual(content_cols[-1] - content_cols[0] + 1, 1280)

    def test_normal_sin_datos_suficientes_no_dice_por_debajo(self):
        """Con la ventana de PERCLOS incompleta el nivel es NORMAL por falta de datos, no por PERCLOS bajo."""
        self.monitor.perclos.total_time = 20.0
        incomplete = self.render(FatigueMonitor.FASE_MONITOREO)
        self.monitor.perclos.total_time = 60.0
        complete = self.render(FatigueMonitor.FASE_MONITOREO)
        self.assertFalse(np.array_equal(incomplete, complete))

    def test_reuniendo_datos_explica_si_es_por_la_postura(self):
        """Con datos incompletos el panel no dice NORMAL: dice que reúne datos, y por qué (postura u otro motivo)."""
        self.monitor.perclos.total_time = 41.0
        by_time = self.render(FatigueMonitor.FASE_MONITOREO)
        self.monitor.head.pose = (0.0, 30.0, 0.0)               # fuera de rango
        by_pose = self.render(FatigueMonitor.FASE_MONITOREO)
        self.assertFalse(np.array_equal(by_time, by_pose))
        self.monitor.perclos.total_time = 60.0
        self.monitor.head.pose = None
        self.assertFalse(np.array_equal(by_time, self.render(FatigueMonitor.FASE_MONITOREO)))

    def test_nivel_provisional_segun_el_perclos_que_se_lleva(self):
        """Con datos incompletos (pero suficientes para estimar) se muestra un nivel provisional que depende del PERCLOS."""
        self.monitor.perclos.total_time = 30.0
        frames = {}
        for value in (2.0, 9.0, 14.0):
            self.monitor.perclos.value = value
            frames[value] = self.render(FatigueMonitor.FASE_MONITOREO)
        self.assertFalse(np.array_equal(frames[2.0], frames[9.0]))
        self.assertFalse(np.array_equal(frames[9.0], frames[14.0]))

    def test_provisional_solo_si_hay_datos_para_estimar(self):
        self.monitor.perclos.value = 14.0
        self.monitor.perclos.total_time = 5.0                   # menos que el denominador mínimo: no se estima
        too_early = self.render(FatigueMonitor.FASE_MONITOREO)
        self.monitor.perclos.value = 2.0
        also_early = self.render(FatigueMonitor.FASE_MONITOREO)
        panel = slice(16, 700), slice(880, 1264)
        np.testing.assert_array_equal(too_early[panel][:200], also_early[panel][:200])   # misma tarjeta de nivel

    def test_el_nombre_del_nivel_cabe_en_la_tarjeta(self):
        from PIL import Image, ImageDraw
        draw = ImageDraw.Draw(Image.new("RGB", (1, 1)))
        for name in fatigue_hud.LEVEL_NAMES.values():
            font = fatigue_hud._fit_font(draw, name, True, 44, 344)
            self.assertLessEqual(draw.textlength(name, font=font), 344)


if __name__ == "__main__":
    unittest.main()
