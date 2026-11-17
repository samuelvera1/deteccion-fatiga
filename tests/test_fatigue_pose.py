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


if __name__ == "__main__":
    unittest.main()
