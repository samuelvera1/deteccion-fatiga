# session_recorder.py
import csv
import json
import os
import platform
import subprocess
import sys
import threading
import time
from datetime import datetime

import cv2
import numpy as np
import psutil


class ParticipantRegistry:
    """
    Seudonimización de participantes: asigna a cada nombre un código anónimo (S01, S02...) y guarda
    la relación nombre <-> código SOLO en un archivo privado local (excluido de git). Las sesiones,
    metadatos y resúmenes usan únicamente el código, de modo que los datos pueden compartirse sin
    exponer la identidad de los participantes.
    """

    HEADER = ["codigo", "nombre", "registrado"]

    def __init__(self, path="participantes_privado.csv"):
        self.path = path

    @staticmethod
    def _normalize(name):
        return " ".join(name.split()).casefold()

    def _load(self):
        if not os.path.exists(self.path):
            return []
        with open(self.path, newline="", encoding="utf-8") as f:
            return list(csv.DictReader(f))

    def code_for(self, name):
        """Código del participante; si el nombre es nuevo, lo registra con el siguiente código libre."""
        rows = self._load()
        key = self._normalize(name)
        for row in rows:
            if self._normalize(row["nombre"]) == key:
                return row["codigo"], False
        code = f"S{len(rows) + 1:02d}"
        new_file = not rows
        with open(self.path, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=self.HEADER)
            if new_file:
                writer.writeheader()
            writer.writerow({"codigo": code, "nombre": " ".join(name.split()),
                             "registrado": datetime.now().isoformat(timespec="seconds")})
        return code, True


