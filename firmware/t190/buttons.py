# buttons.py
# Portado de uPy reference Martin/FC Upy/eBike Old/inDev/buttons.py
# PageButton conserva el sondeo compatible; InterruptPageButton captura
# flancos y procesa gestos activos-bajo fuera de la IRQ. UpDownButtons
# (rocker ADC) queda solo con short,
# no se usa en el T190 actual (rocker eliminado, ver HW.py).

import uasyncio as asyncio
import time

DEBUG = False

DEFAULT_THRESHOLDS = {"UP_MAX": 50, "DOWN_MAX": 2200}
DEFAULT_TIMINGS = {
    "DEBOUNCE_MS":   5,
    "RELEASE_MS":    40,
    "ADC_PERIOD_MS": 20,
}
PAGE_DEFAULTS = {
    "SHORT_MS": 420,
    "LONG_MS": 1200,
    "EXTRA_MS": 2200,
    "DOUBLE_MS": 320,
    "POLL_MS": 20,
}

IDLE, UP, DOWN = 0, 1, 2


def _ticks():
    return time.ticks_ms()


def _diff(a, b):
    return time.ticks_diff(a, b)


if hasattr(time, "ticks_add"):
    _ticks_add = time.ticks_add
else:
    def _ticks_add(base, delta):
        return (base + delta) & 0x7FFFFFFF


class PageButton:
    """Boton digital simple (S3/GPIO21 o BTN0/GPIO0): distingue
    short/double/long/extra por la duracion de la pulsacion.

    El short dispara siempre de inmediato al soltar (sin demora de
    confirmacion). Si un segundo short llega dentro de DOUBLE_MS del
    anterior, se dispara ADEMAS un evento double (no lo reemplaza) --
    asi la navegacion con taps repetidos nunca se "come" una pulsacion
    esperando a ver si viene un segundo click."""

    def __init__(self, pin_in, *, short=lambda: None, double=lambda: None,
                 long=lambda: None, extra=lambda: None, timings=None, label="Page"):
        self.pin = pin_in
        self.cb_short = short
        self.cb_double = double
        self.cb_long = long
        self.cb_extra = extra
        self.t = PAGE_DEFAULTS.copy()
        self.t.update(timings or {})
        self.label = label

        self._is_pressed = False
        self._press_started = 0
        self._last_short_release = None

    def _fire(self, kind, callback):
        if DEBUG:
            now = _ticks()
            duration = _diff(now, self._press_started) if self._press_started else 0
            print("[{}] {:>6}ms {}".format(self.label, duration, kind))
        if callable(callback):
            callback()

    def _handle_release(self, now):
        duration = _diff(now, self._press_started)
        short_ms = int(self.t.get("SHORT_MS", PAGE_DEFAULTS["SHORT_MS"]))
        long_ms = int(self.t.get("LONG_MS", PAGE_DEFAULTS["LONG_MS"]))
        extra_ms = int(self.t.get("EXTRA_MS", PAGE_DEFAULTS["EXTRA_MS"]))
        double_ms = int(self.t.get("DOUBLE_MS", PAGE_DEFAULTS["DOUBLE_MS"]))

        if duration >= extra_ms:
            self._fire("extra", self.cb_extra)
            self._last_short_release = None
        elif duration >= long_ms:
            self._fire("long", self.cb_long)
            self._last_short_release = None
        elif duration <= short_ms:
            self._fire("short", self.cb_short)
            if (self._last_short_release is not None and
                    _diff(now, self._last_short_release) <= double_ms):
                self._fire("double", self.cb_double)
                self._last_short_release = None
            else:
                self._last_short_release = now
        else:
            # Zona muerta SHORT_MS..LONG_MS: sin accion, a proposito.
            self._last_short_release = None

    async def task(self):
        poll_ms = max(5, int(self.t.get("POLL_MS", 20)))

        while True:
            now = _ticks()
            value = self.pin.value()

            if value == 0 and not self._is_pressed:
                self._is_pressed = True
                self._press_started = now

            if value == 1 and self._is_pressed:
                self._is_pressed = False
                self._handle_release(now)

            await asyncio.sleep_ms(poll_ms)


