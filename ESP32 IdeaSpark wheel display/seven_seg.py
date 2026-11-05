# seven_seg.py
# Renderizador de texto para las fuentes font_to_py (fonts/seven_segment_*)
# sobre drivers/tft170.TFT170 -- variante "sin framebuffer" de
# New T190/seven_seg.py: esta placa es un ESP32 clasico sin PSRAM, el driver
# nunca compone sobre un framebuffer propio (ver docstring de drivers/tft170.py).
# Por eso cada glifo se arma en un bytearray RGB565 chico y se manda directo
# por SPI con tft.blit_raw(), en vez de tft.blit(framebuf.FrameBuffer).

import framebuf


def char_width(font, ch):
    _, _, w = font.get_ch(ch)
    return w


def text_width(font, text):
    """Ancho total en px de un string con esta fuente."""
    total = 0
    for ch in text:
        total += char_width(font, ch)
    return total


def _render_char(font, ch, fg, bg):
    """Arma un bytearray RGB565 crudo (w*h*2 bytes) para un caracter."""
    data, h, w = font.get_ch(ch)
    bpr = (w - 1) // 8 + 1
    fh, fl = fg >> 8, fg & 0xFF
    bh, bl = bg >> 8, bg & 0xFF
    buf = bytearray(w * h * 2)
    for row in range(h):
        row_off = row * bpr
        for col in range(w):
            byte = data[row_off + col // 8]
            bit = (byte >> (7 - (col % 8))) & 1
            i = (row * w + col) * 2
            if bit:
                buf[i], buf[i + 1] = fh, fl
            else:
                buf[i], buf[i + 1] = bh, bl
    return buf, w, h


def draw_text(tft, font, text, x, y, fg, bg=0x0000):
    """Dibuja 'text' con 'font' en (x,y) sobre tft (drivers.tft170.TFT170).
    Devuelve la coordenada x final (util para encadenar texto)."""
    cx = x
    for ch in text:
        buf, w, h = _render_char(font, ch, fg, bg)
        tft.blit_raw(buf, cx, y, w, h)
        cx += w
    return cx


def draw_text_centered(tft, font, text, y, fg, bg=0x0000, width=None):
    """Centra 'text' horizontalmente en el ancho dado (por defecto tft.width)."""
    width = width if width is not None else tft.width
    tw = text_width(font, text)
    x = max(0, (width - tw) // 2)
    return draw_text(tft, font, text, x, y, fg, bg)
