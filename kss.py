# kss.py
"""
Escala de Somnolencia de Karolinska (KSS; Åkerstedt y Gillberg, 1990) dentro de la sesión en vivo, como
referencia subjetiva para validar el detector de fatiga: KSS >= 7 se asocia con más fallas de desempeño y
micro-sueños (revisión de Åkerstedt et al., 2014). Los indicadores oculares (PERCLOS, duración del
parpadeo...) se compararán con estas respuestas; ningún umbral de fatiga se fija sin esa validación.

La persona responde con una tecla del 1 al 9: al empezar el conteo, cada `interval_min` minutos y al
terminar la sesión (Q). Se registran el instante de la pregunta, el de la respuesta y la latencia: mientras
lee y responde, la mirada y la postura cambian, así que ese tramo puede excluirse del análisis.

La escala se presenta neutra (sin colores ni marcas que sugieran una respuesta "buena" o "mala").
TRADUCCIÓN PROPIA al español, no una versión validada: confirmar con el director si debe usarse una.
"""
import cv2

import revisar_ui as ui

LABELS = ["Extremadamente alerta",
          "Muy alerta",
          "Alerta",
          "Bastante alerta",
          "Ni alerta ni somnoliento",
          "Algunos signos de somnolencia",
          "Somnoliento, sin esfuerzo para mantenerme despierto",
          "Somnoliento, con algo de esfuerzo para mantenerme despierto",
          "Muy somnoliento, gran esfuerzo para mantenerme despierto, luchando contra el sueño"]


def beep_async():
    """Aviso sonoro sin bloquear el análisis (winsound.Beep congela el bucle mientras suena)."""
    try:
        import winsound
        winsound.PlaySound("SystemAsterisk", winsound.SND_ALIAS | winsound.SND_ASYNC)
    except Exception:
        print("\a", end="", flush=True)


class KSSPrompter:
    def __init__(self, interval_min):
        self.interval_min = float(interval_min)
        self.responses = []         # [{momento, t_pregunta, t_respuesta, latencia_s, valor}]
        self.prompt = None          # pregunta en pantalla: {momento, t_pregunta}
        self.next_t = None          # próxima pregunta periódica (None: preguntar al empezar el conteo)
        self.final_done = False
        self.quit_after = False     # se pidió salir: la sesión termina al responder la pregunta final
        self._overlay = None        # (clave, imagen BGR) de la pregunta dibujada

    def parameters(self):
        return {"activa": True, "escala": "Karolinska Sleepiness Scale (Åkerstedt y Gillberg, 1990)",
                "intervalo_min": self.interval_min, "momentos": ["inicio del conteo", "periódica", "final"],
                "etiquetas": LABELS, "traduccion": "propia, no validada"}

    def due(self, now):
        return (self.prompt is None and not self.quit_after
                and (self.next_t is None or now >= self.next_t))

    def ask(self, moment, now):
        self.prompt = {"momento": moment, "t_pregunta": now}
        beep_async()

    def answer(self, value, now):
        response = {**self.prompt, "t_respuesta": round(now, 3), "latencia_s": round(now - self.prompt["t_pregunta"], 3),
                    "valor": int(value)}
        response["t_pregunta"] = round(response["t_pregunta"], 3)
        self.responses.append(response)
        if self.prompt["momento"] == "final":
            self.final_done = True
        self.prompt = None
        self.next_t = now + self.interval_min * 60
        return response

    def _question(self):
        moment = self.prompt["momento"]
        if moment == "inicio":
            return "¿Qué tan somnoliento te sientes en este momento?"
        if moment == "final":
            return "¿Qué tan somnoliento te has sentido desde la última pregunta?"
        minutes = f"{self.interval_min:g}"
        return f"¿Qué tan somnoliento te has sentido en los últimos {minutes} minutos?"

    def _render(self, width):
        question = self._question()
        c = ui.Canvas(width, 10)
        lines = c.wrap(question, c.fonts.title, width - 48)
        height = 22 + 22 * len(lines) + 12 + 9 * 26 + 40
        c = ui.Canvas(width, height)
        c.card(0, 0, width - 1, height - 1, None)
        y = 18
        c.text(24, y - 2, "ESCALA DE SOMNOLENCIA", c.fonts.section, ui.MUTED)
        y += 18
        for line in lines:
            c.text(24, y, line, c.fonts.title)
            y += 22
        y += 10
        for i, label in enumerate(LABELS, start=1):
            c.keycap(24, y, str(i))
            c.text(56, y + 10, c.fit(label, c.fonts.body, width - 80), c.fonts.body, anchor="lm")
            y += 26
        c.text(24, y + 8, "Pulsa un número del 1 al 9", c.fonts.small, ui.MUTED)
        return c.to_bgr()

    def draw(self, img):
        """Dibuja la pregunta sobre la imagen que se muestra (no sobre el frame analizado ni la grabación)."""
        h, w = img.shape[:2]
        width = min(620, w - 40)
        key = (self.prompt["momento"], width)
        if self._overlay is None or self._overlay[0] != key:
            self._overlay = (key, self._render(width))
        panel = self._overlay[1]
        ph = min(panel.shape[0], h - 20)
        x, y = (w - width) // 2, max(10, (h - ph) // 2)
        roi = img[y:y + ph, x:x + width]
        cv2.addWeighted(panel[:ph], 0.95, roi, 0.05, 0, roi)
