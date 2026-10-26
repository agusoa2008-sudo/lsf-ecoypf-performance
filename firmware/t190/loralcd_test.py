# loralcd_test.py -- Heltec Vision Master T190
# Cada boton BTN0 (GPIO 0): genera UUID v4, envia por LoRa, muestra en LCD ST7789
#
# Archivos necesarios en raiz / del ESP32:
#   st7789py.py  _sx126x.py  sx126x.py  sx1262.py
#
# Pines LCD : VTFT=7  SCK=38 MOSI=48 CS=39 DC=47 RST=40 BL=17
# Pines LoRa: SCK=9  MOSI=10 MISO=11 CS=8  DIO1=14 RST=12 BUSY=13
# Boton     : GPIO 0 (activo LOW, pull-up interno)
# Frecuencia: 915 MHz (America del Sur) -- cambiar a 868.0 para Europa
#
# NOTA: color_order=RGB y MADCTL/offsets verificados contra el driver
#       oficial Heltec (HT_st7789spi.cpp) -- ver drivers/tft170.py para
#       el detalle. Si en tu unidad especifica los colores salen
#       invertidos, probar color_order=st7789.BGR en init_lcd().

import os
import time
import framebuf
from machine import SPI, SoftSPI, Pin
import st7789py as st7789
from sx1262 import SX1262

# --- Pines LCD ----------------------------------------------------------
LCD_VTFT = 7    # V-TFT power: LOW = encender panel (CRITICO en T190)
LCD_SCK  = 38
LCD_MOSI = 48
LCD_CS   = 39
LCD_DC   = 47
LCD_RST  = 40
LCD_BL   = 17   # Backlight (el driver lo pone HIGH al final de __init__)

# --- Pines LoRa ---------------------------------------------------------
LORA_BUS  = 2
LORA_SCK  = 9;  LORA_MOSI = 10;  LORA_MISO = 11
LORA_CS   = 8;  LORA_IRQ  = 14;  LORA_RST  = 12;  LORA_BUSY = 13

BTN_PIN     = 0       # Boton PRG/BOOT, activo LOW
LORA_FREQ   = 915.0   # MHz -- cambiar a 868.0 para Europa
DEBOUNCE_MS = 300     # ms minimos entre pulsaciones

# --- Display ST7789 170x320 ---------------------------------------------
W = 170
H = 320
# custom_rotations para 170x320 (no esta en los displays predefinidos)
# formato: (madctl, width, height, xstart, ystart, needs_swap)
# Valores verificados contra el driver oficial Heltec (HT_st7789spi.cpp,
# setRotation()): https://github.com/HelTecAutomation/Heltec_ESP32
ROTATIONS = (
    (0xC0, 170, 320, 35,  0, False),  # 0 -- Portrait  (real Heltec: MY|MX)
    (0xA0, 320, 170,  0, 35, False),  # 1 -- Landscape (real Heltec: MY|MV)
    (0x00, 170, 320, 35,  0, False),  # 2 -- Portrait invertido (real Heltec: RGB)
    (0x60, 320, 170,  0, 35, False),  # 3 -- Landscape invertido (real Heltec: MX|MV)
)

# --- Paleta -------------------------------------------------------------
BLACK  = st7789.BLACK
WHITE  = st7789.WHITE
RED    = st7789.RED
GREEN  = st7789.GREEN
CYAN   = st7789.CYAN
YELLOW = st7789.YELLOW
TEAL   = st7789.color565(0, 110, 110)
GRAY   = st7789.color565(70, 70, 70)

C_SEP  = GRAY
C_LBL  = CYAN
C_UUID = YELLOW
C_TS   = WHITE
C_OK   = GREEN
C_ERR  = RED
C_IDLE = GRAY


# ========================================================================
# Texto 8x8 con framebuf built-in (sin fuente externa)
# ========================================================================

def txt(tft, x, y, text, fg, bg=None):
    if bg is None:
        bg = BLACK
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
                buf[i], buf[i + 1] = fh, fl
            else:
                buf[i], buf[i + 1] = bh, bl
    tft.blit_buffer(buf, x, y, w, h)


def clr(tft, y, h=10):
    tft.fill_rect(0, y, W, h, BLACK)


# ========================================================================
# UUID v4
# ========================================================================

