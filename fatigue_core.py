# fatigue_core.py
import cv2
import numpy as np

# --- IMPORTACIÓN PORTABLE UNIVERSAL (Python 3.8 a 3.14+) ---
mp_face_mesh = None
mp_drawing_utils = None

# Estrategia 1: Importación directa desde mediapipe.solutions (Estándar en 3.9-3.12)
try:
    import mediapipe.solutions.face_mesh as mp_face_mesh
    import mediapipe.solutions.drawing_utils as mp_drawing_utils
except (ModuleNotFoundError, AttributeError):
    pass

# Estrategia 2: Importación a través del objeto raíz 'mp' (Sistemas legacy)
if mp_face_mesh is None:
    try:
        import mediapipe as mp
        mp_face_mesh = mp.solutions.face_mesh
        mp_drawing_utils = mp.solutions.drawing_utils
    except (AttributeError, ModuleNotFoundError):
        pass

# Estrategia 3: Importación interna explícita (Entornos restringidos / CPython 3.13+)
if mp_face_mesh is None:
    try:
        import mediapipe.python.solutions.face_mesh as mp_face_mesh
        import mediapipe.python.solutions.drawing_utils as mp_drawing_utils
    except ModuleNotFoundError:
        pass

if mp_face_mesh is None or mp_drawing_utils is None:
    raise ImportError(
        "No se pudo cargar el módulo FaceMesh de MediaPipe. "
        "Asegúrate de tener instalada una versión compatible de 'mediapipe' y 'opencv-python'."
    )


class FaceMeshDetector:
    """Núcleo biométrico portátil para la extracción y procesamiento de la malla facial."""
    
    def __init__(self, staticMode=False, maxFaces=1, minDetectionCon=0.7, minTrackCon=0.7):
        self.staticMode = staticMode
        self.maxFaces = maxFaces
        self.minDetectionCon = minDetectionCon
        self.minTrackCon = minTrackCon

        self.mpDraw = mp_drawing_utils
        self.mpFaceMesh = mp_face_mesh
        
        self.faceMesh = self.mpFaceMesh.FaceMesh(
            static_image_mode=self.staticMode,
            max_num_faces=self.maxFaces,
            min_detection_confidence=self.minDetectionCon,
            min_tracking_confidence=self.minTrackCon
        )
        self.drawSpec = self.mpDraw.DrawingSpec(thickness=1, circle_radius=1)
        self.faces3d = []   # landmarks (x, y, z) en píxeles del último frame, mismo orden que faces

    def findFaceMesh(self, img, draw=True):
        imgRGB = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        results = self.faceMesh.process(imgRGB)
        faces = []
        self.faces3d = []
        if results.multi_face_landmarks:
            for faceLms in results.multi_face_landmarks:
                if draw:
                    self.mpDraw.draw_landmarks(
                        img, 
                        faceLms, 
                        self.mpFaceMesh.FACEMESH_CONTOURS,
                        self.drawSpec, 
                        self.drawSpec
                    )
                # Coordenadas sub-píxel: redondear a int añade ~±10% de ruido al EAR a 640x480.
                # z de MediaPipe usa aproximadamente la misma escala que x, por eso se multiplica por el ancho.
                h, w = img.shape[:2]
                face3d = np.array([[lm.x, lm.y, lm.z] for lm in faceLms.landmark]) * np.array([w, h, w])
                faces.append(face3d[:, :2])
                self.faces3d.append(face3d)
        return img, faces

    @staticmethod
    def findDistance(p1, p2):
        x1, y1 = p1
        x2, y2 = p2
        return float(np.hypot(x2 - x1, y2 - y1))