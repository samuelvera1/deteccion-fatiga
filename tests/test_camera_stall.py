"""Cámara en vivo que deja de dar imágenes un momento (FatigueMonitor._wait_for_camera)."""
import contextlib
import io
import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fatigue_framework import FatigueMonitor  # noqa: E402

FRAME = np.zeros((4, 4, 3), dtype=np.uint8)


class FakeCapture:
    """Cámara falsa: falla `failures` lecturas y luego da imágenes (o nunca, con failures=None)."""

    def __init__(self, failures):
        self.failures, self.released = failures, False

    def read(self):
        if self.failures is None or self.failures > 0:
            if self.failures:
                self.failures -= 1
            return False, None
        return True, FRAME

    def release(self):
        self.released = True

    def set(self, *_):
        return True

    def get(self, *_):
        return 0.0


class OpenWindow:
    def is_open(self):
        return True


class CameraStallTest(unittest.TestCase):
    def setUp(self):
        self.monitor = FatigueMonitor(video_source=0, save_trace=False, alert_sound=False, capture_size=None)
        self.monitor.CAMERA_STALL_S, self.monitor.CAMERA_REOPEN_S = 0.6, 0.2

    def wait(self, cap, reopened):
        with contextlib.redirect_stdout(io.StringIO()) as out:
            img, cap = self.monitor._wait_for_camera(cap, OpenWindow(), open_capture=lambda _src: reopened)
        return img, cap, out.getvalue()

    def test_recovers_without_reopening(self):
        self.monitor.CAMERA_REOPEN_S = 5.0          # vuelve sola antes de que toque reabrirla
        cap = FakeCapture(failures=2)
        img, same, log = self.wait(cap, FakeCapture(None))
        self.assertIs(img, FRAME)
        self.assertIs(same, cap)
        self.assertIn("volvió", log)

    def test_reopens_a_camera_that_stays_broken(self):
        broken, fresh = FakeCapture(None), FakeCapture(0)
        img, cap, _ = self.wait(broken, fresh)
        self.assertIs(img, FRAME)
        self.assertIs(cap, fresh)
        self.assertTrue(broken.released)

    def test_gives_up_and_explains(self):
        img, _, log = self.wait(FakeCapture(None), FakeCapture(None))
        self.assertIsNone(img)
        self.assertIn("otro programa", log)


if __name__ == "__main__":
    unittest.main()
