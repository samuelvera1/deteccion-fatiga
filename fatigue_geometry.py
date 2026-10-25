# fatigue_geometry.py
"""Medidas geométricas de la malla facial (funciones puras, sin estado): orientación de la cabeza, apertura
de ojos y boca, forma de la boca. Las distancias van en unidades de IPD para no depender de la distancia a la cámara."""
import numpy as np

from fatigue_core import FaceMeshDetector

distance = FaceMeshDetector.findDistance


def face_axes(face3d):
    """Ejes de la cabeza (columnas: derecha, abajo, adelante) a partir de landmarks 3D: línea entre los
    centros de los ojos y eje frente (10) -> mentón (152), ortonormalizados. Coordenadas de MediaPipe:
    x a la derecha, y hacia abajo, z alejándose de la cámara (z estimada por la red, no medida)."""
    p = np.asarray(face3d, dtype=np.float64)
    across = (p[362] + p[263]) / 2.0 - (p[33] + p[133]) / 2.0
    down = p[152] - p[10]
    if np.linalg.norm(across) < 1e-6:
        return None
    x = across / np.linalg.norm(across)
    y = down - np.dot(down, x) * x
    if np.linalg.norm(y) < 1e-6:
        return None                       # malla degenerada: frente y mentón alineados con los ojos
    y /= np.linalg.norm(y)
    axes = np.column_stack([x, y, np.cross(x, y)])
    return axes if np.all(np.isfinite(axes)) else None


def eye_opening(face, eye_indices, ipd):
    """EAR normalizado por IPD: apertura vertical media del ojo / IPD."""
    _, p2, p3, _, p5, p6 = [face[idx] for idx in eye_indices]
    vertical = (distance(p2, p6) + distance(p3, p5)) / 2.0
    return vertical / ipd if ipd > 0 else 0.0


def mouth_opening(face, ipd):
    """Apertura interna de los labios / IPD (el ancho de la boca cambia al bostezar; la IPD no)."""
    return distance(face[13], face[14]) / ipd if ipd > 0 else 0.0


def mouth_shape(face, ipd):
    """(ancho de boca, distancia nariz-mentón, elevación de comisuras) en unidades de IPD.
    La elevación se mide sobre el eje vertical de la cara (perpendicular a la línea de los ojos, hacia
    el mentón): positiva si las comisuras (61, 291) quedan por encima del labio superior interno (13)."""
    if ipd <= 0:
        return None
    pts = np.asarray(face, dtype=np.float64)
    across = (pts[362] + pts[263]) / 2.0 - (pts[33] + pts[133]) / 2.0
    norm = float(np.linalg.norm(across))
    if norm == 0:
        return None
    down = np.array([-across[1], across[0]]) / norm
    if np.dot(pts[152] - pts[1], down) < 0:          # vídeo espejado: el eje debe apuntar al mentón
        down = -down
    corners = (pts[61] + pts[291]) / 2.0
    width = float(np.linalg.norm(pts[61] - pts[291])) / ipd
    jaw = float(np.linalg.norm(pts[152] - pts[1])) / ipd
    lift = float(np.dot(pts[13] - corners, down)) / ipd
    return width, jaw, lift
