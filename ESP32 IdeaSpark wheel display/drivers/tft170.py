"""
Driver MicroPython para el display TFT 170x320 Ideaspark ST7789 1.9".

Variante "sin framebuffer" de New T190/drivers/tft170.py -- esta placa es un
ESP32 clasico SIN PSRAM (el T190 es un ESP32-S3R8, con 8MB de PSRAM). El
driver del T190 guarda la pantalla completa en RAM como un
framebuf.FrameBuffer (170*320*2 = 108800 bytes) y vuelca todo con show():
en hardware real sin PSRAM eso tira
    MemoryError: memory allocation failed, allocating 108800 bytes
porque no hay un bloque contiguo de esa RAM libre.

Esta version NUNCA guarda la pantalla completa: cada fill()/text()/hline()
escribe directo al panel por SPI en bloques chicos (mismo patron que usa
st7789py.py de Russ Hughes, que tampoco mantiene framebuffer propio).
`text()` arma un framebuf.FrameBuffer chiquito (ancho_string x 8px, para
poder reusar la fuente 8x8 built-in de framebuf) y lo manda directo al
panel -- nunca una pantalla entera a la vez.

Costo: no hay `blit()` de sprites/fuentes custom (requeriria una pantalla
destino en RAM para componer). Si en el futuro se porta la UI de
New T190/main.py (fuentes seven_segment_* vía seven_seg.py, que llama
tft.blit()), hay que adaptar ese renderizador para que mande cada glifo
directo por SPI en vez de componer sobre un framebuffer propio -- no es
cuestion de copiar seven_seg.py tal cual.

Secuencia de init, offsets y MADCTL: mismos valores calibrados para el
panel del T190 (ver New T190/drivers/tft170.py) -- **sin verificar todavia
en el panel real de esta placa Ideaspark**, ver PROYECTO_IDEASPARK.md.

Pines: ver HW.py de esta carpeta -- son parametros del constructor, no
estan hardcodeados en este driver.
"""

from machine import Pin, SPI
import time
import framebuf

# ── Comandos ST7789 ──────────────────────────────────────────────────────────
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

# MADCTL flags
_MADCTL_MY  = 0x80
_MADCTL_MX  = 0x40
_MADCTL_MV  = 0x20
_MADCTL_BGR = 0x08   # sin verificar en el panel Ideaspark; no usar por defecto

_CHUNK_PX = 512   # pixeles por escritura SPI en fill_rect (1024 bytes)


def rgb565(r, g, b):
    """Convierte RGB 8-bit a color RGB565 (big-endian para SPI)."""
    return ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)


class TFT170:
    """
    Driver "sin framebuffer" para un panel 170x320 sobre controlador ST7789.
    Cada operacion de dibujo escribe directo al panel por SPI -- no hay
    copia completa de la pantalla en RAM (ver docstring del modulo).
    Rotation 0 = portrait (170 wide, 320 tall).
    Rotation 1 = landscape (320 wide, 170 tall).
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

    # ── Init secuencia ST7789 (minima, igual al T190 -- ver docstring) ───────

    def _init_display(self):
        self._dc.value(0)
        self._cs_high()

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

        self._write_cmd(_INVON if self._invert else _INVOFF)
        time.sleep_ms(10)

        self._write_cmd(_NORON)
        time.sleep_ms(10)

        self.fill(0)   # ya escribe directo al panel, no hace falta show()

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

    def fill_rect(self, x, y, w, h, color):
        """Rellena un rectangulo escribiendo directo al panel, en bloques de
        a lo sumo _CHUNK_PX pixeles -- nunca asigna un buffer del tamaño del
        rectangulo completo."""
        if w <= 0 or h <= 0:
            return
        x = max(0, x)
        y = max(0, y)
        x2 = min(x + w, self.width) - 1
        y2 = min(y + h, self.height) - 1
        if x2 < x or y2 < y:
            return
        self._set_window(x, y, x2, y2)
        hi, lo = (color >> 8) & 0xFF, color & 0xFF
        px_total = (x2 - x + 1) * (y2 - y + 1)
        chunk = bytes((hi, lo)) * min(_CHUNK_PX, px_total)
        self._dc.value(1)
        self._cs_low()
        remaining = px_total
        while remaining > 0:
            n = min(_CHUNK_PX, remaining)
            self._spi.write(chunk[: n * 2] if n < _CHUNK_PX else chunk)
            remaining -= n
        self._cs_high()

    def fill(self, color):
        """Rellena toda la pantalla (directo al panel, ver fill_rect)."""
        self.fill_rect(0, 0, self.width, self.height, color)

    def hline(self, x, y, w, color):
        self.fill_rect(x, y, w, 1, color)

    def vline(self, x, y, h, color):
        self.fill_rect(x, y, 1, h, color)

    def rect(self, x, y, w, h, color):
        self.hline(x, y, w, color)
        self.hline(x, y + h - 1, w, color)
        self.vline(x, y, h, color)
        self.vline(x + w - 1, y, h, color)

    def pixel(self, x, y, color):
        self.fill_rect(x, y, 1, 1, color)

    def text(self, s, x, y, color=0xFFFF, bg=0x0000):
        """Renderiza 's' con la fuente 8x8 built-in de framebuf en un buffer
        chico (ancho_string x 8px, no la pantalla completa) y lo manda
        directo al panel."""
        if not s:
            return
        w = len(s) * 8
        h = 8
        buf = bytearray(w * h * 2)
        fb = framebuf.FrameBuffer(buf, w, h, framebuf.RGB565)
        fb.fill(bg)
        fb.text(s, 0, 0, color)
        self._blit_raw(buf, x, y, w, h)

    def _blit_raw(self, buf, x, y, w, h):
        if x + w <= 0 or y + h <= 0 or x >= self.width or y >= self.height:
            return
        self._set_window(x, y, x + w - 1, y + h - 1)
        self._dc.value(1)
        self._cs_low()
        mv = memoryview(buf)
        total = len(buf)
        offset = 0
        while offset < total:
            end = min(offset + 1024, total)
            self._spi.write(mv[offset:end])
            offset = end
        self._cs_high()

    def blit_raw(self, buf, x, y, w, h):
        """Version publica de _blit_raw() para renderizadores externos
        (ver seven_seg.py) que arman su propio bytearray RGB565 de un glifo
        chico -- NUNCA una pantalla completa -- y lo mandan directo por SPI,
        igual que text()."""
        self._blit_raw(buf, x, y, w, h)

    def show(self):
        """No-op: fill()/text()/hline() ya escriben directo al panel."""
        pass

    def backlight(self, on=True):
        if self._bl:
            self._bl.value(1 if on else 0)
