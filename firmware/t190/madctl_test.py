# madctl_test.py -- T190 MADCTL orientation finder
# BTN0 (GPIO 0) = siguiente opcion
# Buscar la opcion donde:
#   - "TOP" aparece arriba
#   - "L" aparece a la IZQUIERDA y "R" a la DERECHA
#   - las letras NO estan espejadas
#
# Respuesta ya verificada contra el driver oficial Heltec (HT_st7789spi.cpp,
# setRotation() caso 0): deberia ser OPT 3/3 "MY=1 MX=1" (0xC0). Dejar este
# script como queda para confirmar en tu unidad fisica.

import time
import framebuf
from machine import SoftSPI, Pin
import st7789py as st7789

# --- Pines LCD ----------------------------------------------------------
LCD_VTFT = 7
LCD_SCK  = 38
LCD_MOSI = 48
LCD_CS   = 39
LCD_DC   = 47
LCD_RST  = 40
LCD_BL   = 17
BTN_PIN  = 0

W = 170
H = 320

# 8 opciones: combinaciones de MY(0x80) MX(0x40) MV(0x20) para portrait
OPTIONS = [
    (0, 0x00, "MY=0 MX=0"),
    (1, 0x40, "MY=0 MX=1"),
    (2, 0x80, "MY=1 MX=0"),
    (3, 0xC0, "MY=1 MX=1"),
]

# --- Texto 8x8 ----------------------------------------------------------
def txt(tft, x, y, text, fg, bg=0x0000):
    max_chars = max(0, (W - x) // 8)
    s = str(text)[:max_chars]
    n = len(s)
    if n == 0:
        return
    w, h   = n * 8, 8
    stride = (w + 7) // 8
    mono = bytearray(stride * h)
    framebuf.FrameBuffer(mono, w, h, framebuf.MONO_HLSB).text(s, 0, 0, 1)
    fh, fl = fg >> 8, fg & 0xFF
    bh, bl = bg >> 8, bg & 0xFF
    buf = bytearray(w * h * 2)
    for r in range(h):
        rb = r * stride
        for c in range(w):
            i = (r * w + c) * 2
            if (mono[rb + c // 8] >> (7 - (c % 8))) & 1:
                buf[i], buf[i+1] = fh, fl
            else:
                buf[i], buf[i+1] = bh, bl
    tft.blit_buffer(buf, x, y, w, h)

# --- Inicializar LCD con un MADCTL dado ----------------------------------
def make_tft(madctl):
    rot = ((madctl, 170, 320, 35, 0, False),)
    Pin(LCD_VTFT, Pin.OUT).value(0)
    spi = SoftSPI(baudrate=20_000_000, polarity=0, phase=0,
                  sck=Pin(LCD_SCK), mosi=Pin(LCD_MOSI), miso=Pin(46))
    return st7789.ST7789(
        spi, W, H,
        cs=Pin(LCD_CS,  Pin.OUT),
        dc=Pin(LCD_DC,  Pin.OUT),
        reset=Pin(LCD_RST, Pin.OUT),
        backlight=Pin(LCD_BL, Pin.OUT),
        custom_rotations=rot,
        rotation=0,
        color_order=st7789.RGB,
    )

# --- Dibujar patron de prueba -------------------------------------------
def draw_test(tft, idx, madctl, desc):
    tft.fill(st7789.BLACK)

    # Cabecera
    tft.fill_rect(0, 0, W, 18, st7789.color565(0, 80, 80))
    txt(tft, 2, 5, "OPT {}/{}  0x{:02X}".format(idx, len(OPTIONS)-1, madctl),
        st7789.WHITE, st7789.color565(0, 80, 80))

    # Descripcion
    txt(tft, 0, 24, desc, st7789.CYAN)

    # Patron asimetrico: esquinas etiquetadas
    txt(tft, 0,       40, "TOP-LEFT",    st7789.YELLOW)
    txt(tft, W-72,    40, "TOP-RIGHT",   st7789.YELLOW)
    txt(tft, 0,       H-16, "BOT-LEFT",  st7789.YELLOW)
    txt(tft, W-80,    H-16, "BOT-RIGHT", st7789.YELLOW)

    # Centro: flecha y texto asimetrico
    cy = H // 2
    txt(tft, 0,    cy - 20, "L <---",    st7789.GREEN)
    txt(tft, W-56, cy - 20, "---> R",    st7789.GREEN)
    txt(tft, 28,   cy -  4, "^^ TOP ^^", st7789.RED)
    txt(tft, 20,   cy + 10, "vv BOT vv", st7789.color565(100,100,255))

    # Texto de prueba no simetrico
    txt(tft, 10, cy + 30, "Abc123!?",   st7789.WHITE)

    # Instruccion
    tft.hline(0, H-28, W, st7789.color565(60,60,60))
    txt(tft, 4, H-22, "BTN0=siguiente",  st7789.color565(150,150,150))

# --- Main ---------------------------------------------------------------
def main():
    idx = 0
    # init con primera opcion
    _, madctl, desc = OPTIONS[idx]
    tft = make_tft(madctl)
    draw_test(tft, idx, madctl, desc)

    btn       = Pin(BTN_PIN, Pin.IN, Pin.PULL_UP)
    last_tick = 0

    while True:
        if btn.value() == 0:
            now = time.ticks_ms()
            if time.ticks_diff(now, last_tick) >= 400:
                last_tick = now
                idx = (idx + 1) % len(OPTIONS)
                _, madctl, desc = OPTIONS[idx]
                # reinit con nuevo madctl
                tft = make_tft(madctl)
                draw_test(tft, idx, madctl, desc)
                print("OPT {} madctl=0x{:02X} {}".format(idx, madctl, desc))
        time.sleep_ms(20)

main()
