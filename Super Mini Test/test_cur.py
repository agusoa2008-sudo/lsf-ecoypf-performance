# test_cur.py -- prueba de banco del sensor de corriente ADS1220 (SPI)
# en un ESP32-S3 Super Mini adicional.
#
# Cableado:
#   GPIO9  -> ADS CLK  (SCK)
#   GPIO10 -> ADS CS
#   GPIO11 -> ADS MISO
#   GPIO12 -> ADS MOSI
#   ADS GND -> GND del ESP32 (pin GND real, no un GPIO)
#   ADS VCC -> 3V3 (o 5V si el breakout lo requiere -- revisar datasheet)
#
# GPIO13 queda libre, no se usa en esta prueba.
#
# Requiere drivers/ads1220.py subido junto a este archivo (ya incluido en
# esta carpeta). Config fija del driver: AIN0-AIN1 diferencial, PGA x4,
# VREF interna 2.048V, 20 SPS continuo, SPI modo 1 (CPOL=0, CPHA=1).
#
# Uso: mpremote run test_cur.py   (o copiar la carpeta al device y
# ejecutar desde el REPL con `import test_cur`)
# Ctrl-C para detener el loop de lectura continua.

import time
from machine import Pin, SPI

from drivers.ads1220 import ADS1220

SPI_ID = 1
SCK_PIN = 9
CS_PIN = 10
MISO_PIN = 11
MOSI_PIN = 12
BAUDRATE = 800_000

READ_INTERVAL_MS = 500


def _make_spi():
    return SPI(
        SPI_ID, baudrate=BAUDRATE, polarity=0, phase=1,
        sck=Pin(SCK_PIN), mosi=Pin(MOSI_PIN), miso=Pin(MISO_PIN),
    )


def _run_test():
    spi = _make_spi()
    cs = Pin(CS_PIN, Pin.OUT, value=1)
    adc = ADS1220(spi, cs)

    print("[test_cur] SPI{} SCK={} MOSI={} MISO={} CS={}".format(
        SPI_ID, SCK_PIN, MOSI_PIN, MISO_PIN, CS_PIN))

    if not adc.init():
        raise RuntimeError(
            "El ADS1220 no confirmo la config al releerla -- revisar "
            "cableado (CLK/CS/MISO/MOSI) y que GND este en un pin GND real, "
            "no en un GPIO")
    print("[test_cur] ADS1220 inicializado OK")

    print("[test_cur] calibrando offset con corriente ~0 (no mover nada)...")
    offset = adc.calibrate_zero()
    print("[test_cur] offset crudo = {}".format(offset))

    print("[test_cur] lectura continua cada {} ms -- Ctrl-C para detener".format(
        READ_INTERVAL_MS))
    try:
        while True:
            try:
                amps = adc.read_current()
                print("[test_cur] I = {:.3f} A".format(amps))
            except Exception as exc:
                print("[test_cur] error de lectura:", exc)
            time.sleep_ms(READ_INTERVAL_MS)
    except KeyboardInterrupt:
        print("[test_cur] detenido")


try:
    _run_test()
except Exception as exc:
    print("[test_cur] FALLO:", exc)
    raise
