
# HW.py
# Pin map y helpers para el segundo display "on wheel" -- ESP32 generico,
# marca Ideaspark, variante 1.9" ST7789 170x320 (mismo controlador y
# resolucion que el display integrado del T190).
#
# A diferencia del T190 (Heltec, pines de fabrica documentados), Ideaspark
# no publica datasheet propio: este pinout es ingenieria inversa de la
# comunidad, verificada contra dos fuentes independientes (ver
# PROYECTO_IDEASPARK.md #Fuentes). Ideaspark tiene varias revisiones de
# esta placa -- VERIFICAR contra las fotos de tu propio listado de
# AliExpress antes de cablear nada.

import machine

# ── Display TFT integrado (SPI, 4 hilos) ────────────────────────────────────
# Controlador: ST7789 real, 170(W) x 320(H).
TFT_MOSI = 23
TFT_SCK  = 18
TFT_CS   = 15
TFT_DC   = 2
TFT_RST  = 4   # En algunas revisiones, un microswitch fisico tira este
               # mismo pin a GND como "boton de reset" del panel (ver hilo
               # de Tasmota en PROYECTO_IDEASPARK.md) -- no es un GPIO de
               # usuario leible por software, es un reset de hardware.
TFT_BL   = 32

TFT_WIDTH    = 170
TFT_HEIGHT   = 320
TFT_SPI_ID   = 1
# 20MHz, no 40MHz como en el T190: esta placa es un ESP32 "clasico" (no S3),
# y estos pines no son el matriz nativo por default de VSPI/HSPI -> el SPI
# por GPIO matrix queda limitado a 80MHz/3 = 26.67MHz. Con 40MHz tira
# "E spi_hal: The clock_speed_hz should less than 26666666" y la inicializacion
# del SPI falla.
TFT_BAUDRATE = 20_000_000

# Esta placa no tiene un pin de "power enable" dedicado para el panel (a
# diferencia del T190, que corta alimentacion del display via un P-MOSFET
# en TFT_PWR) -- el display queda energizado mientras la placa tenga
# alimentacion; solo el backlight (TFT_BL) es conmutable por software.


# ── Boton de pagina (reusa el boton BOOT de fabrica) ────────────────────────
# GPIO0 es el pin de bootstrap de modo-descarga en casi todo devkit ESP32
# clasico, expuesto en la placa como boton fisico "BOOT" con su propio
# pull-up. Solo importa su estado durante el reset; en runtime normal es un
# GPIO de entrada activo-bajo como cualquier otro (mismo patron que
# HW.PAGE_BTN_PIN=21/S3 en el T190, que tambien reusa un boton de fabrica).
PAGE_BTN_PIN = 0


# ── Utilidades ───────────────────────────────────────────────────────────────

def make_output(pin_num, *, value=1):
    pin = machine.Pin(pin_num, machine.Pin.OUT)
    pin.value(value)
    return pin


def backlight_on():
    make_output(TFT_BL, value=1)


def backlight_off():
    make_output(TFT_BL, value=0)
