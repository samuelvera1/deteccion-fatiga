# tests/test_fatigue_alert.py
"""Pruebas de la lógica de niveles de fatiga. Ejecutar desde la carpeta del proyecto:
    python -m unittest discover tests
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import fatigue_alert as fa  # noqa: E402


def run(alert, samples, start=0.0, dt=1.0):
    """samples: [(perclos, tiempo válido, micro-sueño)]; devuelve los cambios de nivel con su instante."""
    changes, t = [], start
    for perclos, valid, microsleep in samples:
        level = alert.update(t, perclos, valid, microsleep)
        if level is not None:
            changes.append((t, level))
        t += dt
    return changes


class FatigueAlertTest(unittest.TestCase):
    def setUp(self):
        self.alerts = []
        self.alert = fa.FatigueAlert(60, sound=False, on_alert=self.alerts.append)

    def test_sin_minuto_completo_no_alerta(self):
        # PERCLOS alto pero solo 30 s de datos válidos: no hay alerta
        self.assertEqual(run(self.alert, [(30.0, 30.0, False)] * 5), [])
        self.assertEqual(self.alert.level, fa.NORMAL)

    def test_umbrales(self):
        self.assertEqual(run(self.alert, [(7.9, 60, False)]), [])
        self.assertEqual(run(self.alert, [(8.0, 60, False)], start=1), [(1, fa.PRECAUCION)])
        self.assertEqual(run(self.alert, [(12.0, 60, False)], start=2), [(2, fa.SOMNOLENCIA)])
        self.assertEqual(self.alerts, [fa.SOMNOLENCIA])       # la precaución no dispara alerta sonora

    def test_histeresis(self):
        run(self.alert, [(12.5, 60, False)])
        # entre 10 y 12 % sigue en somnolencia; por debajo de 10 % baja a precaución
        self.assertEqual(run(self.alert, [(11.0, 60, False), (10.0, 60, False)], start=1), [])
        self.assertEqual(run(self.alert, [(9.9, 60, False)], start=3), [(3, fa.PRECAUCION)])
        # entre 6 y 8 % sigue en precaución; por debajo de 6 % vuelve a normal
        self.assertEqual(run(self.alert, [(7.0, 60, False), (6.0, 60, False)], start=4), [])
        self.assertEqual(run(self.alert, [(5.9, 60, False)], start=6), [(6, fa.NORMAL)])

    def test_micro_sueno_inmediato_y_vuelta(self):
        changes = run(self.alert, [(3.0, 20, True), (3.0, 20, True), (3.0, 20, False)])
        self.assertEqual(changes, [(0, fa.MICRO_SUENO), (2, fa.NORMAL)])
        self.assertEqual(self.alerts, [fa.MICRO_SUENO])
        # tras el micro-sueño vuelve al nivel que marque el PERCLOS
        run(self.alert, [(13.0, 60, False)], start=3)
        changes = run(self.alert, [(13.0, 60, True), (13.0, 60, False)], start=4)
        self.assertEqual(changes, [(4, fa.MICRO_SUENO), (5, fa.SOMNOLENCIA)])

    def test_tiempo_por_nivel_y_conteo(self):
        run(self.alert, [(9.0, 60, False)] * 3 + [(15.0, 60, False)] * 2 + [(1.0, 60, False)])
        summary = self.alert.summary()
        self.assertEqual(summary["tiempo_por_nivel_s"][fa.PRECAUCION], 3.0)
        self.assertEqual(summary["tiempo_por_nivel_s"][fa.SOMNOLENCIA], 2.0)
        self.assertEqual(summary["alertas"], {fa.PRECAUCION: 1, fa.SOMNOLENCIA: 1, fa.MICRO_SUENO: 0})

    def test_repeticion_del_sonido(self):
        sounds = []
        fa.play_alarm, original = (lambda level: sounds.append(level)), fa.play_alarm
        try:
            alert = fa.FatigueAlert(60, sound=True)
            run(alert, [(15.0, 60, False)] * 61)          # 61 s en somnolencia: suena en 0, 30 y 60 s
            self.assertEqual(len(sounds), 3)
            sounds.clear()
            run(alert, [(15.0, 60, True)] * 7, start=61)  # 7 s de micro-sueño: suena en 61, 64 y 67 s
            self.assertEqual(sounds, [fa.MICRO_SUENO] * 3)
        finally:
            fa.play_alarm = original


if __name__ == "__main__":
    unittest.main()
