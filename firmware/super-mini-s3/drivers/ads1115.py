"""
Driver minimo MicroPython para el ADC ADS1115 (16 bit, 4 canales, I2C).
Modo single-shot, single-ended (A0-A3 vs GND).
"""

import time

_REG_CONVERSION = 0x00
_REG_CONFIG     = 0x01

_OS_SINGLE   = 0x8000   # arranca una conversion single-shot
_MUX_SINGLE  = {0: 0x4000, 1: 0x5000, 2: 0x6000, 3: 0x7000}  # AINx vs GND

# PGA — full-scale range. 0x0200 = +/-4.096V (buen default para divisores
# resistivos de bateria con margen bajo VDD).
_PGA_4_096V  = 0x0200
_PGA_FSR_V   = 4.096

_MODE_SINGLE = 0x0100
_DR_860SPS   = 0x00E0   # data rate maxima -> conversion mas rapida
_COMP_DISABLE = 0x0003  # deshabilita el comparador/ALERT


class ADS1115:
    def __init__(self, i2c, addr=0x48):
        self._i2c = i2c
        self._addr = addr

    def _start_conversion(self, channel):
        config = (_OS_SINGLE | _MUX_SINGLE[channel] | _PGA_4_096V |
                  _MODE_SINGLE | _DR_860SPS | _COMP_DISABLE)
        buf = bytes([_REG_CONFIG, (config >> 8) & 0xFF, config & 0xFF])
        self._i2c.writeto(self._addr, buf)

    def _read_conversion(self):
        self._i2c.writeto(self._addr, bytes([_REG_CONVERSION]))
        raw = self._i2c.readfrom(self._addr, 2)
        value = (raw[0] << 8) | raw[1]
        if value & 0x8000:
            value -= 1 << 16
        return value

    def read_volts(self, channel, settle_ms=2):
        """Lee un canal single-ended (0-3) y devuelve voltios."""
        self._start_conversion(channel)
        time.sleep_ms(settle_ms)
        raw = self._read_conversion()
        return (raw / 32768.0) * _PGA_FSR_V

    def read_all_volts(self, settle_ms=2):
        """Lee A0..A3 en secuencia. Devuelve lista de 4 voltajes."""
        return [self.read_volts(ch, settle_ms=settle_ms) for ch in range(4)]
