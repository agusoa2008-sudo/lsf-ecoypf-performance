# HW.py
# Pin map y helpers para ESP32-S3 Super Mini (MicroPython).
# https://www.espboards.dev/esp32/esp32-s3-super-mini/
#
# Rol de esta placa: lee el sensor de corriente de bateria (ADS1220, SPI),
# las tensiones de bateria (ADS1115, I2C) y los pulsos de velocidad del
# motor; hace todas las cuentas (Wh, potencia, eficiencia) y manda la
# telemetria ya calculada por ESP-NOW al T190, que queda como display
# remoto (no hace calculos).
#
# Esto solo tiene PINES/BUSES (fijo mientras no se recablee). Los
# parametros de calibracion/conversion (ratio de los divisores de bateria,
# sensibilidad del sensor de corriente, metros por pulso) viven en
# config.json / config.py, para poder ajustarlos sin tocar codigo.

import machine

# ── I2C — ADS1115 (tomas acumulativas para B1..B4 y VBATS) ──────────────────
# Cableado real (dado, no el default de la placa):
#   GPIO12 -> SCL
#   GPIO13 -> SDA
I2C_ID  = 0
I2C_SDA = 2
I2C_SCL = 1

ADS1115_ADDR = 0x48   # ADDR a GND (default de la mayoria de los breakout GY-ADS1115)

# VDD real del breakout -- confirmado 3.3V. El input del ADS1115 nunca
# puede superar VDD (el PGA ±4.096V del driver es el techo "de config", no
# el techo fisico real). Con los ratios actuales (config.json:
# battery.tap_divider_ratio = [5.3, 8.5, 15.3, 18.5]) el canal A1 (B2+B1)
# da ~28.05V de fondo de escala contra ~28V nominales -- margen practicamente
# nulo, se satura facil. ADS1115_SAT_WARN_V marca el umbral para avisar en
# vez de reportar un voltaje clipeado en silencio (ver main.py: sensor_task).
ADS1115_VDD = 3.3
ADS1115_SAT_WARN_V = 3.1   # ~94% de VDD

# Ratio de cada divisor (config.json: battery.tap_divider_ratio) y la
# formula de taps acumulativos -> diferencias B1..B4 y suma VBATS en main.py.

# ── SPI — ADS1220 (corriente de bateria, sensor Hall toroidal "LSF") ───────
# Cableado real (dado, no el default de la placa):
#   GPIO1 -> MOSI
#   GPIO2 -> MISO
#   GPIO3 -> CS
#   GPIO4 -> SCLK
CURRENT_SPI_ID        = 1
CURRENT_SPI_SCK_PIN   = 13
CURRENT_CS_PIN        = 12
CURRENT_SPI_MISO_PIN  = 11
CURRENT_SPI_MOSI_PIN  = 10
CURRENT_SPI_BAUDRATE   = 800_000
# Sensibilidad del sensor Hall (V/A): config.json -> battery.current_sens_v_per_a

# ── LED de estado onboard (NeoPixel WS2812, fijo de fabrica) ───────────────
STATUS_LED_PIN   = 48
STATUS_LED_COUNT = 1

# ── Entrada de pulsos de velocidad del motor ────────────────────────────────
# Cruda por ahora: sin acondicionamiento analogico/filtrado todavia (TBD).
# Metros/pulso y el anti-rebote (debounce_us) estan en config.json -> speed,
# para poder ajustarlos sin reflashear mientras se prueba en banco.
SPEED_PULSE_PIN  = 5   # libre, no usado por SPI/I2C/NeoPixel
SPEED_PULSE_PULL = "UP"
SPEED_PULSE_EDGE = "RISING"

# ── Presencia de B4 (tension del auto) para deep sleep ──────────────────────
# Divisor resistivo externo que escala los 48V del banco B4 del auto a un
# nivel digital en este GPIO: alto = auto encendido/B4 presente, bajo =
# auto apagado/B4 ausente. El Super Mini sigue vivo con su Li-ion propia
# mientras decide si dormir -- ver main.py: SensorBoard.power_task /
# _enter_deep_sleep. GPIO11 esta dentro del rango RTC-capaz del S3
# (GPIO0-21), requerido para despertar de deepsleep con esp32.wake_on_ext1.
B4_PRESENCE_PIN  = 4
B4_PRESENCE_PULL = "DOWN"   # defensivo si el divisor queda desconectado


# ── Utilidades ───────────────────────────────────────────────────────────────

def make_i2c(freq=400_000):
    return machine.I2C(I2C_ID,
                        scl=machine.Pin(I2C_SCL),
                        sda=machine.Pin(I2C_SDA),
                        freq=freq)


def make_current_spi():
    return machine.SPI(
        CURRENT_SPI_ID, baudrate=CURRENT_SPI_BAUDRATE, polarity=0, phase=1,
        sck=machine.Pin(CURRENT_SPI_SCK_PIN),
        mosi=machine.Pin(CURRENT_SPI_MOSI_PIN),
        miso=machine.Pin(CURRENT_SPI_MISO_PIN),
    )


def make_status_led():
    from neopixel import NeoPixel
    return NeoPixel(machine.Pin(STATUS_LED_PIN), STATUS_LED_COUNT)


def make_speed_pulse_pin():
    pull = machine.Pin.PULL_UP if SPEED_PULSE_PULL == "UP" else (
        machine.Pin.PULL_DOWN if SPEED_PULSE_PULL == "DOWN" else None)
    return machine.Pin(SPEED_PULSE_PIN, machine.Pin.IN, pull)


def make_b4_presence_pin():
    pull = machine.Pin.PULL_UP if B4_PRESENCE_PULL == "UP" else (
        machine.Pin.PULL_DOWN if B4_PRESENCE_PULL == "DOWN" else None)
    return machine.Pin(B4_PRESENCE_PIN, machine.Pin.IN, pull)
