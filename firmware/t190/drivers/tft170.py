"""
Driver MicroPython para el display TFT 170x320 del Heltec Vision Master T190.
Panel: N190-1732TBWPG01-C30  —  Controlador: ST7789 real (NO GC9107).

Secuencia de init, offsets y MADCTL verificados contra el driver oficial de
Heltec (Adafruit ST7789 renombrado "HT_ST7789"):
  https://github.com/HelTecAutomation/Heltec_ESP32/blob/master/src/HT_st7789spi.cpp
Para init(170, 320) ese driver calcula:
  _rowstart = (320-320)/2 = 0   (offset en Y)
  _colstart = (240-170)/2 = 35  (offset en X — el panel de 170px esta
                                  centrado en el GRAM nativo de 240px del
                                  controlador)
y su generic_st7789[] NO manda ningun registro de gamma/VCOM/power-control
(PORCTRL/GCTRL/VCOMS/LCMCTRL/VRHS/VDVS/PWCTRL1/gamma) — solo
SWRESET, SLPOUT, COLMOD, MADCTL, INVON, NORON, DISPON. Mandar esos registros
extra (como hacia una version previa de este driver, asumiendo GC9107) puede
dejar al controlador en un estado invalido y corromper la imagen (bandas,
colores raros, texto espejado).

Pines internos (no en headers):
  MOSI = GPIO48 (TFT_SDA)
  SCK  = GPIO38 (TFT_SCL)
  CS   = GPIO39 (TFT_CS)
  DC   = GPIO47 (TFT_RS)
  RST  = GPIO40 (TFT_RST)
  BL   = GPIO17 (LEDK_EN backlight)
  PWR  = GPIO7  (VTFT_Ctrl, LOW = encendido)
"""

import time
from machine import Pin, SPI
import framebuf

# ── Comandos ST7789 ──────────────────────────────────────────────────────────
_NOP     = 0x00
_SWRESET = 0x01
_SLPOUT  = 0x11
_NORON   = 0x13
_INVOFF  = 0x20
_INVON   = 0x21
_DISPON  = 0x29
_CASET   = 0x2A
_RASET   = 0x2B
_RAMWR   = 0x2C
_MADCTL  = 0x36
_COLMOD  = 0x3A

_CHUNK = 1024   # bytes por escritura SPI (multiplo de 2 para RGB565)

# MADCTL flags
_MADCTL_MY  = 0x80
_MADCTL_MX  = 0x40
_MADCTL_MV  = 0x20
_MADCTL_ML  = 0x10
_MADCTL_BGR = 0x08   # el panel del T190 es RGB (bit en 0); no usar por defecto
_MADCTL_MH  = 0x04


def rgb565(r, g, b):
    """Convierte RGB 8-bit a color RGB565 (big-endian para SPI)."""
    return ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)


