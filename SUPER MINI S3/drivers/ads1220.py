"""
Driver MicroPython para el ADC ADS1220 (24 bit, SPI) usado en la placa
"sensor de corriente toroidal" de LSF (ver foto: GND/MOSI/MISO/CS/SCLK/+5V,
toroide azul con sensor Hall adentro).

Puerteado 1:1 desde el driver oficial en C++ del equipo (mismo IC, misma
config de registros, misma formula de conversion) para que la constante de
sensibilidad SENS_V_PER_A siga siendo valida sin recalibrar la placa fisica:
  https://github.com/Electronica-LSF/ECO-YPF-2025-LSF
  PlacaTrasera/components/ADC1220/ADC1220.cpp

Config fija (igual al original): AIN0-AIN1 diferencial, PGA x4, VREF interna
2.048V, modo conversion continua a 20 SPS, SPI modo 1 (CPOL=0, CPHA=1).
"""

import time
from machine import Pin

# ── Comandos (datasheet ADS1220, tabla 10) ───────────────────────────────────
_CMD_RESET = 0x06
_CMD_START = 0x08
_CMD_RDATA = 0x10
_CMD_RREG  = 0x20
_CMD_WREG  = 0x40

# ── Config de registros 0-3 (MUX=AIN0-AIN1, GAIN=4, PGA on; DR=20SPS,
#    modo continuo; VREF interna 2.048V; sin IDAC) ───────────────────────────
_REG0 = 0b00000100
_REG1 = 0b00000100
_REG2 = 0b00000000
_REG3 = 0b00000000

_GAIN = 4
_VREF = 2.048
_FULL_SCALE = 8388608.0   # 2**23

SENS_V_PER_A = 0.007813   # sensibilidad del sensor Hall de la placa LSF


class ADS1220:
    def __init__(self, spi, cs, sens_v_per_a=SENS_V_PER_A):
        self._spi = spi
        self._cs = cs if isinstance(cs, Pin) else Pin(cs, Pin.OUT)
        self._cs.value(1)
        self._sens = sens_v_per_a
        self._offset = 0

    # ── Bajo nivel ────────────────────────────────────────────────────────────

    def _xfer(self, tx):
        rx = bytearray(len(tx))
        self._cs.value(0)
        self._spi.write_readinto(bytes(tx), rx)
        self._cs.value(1)
        return rx

    def _write_regs(self, start_addr, values):
        cmd = _CMD_WREG | ((start_addr << 2) & 0x0C) | ((len(values) - 1) & 0x03)
        self._xfer([cmd] + list(values))

    def _read_regs(self, start_addr, n):
        cmd = _CMD_RREG | ((start_addr << 2) & 0x0C) | ((n - 1) & 0x03)
        rx = self._xfer([cmd] + [0] * n)
        return rx[1:]

    def _read_raw(self):
        rx = self._xfer([_CMD_RDATA, 0, 0, 0])
        raw = ((rx[1] & 0x7F) << 16) | (rx[2] << 8) | rx[3]
        if rx[1] & 0x80:
            raw = -(0x7FFFFF - raw + 1)
        return raw

    # ── API ──────────────────────────────────────────────────────────────────

    def init(self):
        """Reset + escribe config + arranca conversion continua. Devuelve
        True si el ADC confirma la config al releerla."""
        time.sleep_ms(100)
        self._xfer([_CMD_RESET])
        time.sleep_ms(100)

        regs = (_REG0, _REG1, _REG2, _REG3)
        self._write_regs(0, regs)
        readback = self._read_regs(0, 4)
        if tuple(readback) != regs:
            return False

        self._xfer([_CMD_START])
        time.sleep_ms(100)
        return True

    def calibrate_zero(self, n=3, delay_ms=60):
        """Promedia n lecturas crudas con corriente ~0 y las guarda como
        offset. Llamar una vez al arrancar, con la bateria en reposo."""
        total = 0
        for _ in range(n):
            total += self._read_raw()
            time.sleep_ms(delay_ms)
        self._offset = total // n
        return self._offset

    def read_current(self):
        """Corriente instantanea en Amperes (una lectura del ADC)."""
        raw = (self._read_raw() - self._offset) / _GAIN
        volts = (raw * _VREF) / _FULL_SCALE
        return volts / self._sens

    def set_sensitivity(self, sens_v_per_a):
        """Actualiza la sensibilidad (V/A) en caliente -- usado por
        main.reload_config() para recalibrar sin reiniciar."""
        self._sens = sens_v_per_a