def uuid4():
    b = bytearray(os.urandom(16))
    b[6] = (b[6] & 0x0F) | 0x40  # version 4
    b[8] = (b[8] & 0x3F) | 0x80  # variant RFC 4122
    return (
        "{:02x}{:02x}{:02x}{:02x}-"
        "{:02x}{:02x}-{:02x}{:02x}-"
        "{:02x}{:02x}-"
        "{:02x}{:02x}{:02x}{:02x}{:02x}{:02x}"
    ).format(*b)


# ========================================================================
# Layout del display portrait 170x320 (fuente 8px)
#
#   y=  0-19  Cabecera teal "=== T190 LoRa TX ==="
#   y= 22     Separador
#   y= 28     "UUID:"
#   y= 40     uuid[ 0:21]
#   y= 52     uuid[21:36]
#   y= 64     Separador
#   y= 70     "TIMESTAMP:"
#   y= 82     <segundos>
#   y= 94     Separador
#   y=100     "TX COUNT:"
#   y=112     <contador>
#   y=124     Separador
#   y=132     Estado TX (OK / Error)
#   y=144     Separador
#   y=152     Pista de accion
# ========================================================================

Y_TITLE =   4
Y_ULBL  =  28
Y_U1    =  40
Y_U2    =  52
Y_TSLBL =  70
Y_TSVAL =  82
Y_CTLBL = 100
Y_CTVAL = 112
Y_STAT  = 132
Y_HINT  = 152


def draw_base(tft):
    tft.fill(BLACK)
    tft.fill_rect(0, 0, W, 20, TEAL)
    txt(tft, 2, Y_TITLE, "=== T190 LoRa TX ===", WHITE, TEAL)
    tft.hline(0, 22, W, C_SEP)
    txt(tft, 0, Y_ULBL,  "UUID:",      C_LBL)
    tft.hline(0, 64, W, C_SEP)
    txt(tft, 0, Y_TSLBL, "TIMESTAMP:", C_LBL)
    tft.hline(0, 94, W, C_SEP)
    txt(tft, 0, Y_CTLBL, "TX COUNT:",  C_LBL)
    tft.hline(0, 124, W, C_SEP)
    tft.hline(0, 144, W, C_SEP)


def draw_uuid(tft, uid):
    clr(tft, Y_U1)
    clr(tft, Y_U2)
    txt(tft, 0, Y_U1, uid[:21], C_UUID)
    txt(tft, 0, Y_U2, uid[21:], C_UUID)


def draw_ts(tft, ts):
    clr(tft, Y_TSVAL)
    txt(tft, 0, Y_TSVAL, str(ts) + " s", C_TS)


def draw_cnt(tft, n):
    clr(tft, Y_CTVAL)
    txt(tft, 0, Y_CTVAL, str(n), C_LBL)


def draw_stat(tft, msg, ok=True):
    clr(tft, Y_STAT, h=12)
    txt(tft, 0, Y_STAT, msg, C_OK if ok else C_ERR)


def draw_hint(tft, msg):
    clr(tft, Y_HINT, h=10)
    txt(tft, 0, Y_HINT, msg, C_IDLE)


# ========================================================================
# Inicializacion de hardware
# ========================================================================

def init_lcd():
    # VTFT_CTRL LOW enciende la alimentacion VCC del panel -- critico en T190
    Pin(LCD_VTFT, Pin.OUT).value(0)
    time.sleep_ms(120)
    # SoftSPI: SPI(1) esta reservado en el firmware T190; SPI(2) lo usa LoRa.
    # El LCD es write-only pero SoftSPI requiere un pin MISO valido -- usamos
    # GPIO 46 como dummy (no conectado al LCD, nunca se lee).
    spi = SoftSPI(baudrate=20_000_000, polarity=0, phase=0,
                  sck=Pin(LCD_SCK), mosi=Pin(LCD_MOSI), miso=Pin(46))
    return st7789.ST7789(
        spi, W, H,
        cs=Pin(LCD_CS,  Pin.OUT),
        dc=Pin(LCD_DC,  Pin.OUT),
        reset=Pin(LCD_RST, Pin.OUT),
        backlight=Pin(LCD_BL, Pin.OUT),
        custom_rotations=ROTATIONS,
        rotation=0,
        color_order=st7789.RGB,
    )


