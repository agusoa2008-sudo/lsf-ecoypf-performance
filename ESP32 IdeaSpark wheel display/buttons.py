# buttons.py
# Boton de pagina para el boton BOOT (HW.PAGE_BTN_PIN, GPIO0 en este ESP32
# clasico). Solo dos gestos: corto y largo -- sin doble-click, para no tener
# que esperar una segunda pulsacion antes de disparar "corto" (ese delay
# artificial es lo que hace el PageButton con doble-click de
# uPy reference Martin/FC Upy/eBike Old/inDev/buttons.py, no lo necesitamos
# aca). El umbral largo/corto se mide por duracion de la pulsacion, igual
# que esa version original.

import uasyncio as asyncio
import time

DEFAULT_LONG_MS = 1200
DEFAULT_POLL_MS = 20


class PageButton:
    """Boton simple: short_cb al soltar una pulsacion corta,
    long_cb al soltar una que duro >= long_ms."""

    def __init__(self, pin_in, *, short=lambda: None, long=lambda: None,
                 long_ms=DEFAULT_LONG_MS, poll_ms=DEFAULT_POLL_MS, label="Page"):
        self.pin = pin_in
        self.cb_short = short
        self.cb_long = long
        self.long_ms = long_ms
        self.poll_ms = poll_ms
        self.label = label
        self._is_pressed = False
        self._press_started = 0

    async def task(self):
        poll_ms = max(5, int(self.poll_ms))
        while True:
            now = time.ticks_ms()
            value = self.pin.value()
            if value == 0 and not self._is_pressed:
                self._is_pressed = True
                self._press_started = now
            if value == 1 and self._is_pressed:
                self._is_pressed = False
                duration = time.ticks_diff(now, self._press_started)
                if duration >= self.long_ms:
                    self.cb_long()
                else:
                    self.cb_short()
            await asyncio.sleep_ms(poll_ms)
