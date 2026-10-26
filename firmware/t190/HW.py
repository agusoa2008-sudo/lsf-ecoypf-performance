
# HW.py
# Pin map y helpers para Heltec Vision Master T190 (ESP32-S3R8) con MicroPython.
# Display TFT 170x320 integrado (N190-1732TBWPG01-C30).
# Hardware map for the T190 gateway: TFT, onboard SX1262, GPS, system battery
# measurement, and header GPIOs available for future peripherals.

import machine
import time

# ── Display TFT integrado (SPI interno, NO en headers) ──────────────────────
# Controlador: ST7789 (170 RGB x 320, 4-wire SPI)
TFT_MOSI   = 48   # TFT_SDA
TFT_SCK    = 38   # TFT_SCL
TFT_CS     = 39   # TFT_CS
TFT_DC     = 47   # TFT_RS  (Data/Command)
TFT_RST    = 40   # TFT_RST
TFT_BL     = 17   # LEDK_EN (backlight enable, HIGH = encendido)
TFT_PWR    = 7    # VTFT_Ctrl (P-MOSFET, LOW = display encendido)

TFT_WIDTH  = 170
TFT_HEIGHT = 320
TFT_SPI_ID = 1
TFT_BAUDRATE = 40_000_000

# ── LoRa HT-RA62 (SX1262) onboard — reservado para la radio ─────────────────
# El modulo LoRa esta soldado a estos GPIO; no reasignarlos a periféricos.
LORA_SCK   = 9    # J3-6
LORA_MOSI  = 10   # J3-5
LORA_MISO  = 11   # J3-4
LORA_CS    = 8    # J3-7  (NSS)
LORA_RST   = 12   # J3-3
LORA_BUSY  = 13   # J2-5
LORA_DIO1  = 14   # J2-6
LORA_FREQ_MHZ = 915.0   # cambiar a 868.0 en Europa
LORA_BW_KHZ = 125.0
LORA_SF = 9
LORA_CR = 6
LORA_SYNC_WORD = 0x12
LORA_POWER_DBM = 17
LORA_PREAMBLE_LEN = 12
LORA_CURRENT_LIMIT_MA = 80
LORA_TCXO_VOLTAGE = 1.6

# ── MicroSD SPI — comparte lineas con el SX1262 ─────────────────────────────
# Pendiente de integrar ambos dispositivos sobre el mismo objeto SPI.
SD_SPI_ID = 2
SD_SCK_PIN = LORA_SCK
SD_MOSI_PIN = LORA_MOSI
SD_MISO_PIN = LORA_MISO
SD_CS_PIN = 4             # GPIO junto al CS LoRa (GPIO8), independiente
SD_CS_ACTIVE_LEVEL = 0

# ── OLED I2C externo ────────────────────────────────────────────────────────
# GPIO15/16 tambien son XTAL_32K_P/N; usarlos como I2C implica no montar ni
# habilitar un cristal externo de 32.768 kHz en esos pines.
OLED_I2C_ID = 0
OLED_I2C_SCL_PIN = 15
OLED_I2C_SDA_PIN = 16
OLED_I2C_FREQ = 400_000

# ── Botonería ────────────────────────────────────────────────────────────────
# El T190 expone dos botones utilizables por firmware:
PAGE_BTN_PIN   = 21   # USER_KEY S3 — activo-bajo, pull-up externo 10K a 3.3V
                       # corto: anterior; doble: reset viaje; largo: waypoint;
                       # EXTRA >=2.2 s: deep sleep al soltar. Flancos activos
                       # en LOW; gestos de InterruptPageButton.
BTN0_PIN       = 0    # BOOT/PRG — activo-bajo, pull-up interno. Strapping pin
                       # de boot (solo se evalua para entrar a modo bootloader
                       # durante power-on/reset real); en runtime es un GPIO
                       # normal, ya usado asi en loralcd_test.py/madctl_test.py.
                       # NOTA: startup_cleanup.py lo lee UNA VEZ al bootear como
                       # gatillo de recuperacion (mantenido bajo -> borra
                       # main.py) -- no interfiere con leerlo despues en el loop
                       # principal, una vez que main.py ya esta corriendo.
                       # LED2 naranja tambien comparte GPIO0 (activo-bajo);
                       # mantenerlo como entrada mientras se usa BTN0.
                       # Solo short: pantalla siguiente (navegacion simple,
                       # a proposito, para minimizar error manejando).
# No hay un GPIO de START dedicado expuesto en los headers del T190. La
# captura de largada GPS se asigna a la pulsacion larga del boton PAGE.

# ── Batería del sistema (ADC interno) ───────────────────────────────────────
VBAT_ADC_PIN = 6            # VBAT_Read, divisor R9=390K / R11=100K
VBAT_ADC_CTRL_PIN = 46      # ADC_Ctrl; GPIO46 es strapping, se conmuta ya en runtime
VBAT_ADC_CTRL_ON = 1
VBAT_ADC_CTRL_OFF = 0
VBAT_DIV_RATIO = (390 + 100) / 100.0
VBAT_ADC_DISCARD_SAMPLES = 8
VBAT_ADC_SAMPLES = 9
VBAT_ADC_SAMPLE_INTERVAL_MS = 10
VBAT_ADC_SETTLE_MS = 50

# ── VEXT (salida 3.3V conmutable para sensores externos) ────────────────────
VEXT_CTRL_PIN = 5           # Ve_Ctrl — HIGH conecta Ve_3V3 al QuickLink
VEXT_CTRL_ON = 1
VEXT_CTRL_OFF = 0