class InterruptPageButton(PageButton):
    """PageButton con captura de flancos por IRQ y debounce en asyncio."""

    _EDGE_QUEUE_SIZE = 16
    _EDGE_QUEUE_MASK = _EDGE_QUEUE_SIZE - 1

    def __init__(self, pin_in, *, irq_trigger, debounce_ms=25,
                 timings=None, **kwargs):
        super().__init__(pin_in, timings=timings, **kwargs)
        self.debounce_ms = max(1, int(debounce_ms))
        self._edge_values = [1] * self._EDGE_QUEUE_SIZE
        self._edge_ticks = [0] * self._EDGE_QUEUE_SIZE
        self._edge_head = 0
        self._edge_tail = 0
        self._edge_overflows = 0
        self._stable_value = 1
        self._candidate_value = int(pin_in.value())
        self._candidate_tick = _ticks()
        self.pin.irq(handler=self._on_edge, trigger=irq_trigger)

    def _on_edge(self, pin):
        head = self._edge_head
        if head - self._edge_tail >= self._EDGE_QUEUE_SIZE:
            self._edge_tail += 1
            self._edge_overflows += 1
        index = head & self._EDGE_QUEUE_MASK
        self._edge_values[index] = pin.value()
        self._edge_ticks[index] = _ticks()
        self._edge_head = head + 1

    def close(self):
        self.pin.irq(handler=None)

    async def task(self):
        poll_ms = max(2, min(10, int(self.t.get("POLL_MS", 5))))
        while True:
            while self._edge_tail < self._edge_head:
                index = self._edge_tail & self._EDGE_QUEUE_MASK
                value = self._edge_values[index]
                tick = self._edge_ticks[index]
                self._edge_tail += 1
                if value != self._candidate_value:
                    self._candidate_value = value
                    self._candidate_tick = tick

            now = _ticks()
            if (self._candidate_value != self._stable_value and
                    _diff(now, self._candidate_tick) >= self.debounce_ms):
                if self.pin.value() == self._candidate_value:
                    self._stable_value = self._candidate_value
                    if self._stable_value == 0:
                        self._is_pressed = True
                        self._press_started = self._candidate_tick
                    elif self._is_pressed:
                        self._is_pressed = False
                        self._handle_release(self._candidate_tick)
                else:
                    self._candidate_value = int(self.pin.value())
                    self._candidate_tick = now

            await asyncio.sleep_ms(poll_ms)


class UpDownButtons:
    """Rocker UP/DOWN sobre un unico pin ADC (divisor resistivo externo).
    UP_MAX/DOWN_MAX son umbrales del valor crudo del ADC (0-4095) —
    calibrar con hardware real antes de confiar en la deteccion."""

    def __init__(self, adc, *,
                 up_short=lambda: None, down_short=lambda: None,
                 thresholds=None, timings=None, label_up="Up", label_down="Down"):
        self.adc = adc

        th = DEFAULT_THRESHOLDS.copy(); th.update(thresholds or {})
        ti = DEFAULT_TIMINGS.copy(); ti.update(timings or {})

        self.UP_MAX        = th["UP_MAX"]
        self.DOWN_MAX      = th["DOWN_MAX"]
        self.DEBOUNCE_MS   = ti["DEBOUNCE_MS"]
        self.RELEASE_MS    = ti["RELEASE_MS"]
        self.ADC_PERIOD_MS = ti["ADC_PERIOD_MS"]

        self.cb_up_short   = up_short
        self.cb_down_short = down_short
        self.label_up = label_up
        self.label_down = label_down

    def _fire(self, label, callback):
        if DEBUG:
            print("[{}] short".format(label))
        if callable(callback):
            callback()

    def _get_state(self, raw):
        if raw <= self.UP_MAX:
            return UP
        if raw <= self.DOWN_MAX:
            return DOWN
        return IDLE

    async def _debounced_press(self, expect_state):
        t0 = _ticks()
        while _diff(_ticks(), t0) < self.DEBOUNCE_MS:
            if self._get_state(self.adc.read()) != expect_state:
                return False
            await asyncio.sleep_ms(self.ADC_PERIOD_MS)
        return True

    async def _wait_release(self):
        t_rel = _ticks()
        while _diff(_ticks(), t_rel) < self.RELEASE_MS:
            if self._get_state(self.adc.read()) != IDLE:
                t_rel = _ticks()
            await asyncio.sleep_ms(self.ADC_PERIOD_MS)

    async def task(self):
        while True:
            state = self._get_state(self.adc.read())
            if state == IDLE:
                await asyncio.sleep_ms(self.ADC_PERIOD_MS)
                continue
            if not await self._debounced_press(state):
                await asyncio.sleep_ms(self.ADC_PERIOD_MS)
                continue

            label = self.label_up if state == UP else self.label_down
            cb = self.cb_up_short if state == UP else self.cb_down_short
            self._fire(label, cb)

            await self._wait_release()
            await asyncio.sleep_ms(self.ADC_PERIOD_MS)