def init_lora():
    lora = SX1262(
        spi_bus=LORA_BUS,
        clk=LORA_SCK, mosi=LORA_MOSI, miso=LORA_MISO,
        cs=LORA_CS,   irq=LORA_IRQ,
        rst=LORA_RST, gpio=LORA_BUSY,
    )
    lora.begin(
        freq=LORA_FREQ, bw=125.0, sf=7, cr=5,
        syncWord=0x12, power=14, tcxoVoltage=1.6,
    )
    return lora


def splash(tft, y, msg, color):
    clr(tft, y, h=14)
    txt(tft, 0, y, msg, color)


# ========================================================================
# Test de colores
# ========================================================================

COLORS_TEST = [
    ("WHITE",   st7789.WHITE),
    ("RED",     st7789.RED),
    ("GREEN",   st7789.GREEN),
    ("BLUE",    st7789.BLUE),
    ("CYAN",    st7789.CYAN),
    ("MAGENTA", st7789.MAGENTA),
    ("YELLOW",  st7789.YELLOW),
]

def color_test(tft):
    """Muestra cada color 1.5 s: fondo del color, nombre centrado a media altura."""
    for name, color in COLORS_TEST:
        tft.fill(color)
        # Calcular x para centrar el nombre (fuente 8px ancho por caracter)
        cx = max(0, (W - len(name) * 8) // 2)
        cy = H // 2 - 4   # centrado vertical (fuente 8px alto)
        # Fondo contraste: blanco sobre colores oscuros, negro sobre claros
        luminance = ((color >> 11) & 0x1F) * 8 + ((color >> 5) & 0x3F) * 4 + (color & 0x1F) * 8
        fg = BLACK if luminance > 3000 else WHITE
        txt(tft, cx, cy, name, fg, color)
        time.sleep_ms(1500)


# ========================================================================
# Main
# ========================================================================

def main():
    # -- Init LCD ---------------------------------------------------------
    tft = init_lcd()
    tft.fill_rect(0, 0, W, 20, TEAL)
    txt(tft, 2, Y_TITLE, "  T190 LoRa Test  ", WHITE, TEAL)
    splash(tft, 30, "LCD OK", C_OK)

    # -- Test de colores --------------------------------------------------
    color_test(tft)

    # -- Init LoRa --------------------------------------------------------
    splash(tft, 48, "Init LoRa...", C_LBL)
    try:
        lora = init_lora()
        splash(tft, 48, "LoRa OK  " + str(int(LORA_FREQ)) + "MHz", C_OK)
    except Exception as e:
        splash(tft, 48, "LoRa FAIL!", C_ERR)
        splash(tft, 66, str(e)[:21], C_ERR)
        print("LoRa error:", e)
        return

    time.sleep_ms(800)

    # -- UI base ----------------------------------------------------------
    draw_base(tft)
    draw_cnt(tft, 0)
    draw_stat(tft, "---", ok=True)
    draw_hint(tft, "BTN0 = SEND")

    # -- Loop principal ---------------------------------------------------
    btn       = Pin(BTN_PIN, Pin.IN, Pin.PULL_UP)
    count     = 0
    last_tick = 0

    while True:
        if btn.value() == 0:
            now = time.ticks_ms()
            if time.ticks_diff(now, last_tick) >= DEBOUNCE_MS:
                last_tick = now
                count += 1

                uid     = uuid4()
                ts      = time.time()
                payload = '{{"uuid":"{}","ts":{},"n":{}}}'.format(uid, ts, count)

                draw_uuid(tft, uid)
                draw_ts(tft, ts)
                draw_cnt(tft, count)
                draw_stat(tft, "Sending...", ok=True)
                draw_hint(tft, "TX en curso...")

                print("TX #{}: {}".format(count, payload))
                length, state = lora.send(payload.encode())

                if state == 0:
                    draw_stat(tft, "OK len={}".format(length), ok=True)
                    draw_hint(tft, "BTN0 = SEND")
                    print("TX OK len={}".format(length))
                else:
                    from _sx126x import ERROR
                    ename = ERROR.get(state, str(state))
                    draw_stat(tft, "ERR " + ename[:15], ok=False)
                    draw_hint(tft, "BTN0 = REINTENTAR")
                    print("TX ERR {} {}".format(state, ename))

        time.sleep_ms(20)


main()