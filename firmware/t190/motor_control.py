
# DEPRECATED: prototipo de control de motor, no soportado por el firmware T190
# actual. Se conserva como referencia; sus pines y helpers fueron retirados
# de HW.py.
#
#   MotorController
#     - lee acelerador y freno de mano por 2 ADC (HW.ADC_THROTTLE_PIN / ADC_BRAKE_PIN)
#     - el freno tiene prioridad de seguridad: si hay freno, el acelerador se fuerza a 0
#     - escribe esos valores como voltaje sintetico en el controlador chino
#       via 2x MCP4725 (HW.DAC0_ADDR = acelerador, HW.DAC1_ADDR = freno/regen)
#
#   SpeedSensor
#     - cuenta pulsos de velocidad del vehiculo en HW.SPEED_PULSE_PIN (IRQ)
#     - calcula velocidad instantanea en km/h a partir del periodo entre pulsos
#
# Llamar MotorController.update() periodicamente (recomendado 20-50ms) desde
# el loop principal / tarea asyncio.

import machine
import time

import HW


class MotorController:
    def __init__(self, i2c=None, deadband=0.02):
        self._i2c = i2c or HW.make_i2c()
        self._adc_throttle = HW.make_adc(HW.ADC_THROTTLE_PIN)
        self._adc_brake = HW.make_adc(HW.ADC_BRAKE_PIN)
        self._deadband = deadband

        self.throttle = 0.0   # 0.0-1.0, acelerador normalizado (ya con freno aplicado)
        self.brake = 0.0      # 0.0-1.0, freno normalizado
        self.throttle_raw = 0.0  # 0.0-1.0, acelerador normalizado SIN aplicar el corte por freno

        # Seguridad: salida a cero antes de arrancar a leer/controlar.
        HW.dacs_zero_both(self._i2c)

    @staticmethod
    def _normalize(volts, vmin, vmax):
        if vmax <= vmin:
            return 0.0
        if volts <= vmin:
            return 0.0
        if volts >= vmax:
            return 1.0
        return (volts - vmin) / (vmax - vmin)

    def update(self):
        """Lee ADC, aplica deadband + prioridad de freno, escribe los DAC.
        Devuelve (throttle, brake) normalizados 0.0-1.0."""
        v_thr = HW.adc_read_volts(self._adc_throttle)
        v_brk = HW.adc_read_volts(self._adc_brake)

        thr = self._normalize(v_thr, HW.ADC_THROTTLE_MIN_V, HW.ADC_THROTTLE_MAX_V)
        brk = self._normalize(v_brk, HW.ADC_BRAKE_MIN_V, HW.ADC_BRAKE_MAX_V)

        if thr < self._deadband:
            thr = 0.0
        if brk < self._deadband:
            brk = 0.0

        self.throttle_raw = thr
        self.brake = brk
        # Freno tiene prioridad: corta el acelerador por seguridad.
        self.throttle = 0.0 if brk > 0.0 else thr

        out_span = HW.DAC_OUT_MAX_V - HW.DAC_OUT_MIN_V
        out_v_throttle = HW.DAC_OUT_MIN_V + self.throttle * out_span
        out_v_brake    = HW.DAC_OUT_MIN_V + self.brake * out_span

        HW.set_dac_volts(self._i2c, HW.DAC0_ADDR, out_v_throttle)
        HW.set_dac_volts(self._i2c, HW.DAC1_ADDR, out_v_brake)

        return self.throttle, self.brake

    def stop(self):
        """Corte de emergencia: fuerza ambas salidas DAC a 0V."""
        self.throttle = 0.0
        self.brake = 0.0
        HW.dacs_zero_both(self._i2c)


class SpeedSensor:
    """Cuenta pulsos del sensor Hall de velocidad (motor o rueda) via IRQ
    y estima velocidad instantanea en km/h a partir del periodo entre pulsos.

    Calibrar HW.SPEED_PULSES_PER_REV y HW.SPEED_WHEEL_CIRCUMFERENCE_M segun
    el vehiculo real antes de confiar en el valor de speed_kmh().
    """

    def __init__(self, pulses_per_rev=None, wheel_circumference_m=None,
                 debounce_us=None):
        self._pulses_per_rev = pulses_per_rev or HW.SPEED_PULSES_PER_REV
        self._circumference_m = wheel_circumference_m or HW.SPEED_WHEEL_CIRCUMFERENCE_M
        self._debounce_us = debounce_us or HW.SPEED_PULSE_DEBOUNCE_US

        self._count = 0
        self._last_us = 0
        self._last_period_us = 0

        self._pin = HW.make_speed_pulse_pin()
        trigger = (machine.Pin.IRQ_RISING if HW.SPEED_PULSE_EDGE == "RISING"
                   else machine.Pin.IRQ_FALLING)
        self._pin.irq(trigger=trigger, handler=self._on_pulse)

    def _on_pulse(self, pin):
        now = time.ticks_us()
        dt = time.ticks_diff(now, self._last_us)
        if dt < self._debounce_us:
            return
        self._last_period_us = dt
        self._last_us = now
        self._count += 1

    def pulse_count(self):
        return self._count

    def speed_kmh(self):
        """Velocidad instantanea estimada desde el ultimo periodo entre pulsos.
        Devuelve 0.0 si no hubo pulsos recientes (vehiculo detenido o sin dato)."""
        if self._last_period_us <= 0:
            return 0.0
        # Si el ultimo pulso fue hace mas de 2s, se considera detenido.
        if time.ticks_diff(time.ticks_us(), self._last_us) > 2_000_000:
            return 0.0
        rev_per_s = 1.0 / (self._pulses_per_rev * (self._last_period_us / 1_000_000.0))
        return rev_per_s * self._circumference_m * 3.6

    def reset_trip(self):
        self._count = 0
