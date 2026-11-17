"""La guía de voz de grabar_perclos.py sigue la tabla de docs/guion_perclos.md (4 minutos)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import grabar_perclos as g  # noqa: E402

TURNS = tuple((turn, "Al frente.") for turn in g.HEAD_TURNS)
PHONE = ("Mira el celular.", "Vuelve a la pantalla.")


def minute(t):
    return int(t // g.BLOCK_S)


def pairs(start_text, end_text):
    """(inicio, fin) de cada acción que empieza con start_text y termina con el siguiente end_text."""
    out, opened = [], None
    for t, text in g.SCRIPT:
        if text == start_text:
            opened = t
        elif text == end_text and opened is not None:
            out.append((opened, t))
            opened = None
    return out


def spoken_seconds(text):
    """Cota de lo que tarda la voz de Windows (Helena, velocidad 2) en decir el texto: medida sobre todas las frases
    de la guía, el audio termina antes de 0,31 s + 0,07 s por carácter."""
    return 0.31 + 0.07 * len(text)


class GuideScriptTest(unittest.TestCase):
    def test_voluntary_closures_per_minute(self):
        closed = {}
        for start, end in pairs("Cierra.", "Abre."):
            self.assertEqual(minute(start), minute(end - 1e-9), "un cierre no cruza de un minuto a otro")
            closed[minute(start)] = closed.get(minute(start), 0.0) + end - start
        # minuto 2: 3 x 1,5 s; minuto 3: 4 x 2 s; minuto 4: 2 x 4 s + 3 s; el minuto 1 sin cierres
        self.assertEqual(closed, {1: 4.5, 2: 8.0, 3: 11.0})

    def test_every_closure_has_a_countdown(self):
        cues = set(g.SCRIPT)
        for start, _ in pairs("Cierra.", "Abre."):
            self.assertTrue({(start - 3, "Tres."), (start - 2, "Dos."), (start - 1, "Uno.")} <= cues, start)

    def test_directed_blinks_in_first_minute(self):
        singles = [t for t, text in g.SCRIPT if text in g.BLINK_CUES]
        triples = [t for t, text in g.SCRIPT if text == g.TRIPLE_BLINK]
        self.assertEqual((len(singles), len(triples)), (5, 2))      # 5 + 2 x 3 = 11 parpadeos pedidos
        self.assertEqual({minute(t) for t in singles + triples}, {0})

    def test_slow_blinks_and_traps(self):
        slow = [t for t, text in g.SCRIPT if text == "Parpadeo lento."]
        self.assertEqual((len(slow), {minute(t) for t in slow}), (3, {1}))
        squint = pairs(*g.SQUINT)
        self.assertEqual([(minute(s), e - s) for s, e in squint], [(0, 5.0), (2, 4.0)])
        # lo que puede sacar la postura de rango (celular, giros) suma como mucho 4 s por minuto: cada ventana conserva
        # los 54 s válidos que exige PERCLOS
        out_of_range = {}
        for s, e in pairs(*PHONE) + [p for turn in TURNS for p in pairs(*turn)]:
            out_of_range[minute(s)] = out_of_range.get(minute(s), 0.0) + e - s
        self.assertEqual(out_of_range, {0: 4.0, 1: 4.0, 2: 3.0})

    def test_blink_while_looking_to_each_side(self):
        """Un parpadeo girando la cabeza a cada lado y otro mirando a cada lado solo con los ojos."""
        found = []
        for start in g.HEAD_TURNS + g.EYES_ONLY:
            s = next(t for t, text in g.SCRIPT if text == start)
            e = next(t for t, text in g.SCRIPT if text == "Al frente." and t > s)
            blinks = [t for t, text in g.SCRIPT if text == g.LOOK_BLINK and s < t < e]
            self.assertEqual(len(blinks), 1, start)
            found.append(blinks[0])
        self.assertEqual(len(found), sum(1 for _, text in g.SCRIPT if text == g.LOOK_BLINK))

    def test_cues_fit_and_script_lasts_four_minutes(self):
        times = [t for t, _ in g.SCRIPT]
        self.assertEqual(times, sorted(times))
        for (t, text), (t_next, _) in zip(g.SCRIPT, g.SCRIPT[1:]):
            self.assertLessEqual(spoken_seconds(text), t_next - t, f"«{text}» se corta en {t} s")
        self.assertGreater(times[-1], g.N_BLOCKS * g.BLOCK_S)
        self.assertEqual(g.N_BLOCKS, 4)
        self.assertTrue(all(any(t == k * g.BLOCK_S for t, _ in g.SCRIPT) for k in range(g.N_BLOCKS)))


if __name__ == "__main__":
    unittest.main()


class CameraPlacementTest(unittest.TestCase):
    def test_camera_yaw_of_a_turned_face(self):
        from tests.test_fatigue_pose import face, rot_y
        for deg in (0.0, 30.0, -45.0):
            self.assertAlmostEqual(g.camera_yaw(face(rot_y(deg))), abs(deg), places=6)

    def test_feedback_guides_toward_the_target(self):
        self.assertEqual(g.angle_feedback(None, 30.0)[0], False)
        inside, phrase = g.angle_feedback(18.4, 30.0)
        self.assertFalse(inside)
        self.assertIn("más hacia el lado", phrase)
        self.assertIn("18 grados", phrase)
        self.assertIn("menos", g.angle_feedback(52.0, 45.0)[1])
        self.assertTrue(g.angle_feedback(33.0, 30.0)[0])
        self.assertTrue(g.angle_feedback(41.0, 45.0)[0])

    def test_targets_and_source(self):
        self.assertEqual(g.TARGET_ANGLES, {"lateral_30": 30.0, "lateral_45": 45.0})
        self.assertEqual(g._source_from([]), 0)
        self.assertEqual(g._source_from(["--fuente", "1"]), 1)


class PostureScriptTest(unittest.TestCase):
    """Guion de E13: 6 posturas de 30 s, cada una con 2 parpadeos pedidos y un cierre de 2 s."""

    def test_blocks(self):
        script = g.script_for("postura")
        self.assertIs(script, g.POSTURE_SCRIPT)
        self.assertIs(g.script_for("sin_gafas"), g.SCRIPT)
        for k, (instruction, _) in enumerate(g.POSTURES):
            t0, t1 = k * g.POSTURE_BLOCK_S, (k + 1) * g.POSTURE_BLOCK_S
            cues = [(t, text) for t, text in script if t0 <= t < t1]
            self.assertEqual(cues[0], (t0, instruction))
            self.assertEqual(sum(text in g.BLINK_CUES for _, text in cues), 2)
            closes = [t for t, text in cues if text == "Cierra."]
            opens = [t for t, text in cues if text == "Abre."]
            self.assertEqual([b - a for a, b in zip(closes, opens)], [2.0])

    def test_cues_fit_and_last_three_minutes(self):
        script = g.POSTURE_SCRIPT
        for (t, text), (t_next, _) in zip(script, script[1:]):
            self.assertLessEqual(spoken_seconds(text), t_next - t, f"«{text}» se corta en {t} s")
        self.assertEqual(script[-1][0], len(g.POSTURES) * g.POSTURE_BLOCK_S + 2.0)
        self.assertIn("postura", g.CONDITIONS)
