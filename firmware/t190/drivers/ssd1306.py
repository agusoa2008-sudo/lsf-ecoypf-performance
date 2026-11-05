# MicroPython SSD1306 OLED driver, I2C interface only (sin soporte SPI,
# no se usa en el T190).
#
# init_display() espera _CHARGE_PUMP_SETTLE_MS despues de prender la
# charge pump/display (SET_CHARGE_PUMP + SET_DISP|0x01) y antes del
# primer fill()+show(). Confirmado en banco: escrituras I2C de hasta 256
# bytes sueltas andan bien, pero esa misma escritura tira OSError
# ETIMEDOUT si se manda pegada al power-on de la charge pump -- el
# transitorio de corriente hace caer el rail Ve_3V3 justo en ese
# momento. No es un problema de pines, de pull-ups, ni de tamano de
# transaccion I2C en si.
#
# write_framebuf() igual manda el buffer en bloques de _CHUNK bytes (no
# todo en una transaccion) como margen extra de robustez.

from micropython import const
import framebuf
import time

_CHUNK = const(128)  # bytes de datos por transaccion I2C (1 "pagina")
_CHARGE_PUMP_SETTLE_MS = const(100)


# register definitions
SET_CONTRAST = const(0x81)
SET_ENTIRE_ON = const(0xA4)
SET_NORM_INV = const(0xA6)
SET_DISP = const(0xAE)
SET_MEM_ADDR = const(0x20)
SET_COL_ADDR = const(0x21)
SET_PAGE_ADDR = const(0x22)
SET_DISP_START_LINE = const(0x40)
SET_SEG_REMAP = const(0xA0)
SET_MUX_RATIO = const(0xA8)
SET_COM_OUT_DIR = const(0xC0)
SET_DISP_OFFSET = const(0xD3)
SET_COM_PIN_CFG = const(0xDA)
SET_DISP_CLK_DIV = const(0xD5)
SET_PRECHARGE = const(0xD9)
SET_VCOM_DESEL = const(0xDB)
SET_CHARGE_PUMP = const(0x8D)


class SSD1306:
    def __init__(self, width, height, external_vcc):
        self.width = width
        self.height = height
        self.external_vcc = external_vcc
        self.pages = self.height // 8
        # La subclase crea self.buffer/self.framebuf antes de llamar a
        # super().__init__() -- necesita anteponer el byte de control.
        self.poweron()
        self.init_display()

    def init_display(self):
        for cmd in (
            SET_DISP | 0x00,  # off
            # address setting
            SET_MEM_ADDR,
            0x00,  # horizontal
            # resolution and layout
            SET_DISP_START_LINE | 0x00,
            SET_SEG_REMAP | 0x01,  # column addr 127 mapped to SEG0
            SET_MUX_RATIO,
            self.height - 1,
            SET_COM_OUT_DIR | 0x08,  # scan from COM[N] to COM0
            SET_DISP_OFFSET,
            0x00,
            SET_COM_PIN_CFG,
            0x02 if self.width > 2 * self.height else 0x12,
            # timing and driving scheme
            SET_DISP_CLK_DIV,
            0x80,
            SET_PRECHARGE,
            0x22 if self.external_vcc else 0xF1,
            SET_VCOM_DESEL,
            0x30,  # 0.83*Vcc
            # display
            SET_CONTRAST,
            0xFF,  # maximum
            SET_ENTIRE_ON,  # output follows RAM contents
            SET_NORM_INV,  # not inverted
            # charge pump
            SET_CHARGE_PUMP,
            0x10 if self.external_vcc else 0x14,
            SET_DISP | 0x01,
        ):  # on
            self.write_cmd(cmd)
        time.sleep_ms(_CHARGE_PUMP_SETTLE_MS)
        self.fill(0)
        self.show()

    def poweroff(self):
        self.write_cmd(SET_DISP | 0x00)

    def poweron(self):
        pass

    def contrast(self, contrast):
        self.write_cmd(SET_CONTRAST)
        self.write_cmd(contrast)

    def invert(self, invert):
        self.write_cmd(SET_NORM_INV | (invert & 1))

    def rotate(self, rotate):
        self.write_cmd(SET_COM_OUT_DIR | ((rotate & 1) << 3))
        self.write_cmd(SET_SEG_REMAP | (rotate & 1))

    def show(self):
        x0 = 0
        x1 = self.width - 1
        if self.width != 128:
            # narrow displays use centred columns
            col_offset = (128 - self.width) // 2
            x0 += col_offset
            x1 += col_offset
        self.write_cmd(SET_COL_ADDR)
        self.write_cmd(x0)
        self.write_cmd(x1)
        self.write_cmd(SET_PAGE_ADDR)
        self.write_cmd(0)
        self.write_cmd(self.pages - 1)
        self.write_framebuf()

    def fill(self, col):
        self.framebuf.fill(col)

    def pixel(self, x, y, col):
        self.framebuf.pixel(x, y, col)

    def scroll(self, dx, dy):
        self.framebuf.scroll(dx, dy)

    def text(self, string, x, y, col=1):
        self.framebuf.text(string, x, y, col)

    def blit(self, fbuf, x, y, key=-1):
        self.framebuf.blit(fbuf, x, y, key)

    def line(self, x1, y1, x2, y2, col):
        self.framebuf.line(x1, y1, x2, y2, col)

    def vline(self, x, y, h, col):
        self.framebuf.vline(x, y, h, col)

    def hline(self, x, y, w, col):
        self.framebuf.hline(x, y, w, col)

    def rect(self, x, y, w, h, col):
        self.framebuf.rect(x, y, w, h, col)

    def fill_rect(self, x, y, w, h, col):
        self.framebuf.fill_rect(x, y, w, h, col)


class SSD1306_I2C(SSD1306):
    def __init__(self, width, height, i2c, addr=0x3C, external_vcc=False):
        self.i2c = i2c
        self.addr = addr
        self.temp = bytearray(2)
        # Buffer de pixeles "limpio" (sin byte de control antepuesto): se
        # arma el bloque con control + datos en write_framebuf(), de a
        # _CHUNK bytes por vez.
        self.buffer = bytearray((height // 8) * width)
        self._chunk = bytearray(_CHUNK + 1)
        self._chunk[0] = 0x40  # Co=0, D/C#=1
        self.framebuf = framebuf.FrameBuffer(self.buffer, width, height, framebuf.MVLSB)
        super().__init__(width, height, external_vcc)

    def write_cmd(self, cmd):
        self.temp[0] = 0x80  # Co=1, D/C#=0
        self.temp[1] = cmd
        self.i2c.writeto(self.addr, self.temp)

    def write_framebuf(self):
        buf = self.buffer
        chunk = self._chunk
        n = len(buf)
        for i in range(0, n, _CHUNK):
            end = i + _CHUNK if i + _CHUNK < n else n
            size = end - i
            chunk[1:1 + size] = buf[i:end]
            self.i2c.writeto(self.addr, memoryview(chunk)[:1 + size])

    def poweron(self):
        pass
