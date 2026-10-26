# oled_test.py -- prueba de banco del OLED I2C externo de 0.96" (SSD1306)
#
# Cableado (header J2, ver PROYECTO_T190.md):
#   GPIO15 (ESP32) -> SCL del modulo OLED
#   GPIO16 (ESP32) -> SDA del modulo OLED
#   Ve_3V3 (QuickLink) -> VCC   GND -> GND
#
# El OLED se alimenta del Ve_3V3 del QuickLink (HW.VEXT_CTRL_PIN=5), el
# mismo rail conmutado que hoy usa el GPS -- no de un 3V3 constante. Por
# eso hay que habilitarlo (HW.vext_enable()) antes de usar el bus I2C.
#
# Un OLED de 0.96" es casi siempre un panel SSD1306 de 128x64 por I2C,
# direccion 0x3C (algunos modulos usan 0x3D). El driver esta en
# drivers/ssd1306.py (SSD1306_I2C).
#
# GPIO15/16 tambien son XTAL_32K_P/N: solo sirven como I2C si no hay un
# cristal de 32.768 kHz montado en esos pines (no es el caso en el T190).
#
# Uso: mpremote run oled_test.py   (o copiar al ESP32 y ejecutar desde el REPL)
# Ctrl-C para detener.

import time

import HW
from drivers.ssd1306 import SSD1306_I2C

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

oled.fill(0)
oled.text("T190 OLED OK", 0, 0)
oled.text("addr 0x{:02X}".format(addr), 0, 16)
oled.show()
print("Si el texto se ve en el OLED, el driver y el cableado estan bien.")

n = 0
try:
    while True:
        oled.fill(0)
        oled.text("T190 OLED OK", 0, 0)
        oled.text("tick {}".format(n), 0, 16)
        oled.show()
        n += 1
        time.sleep(1)
except KeyboardInterrupt:
    pass
