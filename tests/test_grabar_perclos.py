"""La guía de voz de grabar_perclos.py sigue la tabla de docs/guion_perclos.md."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import grabar_perclos as g  # noqa: E402


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


class GuideScriptTest(unittest.TestCase):
    def test_voluntary_closures_per_minute(self):
        closed = {}
        for start, end in pairs("Cierra.", "Abre."):
            self.assertEqual(minute(start), minute(end - 1e-9), "un cierre no cruza de un minuto a otro")
            closed[minute(start)] = closed.get(minute(start), 0.0) + end - start
        # minuto 1: 2 x 1,5 s; minuto 2: 4 x 2 s; minuto 4: 2 x 4 s + 2 s; minutos 0, 3 y 5 sin cierres
        self.assertEqual(closed, {1: 3.0, 2: 8.0, 4: 10.0})

    def test_slow_blinks_and_traps(self):
        slow = [t for t, text in g.SCRIPT if text == "Parpadeo lento."]
        self.assertEqual((len(slow), {minute(t) for t in slow}), (4, {1}))
        phone = pairs("Mira el celular.", "Vuelve a la pantalla.")
        squint = pairs("Entrecierra los ojos, sin cerrarlos.", "Normal.")
        self.assertEqual([e - s for s, e in phone], [5.0] * 3)
        self.assertEqual([e - s for s, e in squint], [5.0] * 2)
        self.assertEqual({minute(t) for s, e in phone + squint for t in (s, e)}, {3})

    def test_cues_are_sorted_spaced_and_end_after_six_minutes(self):
        times = [t for t, _ in g.SCRIPT]
        self.assertEqual(times, sorted(times))
        # cada frase se dice entera: la siguiente llega al menos 1,5 s después
        self.assertGreaterEqual(min(b - a for a, b in zip(times, times[1:])), 1.5)
        self.assertGreater(times[-1], 6 * g.BLOCK_S)
        self.assertEqual([t for t, text in g.SCRIPT if text.startswith("Minuto")], [k * g.BLOCK_S for k in range(6)])


if __name__ == "__main__":
    unittest.main()
