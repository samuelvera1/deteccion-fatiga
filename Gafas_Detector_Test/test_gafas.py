# test_gafas_auto.py
import cv2
import numpy as np
import mediapipe as mp
from collections import deque

class DynamicGlassesDetector:
    """Módulo autónomo de detección dinámica de gafas en tiempo real (sin calibración manual)."""

    def __init__(self, window_size=12):
        self.window_size = window_size
        self.history = deque(maxlen=window_size)
        
        self.mp_face_mesh = mp.solutions.face_mesh
        self.face_mesh = self.mp_face_mesh.FaceMesh(
            max_num_faces=1,
            refine_landmarks=True,
            min_detection_confidence=0.6,
            min_tracking_confidence=0.6
        )
        self.has_glasses = False

    @staticmethod
    def _dist3d(p1, p2):
        """Calcula la distancia euclidiana en el espacio tridimensional 3D."""
        return float(np.linalg.norm(np.array(p1) - np.array(p2)))

    def evaluate_frame(self, frame):
        h, w, _ = frame.shape
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        results = self.face_mesh.process(rgb)

        if not results.multi_face_landmarks:
            return frame, self.has_glasses, 0.0

        face_landmarks = results.multi_face_landmarks[0].landmark
        
        # Mapeo de coordenadas 3D escaladas
        pts = np.array([[lm.x * w, lm.y * h, lm.z * w] for lm in face_landmarks])

        # Puntos clave de MediaPipe:
        # 168: Puente nasal superior | 6: Puente nasal inferior
        # 130: Esquina exterior ojo izq | 359: Esquina exterior ojo der
        p_bridge_top = pts[168]
        p_bridge_bot = pts[6]
        p_eye_left = pts[130]
        p_eye_right = pts[359]

        dist_eyes = self._dist3d(p_eye_left, p_eye_right)
        dist_bridge = self._dist3d(p_bridge_top, p_bridge_bot)

        if dist_eyes == 0:
            ratio_3d = 0.0
        else:
            # Proporción geométrica 3D adimensional
            ratio_3d = (dist_bridge / dist_eyes) * 100.0

        # Muestreo instantáneo (umbral geométrico base: 24.5)
        instant_detection = ratio_3d > 24.5
        self.history.append(instant_detection)

        # Transición por histéresis: requiere más del 65% de votos positivos en la ventana
        if len(self.history) == self.window_size:
            positive_votes = sum(self.history)
            if positive_votes >= int(self.window_size * 0.65):
                self.has_glasses = True
            elif positive_votes <= int(self.window_size * 0.35):
                self.has_glasses = False

        # Visualización en pantalla
        color = (0, 255, 0) if self.has_glasses else (0, 0, 255)
        texto = f"ESTADO: {'CON GAFAS' if self.has_glasses else 'SIN GAFAS'}"
        
        cv2.rectangle(frame, (20, 20), (450, 90), (0, 0, 0), -1)
        cv2.putText(frame, texto, (35, 55), cv2.FONT_HERSHEY_COMPLEX, 0.8, color, 2)
        cv2.putText(frame, f"Ratio 3D Continuo: {ratio_3d:.2f}", (35, 80), 
                    cv2.FONT_HERSHEY_COMPLEX, 0.5, (200, 200, 200), 1)

        # Dibujar los puntos del puente nasal para referencia visual
        cv2.circle(frame, (int(p_bridge_top[0]), int(p_bridge_top[1])), 3, (0, 255, 255), -1)
        cv2.circle(frame, (int(p_bridge_bot[0]), int(p_bridge_bot[1])), 3, (0, 255, 255), -1)

        return frame, self.has_glasses, ratio_3d

    def run(self, video_source=0):
        cap = cv2.VideoCapture(video_source)
        print("\n=======================================================")
        print("  DETECTOR DINÁMICO DE GAFAS (AUTOMÁTICO EN TIEMPO REAL)")
        print("=======================================================")
        print("  - Pongase y quitese las gafas frente a la camara.")
        print("  - Presione 'q' para salir.")
        print("=======================================================\n")

        while True:
            ret, frame = cap.read()
            if not ret:
                print("Error al acceder a la camara.")
                break

            frame, glasses_active, ratio = self.evaluate_frame(frame)
            cv2.imshow("Prueba Automatica de Gafas", frame)

            if cv2.waitKey(1) & 0xFF == ord('q'):
                break

        cap.release()
        cv2.destroyAllWindows()

if __name__ == "__main__":
    detector = DynamicGlassesDetector(window_size=12)
    detector.run()