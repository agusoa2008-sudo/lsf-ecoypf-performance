"""Hardware map and radio/AP settings for the XIAO ESP32-S3 paddock node."""

import machine

# Seeed XIAO ESP32-S3 + Wio-SX1262 pinout used by uPy reference Martin.
LORA_SPI_ID = 1
LORA_SCK_PIN_ID = 7
LORA_MOSI_PIN_ID = 9
LORA_MISO_PIN_ID = 8
LORA_CS_PIN_ID = 41
LORA_RESET_PIN_ID = 42
LORA_BUSY_PIN_ID = 40
LORA_DIO1_PIN_ID = 39
LORA_DIO2_PIN_ID = 38

# Match the 1 km line-of-sight tradeoff profile in ../New T190/HW.py.
LORA_DEFAULT_FREQ = 915.0
LORA_DEFAULT_BW = 125.0
LORA_DEFAULT_SF = 9
LORA_DEFAULT_CR = 6
LORA_DEFAULT_POWER = 17
LORA_DEFAULT_SYNC_WORD = 0x12
LORA_DEFAULT_PREAMBLE_LEN = 12
LORA_DEFAULT_CURRENT_LIMIT = 80
LORA_DEFAULT_TCXO_VOLTAGE = 1.6
LORA_DEFAULT_USE_LDO = False
LORA_DEFAULT_BLOCKING = False

LORA_DEFAULT_PRESET = "tradeoff"
LORA_PRESETS = {
    "tradeoff": {
        "freq": LORA_DEFAULT_FREQ,
        "bw": LORA_DEFAULT_BW,
        "sf": LORA_DEFAULT_SF,
        "cr": LORA_DEFAULT_CR,
        "power": LORA_DEFAULT_POWER,
        "syncWord": LORA_DEFAULT_SYNC_WORD,
        "preambleLength": LORA_DEFAULT_PREAMBLE_LEN,
        "currentLimit": LORA_DEFAULT_CURRENT_LIMIT,
        "tcxoVoltage": LORA_DEFAULT_TCXO_VOLTAGE,
        "useRegulatorLDO": LORA_DEFAULT_USE_LDO,
        "blocking": LORA_DEFAULT_BLOCKING,
    },
}

AP_SSID = "Paddock-LSF"
AP_PASSWORD = "lasalle2026"
AP_IP = "192.168.4.1"
AP_NETMASK = "255.255.255.0"


def make_output(pin_num, value=0):
    return machine.Pin(pin_num, machine.Pin.OUT, value=value)


def make_input(pin_num):
    return machine.Pin(pin_num, machine.Pin.IN)


def make_spi(baudrate=8_000_000):
    return machine.SPI(
        LORA_SPI_ID,
        baudrate=baudrate,
        polarity=0,
        phase=0,
        sck=machine.Pin(LORA_SCK_PIN_ID),
        mosi=machine.Pin(LORA_MOSI_PIN_ID),
        miso=machine.Pin(LORA_MISO_PIN_ID),
    )
