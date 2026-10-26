# oled_seven_seg_test.py -- prueba de banco: fuentes siete-segmentos
# (fonts/seven_segment_24 y _40, las mismas que ya usa el TFT) dibujadas
# sobre el OLED I2C externo de 0.96" (GPIO15 SCL / GPIO16 SDA) via
# seven_seg.draw_text_mono_centered().
#
# El OLED se alimenta del Ve_3V3 del QuickLink (HW.VEXT_CTRL_PIN=5), el
# mismo rail conmutado que hoy usa el GPS -- no de un 3V3 constante. Por
# eso hay que habilitarlo (HW.vext_enable()) antes de usar el bus I2C.
#
# Layout (128x64): linea superior con fuente 40px (valor principal, ej.
# velocidad), linea inferior con fuente 24px (unidad/etiqueta fija).
#
# Uso: mpremote run oled_seven_seg_test.py   (o copiar al ESP32 y ejecutar
# desde el REPL). Ctrl-C para detener.

import time

import HW
import seven_seg
from drivers.ssd1306 import SSD1306_I2C
from fonts import seven_segment_24 as SEG24
from fonts import seven_segment_40 as SEG40

OLED_WIDTH = 128
OLED_HEIGHT = 64

HW.vext_enable()
time.sleep_ms(50)  # settle del Ve_3V3 antes de hablarle al OLED por I2C

i2c = HW.make_oled_i2c()
print("Scan I2C (SCL={} SDA={}):".format(HW.OLED_I2C_SCL_PIN, HW.OLED_I2C_SDA_PIN))
found = i2c.scan()
print(["0x{:02X}".format(addr) for addr in found])

if not found:
    raise SystemExit(
        "Nadie contesto en el bus I2C. Revisar VCC/GND del modulo, "
        "que SCL/SDA no esten invertidos, y que tenga pull-ups a 3.3V."
    )

addr = 0x3C if 0x3C in found else found[0]
oled = SSD1306_I2C(OLED_WIDTH, OLED_HEIGHT, i2c, addr=addr)

n = 0
try:
    while True:
        oled.fill(0)
        seven_seg.draw_text_mono_centered(oled, SEG40, "{:02d}".format(n % 100), 0)
        seven_seg.draw_text_mono_centered(oled, SEG24, "KM/H", 42)
        oled.show()
        n += 1
        time.sleep(1)
except KeyboardInterrupt:
    pass
