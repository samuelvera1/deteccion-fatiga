# tests/test_exe_support.py
"""Pruebas de lo que solo se usa en el ejecutable: registro cuando no hay consola y sonidos de advertencia."""
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import fatigue_audio  # noqa: E402
import main  # noqa: E402


class LogWithoutConsoleTest(unittest.TestCase):
    def test_sin_consola_imprime_en_el_registro(self):
        with tempfile.TemporaryDirectory() as folder:
            exe = os.path.join(folder, "FatigaDetector.exe")
            real_out, real_err = sys.stdout, sys.stderr
            try:
                with mock.patch.object(sys, "executable", exe), mock.patch.object(sys, "stdout", None), \
                        mock.patch.object(sys, "stderr", None):
                    main.redirect_output_to_log()
                    print("[AVISO] hola desde el ejecutable sin consola")
                    sys.stdout.flush()
                    log_file = sys.stdout
                log_file.close()
            finally:
                sys.stdout, sys.stderr = real_out, real_err
            with open(os.path.join(folder, "fatiga_detector.log"), encoding="utf-8") as f:
                text = f.read()
            self.assertIn("Fatiga Detector", text)
            self.assertIn("hola desde el ejecutable sin consola", text)

    def test_con_consola_no_toca_la_salida(self):
        before = sys.stdout
        main.redirect_output_to_log()
        self.assertIs(sys.stdout, before)


class AlertSoundTest(unittest.TestCase):
    def test_cada_estado_tiene_su_melodia(self):
        paths = {level: fatigue_audio._sound_path(level) for level in ("NORMAL", "PRECAUCION", "SOMNOLENCIA", "MICRO_SUENO")}
        for level, path in paths.items():
            self.assertTrue(path and os.path.exists(path), level)
        self.assertEqual(len(set(paths.values())), 4)

    def test_cuanto_mas_grave_el_estado_mas_fuerte_y_mas_grave_suena(self):
        """El micro-sueño es el más grave y fuerte; el volumen y el tono no suben hacia el estado más leve."""
        import wave

        import numpy as np
        peaks, pitches = {}, {}
        for level in ("NORMAL", "PRECAUCION", "SOMNOLENCIA", "MICRO_SUENO"):
            with wave.open(fatigue_audio._sound_path(level)) as w:
                data = np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(float)
                rate = w.getframerate()
            peaks[level] = np.abs(data).max() / 32767
            spectrum = np.abs(np.fft.rfft(data))
            pitches[level] = np.fft.rfftfreq(len(data), 1 / rate)[spectrum.argmax()]
        order = ["NORMAL", "PRECAUCION", "SOMNOLENCIA", "MICRO_SUENO"]
        self.assertEqual(sorted(order, key=lambda lv: peaks[lv]), order)
        self.assertEqual(sorted(order, key=lambda lv: -pitches[lv]), order)
        self.assertLess(pitches["MICRO_SUENO"], 300)

    def test_un_archivo_propio_reemplaza_la_melodia(self):
        with tempfile.TemporaryDirectory() as folder:
            os.makedirs(os.path.join(folder, "sonidos"))
            own = os.path.join(folder, "sonidos", "somnolencia.wav")
            shutil.copy(fatigue_audio._sound_path("SOMNOLENCIA"), own)
            root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # donde están assets/sounds
            with mock.patch.object(sys, "frozen", True, create=True), \
                    mock.patch.object(sys, "_MEIPASS", root, create=True), \
                    mock.patch.object(sys, "executable", os.path.join(folder, "FatigaDetector.exe")):
                self.assertEqual(fatigue_audio._sound_path("SOMNOLENCIA"), own)
                self.assertTrue(fatigue_audio._sound_path("MICRO_SUENO").endswith("microsueno.wav"))
                self.assertTrue(fatigue_audio._sound_path("PRECAUCION").endswith("precaucion.wav"))


if __name__ == "__main__":
    unittest.main()
