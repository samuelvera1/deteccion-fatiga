"""Comparación de PERCLOS con los tramos de ojo cerrado anotados (O) en evaluar.py, con una sesión sintética."""
import csv
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import evaluar  # noqa: E402

FPS = 30.0
N_FRAMES = 2100     # 70 s: una ventana completa de 60 s y otra de 10 s que no cuenta


def t(frame):
    return f"{frame / FPS:.3f}"


class PerclosAgreementTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        # Cierre del sistema: parpadeo 1 bien detectado (300-306), parpadeo 2 que no llega al 80 % (600-606) y un
        # falso cierre con el ojo abierto (1000)
        closure = {f: 0.0 for f in range(N_FRAMES)}
        closure.update({301: 0.9, 302: 1.0, 303: 1.0, 304: 1.0, 305: 0.9})
        closure.update({f: 0.5 for f in range(601, 606)})
        closure[1000] = 0.9
        with open(os.path.join(self.dir, "metadata.json"), "w", encoding="utf-8") as f:
            json.dump({"sesion_id": "sintetica", "codigo_anonimo": "P00", "fps_nativo_fuente": FPS,
                       "parametros": {"perclos": {"cierre_min": 0.8}},
                       "resumen": {"inicio_monitoreo_s": 0.0, "duracion_s": N_FRAMES / FPS}}, f)
        with open(os.path.join(self.dir, "eventos.csv"), "w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow(["Evento", "t_s", "Duracion_s"])
        with open(os.path.join(self.dir, "traza.csv"), "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["t", "frame", "fase", "eyes_closed", "postura_valida", "cierre", "mouth", "cabeza_vel"])
            for fr in range(N_FRAMES):
                w.writerow([t(fr), fr, "monitoreo", 0, 1, f"{closure[fr]:.4f}", "0.0", "0.0"])

    def tearDown(self):
        shutil.rmtree(self.dir)

    def reference(self, rows):
        path = os.path.join(self.dir, "anotaciones_ciego.csv")
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["t_s", "frame", "tipo", "fin_t_s", "fin_frame", "comentario", "ciego", "anotador", "registrado"])
            for kind, f0, f1 in rows:
                w.writerow([t(f0), f0, kind, t(f1), f1, "", "1", "", ""])
        return evaluar.Reference(path)

    def test_counts_and_window(self):
        ref = self.reference([("PARPADEO", 300, 307), ("OJO_CERRADO", 302, 305),
                              ("PARPADEO", 600, 607), ("OJO_CERRADO", 602, 605)])
        self.assertEqual(ref.warnings, [])
        p = evaluar.perclos_agreement(evaluar.Session(self.dir), ref)
        c = p["conteos"]
        self.assertEqual((c["pos"], c["pos_sistema"]), (6, 3))
        # Intermedios: cada parpadeo con 2 cuadros de margen (298-308) menos sus 3 cuadros O
        self.assertEqual((c["int"], c["int_sistema"]), (16, 2))
        self.assertEqual((c["neg"], c["neg_sistema"]), (N_FRAMES - 22, 1))
        self.assertEqual(p["sensibilidad"], 0.5)
        self.assertEqual(p["ventanas_validas"], 1)
        w = p["ventanas"][0]
        self.assertAlmostEqual(w["perclos_sistema"], 100 * 6 / 1800, places=2)
        self.assertAlmostEqual(w["perclos_ojo_cerrado"], 100 * 6 / 1800, places=2)
        self.assertAlmostEqual(w["perclos_cierres"], 100 * 14 / 1800, places=2)
        self.assertEqual(p["ventanas_en_intervalo"], 1)

    def test_not_evaluable_is_skipped(self):
        ref = self.reference([("PARPADEO", 300, 307), ("OJO_CERRADO", 302, 305), ("NO_EVALUABLE", 990, 1010)])
        p = evaluar.perclos_agreement(evaluar.Session(self.dir), ref)
        self.assertEqual(p["conteos"]["neg_sistema"], 0)      # el falso cierre (1000) quedó en el tramo X

    def test_without_closed_annotations_returns_none(self):
        ref = self.reference([("PARPADEO", 300, 307)])
        self.assertIsNone(evaluar.perclos_agreement(evaluar.Session(self.dir), ref))

    def test_warnings_for_closed_outside_blink_and_zero_length(self):
        ref = self.reference([("PARPADEO", 300, 307), ("OJO_CERRADO", 302, 302), ("OJO_CERRADO", 900, 903)])
        text = " ".join(ref.warnings)
        self.assertIn("no están dentro de un parpadeo", text)
        self.assertIn("duran cero", text)

    def test_combine_pools_counts_and_windows(self):
        ref = self.reference([("PARPADEO", 300, 307), ("OJO_CERRADO", 302, 305)])
        report, _ = evaluar.evaluate(evaluar.Session(self.dir), ref)
        total = evaluar.combine([report, report])
        self.assertEqual(total["perclos"]["conteos"]["pos"], 6)
        self.assertEqual(total["perclos"]["ventanas_validas"], 2)


if __name__ == "__main__":
    unittest.main()
