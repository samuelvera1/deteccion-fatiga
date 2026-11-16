# display.py
"""Dónde se muestran el monitor en vivo y el revisor de vídeo. En la consola, cada uno en su propia ventana de OpenCV
(OpenCvWindow); en el programa con ventanas, como una pantalla más dentro de la ventana única (gui.VideoScreen),
que main.py elige con use(). Ambas tienen la misma interfaz, así el monitor y el revisor no dependen de cuál sea."""
import cv2


class OpenCvWindow:
    def __init__(self, name, size=None):
        self.name = name
        cv2.namedWindow(name, cv2.WINDOW_NORMAL if size else cv2.WINDOW_AUTOSIZE)
        if size:
            cv2.resizeWindow(name, *size)

    def show(self, img):
        cv2.imshow(self.name, img)

    def wait_key(self, ms):
        """Código de la tecla pulsada (0-255) o 255 si no se pulsó ninguna en ms milisegundos."""
        return cv2.waitKey(ms) & 0xFF

    def is_open(self):
        """False en cuanto se cierra la ventana con la X."""
        return cv2.getWindowProperty(self.name, cv2.WND_PROP_VISIBLE) >= 1

    def size(self):
        """(ancho, alto) del área de imagen, o None si no se conoce."""
        try:
            _, _, w, h = cv2.getWindowImageRect(self.name)
        except cv2.error:
            return None
        return (w, h) if w > 0 and h > 0 else None

    def on_mouse(self, callback):
        """callback(evento, x, y, flags, param) con los eventos de OpenCV y x, y en píxeles de la imagen."""
        cv2.setMouseCallback(self.name, callback)

    def close(self):
        cv2.destroyAllWindows()


_window_class = OpenCvWindow


def use(window_class):
    global _window_class
    _window_class = window_class


def open_window(name, size=None):
    return _window_class(name, size)