class SessionRecorder:
    """
    Registro reproducible de una sesión experimental en sesiones/<AAAAMMDD_HHMMSS>_<sujeto>/:
      - metadata.json: sujeto, fuente, reloj usado, commit de git (y archivos con cambios sin commit),
        versiones de librerías, TODOS los parámetros del método, FPS reales, CPU/RAM y resumen.
      - eventos.csv: un registro por evento (parpadeo, bostezo, micro-sueño, calibraciones...).
      - traza.csv: métricas por frame (opcional), para re-ajustar umbrales sin volver a grabar.
    Además añade una fila por sesión a sesiones/resumen_sesiones.csv para comparar sesiones y sujetos.
    """

    EVENT_HEADER = ["t_s", "Timestamp", "Evento", "Fase", "PERCLOS_Pct", "Modo_Gafas", "Apertura_Ocular_IPD",
                    "Duracion_s"]
    SUMMARY_HEADER = ["sesion_id", "sujeto", "codigo_anonimo", "condicion", "inicio", "duracion_s", "fuente",
                      "commit", "cambios_sin_commit", "gafas_final", "parpadeos", "parpadeos_prolongados",
                      "proporcion_parpadeos_prolongados", "duracion_media_parpadeo_s", "bostezos", "micro_bostezos",
                      "sonrisas_descartadas", "tiempo_postura_fuera_de_rango_s",
                      "perclos_final_pct", "recalibraciones", "frames", "frames_con_rostro", "fps_medio",
                      "cpu_proceso_pct", "ram_proceso_mb"]

    def __init__(self, subject_id="anonimo", base_dir="sesiones", save_trace=True, condition=None,
                 subject_code=None):
        # El sujeto se guarda tal cual (p. ej. "Samuel Vera"); en el nombre de carpeta los espacios y
        # símbolos pasan a "_". subject_code (S01...) se guarda aparte para poder anonimizar después.
        self.subject_name = " ".join(str(subject_id).split()) or "anonimo"
        self.subject_id = self._safe_name(self.subject_name) or "anonimo"
        self.subject_code = subject_code
        self.condition = self._safe_name(condition) if condition else None
        self.started = datetime.now()
        self.session_id = f"{self.started:%Y%m%d_%H%M%S}_{self.subject_id}"
        self.base_dir = base_dir
        self.dir = os.path.join(base_dir, self.session_id)
        os.makedirs(self.dir, exist_ok=True)
        self.save_trace = save_trace

        self._events_file = open(os.path.join(self.dir, "eventos.csv"), "w", newline="", encoding="utf-8")
        self._events = csv.writer(self._events_file)
        self._events.writerow(self.EVENT_HEADER)
        self._trace_file = None
        self._trace = None

        self._frame_times = []
        self._last_tick = None
        self._cpu_samples, self._ram_samples = [], []
        self._sampling = False

        self.metadata = {
            "sesion_id": self.session_id,
            "sujeto": self.subject_name,
            "codigo_anonimo": self.subject_code,
            "condicion": self.condition,
            "inicio": self.started.isoformat(timespec="seconds"),
            "git": self._git_info(),
            "versiones": {"python": sys.version.split()[0], "opencv": cv2.__version__,
                          "mediapipe": self._module_version("mediapipe"), "numpy": np.__version__},
            "plataforma": platform.platform(),
        }

    # ------------------------------------------------------------------ información del entorno

    @staticmethod
    def _safe_name(text):
        return "".join(c if c.isalnum() or c in "-_" else "_" for c in str(text))

    @staticmethod
    def _module_version(name):
        try:
            return __import__(name).__version__
        except Exception:
            return None

    @staticmethod
    def _git_info():
        """Commit del código y archivos versionados con cambios sin commit (sesión no reproducible)."""
        here = os.path.dirname(os.path.abspath(__file__))

        def git(*args):
            return subprocess.run(["git", *args], cwd=here, capture_output=True, text=True, timeout=5).stdout

        try:
            commit = git("rev-parse", "HEAD").strip() or None
            # Formato porcelain: "XY ruta" (2 columnas de estado + espacio); no recortar o se pierde la columna X
            changed = [line[3:] for line in git("status", "--porcelain", "--untracked-files=no").splitlines() if line]
            return {"commit": commit, "cambios_sin_commit": changed}
        except Exception:
            return {"commit": None, "cambios_sin_commit": None}

    # ------------------------------------------------------------------ ciclo de la sesión

    def begin(self, source, clock, frame_size, native_fps, parameters):
        self.metadata.update({
            "fuente": str(source),
            "reloj": clock,
            "resolucion": list(frame_size) if frame_size else None,
            "fps_nativo_fuente": native_fps,
            "parametros": parameters,
        })
        self._write_metadata()          # se escribe ya: si el programa se cierra mal, la sesión queda documentada
        self._start_resource_sampling()

        git = self.metadata["git"]
        print(f"[SESION] {self.session_id} -> {os.path.abspath(self.dir)}")
        if git["commit"] is None:
            print("[AVISO] No se pudo leer el commit de git: la versión del código no quedará registrada.")
        elif git["cambios_sin_commit"]:
            print(f"[AVISO] Hay cambios sin commit en {git['cambios_sin_commit']}: esta sesión no se podrá "
                  f"reproducir exactamente con el commit {git['commit'][:7]}. Haz commit antes de experimentos formales.")

    def tick(self):
        """Llamar una vez por frame procesado: mide los FPS reales de procesamiento."""
        now = time.perf_counter()
        if self._last_tick is not None:
            self._frame_times.append(now - self._last_tick)
        self._last_tick = now

    @property
    def current_fps(self):
        recent = self._frame_times[-30:]
        return 1.0 / float(np.mean(recent)) if recent else None

    def log_event(self, t, event, phase, perclos, has_glasses, ear, duration=None):
        """duration: duración del evento en s (parpadeos, micro-sueño); vacío si no aplica."""
        self._events.writerow([f"{t:.3f}", datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3], event, phase,
                               f"{perclos:.2f}", "ACTIVO" if has_glasses else "INACTIVO", f"{ear:.4f}",
                               "" if duration is None else f"{duration:.3f}"])
        self._events_file.flush()

    def open_trace(self, header):
        if not self.save_trace:
            return
        self._trace_file = open(os.path.join(self.dir, "traza.csv"), "w", newline="", encoding="utf-8")
        self._trace = csv.writer(self._trace_file)
        self._trace.writerow(header)

    def trace(self, row):
        if self._trace:
            self._trace.writerow(row)

    def finish(self, summary):
        """Cierra archivos, añade rendimiento y resumen a metadata.json y una fila a resumen_sesiones.csv."""
        self._sampling = False
        self._events_file.close()
        if self._trace_file:
            self._trace_file.close()

        dt = np.array(self._frame_times) if self._frame_times else None
        self.metadata["fin"] = datetime.now().isoformat(timespec="seconds")
        self.metadata["rendimiento"] = {
            "fps_procesamiento_medio": round(float(1.0 / dt.mean()), 2) if dt is not None else None,
            "fps_procesamiento_mediana": round(float(1.0 / np.median(dt)), 2) if dt is not None else None,
            "fps_procesamiento_p5": round(float(1.0 / np.percentile(dt, 95)), 2) if dt is not None else None,
            "cpu_proceso_pct_medio": round(float(np.mean(self._cpu_samples)), 1) if self._cpu_samples else None,
            "ram_proceso_mb_media": round(float(np.mean(self._ram_samples)), 1) if self._ram_samples else None,
        }
        self.metadata["resumen"] = summary
        self._write_metadata()
        self._append_summary_row()
        return self.metadata

    # ------------------------------------------------------------------ internos

    def _write_metadata(self):
        with open(os.path.join(self.dir, "metadata.json"), "w", encoding="utf-8") as f:
            json.dump(self.metadata, f, ensure_ascii=False, indent=2,
                      default=lambda o: o.item() if hasattr(o, "item") else str(o))

    def _append_summary_row(self):
        path = os.path.join(self.base_dir, "resumen_sesiones.csv")
        self._migrate_summary_header(path)
        new_file = not os.path.exists(path)
        m, r, perf = self.metadata, self.metadata["resumen"], self.metadata["rendimiento"]
        with open(path, "a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            if new_file:
                writer.writerow(self.SUMMARY_HEADER)
            writer.writerow([m["sesion_id"], m["sujeto"], m["codigo_anonimo"], m["condicion"], m["inicio"],
                             r["duracion_s"], m["fuente"],
                             m["git"]["commit"], bool(m["git"]["cambios_sin_commit"]), r["gafas_final"],
                             r["parpadeos"], r["parpadeos_prolongados"], r["proporcion_parpadeos_prolongados"],
                             r["duracion_media_parpadeo_s"], r["bostezos"], r["micro_bostezos"],
                             r["sonrisas_descartadas"], r["tiempo_postura_fuera_de_rango_s"], r["perclos_final_pct"],
                             r["recalibraciones"], r["frames"], r["frames_con_rostro"],
                             perf["fps_procesamiento_medio"], perf["cpu_proceso_pct_medio"], perf["ram_proceso_mb_media"]])

    def _migrate_summary_header(self, path):
        """Si resumen_sesiones.csv tiene columnas de una versión anterior, lo reescribe con las actuales
        conservando los datos por nombre de columna (las columnas nuevas quedan vacías)."""
        if not os.path.exists(path):
            return
        with open(path, newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
            f.seek(0)
            header = next(csv.reader(f), None)
        if header == self.SUMMARY_HEADER:
            return
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=self.SUMMARY_HEADER, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)

    def _start_resource_sampling(self):
        """CPU y RAM del propio proceso, una muestra por segundo (CPU normalizada al total de núcleos)."""
        process = psutil.Process(os.getpid())
        process.cpu_percent(None)
        cores = psutil.cpu_count() or 1
        self._sampling = True

        def sample():
            while self._sampling:
                time.sleep(1.0)
                self._cpu_samples.append(process.cpu_percent(None) / cores)
                self._ram_samples.append(process.memory_info().rss / (1024 * 1024))

        threading.Thread(target=sample, daemon=True).start()