class TFT170:
    """
    Driver para el display 170x320 del T190.
    La resolucion fisica es 170(W) x 320(H), centrada en el GRAM nativo de
    240x320 del controlador ST7789 (offset X=35, sin offset en Y).
    Rotation 0 = portrait (170 wide, 320 tall).
    Rotation 1 = landscape (320 wide, 170 tall).
    Valores de MADCTL/offset calcados 1:1 del setRotation() de Heltec.
    """

    RAW_WIDTH  = 170
    RAW_HEIGHT = 320

    _ROTATION = {
        0: {"madctl": _MADCTL_MX | _MADCTL_MY,
            "width": 170, "height": 320, "x_offset": 35, "y_offset": 0},
        1: {"madctl": _MADCTL_MY | _MADCTL_MV,
            "width": 320, "height": 170, "x_offset": 0,  "y_offset": 35},
        2: {"madctl": 0x00,
            "width": 170, "height": 320, "x_offset": 35, "y_offset": 0},
        3: {"madctl": _MADCTL_MX | _MADCTL_MV,
            "width": 320, "height": 170, "x_offset": 0,  "y_offset": 35},
    }

    def __init__(self, spi, dc, rst, cs=None, bl=None, *, rotation=0,
                 invert=True, bgr=False):
        self._spi = spi
        self._dc  = dc
        self._rst = rst
        self._cs  = cs
        self._bl  = bl

        rot = self._ROTATION.get(rotation % 4, self._ROTATION[0])
        self.width    = rot["width"]
        self.height   = rot["height"]
        self._x_off   = rot["x_offset"]
        self._y_off   = rot["y_offset"]
        self._madctl  = rot["madctl"] | (_MADCTL_BGR if bgr else 0x00)
        self._invert  = invert

        # FrameBuffer RGB565 en RAM
        buf_size = self.width * self.height * 2
        self._buf = bytearray(buf_size)
        self.framebuf = framebuf.FrameBuffer(self._buf, self.width, self.height,
                                             framebuf.RGB565)

        self._init_display()

    # ── Bajo nivel ────────────────────────────────────────────────────────────

    def _cs_low(self):
        if self._cs:
            self._cs.value(0)

    def _cs_high(self):
        if self._cs:
            self._cs.value(1)

    def _write_cmd(self, cmd):
        self._dc.value(0)
        self._cs_low()
        self._spi.write(bytes([cmd]))
        self._cs_high()

    def _write_data(self, data):
        self._dc.value(1)
        self._cs_low()
        self._spi.write(data)
        self._cs_high()

    def _write_reg(self, cmd, *data):
        self._write_cmd(cmd)
        if data:
            self._write_data(bytes(data))

    # ── Init secuencia ST7789 (igual a generic_st7789[] de Heltec) ──────────────

    def _init_display(self):
        self._dc.value(0)
        self._cs_high()

        # Reset hardware
        if self._rst:
            self._rst.value(1)
            time.sleep_ms(10)
            self._rst.value(0)
            time.sleep_ms(20)
            self._rst.value(1)
            time.sleep_ms(150)

        self._write_cmd(_SWRESET)
        time.sleep_ms(150)
        self._write_cmd(_SLPOUT)
        time.sleep_ms(150)

        self._write_reg(_COLMOD, 0x55)        # RGB565, 16 bits/pixel
        time.sleep_ms(10)
        self._write_reg(_MADCTL, self._madctl)

        # Heltec manda INVON incondicional ("hack") — el panel necesita
        # inversion de color para verse correcto.
        self._write_cmd(_INVON if self._invert else _INVOFF)
        time.sleep_ms(10)

        self._write_cmd(_NORON)
        time.sleep_ms(10)

        self.fill(0)
        self.show()

        self._write_cmd(_DISPON)
        time.sleep_ms(10)

        if self._bl:
            self._bl.value(1)

    # ── Ventana de dirección ──────────────────────────────────────────────────

    def _set_window(self, x0, y0, x1, y1):
        x0 += self._x_off
        x1 += self._x_off
        y0 += self._y_off
        y1 += self._y_off
        self._write_cmd(_CASET)
        self._dc.value(1)
        self._cs_low()
        self._spi.write(bytes([x0 >> 8, x0 & 0xFF, x1 >> 8, x1 & 0xFF]))
        self._cs_high()
        self._write_cmd(_RASET)
        self._dc.value(1)
        self._cs_low()
        self._spi.write(bytes([y0 >> 8, y0 & 0xFF, y1 >> 8, y1 & 0xFF]))
        self._cs_high()
        self._write_cmd(_RAMWR)

    # ── API pública ───────────────────────────────────────────────────────────

    def show(self):
        """Vuelca el framebuffer completo al display."""
        self._set_window(0, 0, self.width - 1, self.height - 1)
        self._dc.value(1)
        self._cs_low()
        mv = memoryview(self._buf)
        total = len(self._buf)
        offset = 0
        while offset < total:
            end = min(offset + _CHUNK, total)
            self._spi.write(mv[offset:end])
            offset = end
        self._cs_high()

    def show_region(self, x, y, w, h):
        """Vuelca solo una región del framebuffer (optimización de redibujado)."""
        if w <= 0 or h <= 0:
            return
        x = max(0, x)
        y = max(0, y)
        if x >= self.width or y >= self.height:
            return
        x2 = min(x + w - 1, self.width - 1)
        y2 = min(y + h - 1, self.height - 1)
        self._set_window(x, y, x2, y2)
        self._dc.value(1)
        self._cs_low()
        stride = self.width * 2
        for row in range(y, y2 + 1):
            row_start = row * stride + x * 2
            row_end   = row * stride + (x2 + 1) * 2
            self._spi.write(memoryview(self._buf)[row_start:row_end])
        self._cs_high()

    def fill(self, color):
        """Rellena el framebuffer con un color RGB565."""
        self.framebuf.fill(color)

    def fill_rect(self, x, y, w, h, color):
        self.framebuf.fill_rect(x, y, w, h, color)

    def pixel(self, x, y, color=None):
        if color is None:
            return self.framebuf.pixel(x, y)
        self.framebuf.pixel(x, y, color)

    def text(self, s, x, y, color=0xFFFF):
        self.framebuf.text(s, x, y, color)

    def hline(self, x, y, w, color):
        self.framebuf.hline(x, y, w, color)

    def vline(self, x, y, h, color):
        self.framebuf.vline(x, y, h, color)

    def rect(self, x, y, w, h, color):
        self.framebuf.rect(x, y, w, h, color)

    def blit(self, fbuf, x, y, key=-1, palette=None):
        if palette:
            self.framebuf.blit(fbuf, x, y, key, palette)
        else:
            self.framebuf.blit(fbuf, x, y, key)

    def backlight(self, on=True):
        if self._bl:
            self._bl.value(1 if on else 0)

    def set_rotation(self, rotation):
        rot = self._ROTATION.get(rotation % 4, self._ROTATION[0])
        bgr_bit = self._madctl & _MADCTL_BGR
        self.width   = rot["width"]
        self.height  = rot["height"]
        self._x_off  = rot["x_offset"]
        self._y_off  = rot["y_offset"]
        self._madctl = rot["madctl"] | bgr_bit
        self._write_reg(_MADCTL, self._madctl)
        buf_size = self.width * self.height * 2
        self._buf = bytearray(buf_size)
        self.framebuf = framebuf.FrameBuffer(self._buf, self.width, self.height,
                                             framebuf.RGB565)
