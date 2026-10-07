# test_gafas_roi.py
import cv2
import numpy as np
import mediapipe as mp
from collections import deque

class ROIGlassesDetector:
    """Detector de gafas por densidad de bordes en ROI calibrado a 9.5%."""

    def __init__(self, history_size=8):
        self.history = deque(maxlen=history_size)
        self.mp_face_mesh = mp.solutions.face_mesh
        self.face_mesh = self.mp_face_mesh.FaceMesh(
            max_num_faces=1,
            refine_landmarks=True,
            min_detection_confidence=0.6,
            min_tracking_confidence=0.6
        )
        self.has_glasses = False

    def process_frame(self, frame):
        h, w, _ = frame.shape
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        results = self.face_mesh.process(rgb)

        if not results.multi_face_landmarks:
            return frame, False, 0.0

        face = results.multi_face_landmarks[0].landmark

        # ROI enfocada en la zona media de los ojos (omite cejas)
        x_min = int(min(face[130].x, face[226].x) * w)
        x_max = int(max(face[359].x, face[446].x) * w)
        y_min = int(min(face[159].y, face[386].y) * h) - 5
        y_max = int(max(face[145].y, face[374].y) * h) + 15

        x_min = max(0, x_min)
        x_max = min(w, x_max)
        y_min = max(0, y_min)
        y_max = min(h, y_max)

        roi = frame[y_min:y_max, x_min:x_max]
        if roi.size == 0:
            return frame, False, 0.0

        # Filtro de textura
        gray_roi = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        blurred_roi = cv2.GaussianBlur(gray_roi, (3, 3), 0)
        edges = cv2.Canny(blurred_roi, threshold1=40, threshold2=110)

        # Densidad de bordes (%)
        edge_density = (np.count_nonzero(edges) / edges.size) * 100.0

        # Umbral optimizado a 9.5% basado en la telemetría real de tu video
        instant_detection = edge_density > 9.5
        self.history.append(instant_detection)

        if len(self.history) == self.history.maxlen:
            positive_votes = sum(self.history)
            self.has_glasses = positive_votes >= (self.history.maxlen * 0.5)

        # Renderizado de prueba
        cv2.rectangle(frame, (x_min, y_min), (x_max, y_max), (255, 255, 0), 1)

        edges_bgr = cv2.cvtColor(edges, cv2.COLOR_GRAY2BGR)
        edges_resized = cv2.resize(edges_bgr, (150, 60))
        frame[10:70, w-160:w-10] = edges_resized

        color = (0, 255, 0) if self.has_glasses else (0, 0, 255)
        texto = f"GAFAS: {'SI' if self.has_glasses else 'NO'}"
        
        cv2.rectangle(frame, (20, 20), (380, 90), (0, 0, 0), -1)
        cv2.putText(frame, texto, (35, 55), cv2.FONT_HERSHEY_COMPLEX, 0.8, color, 2)
        cv2.putText(frame, f"Densidad Bordes ROI: {edge_density:.2f}%", (35, 80), 
                    cv2.FONT_HERSHEY_COMPLEX, 0.5, (200, 200, 200), 1)

        return frame, self.has_glasses, edge_density

    def run(self, video_source=0):
        cap = cv2.VideoCapture(video_source)
        print("\n=======================================================")
        print("  DETECTOR DE GAFAS POR DENSIDAD EN ROI (UMBRAL 9.5%) ")
        print("=======================================================\n")

        while True:
            ret, frame = cap.read()
            if not ret:
                break

            frame, glasses_active, density = self.process_frame(frame)
            cv2.imshow("Prueba ROI Deteccion de Gafas", frame)

            if cv2.waitKey(1) & 0xFF == ord('q'):
                break

        cap.release()
        cv2.destroyAllWindows()

if __name__ == "__main__":
    detector = ROIGlassesDetector()
    detector.run()