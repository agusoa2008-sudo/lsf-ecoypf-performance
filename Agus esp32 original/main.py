"""
Dashboard Hypercar – ESP32 + ST7789 1.9" (320×170 landscape)
Velocidad máx: 50 km/h | Sin framebuf | Sin MemoryError

Layout fiel a la imagen de referencia:
 ┌────────────────────────────────────────────────────┐
 │ ████████████████████░░░░░░░░░   barra trapezoidal  │
 │                                                    │
 │       [ 4 5 ]           │   ┌────────┐             │
 │        KM/H             │   │  BAT   │   85%       │
 │                         │   └────────┘             │
 └────────────────────────────────────────────────────┘
"""

import machine
import st7789
import time
import math

# Hardware
spi = machine.SPI(1, baudrate=30_000_000, polarity=1, phase=1,
                  sck=machine.Pin(18), mosi=machine.Pin(23))
tft = st7789.ST7789(spi, 320, 170,
                    reset=machine.Pin(4, machine.Pin.OUT),
                    dc=machine.Pin(2, machine.Pin.OUT),
                    cs=machine.Pin(15, machine.Pin.OUT),
                    backlight=machine.Pin(32, machine.Pin.OUT))

# Colores
BLACK    = st7789.BLACK
WHITE    = st7789.WHITE
GREEN_EV = 0x4FE0
GREEN_DIM= 0x0280
DKGRAY   = 0x18C3
ACCENT   = 0x3186
AMBER    = 0xFD00

W, H     = 320, 170
VEL_MAX  = 50

# Barra trapezoidal
BAR_Y    = 5
BAR_H    = 16
BAR_X0   = 8
BAR_X1   = 300
BAR_SKEW = 8

# Velocidad
VEL_SZ   = 3
DCHAR_W  = (20 * VEL_SZ) + (2 * VEL_SZ)
DIV_X    = 195
VEL_ZONE_W = DIV_X - 8
VEL_X    = (VEL_ZONE_W - DCHAR_W * 2) // 2 + 4
VEL_Y    = 28
LABEL_X  = (VEL_ZONE_W - 32) // 2 + 4
LABEL_Y  = VEL_Y + (36 * VEL_SZ) + 5

# Divisor
DIV_Y    = BAR_Y + BAR_H + 4
DIV_H    = H - DIV_Y - 6

# Bateria
BAT_ZONE_X = DIV_X + 6
BAT_ZONE_W = W - BAT_ZONE_X - 8
BAT_W    = 44
BAT_H    = 66
BAT_X    = BAT_ZONE_X + (BAT_ZONE_W - BAT_W) // 2
BAT_Y2   = 24
BAT_SEG  = 4
BAT_SH   = 12
BAT_GAP  = 2
PCT_X    = BAT_ZONE_X
PCT_Y    = BAT_Y2 + BAT_H + 6

FRAME    = 3
CHAM     = 12

_prev_vel = -1
_prev_bat = -1
_prev_bpx = -1


def _pad(s, w):
    while len(s) < w:
        s = ' ' + s
    return s


def _bat_color(pct):
    return GREEN_EV if pct >= 30 else AMBER


def _draw_bar_row(y, skew_px, px_filled, c_on, c_off):
    x0    = BAR_X0 + skew_px
    total = BAR_X1 - x0
    if total <= 0:
        return
    fill = min(px_filled, total)
    if fill > 0:
        tft.fill_rect(x0, y, fill, 1, c_on)
    if fill < total:
        tft.fill_rect(x0 + fill, y, total - fill, 1, c_off)


def _full_bar(px_filled):
    for row in range(BAR_H):
        skew = row * BAR_SKEW // BAR_H
        _draw_bar_row(BAR_Y + row, skew, px_filled, GREEN_EV, GREEN_DIM)


def _draw_bat_outline():
    bx, by = BAT_X, BAT_Y2
    bw, bh = BAT_W, BAT_H
    t = 2
    tft.fill_rect(bx,      by,      bw,      t,       WHITE)
    tft.fill_rect(bx,      by+bh-t, bw,      t,       WHITE)
    tft.fill_rect(bx,      by+t,    t,       bh-2*t,  WHITE)
    tft.fill_rect(bx+bw-t, by+t,    t,       bh-2*t,  WHITE)
    tw, th = 12, 5
    tx = bx + (bw - tw) // 2
    tft.fill_rect(tx, by-th, tw, th, WHITE)
    tft.fill_rect(bx+t, by+t, bw-2*t, bh-2*t, BLACK)


