"""Postura relativa a la calibración y ángulo de la cámara (fatigue_pose.HeadPoseTracker)."""
import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fatigue_pose import HeadPoseTracker  # noqa: E402


def rot_y(deg):
    a = np.radians(deg)
    return np.array([[np.cos(a), 0.0, np.sin(a)], [0.0, 1.0, 0.0], [-np.sin(a), 0.0, np.cos(a)]])


def rot_x(deg):
    a = np.radians(deg)
    return np.array([[1.0, 0.0, 0.0], [0.0, np.cos(a), -np.sin(a)], [0.0, np.sin(a), np.cos(a)]])


def face(rotation):
    """Malla 3D mínima (los puntos que usa face_axes) de una cara con esa orientación respecto a la cámara."""
    pts = np.zeros((478, 3))
    local = {33: (-1.2, 0, 0), 133: (-0.8, 0, 0), 362: (0.8, 0, 0), 263: (1.2, 0, 0), 10: (0, -1.5, 0), 152: (0, 2, 0)}
    for idx, p in local.items():
        pts[idx] = rotation @ np.array(p, dtype=float) + np.array([0.0, 0.0, 10.0])
    return pts


def calibrated(rotation):
    head = HeadPoseTracker(max_pitch=10.0, max_yaw=40.0, frontal_max=15.0, on_out_of_range=lambda d: None)
    for k in range(5):
        head.update(face(rotation), now=k / 30)
        head.add_calibration_sample()
    head.lock_reference()
    return head


class CameraAnglesTest(unittest.TestCase):
    def test_frontal_camera(self):
        yaw, pitch = calibrated(np.eye(3)).camera_angles
        self.assertAlmostEqual(yaw, 0.0, places=6)
        self.assertAlmostEqual(pitch, 0.0, places=6)

    def test_side_camera(self):
        yaw, pitch = calibrated(rot_y(35.0)).camera_angles
        self.assertAlmostEqual(abs(yaw), 35.0, places=6)
        self.assertAlmostEqual(pitch, 0.0, places=6)

    def test_camera_below_and_to_the_side(self):
        yaw, pitch = calibrated(rot_y(-30.0) @ rot_x(12.0)).camera_angles
        self.assertAlmostEqual(abs(yaw), 30.0, places=6)
        self.assertAlmostEqual(abs(pitch), 12.0, places=6)

    def test_without_reference(self):
        head = HeadPoseTracker(max_pitch=10.0, max_yaw=40.0, frontal_max=15.0, on_out_of_range=lambda d: None)
        self.assertIsNone(head.camera_angles)

    def test_pitch_limit_is_asymmetric(self):
        """E12: cabeza hacia abajo hasta 10°, hacia arriba hasta 15° (pitch positivo = abajo)."""
        head = HeadPoseTracker((10.0, 15.0), 40.0, 15.0, on_out_of_range=lambda d: None)
        for k in range(5):
            head.update(face(np.eye(3)), now=k / 30)
            head.add_calibration_sample()
        head.lock_reference()
        for deg, valid in ((9.0, True), (12.0, False), (-12.0, True), (-14.5, True), (-16.0, False)):
            head.update(face(rot_x(deg)), now=1.0)
            self.assertAlmostEqual(head.pose[1], deg, places=6)
            self.assertEqual(head.eye_valid, valid, deg)

    def test_valid_range_is_relative_to_calibration(self):
        """Con la cámara a 35° de costado, mirar la pantalla como en la calibración es postura válida; girar 45° más
        desde ahí no lo es, aunque con la cámara de frente ese mismo giro absoluto (10°) sería válido."""
        head = calibrated(rot_y(35.0))
        head.update(face(rot_y(35.0)), now=1.0)
        self.assertTrue(head.eye_valid)
        self.assertAlmostEqual(head.pose[0], 0.0, places=6)
        head.update(face(rot_y(-10.0)), now=2.0)
        self.assertAlmostEqual(abs(head.pose[0]), 45.0, places=6)
        self.assertFalse(head.eye_valid)



class PostureRebaseTest(unittest.TestCase):
    """E14: postura fuera de rango y quieta 20 s -> referencia y ojo abierto rehechos."""

    def run_frames(self, rotation, seconds, ear=0.10, start=1.0, fps=30.0):
        result = None
        for k in range(int(seconds * fps)):
            now = start + k / fps
            self.head.update(face(rotation), now)
            valid = self.head.track_range(now)
            got = self.rebaser.update(self.head, now, valid, ear if k % 40 else ear * 0.3)   # un parpadeo cada 40
            result = got if got is not None else result
        return result

    def setUp(self):
        from fatigue_pose import SustainedPostureRebaser
        self.head = calibrated(np.eye(3))
        self.head.max_pitch_down, self.head.max_pitch_up = 10.0, 15.0
        self.rebaser = SustainedPostureRebaser(hold_s=20.0, max_std=4.0, cap_pitch=30.0, cap_yaw=40.0)

    def test_sustained_new_posture_is_rebased(self):
        self.assertIsNone(self.run_frames(rot_x(13.0), 15.0))          # 15 s: todavía no
        new_open = self.run_frames(rot_x(13.0), 6.0, start=16.0)        # pasa de 20 s seguidos
        self.assertAlmostEqual(new_open, 0.10)                          # sin los parpadeos
        self.assertEqual(self.rebaser.count, 1)
        self.head.update(face(rot_x(13.0)), 30.0)
        self.assertTrue(self.head.eye_valid)
        self.assertAlmostEqual(abs(self.head.pose[1]), 0.0, places=6)
        self.assertAlmostEqual(self.head.camera_angles[1], 0.0, places=6)   # la calibración original no cambia
        self.head.update(face(np.eye(3)), 31.0)                              # volver a la postura original:
        self.assertAlmostEqual(abs(self.head.pose[1]), 13.0, places=6)       # 13° respecto a la nueva referencia

    def test_moving_head_is_not_rebased(self):
        result = None
        for k in range(30 * 25):
            now = 1.0 + k / 30
            deg = 12.0 + 8.0 * np.sin(k / 15)                       # fuera de rango pero moviéndose (±8°)
            self.head.update(face(rot_x(deg)), now)
            got = self.rebaser.update(self.head, now, self.head.track_range(now), 0.1)
            result = got if got is not None else result
        self.assertIsNone(result)

    def test_beyond_cap_is_not_rebased(self):
        self.assertIsNone(self.run_frames(rot_x(35.0), 25.0))      # 35° respecto a la calibración: más allá del tope


class CameraLimitWarningTest(unittest.TestCase):
    """Límite declarado (E10): con la cámara a más de 40° de la cara se avisa al calibrar."""

    def warn(self, deg):
        import contextlib
        import io

        from fatigue_framework import FatigueMonitor
        monitor = FatigueMonitor(video_source="x.mp4", save_trace=False, alert_sound=False)
        monitor.head.ref0 = rot_y(deg)
        with contextlib.redirect_stdout(io.StringIO()) as out:
            monitor._warn_if_camera_too_far_aside()
        return out.getvalue()

    def test_warns_beyond_limit_only(self):
        self.assertEqual(self.warn(30.0), "")
        self.assertIn("muy de lado", self.warn(44.0))
        self.assertIn("muy de lado", self.warn(-47.0))


if __name__ == "__main__":
    unittest.main()
