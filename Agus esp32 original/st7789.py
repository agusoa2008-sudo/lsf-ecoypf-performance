import time
import ustruct
from machine import Pin

# ── Paleta de colores RGB565 ──────────────────────────────────────────────────
BLACK  = 0x0000
BLUE   = 0x001F
RED    = 0xF800
GREEN  = 0x07E0
WHITE  = 0xFFFF
CYAN   = 0x07FF
YELLOW = 0xFFE0
GRAY   = 0x8410
DKGRAY = 0x4208
DKGRAY2= 0x2945


def _pad_left(s, width):
    """Reemplaza str.rjust — MicroPython no lo incluye."""
    while len(s) < width:
        s = ' ' + s
    return s


class ST7789:
    def __init__(self, spi, width, height, reset, dc, cs=None, backlight=None):
        self.spi       = spi
        self.width     = width    # 320 en landscape
        self.height    = height   # 170 en landscape
        self.reset     = reset
        self.dc        = dc
        self.cs        = cs
        self.backlight = backlight
        self.x_offset  = 0
        self.y_offset  = 0
        self.init()

    # ── SPI ──────────────────────────────────────────────────────────────────
    def write_cmd(self, cmd):
        self.dc.value(0)
        if self.cs: self.cs.value(0)
        self.spi.write(bytearray([cmd]))
        if self.cs: self.cs.value(1)

    def write_data(self, data):
        if not data: return
        self.dc.value(1)
        if self.cs: self.cs.value(0)
        self.spi.write(data)
        if self.cs: self.cs.value(1)

    # ── Init ─────────────────────────────────────────────────────────────────
    def init(self):
        self.reset.value(1); time.sleep_ms(50)
        self.reset.value(0); time.sleep_ms(50)
        self.reset.value(1); time.sleep_ms(150)

        self.write_cmd(0x01); time.sleep_ms(150)   # Software reset
        self.write_cmd(0x11); time.sleep_ms(150)   # Sleep out

        # MADCTL: MY|MX|MV|ML|BGR|MH
        # 0x70 = 0b01110000 → MX|MV|MY → landscape con colores correctos
        self.write_cmd(0x36)
        self.write_data(b'\x70')

        self.write_cmd(0x3A)
        self.write_data(b'\x05')   # 16-bit color RGB565

        self.write_cmd(0x21); time.sleep_ms(10)    # Inversion ON (necesario ST7789)
        self.write_cmd(0x29); time.sleep_ms(100)   # Display ON

        if self.backlight: self.backlight.value(1)

    # ── Ventana de escritura ─────────────────────────────────────────────────
    def set_window(self, x, y, w, h):
        x0 = x + self.x_offset
        y0 = y + self.y_offset
        self.write_cmd(0x2A)
        self.write_data(ustruct.pack(">HH", x0, x0 + w - 1))
        self.write_cmd(0x2B)
        self.write_data(ustruct.pack(">HH", y0, y0 + h - 1))
        self.write_cmd(0x2C)

    # ── Rectángulo relleno ───────────────────────────────────────────────────
    def fill_rect(self, x, y, w, h, color):
        if w <= 0 or h <= 0: return
        self.set_window(x, y, w, h)
        pixel      = ustruct.pack(">H", color)
        chunk_size = 1024
        total      = w * h
        chunk      = min(total, chunk_size)
        line       = pixel * chunk
        for _ in range(total // chunk):
            self.write_data(line)
        rest = total % chunk
        if rest > 0:
            self.write_data(line[:rest * 2])

    def fill(self, color):
        self.fill_rect(0, 0, self.width, self.height, color)

    # ── Fuente bitmap 8×8 ────────────────────────────────────────────────────
    FONT_8 = {
        ' ': [0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00],
        '0': [0x3C,0x66,0x6E,0x76,0x66,0x66,0x3C,0x00],
        '1': [0x18,0x38,0x18,0x18,0x18,0x18,0x7E,0x00],
        '2': [0x3C,0x66,0x06,0x0C,0x18,0x30,0x7E,0x00],
        '3': [0x3C,0x66,0x06,0x1C,0x06,0x66,0x3C,0x00],
        '4': [0x0C,0x1C,0x2C,0x4C,0x7E,0x0C,0x0C,0x00],
        '5': [0x7E,0x60,0x7C,0x06,0x06,0x66,0x3C,0x00],
        '6': [0x1C,0x30,0x60,0x7C,0x66,0x66,0x3C,0x00],
        '7': [0x7E,0x06,0x0C,0x18,0x30,0x30,0x30,0x00],
        '8': [0x3C,0x66,0x66,0x3C,0x66,0x66,0x3C,0x00],
        '9': [0x3C,0x66,0x66,0x3E,0x06,0x0C,0x38,0x00],
        '/': [0x02,0x06,0x0C,0x18,0x30,0x60,0x40,0x00],
        '%': [0x62,0x66,0x0C,0x18,0x30,0x66,0x46,0x00],
        'K': [0x66,0x6C,0x78,0x70,0x78,0x6C,0x66,0x00],
        'M': [0x63,0x77,0x7F,0x6B,0x63,0x63,0x63,0x00],
        'H': [0x66,0x66,0x66,0x7E,0x66,0x66,0x66,0x00],
        'k': [0x60,0x60,0x66,0x6C,0x78,0x6C,0x66,0x00],
        'm': [0x00,0x00,0x76,0x7F,0x6B,0x63,0x63,0x00],
        'h': [0x60,0x60,0x6C,0x76,0x66,0x66,0x66,0x00],
        '.': [0x00,0x00,0x00,0x00,0x00,0x18,0x18,0x00],
        '-': [0x00,0x00,0x00,0x7E,0x00,0x00,0x00,0x00],
    }

    def text(self, s, x, y, color, scale=1, bg=0x0000):
        cx = x
        for ch in s:
            glyph = self.FONT_8.get(ch, self.FONT_8[' '])
            for row, bits in enumerate(glyph):
                for col in range(8):
                    px = cx + col * scale
                    py = y  + row * scale
                    if bits & (0x80 >> col):
                        self.fill_rect(px, py, scale, scale, color)
                    elif bg is not None:
                        self.fill_rect(px, py, scale, scale, bg)
            cx += 8 * scale

    # ── Dígitos 7 segmentos grandes ──────────────────────────────────────────
    _SEG7 = {
        '0': (1,1,1,1,1,1,0),
        '1': (0,1,1,0,0,0,0),
        '2': (1,1,0,1,1,0,1),
        '3': (1,1,1,1,0,0,1),
        '4': (0,1,1,0,0,1,1),
        '5': (1,0,1,1,0,1,1),
        '6': (1,0,1,1,1,1,1),
        '7': (1,1,1,0,0,0,0),
        '8': (1,1,1,1,1,1,1),
        '9': (1,1,1,1,0,1,1),
        ' ': (0,0,0,0,0,0,0),
        '-': (0,0,0,0,0,0,1),
    }

    def digit_large(self, ch, x, y, color, sz=1, bg=0x0000):
        """Dibuja un carácter 7-seg. sz=1 → 20×36 px."""
        W   = 20 * sz
        H   = 36 * sz
        t   = 3  * sz
        gap = 1  * sz
        self.fill_rect(x, y, W, H, bg)
        segs = self._SEG7.get(ch, self._SEG7[' '])
        a, b, c, d, e, f, g = segs
        mid_y = y + H // 2
        bot_y = y + H - t
        if a: self.fill_rect(x+gap+t,  y,            W-2*(gap+t), t,          color)
        if d: self.fill_rect(x+gap+t,  bot_y,        W-2*(gap+t), t,          color)
        if g: self.fill_rect(x+gap+t,  mid_y-t//2,   W-2*(gap+t), t,          color)
        if f: self.fill_rect(x,        y+gap+t,      t,           H//2-gap-t, color)
        if b: self.fill_rect(x+W-t,    y+gap+t,      t,           H//2-gap-t, color)
        if e: self.fill_rect(x,        mid_y+gap,    t,           H//2-gap-t, color)
        if c: self.fill_rect(x+W-t,    mid_y+gap,    t,           H//2-gap-t, color)

    def number_large(self, n, x, y, color, sz=1, bg=0x0000, width=2):
        """Dibuja número con dígitos 7-seg grandes. Sin str.rjust."""
        s = str(int(n))
        s = _pad_left(s, width)          # ← usa helper, no rjust
        char_w = (20 * sz) + (2 * sz)
        for i, ch in enumerate(s):
            self.digit_large(ch, x + i * char_w, y, color, sz=sz, bg=bg)

    def hline(self, x, y, w, color):
        self.fill_rect(x, y, w, 1, color)

    def vline(self, x, y, h, color):
        self.fill_rect(x, y, 1, h, color)
