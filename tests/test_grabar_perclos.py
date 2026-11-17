"""La guía de voz de grabar_perclos.py sigue la tabla de docs/guion_perclos.md (4 minutos)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import grabar_perclos as g  # noqa: E402

TURNS = (("Gira un poco a la izquierda.", "Al frente."), ("Gira un poco a la derecha.", "Al frente."))
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

    def test_slow_blinks_and_traps(self):
        slow = [t for t, text in g.SCRIPT if text == "Parpadeo lento."]
        self.assertEqual((len(slow), {minute(t) for t in slow}), (3, {1}))
        squint = pairs(*g.SQUINT)
        self.assertEqual([(minute(s), e - s) for s, e in squint], [(0, 5.0), (2, 4.0)])
        # lo que puede sacar la postura de rango (celular, giros) suma como mucho 3 s por minuto: cada ventana conserva
        # los 54 s válidos que exige PERCLOS
        out_of_range = {}
        for s, e in pairs(*PHONE) + [p for turn in TURNS for p in pairs(*turn)]:
            out_of_range[minute(s)] = out_of_range.get(minute(s), 0.0) + e - s
        self.assertEqual(out_of_range, {0: 3.0, 1: 3.0, 2: 3.0})

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
