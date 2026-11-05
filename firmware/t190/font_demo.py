# font_demo.py -- Demo de fuentes bitmap (font_to_py de Peter Hinch) en T190
#
# Fuente: seven-segment_24.py  (height=24, hmap=True, reverse=False)
# API de cada modulo de fuente:
#   font.height()     -> int    altura en px
#   font.baseline()   -> int    baseline desde la parte superior
#   font.max_width()  -> int    ancho maximo de un caracter
#   font.hmap()       -> True   mapeado horizontal (row-major)
#   font.reverse()    -> False  bit 7 = pixel izquierdo (MONO_HLSB)
#   font.monospaced()-> bool
#   font.min_ch()     -> int    codigo ASCII minimo
#   font.max_ch()     -> int    codigo ASCII maximo
#   font.get_ch(ch)   -> (memoryview, height, width)
#                        data: (width-1)//8+1 bytes por fila, height filas
#                        bit 7 del byte = pixel mas a la izquierda

import time
from machine import SoftSPI, Pin
import st7789py as st7789
from fonts import seven_segment_24 as seg24   # fonts/seven_segment_24.py

# --- Pines T190 ---------------------------------------------------------
W, H = 170, 320
# Valores verificados contra el driver oficial Heltec (HT_st7789spi.cpp)
ROTATIONS = ((0xC0, 170, 320, 35,  0, False),
             (0xA0, 320, 170,  0, 35, False),
             (0x00, 170, 320, 35,  0, False),
             (0x60, 320, 170,  0, 35, False))

def make_tft():
    Pin(7, Pin.OUT).value(0)
    time.sleep_ms(120)
    spi = SoftSPI(baudrate=20_000_000, polarity=0, phase=0,
                  sck=Pin(38), mosi=Pin(48), miso=Pin(46))
    return st7789.ST7789(spi, W, H,
        cs=Pin(39, Pin.OUT), dc=Pin(47, Pin.OUT),
        reset=Pin(40, Pin.OUT), backlight=Pin(17, Pin.OUT),
        custom_rotations=ROTATIONS, rotation=0,
        color_order=st7789.RGB)


# --- Renderizador generico para fuentes font_to_py ----------------------

