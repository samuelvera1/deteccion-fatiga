# tests/test_session_view.py
"""Pruebas del formato de la ventana de resumen (sin ventanas)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import session_view as sv  # noqa: E402


def make_meta(**changes):
    meta = {
        "sujeto": "Laura Méndez", "condicion": "con_gafas", "inicio": "2026-10-25T11:05:00",
        "git": {"commit": "cc1e94b0d6ad5afdb19e3b28a5d1c2bb1c58b79c", "cambios_sin_commit": []},
        "software": {"version": "1.0.0"},
        "rendimiento": {"fps_procesamiento_medio": 28.64},
        "resumen": {
            "duracion_s": 920.0, "inicio_monitoreo_s": 10.0, "parpadeos": 214, "parpadeos_prolongados": 18,
            "duracion_media_parpadeo_s": 0.2861, "bostezos": 3, "micro_bostezos": 1, "perclos_final_pct": 6.42,
            "recalibraciones": 0,
            "fatiga": {"tiempo_por_nivel_s": {"NORMAL": 742.0, "PRECAUCION": 128.0, "SOMNOLENCIA": 46.0,
                                              "MICRO_SUENO": 4.0},
                       "alertas": {"PRECAUCION": 3, "SOMNOLENCIA": 1, "MICRO_SUENO": 2}},
        },
    }
    meta.update(changes)
    return meta


class FormatTest(unittest.TestCase):
    def test_coma_decimal(self):
        self.assertEqual(sv.decimal(6.42), "6,4")
        self.assertEqual(sv.decimal(0.286, 2), "0,29")

    def test_porcentaje_sin_decimales_solo_en_los_extremos(self):
        self.assertEqual(sv.percent(100.0), "100 %")
        self.assertEqual(sv.percent(0.0), "0 %")
        self.assertEqual(sv.percent(80.65), "80,7 %")
        self.assertEqual(sv.percent(5.0), "5,0 %")

    def test_reloj(self):
        self.assertEqual(sv.clock(920), "15:20")
        self.assertEqual(sv.clock(4), "00:04")
        self.assertEqual(sv.clock(3725), "1:02:05")

    def test_plural(self):
        self.assertEqual(sv.plural(1, "micro-bostezo", "micro-bostezos"), "1 micro-bostezo")
        self.assertEqual(sv.plural(0, "micro-bostezo", "micro-bostezos"), "0 micro-bostezos")


class SummaryViewTest(unittest.TestCase):
    def test_sesion_normal(self):
        view = sv.summary_view(make_meta(), True, "sesiones/x")
        self.assertEqual(view["participant"], "Laura Méndez")
        self.assertEqual(view["glasses"], "Con gafas")
        self.assertEqual(view["when"], "25/10/2026 · 11:05")
        self.assertEqual(view["duration"], "15:20")
        self.assertEqual(view["blinks_sub"], ["18 prolongados", "media 0,29 s"])
        self.assertEqual(view["yawns_sub"], ["1 micro-bostezo"])
        self.assertEqual(view["perclos"], "6,4 %")
        self.assertEqual(view["perclos_sub"], "ventana de 60 s")
        self.assertEqual(view["build"], "v1.0.0 · commit cc1e94b")
        self.assertTrue(view["counted"])
        self.assertIsNone(view["warning"])

    def test_niveles_suman_el_total(self):
        view = sv.summary_view(make_meta(), True, "sesiones/x")
        self.assertEqual([lv["time"] for lv in view["levels"]], ["12:22", "02:08", "00:46", "00:04"])
        self.assertEqual([lv["percent"] for lv in view["levels"]], ["80,7 %", "13,9 %", "5,0 %", "0,4 %"])
        self.assertAlmostEqual(sum(lv["share"] for lv in view["levels"]), 1.0)
        self.assertEqual([lv["alerts"] for lv in view["levels"]], ["—", "3", "1", "2"])

    def test_sin_nombre_es_anonimo(self):
        view = sv.summary_view(make_meta(sujeto="anonimo", condicion=None), True, "sesiones/x")
        self.assertEqual(view["participant"], "Anónimo")
        self.assertEqual(view["glasses"], "Gafas: no indicado")

    def test_ojo_cerrado_no_medido(self):
        view = sv.summary_view(make_meta(), False, "sesiones/x")
        self.assertFalse(view["reliable"])
        self.assertEqual(view["perclos_sub"], "no fiable")
        self.assertIn("ojo cerrado no se midió bien", view["warning"])

    def test_sin_conteo_no_divide_por_cero(self):
        meta = make_meta()
        meta["resumen"]["inicio_monitoreo_s"] = None
        meta["resumen"]["fatiga"] = {"tiempo_por_nivel_s": {}, "alertas": {}}
        view = sv.summary_view(meta, True, "sesiones/x")
        self.assertFalse(view["counted"])
        self.assertEqual([lv["percent"] for lv in view["levels"]], ["—"] * 4)
        self.assertIn("terminó antes de completar la calibración", view["warning"])

    def test_sesion_cortada_no_culpa_al_ojo_cerrado(self):
        """Si no llegó a empezar el conteo, el aviso es ese aunque el ojo cerrado tampoco se haya medido."""
        meta = make_meta()
        meta["resumen"]["inicio_monitoreo_s"] = None
        meta["resumen"]["fatiga"] = {"tiempo_por_nivel_s": {}, "alertas": {}}
        view = sv.summary_view(meta, False, "sesiones/x")
        self.assertIn("calibración", view["warning"])
        self.assertNotIn("ojo cerrado", view["warning"])

    def test_sesion_real_guardada_por_el_programa(self):
        """Una sesión de verdad (si existe en este equipo) se convierte sin errores."""
        import glob
        import json
        files = sorted(glob.glob(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                              "sesiones", "*", "metadata.json")))
        for path in files[-5:]:
            with open(path, encoding="utf-8") as f:
                meta = json.load(f)
            if meta.get("resumen"):
                sv.summary_view(meta, True, os.path.dirname(path))


if __name__ == "__main__":
    unittest.main()
