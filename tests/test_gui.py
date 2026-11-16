# tests/test_gui.py
"""Pruebas de la ventana única con el ciclo REAL de vida (pantalla -> mainloop -> elección -> pantalla siguiente), que es
el que usa el programa. Un botón se pulsa solo tras unos milisegundos. Necesitan pantalla: sin ella se omiten."""
import os
import sys
import unittest
from types import SimpleNamespace

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import session_view  # noqa: E402
from tests.test_session_view import make_meta  # noqa: E402

try:
    import tkinter
    tkinter.Tk().destroy()
    import cv2
    import gui
    HAS_DISPLAY = True
except Exception:       # sin pantalla o sin tkinter
    HAS_DISPLAY = False


def click(button):
    """Clic real sobre un botón de CustomTkinter (el mismo camino que un clic del ratón): cambia el color, programa
    la animación de 100 ms y ejecuta el comando. Es lo que rompía el cierre de las ventanas cuando se cancelaban a
    mano los callbacks pendientes."""
    def action():
        button._mouse_inside = True
        button._on_release()
    return action


def key(keysym, char=""):
    return SimpleNamespace(keysym=keysym, char=char)


@unittest.skipUnless(HAS_DISPLAY, "sin pantalla")
class SingleWindowTest(unittest.TestCase):
    """Todas las pantallas en la misma ventana, como en el programa."""

    @classmethod
    def setUpClass(cls):
        cls.app = gui.get_app()

    @classmethod
    def tearDownClass(cls):
        gui.close()

    def press(self, screen, action, delay=500):
        """Programa una acción para cuando la pantalla ya esté a la vista y devuelve lo que elige."""
        self.app.after(delay, action)
        return self.app.run(screen)

    def test_inicio_empezar_devuelve_las_opciones(self):
        screen = gui.StartScreen(self.app)
        screen.name.insert(0, "  Laura Méndez ")
        screen.glasses.set("Con gafas")
        screen.record.select()
        result = self.press(screen, click(screen.start_button))
        self.assertEqual(result, {"name": "Laura Méndez", "condition": "con_gafas", "record": True})

    def test_inicio_valores_por_defecto(self):
        screen = gui.StartScreen(self.app)
        self.assertEqual(self.press(screen, click(screen.start_button)),
                         {"name": "", "condition": None, "record": False})

    def test_inicio_salir_devuelve_none(self):
        screen = gui.StartScreen(self.app)
        self.assertIsNone(self.press(screen, click(screen.exit_button)))

    def test_resumen_nueva_sesion_y_cerrar(self):
        view = session_view.summary_view(make_meta(), True, "sesiones/x")
        screen = gui.SummaryScreen(self.app, view)
        self.assertEqual(self.press(screen, click(screen.new_button)), "new")
        screen = gui.SummaryScreen(self.app, view)
        self.assertIsNone(self.press(screen, click(screen.close_button)))

    def test_resumen_con_ojo_cerrado_no_medido(self):
        view = session_view.summary_view(make_meta(), False, "sesiones/x")
        screen = gui.SummaryScreen(self.app, view)
        self.assertIsNone(self.press(screen, click(screen.close_button)))

    def test_resumen_boton_revisar_el_video(self):
        screen = gui.SummaryScreen(self.app, session_view.summary_view(make_meta(), True, "sesiones/x"))
        self.assertEqual(self.press(screen, click(screen.review_button)), "review")

    def test_revision_elegir_modo(self):
        meta = make_meta()
        meta["grabacion"] = {"archivo": "grabacion.mp4"}
        view = session_view.summary_view(meta, True, "sesiones/x")
        self.assertTrue(view["recorded"])
        screen = gui.ReviewScreen(self.app, view)
        self.assertEqual(self.press(screen, click(screen.blind_button)), "blind")
        screen = gui.ReviewScreen(self.app, view)
        self.assertEqual(self.press(screen, click(screen.review_button)), "review")
        screen = gui.ReviewScreen(self.app, view)
        self.assertIsNone(self.press(screen, click(screen.cancel_button)))

    def test_revision_de_sesion_sin_grabacion_solo_avisa(self):
        view = session_view.summary_view(make_meta(), True, "sesiones/x")
        self.assertFalse(view["recorded"])
        screen = gui.ReviewScreen(self.app, view)
        self.assertFalse(hasattr(screen, "blind_button"))
        self.assertIsNone(self.press(screen, click(screen.cancel_button)))

    def test_aviso_de_camara_reintentar_y_salir(self):
        screen = gui.CameraErrorScreen(self.app)
        self.assertEqual(self.press(screen, click(screen.retry_button)), "retry")
        screen = gui.CameraErrorScreen(self.app)
        self.assertIsNone(self.press(screen, click(screen.exit_button)))

    def test_pantallas_seguidas_en_la_misma_ventana(self):
        """inicio -> monitor -> resumen -> inicio otra vez, sin abrir otra ventana (así funciona 'Nueva sesión')."""
        for _ in range(2):
            start = gui.StartScreen(self.app)
            self.assertIsNotNone(self.press(start, click(start.start_button)))
            video = gui.VideoScreen("monitor")
            video.show(np.zeros((720, 1280, 3), np.uint8))
            video.close()
            summary = gui.SummaryScreen(self.app, session_view.summary_view(make_meta(), True, "sesiones/x"))
            self.assertEqual(self.press(summary, click(summary.new_button)), "new")
            self.assertEqual(self.app.winfo_children(), [summary])    # solo la pantalla actual

    def test_monitor_recibe_teclas_y_raton_como_opencv(self):
        video = gui.VideoScreen("monitor")
        clicks = []
        video.on_mouse(lambda event, x, y, flags, param: clicks.append((event, x, y)))
        video.show(np.zeros((720, 1280, 3), np.uint8))
        self.assertEqual(video.wait_key(1), 255)
        video.on_key(key("q", "q"))
        video.on_key(key("Return", "\r"))
        self.assertEqual((video.wait_key(1), video.wait_key(1)), (ord("q"), 13))
        # el clic en el centro de la pantalla es el centro de la imagen, sea cual sea la escala
        width, height = video.size()
        video._on_mouse(cv2.EVENT_LBUTTONDOWN, SimpleNamespace(x=width // 2, y=height // 2))
        event, x, y = clicks[-1]
        self.assertEqual(event, cv2.EVENT_LBUTTONDOWN)
        self.assertLessEqual(abs(x - 640), 2)
        self.assertLessEqual(abs(y - 360), 2)
        self.assertTrue(video.is_open())
        video.close()


@unittest.skipUnless(HAS_DISPLAY, "sin pantalla")
class CloseWindowTest(unittest.TestCase):
    def test_cerrar_con_la_x_termina(self):
        app = gui.get_app()
        try:
            app.after(500, app._on_close)
            self.assertIsNone(app.run(gui.StartScreen(app)))
            self.assertTrue(gui.closed())
            self.assertFalse(gui.VideoScreen("monitor").is_open())
        finally:
            gui.close()

    def test_cerrar_durante_el_monitor_pide_confirmacion(self):
        app = gui.get_app()
        try:
            video = gui.VideoScreen(gui.fatigue_hud.WINDOW_NAME)
            video.show(np.zeros((720, 1280, 3), np.uint8))
            app._on_close()
            self.assertTrue(video.is_open())                 # pregunta antes de cerrar
            prompt = video._prompt
            app._on_close()                                  # otra X no abre un segundo aviso
            self.assertIs(video._prompt, prompt)
            click(video.keep_button)()
            self.assertIsNone(video._prompt)
            self.assertTrue(video.is_open())
            app._on_close()
            click(video.close_button)()
            self.assertFalse(video.is_open())
        finally:
            gui.close()

    def test_cerrar_el_revisor_no_pregunta(self):
        app = gui.get_app()
        try:
            video = gui.VideoScreen("Revision de video")
            app._on_close()
            self.assertFalse(video.is_open())
        finally:
            gui.close()


if __name__ == "__main__":
    unittest.main()
