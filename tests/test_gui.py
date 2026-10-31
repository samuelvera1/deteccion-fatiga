# tests/test_gui.py
"""Pruebas de las ventanas con el ciclo REAL de vida (run() -> mainloop -> cierre -> destroy), que es el que usa el
programa. Un botón se pulsa solo tras unos milisegundos. Necesitan pantalla: sin ella se omiten."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import session_view  # noqa: E402
from tests.test_session_view import make_meta  # noqa: E402

try:
    import tkinter
    tkinter.Tk().destroy()
    import gui
    HAS_DISPLAY = True
except Exception:       # sin pantalla o sin tkinter
    HAS_DISPLAY = False


def press(window, action, delay=500):
    """Programa una acción para cuando la ventana ya esté abierta y devuelve el resultado de run()."""
    window.after(delay, action)
    return window.run()


def click(button):
    """Clic real sobre un botón de CustomTkinter (el mismo camino que un clic del ratón): cambia el color, programa
    la animación de 100 ms y ejecuta el comando. Es lo que rompía el cierre de las ventanas cuando se cancelaban a
    mano los callbacks pendientes."""
    def action():
        button._mouse_inside = True
        button._on_release()
    return action


@unittest.skipUnless(HAS_DISPLAY, "sin pantalla")
class GuiLifecycleTest(unittest.TestCase):
    def test_inicio_empezar_devuelve_las_opciones(self):
        window = gui.StartWindow()
        window.name.insert(0, "  Laura Méndez ")
        window.glasses.set("Con gafas")
        window.record.select()
        result = press(window, click(window.start_button))
        self.assertEqual(result, {"name": "Laura Méndez", "condition": "con_gafas", "record": True})

    def test_inicio_valores_por_defecto(self):
        window = gui.StartWindow()
        self.assertEqual(press(window, click(window.start_button)), {"name": "", "condition": None, "record": False})

    def test_inicio_salir_devuelve_none(self):
        window = gui.StartWindow()
        self.assertIsNone(press(window, click(window.exit_button)))

    def test_resumen_nueva_sesion_y_cerrar(self):
        view = session_view.summary_view(make_meta(), True, "sesiones/x")
        window = gui.SummaryWindow(view)
        self.assertEqual(press(window, click(window.new_button)), "new")
        window = gui.SummaryWindow(view)
        self.assertIsNone(press(window, click(window.close_button)))

    def test_resumen_con_ojo_cerrado_no_medido(self):
        view = session_view.summary_view(make_meta(), False, "sesiones/x")
        window = gui.SummaryWindow(view)
        self.assertIsNone(press(window, click(window.close_button)))

    def test_resumen_boton_revisar_el_video(self):
        window = gui.SummaryWindow(session_view.summary_view(make_meta(), True, "sesiones/x"))
        self.assertEqual(press(window, click(window.review_button)), "review")

    def test_revision_elegir_modo(self):
        meta = make_meta()
        meta["grabacion"] = {"archivo": "grabacion.mp4"}
        view = session_view.summary_view(meta, True, "sesiones/x")
        self.assertTrue(view["recorded"])
        window = gui.ReviewWindow(view)
        self.assertEqual(press(window, click(window.blind_button)), "blind")
        window = gui.ReviewWindow(view)
        self.assertEqual(press(window, click(window.review_button)), "review")
        window = gui.ReviewWindow(view)
        self.assertIsNone(press(window, click(window.cancel_button)))

    def test_revision_de_sesion_sin_grabacion_solo_avisa(self):
        view = session_view.summary_view(make_meta(), True, "sesiones/x")
        self.assertFalse(view["recorded"])
        window = gui.ReviewWindow(view)
        self.assertFalse(hasattr(window, "blind_button"))
        self.assertIsNone(press(window, click(window.cancel_button)))

    def test_aviso_de_camara_reintentar_y_salir(self):
        window = gui.CameraErrorWindow()
        self.assertEqual(press(window, click(window.retry_button)), "retry")
        window = gui.CameraErrorWindow()
        self.assertIsNone(press(window, click(window.exit_button)))

    def test_ventanas_seguidas_como_en_el_programa(self):
        """inicio -> resumen -> inicio otra vez, en el mismo proceso (así funciona 'Nueva sesión')."""
        for _ in range(2):
            start = gui.StartWindow()
            self.assertIsNotNone(press(start, click(start.start_button)))
            summary = gui.SummaryWindow(session_view.summary_view(make_meta(), True, "sesiones/x"))
            self.assertEqual(press(summary, click(summary.new_button)), "new")


if __name__ == "__main__":
    unittest.main()