def _draw_bat_fill(pct):
    bx = BAT_X + 4
    by = BAT_Y2 + BAT_H - 4
    sw = BAT_W - 8
    col = _bat_color(pct)
    segs_on = int((pct / 100) * BAT_SEG + 0.5)
    segs_on = max(0, min(BAT_SEG, segs_on))
    for i in range(BAT_SEG):
        seg_y = by - (i + 1) * (BAT_SH + BAT_GAP)
        color = col if i < segs_on else BLACK
        tft.fill_rect(bx, seg_y, sw, BAT_SH, color)


def draw_static():
    tft.fill(BLACK)
    tft.fill_rect(CHAM,    0,       W-2*CHAM, FRAME,    DKGRAY)
    tft.fill_rect(CHAM,    H-FRAME, W-2*CHAM, FRAME,    DKGRAY)
    tft.fill_rect(0,       CHAM,    FRAME,    H-2*CHAM, DKGRAY)
    tft.fill_rect(W-FRAME, CHAM,    FRAME,    H-2*CHAM, DKGRAY)
    _full_bar(0)
    tft.fill_rect(DIV_X, DIV_Y, 2, DIV_H, ACCENT)
    tft.text("KM/H", LABEL_X, LABEL_Y, WHITE, scale=2, bg=BLACK)
    _draw_bat_outline()
    _draw_bat_fill(0)
    tft.text("%", PCT_X + 52, PCT_Y + 2, WHITE, scale=2, bg=BLACK)


def update(vel, bat):
    global _prev_vel, _prev_bat, _prev_bpx
    vel = max(0.0, min(float(VEL_MAX), vel))
    bat = max(0,   min(100, int(bat)))

    new_px = int((vel / VEL_MAX) * (BAR_X1 - BAR_X0))
    if new_px != _prev_bpx:
        _full_bar(new_px)
        _prev_bpx = new_px

    vel_int = int(vel)
    if vel_int != _prev_vel:
        tft.fill_rect(VEL_X - 4, VEL_Y, DCHAR_W * 2 + 8, 36 * VEL_SZ + 2, BLACK)
        col = GREEN_EV if vel_int > 0 else WHITE
        tft.number_large(vel_int, VEL_X, VEL_Y, col, sz=VEL_SZ, bg=BLACK, width=2)
        _prev_vel = vel_int

    if bat != _prev_bat:
        _draw_bat_fill(bat)
        s = _pad(str(bat), 3)
        tft.fill_rect(PCT_X, PCT_Y, 50, 18, BLACK)
        tft.text(s, PCT_X, PCT_Y + 2, WHITE, scale=2, bg=BLACK)
        _prev_bat = bat


# ── Simulación ────────────────────────────────────────────────────────────────
draw_static()

vel_sim      = 0.0
vel_obj      = 0.0
bat_sim      = 100.0
VEL_SMOOTH   = 0.025   # suavidad: más bajo = más lento y progresivo
VEL_CHANGE_MS = 5000   # ms entre cambios de velocidad objetivo
last_change  = time.ticks_ms()

# Secuencia de velocidades objetivo (ciclo)
vel_seq  = [0, 15, 30, 45, 50, 40, 25, 10, 0]
vel_idx  = 0

while True:
    now = time.ticks_ms()

    # Avanzar al siguiente objetivo cuando se cumple el tiempo
    if time.ticks_diff(now, last_change) > VEL_CHANGE_MS:
        vel_idx = (vel_idx + 1) % len(vel_seq)
        vel_obj  = float(vel_seq[vel_idx])
        last_change = now

    # Suavizado exponencial — muy progresivo
    vel_sim += (vel_obj - vel_sim) * VEL_SMOOTH

    # Batería baja muy lentamente
    bat_sim -= 0.004
    if bat_sim < 0.0:
        bat_sim = 100.0

    update(vel_sim, int(bat_sim + 0.5))
    time.sleep_ms(40)