# ── GPS conectado al QuickLink ──────────────────────────────────────────────
GPS_UART_ID = 1
GPS_RX_PIN = 1              # QL_SCL / GPIO1 <- TX del GPS
GPS_TX_PIN = 2              # QL_SDA / GPIO2 -> RX del GPS
GPS_BAUDRATE = 9600

# ── Pines de placa adicionales (segun el esquema HT-VMT190) ─────────────────
STATUS_LED_PIN = 0           # LED2 naranja, compartido con BOOT; activo en LOW
STATUS_LED_ACTIVE_LEVEL = 0
TP_INT_PIN = 18              # net TP_INT, no usado por la pantalla actual
TP_RST_PIN = 41              # net TP_RST / test pad
TP_SCL_PIN = 42              # net TP_SCL / test pad
TP_SDA_PIN = 45              # net TP_SDA / test pad
USB_DM_PIN = 19              # USB nativo D-
USB_DP_PIN = 20              # USB nativo D+
UART0_TX_PIN = 43            # consola REPL
UART0_RX_PIN = 44            # consola REPL

# GPIO4 esta reservado como CS de microSD (todavia sin driver); GPIO3 queda
# libre y GPIO15/16 quedan asignados al OLED I2C.
HEADER_UNASSIGNED_PINS = (3,)

# ── Deep sleep wake ─────────────────────────────────────────────────────────
MAIN_WAKE_PIN = 21   # Boton usuario S3

# ── UART0 debug / REPL (J2 pines 9 y 10) ────────────────────────────────────
# GPIO43 = U0_TXD,  GPIO44 = U0_RXD  (tambien via USB-JTAG/CDC)


# ── Utilidades ───────────────────────────────────────────────────────────────

def make_input(pin_num, pull=None):
    if pull:
        return machine.Pin(pin_num, machine.Pin.IN, pull)
    return machine.Pin(pin_num, machine.Pin.IN)


def make_output(pin_num, *, value=1):
    pin = machine.Pin(pin_num, machine.Pin.OUT)
    pin.value(value)
    return pin


def display_power_on():
    """Enciende el display (VTFT_Ctrl LOW activa el P-MOSFET)."""
    make_output(TFT_PWR, value=0)


def display_power_off():
    make_output(TFT_PWR, value=1)


def backlight_on():
    make_output(TFT_BL, value=1)


def backlight_off():
    make_output(TFT_BL, value=0)


def vext_enable():
    make_output(VEXT_CTRL_PIN, value=VEXT_CTRL_ON)


def vext_disable():
    make_output(VEXT_CTRL_PIN, value=VEXT_CTRL_OFF)


def make_oled_i2c():
    """Bus I2C para el OLED externo (GPIO15 SCL / GPIO16 SDA)."""
    return machine.I2C(OLED_I2C_ID,
                        scl=machine.Pin(OLED_I2C_SCL_PIN),
                        sda=machine.Pin(OLED_I2C_SDA_PIN),
                        freq=OLED_I2C_FREQ)


def read_system_battery_sample():
    """Devuelve VBAT, voltaje en GPIO6 y ADC crudo para diagnóstico."""
    ctrl = machine.Pin(VBAT_ADC_CTRL_PIN, machine.Pin.OUT,
                       value=VBAT_ADC_CTRL_ON)
    try:
        time.sleep_ms(VBAT_ADC_SETTLE_MS)
        adc = machine.ADC(machine.Pin(VBAT_ADC_PIN))
        read_uv = getattr(adc, "read_uv", None)
        try:
            attenuation = (machine.ADC.ATTN_6DB if callable(read_uv)
                           else machine.ADC.ATTN_11DB)
            adc.atten(attenuation)
        except AttributeError:
            adc.atten(machine.ADC.ATTN_11DB)

        if callable(read_uv):
            read_pin_voltage = lambda: read_uv() / 1_000_000.0
            read_method = "read_uv"
        else:
            width = getattr(machine.ADC, "WIDTH_12BIT", None)
            set_width = getattr(adc, "width", None)
            if width is not None and callable(set_width):
                set_width(width)
            read_pin_voltage = lambda: adc.read() * 3.3 / 4095.0
            read_method = "raw_aprox"

        for _ in range(VBAT_ADC_DISCARD_SAMPLES):
            time.sleep_ms(VBAT_ADC_SAMPLE_INTERVAL_MS)
            read_pin_voltage()
            adc.read()
        samples = []
        raw_samples = []
        for _ in range(VBAT_ADC_SAMPLES):
            time.sleep_ms(VBAT_ADC_SAMPLE_INTERVAL_MS)
            samples.append(read_pin_voltage())
            raw_samples.append(adc.read())
        samples.sort()
        raw_samples.sort()
        pin_voltage = samples[len(samples) // 2]
        voltage = pin_voltage * VBAT_DIV_RATIO
        if not 2.5 <= voltage <= 4.5:
            raise ValueError("VBAT T190 fuera de rango: {:.2f} V".format(voltage))
        return {
            "voltage_v": voltage,
            "pin_voltage_v": pin_voltage,
            "raw_median": raw_samples[len(raw_samples) // 2],
            "read_method": read_method,
        }
    finally:
        ctrl.value(VBAT_ADC_CTRL_OFF)


def read_system_battery_v():
    """Lee VBAT del T190 y devuelve la mediana de las muestras."""
    return read_system_battery_sample()["voltage_v"]