def render_char(font, ch, fg, bg):
    """Convierte un caracter de una fuente font_to_py a buffer RGB565."""
    data, h, w = font.get_ch(ch)
    bpr = (w - 1) // 8 + 1   # bytes por fila
    fh, fl = fg >> 8, fg & 0xFF
    bh, bl = bg >> 8, bg & 0xFF
    buf = bytearray(w * h * 2)
    for row in range(h):
        for col in range(w):
            byte = data[row * bpr + col // 8]
            bit  = (byte >> (7 - (col % 8))) & 1
            i = (row * w + col) * 2
            if bit:
                buf[i], buf[i+1] = fh, fl
            else:
                buf[i], buf[i+1] = bh, bl
    return buf, w, h

def txt_font(tft, font, text, x, y, fg, bg=st7789.BLACK, clip_w=None):
    """
    Dibuja 'text' con 'font' en (x, y).
    Retorna el x final (util para continuar escribiendo a la derecha).
    clip_w: si se especifica, no dibuja mas alla de x+clip_w px.
    """
    max_x = x + clip_w if clip_w else W
    cx = x
    for ch in text:
        buf, cw, ch_h = render_char(font, ch, fg, bg)
        if cx + cw > max_x:
            break
        tft.blit_buffer(buf, cx, y, cw, ch_h)
        cx += cw
    return cx

def str_width(font, text):
    """Calcula el ancho en px de un string con una fuente dada."""
    total = 0
    for ch in text:
        _, _, w = font.get_ch(ch)
        total += w
    return total


# --- Demo ---------------------------------------------------------------

def demo(tft):
    BLACK  = st7789.BLACK
    WHITE  = st7789.WHITE
    CYAN   = st7789.CYAN
    YELLOW = st7789.YELLOW
    GREEN  = st7789.GREEN
    RED    = st7789.RED
    TEAL   = st7789.color565(0, 110, 110)

    # -- Pantalla 1: informacion de la fuente ---------------------------
    tft.fill(BLACK)
    tft.fill_rect(0, 0, W, 20, TEAL)

    # Titulo con fuente 8x8 built-in
    import framebuf
    def t8(x, y, s, fg, bg=BLACK):
        n = len(s)
        if n == 0: return
        w, h = n*8, 8
        stride = (w+7)//8
        mono = bytearray(stride*h)
        framebuf.FrameBuffer(mono, w, h, framebuf.MONO_HLSB).text(s, 0, 0, 1)
        fh,fl = fg>>8, fg&0xFF
        bh,bl = bg>>8, bg&0xFF
        buf = bytearray(w*h*2)
        for r in range(h):
            rb = r*stride
            for c in range(w):
                i=(r*w+c)*2
                if (mono[rb+c//8] >> (7-(c%8))) & 1:
                    buf[i],buf[i+1]=fh,fl
                else:
                    buf[i],buf[i+1]=bh,bl
        tft.blit_buffer(buf, x, y, w, h)

    t8(2, 6, "Font: seven-segment 24", WHITE, TEAL)

    t8(0, 28, "height   : " + str(seg24.height()),    CYAN)
    t8(0, 40, "baseline : " + str(seg24.baseline()),  CYAN)
    t8(0, 52, "max_width: " + str(seg24.max_width()), CYAN)
    t8(0, 64, "hmap     : " + str(seg24.hmap()),      CYAN)
    t8(0, 76, "reverse  : " + str(seg24.reverse()),   CYAN)
    t8(0, 88, "chars    : " + str(seg24.min_ch()) + "-" + str(seg24.max_ch()), CYAN)

    # Muestra de digitos 0-9
    t8(0, 108, "Digitos 0-9:", YELLOW)
    x = 0
    for ch in "0123456789":
        buf, cw, ch_h = render_char(seg24, ch, GREEN, BLACK)
        if x + cw <= W:
            tft.blit_buffer(buf, x, 120, cw, ch_h)
            x += cw + 2

    # Muestra hora simulada
    t8(0, 156, "Ejemplo HH:MM", YELLOW)
    tiempo = "12:34"
    tw = str_width(seg24, tiempo)
    cx = max(0, (W - tw) // 2)   # centrar
    txt_font(tft, seg24, tiempo, cx, 168, YELLOW, BLACK)

    time.sleep_ms(3000)

    # -- Pantalla 2: contador animado ----------------------------------
    tft.fill(BLACK)
    t8(2, 6, "Contador animado", WHITE)
    tft.hline(0, 18, W, st7789.color565(60,60,60))

    for i in range(100):
        s = "{:02d}".format(i)
        tw = str_width(seg24, s)
        cx = (W - tw) // 2
        # Borrar zona
        tft.fill_rect(0, 30, W, seg24.height() + 4, BLACK)
        txt_font(tft, seg24, s, cx, 32, CYAN, BLACK)
        time.sleep_ms(80)

    # -- Pantalla 3: escala de colores ----------------------------------
    tft.fill(BLACK)
    t8(2, 6, "Colores de fuente", WHITE)

    pairs = [
        ("88:88", GREEN,   BLACK),
        ("88:88", YELLOW,  BLACK),
        ("88:88", RED,     BLACK),
        ("88:88", CYAN,    BLACK),
        ("88:88", WHITE,   BLACK),
        ("88:88", st7789.color565(255,128,0), BLACK),  # naranja
        ("88:88", st7789.color565(200,0,200), BLACK),  # violeta
    ]
    y = 20
    for s, fg, bg in pairs:
        tft.fill_rect(0, y, W, seg24.height() + 2, BLACK)
        txt_font(tft, seg24, s, 4, y, fg, bg)
        y += seg24.height() + 4

    time.sleep_ms(2000)


def main():
    tft = make_tft()
    demo(tft)
    tft.fill(st7789.BLACK)

main()
