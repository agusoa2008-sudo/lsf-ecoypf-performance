"""Indicador de estado por parpadeo sobre el LED onboard (GPIO21, un solo
color, sin RGB) del Seeed XIAO ESP32-S3 -- a diferencia del Super Mini
(NeoPixel WS2812), este board no tiene color, asi que el estado se
codifica en el ritmo de parpadeo.

Patron (ver main.py: led_task):
  - apagado         = arrancando, antes de levantar LoRa
  - parpadeo rapido = LoRa sin inicializar / en error
  - parpadeo lento  = LoRa OK pero sin paquete fresco del T190 (stale)
  - prendido fijo   = recibiendo telemetria fresca
"""

import time

BLINK_FAST_MS = 150
BLINK_SLOW_MS = 500


class StatusLed:
    def __init__(self, pin, active_low=True):
        self._pin = pin
        self._active_low = active_low
        self._on = False
        self._last_toggle_ms = time.ticks_ms()
        self.off()

    def _set(self, on):
        self._on = on
        pin_value = 0 if on else 1
        if not self._active_low:
            pin_value = 1 - pin_value
        self._pin.value(pin_value)

    def off(self):
        self._set(False)

    def tick(self, radio_ok, fresh):
        """Llamar periodicamente (ver main.py: led_task, cada ~100ms).
        radio_ok: bool, LoRa inicializado sin error.
        fresh: bool, hubo un paquete valido reciente del T190."""
        now = time.ticks_ms()
        if radio_ok and fresh:
            if not self._on:
                self._set(True)
            return
        period = BLINK_SLOW_MS if radio_ok else BLINK_FAST_MS
        if time.ticks_diff(now, self._last_toggle_ms) >= period:
            self._set(not self._on)
            self._last_toggle_ms = now
