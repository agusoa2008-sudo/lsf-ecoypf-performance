# test_sd.py -- prueba de microSD SPI en el Heltec T190
#
# La prueba inicializa la tarjeta, monta FAT, informa capacidad y realiza
# una escritura/lectura de verificacion. No formatea la tarjeta ni sobrescribe
# archivos existentes. Deja un archivo SDTESTxx.TXT como evidencia.
#
# Cableado:
#   SD SCK   -> GPIO9  (compartido con LoRa)
#   SD MOSI  -> GPIO10 (compartido con LoRa)
#   SD MISO  -> GPIO11 (compartido con LoRa)
#   SD CS    -> GPIO4  (CS LoRa independiente en GPIO8)
#   SD VCC   -> 3V3     SD GND -> GND
#
# Detener antes el firmware LoRa desde el REPL con stop(wait_ms=5000).
# Ejecutar luego: mpremote run test_sd.py
# Requiere sdcard.py en el filesystem del dispositivo.

import os
from machine import Pin, SPI

import HW
import sdcard


MOUNT_POINT = "/sd"
TEST_FILE_PREFIX = "SDTEST"
TEST_FILE_SUFFIX = ".TXT"
TEST_SIZE = 1024
SPI_BAUDRATE = 1_000_000


def _check_hw_config():
    required = (
        "LORA_CS", "SD_SPI_ID", "SD_SCK_PIN", "SD_MOSI_PIN",
        "SD_MISO_PIN", "SD_CS_PIN",
    )
    missing = [name for name in required if not hasattr(HW, name)]
    if missing:
        raise RuntimeError(
            "HW.py del dispositivo no tiene {}. Sube el HW.py actualizado "
            "del T190 y reinicia antes de volver a ejecutar test_sd.".format(
                ", ".join(missing)))
    if HW.SD_CS_PIN != 4:
        raise RuntimeError(
            "HW.SD_CS_PIN es GPIO{}, pero el cableado esperado para esta prueba "
            "es GPIO4. Corrige HW.py o el cableado.".format(HW.SD_CS_PIN))


def _new_test_path():
    existing = os.listdir(MOUNT_POINT)
    for index in range(100):
        name = "{}{:02d}{}".format(TEST_FILE_PREFIX, index, TEST_FILE_SUFFIX)
        if name not in existing:
            return "{}/{}".format(MOUNT_POINT, name)
    raise OSError("No quedan nombres libres SDTEST00.TXT-SDTEST99.TXT")


def _payload():
    return bytes(bytearray((index * 37 + 11) & 0xFF for index in range(TEST_SIZE)))


def _run_test():
    _check_hw_config()
    spi = None
    mounted = False
    lora_cs = Pin(HW.LORA_CS, Pin.OUT, value=1)
    sd_cs = Pin(HW.SD_CS_PIN, Pin.OUT, value=1)

    try:
        spi = SPI(
            HW.SD_SPI_ID,
            baudrate=SPI_BAUDRATE,
            polarity=0,
            phase=0,
            sck=Pin(HW.SD_SCK_PIN),
            mosi=Pin(HW.SD_MOSI_PIN),
            miso=Pin(HW.SD_MISO_PIN),
        )
        print("[test_sd] SPI{} SCK/MOSI/MISO={}/{}/{} SD_CS={} LoRa_CS={}".format(
            HW.SD_SPI_ID, HW.SD_SCK_PIN, HW.SD_MOSI_PIN, HW.SD_MISO_PIN,
            HW.SD_CS_PIN, HW.LORA_CS))

        card = sdcard.SDCard(spi, sd_cs)
        capacity_bytes = card.sectors * 512
        print("[test_sd] tarjeta detectada: {} sectores, {:.2f} GB ({:.2f} GiB)".format(
            card.sectors, capacity_bytes / 1_000_000_000,
            capacity_bytes / (1024 * 1024 * 1024)))

        os.mount(card, MOUNT_POINT)
        mounted = True
        print("[test_sd] FAT montado en {}".format(MOUNT_POINT))

        stats = os.statvfs(MOUNT_POINT)
        total_fs_bytes = stats[1] * stats[2]
        free_fs_bytes = stats[1] * stats[3]
        print("[test_sd] filesystem: total {:.2f} GiB, libre {:.2f} GiB".format(
            total_fs_bytes / (1024 * 1024 * 1024),
            free_fs_bytes / (1024 * 1024 * 1024)))

        path = _new_test_path()
        expected = _payload()
        with open(path, "wb") as test_file:
            written = test_file.write(expected)
            test_file.flush()
        if written != len(expected):
            raise OSError("Escritura incompleta: {} de {} bytes".format(
                written, len(expected)))

        with open(path, "rb") as test_file:
            actual = test_file.read()
        if actual != expected:
            raise OSError("La verificacion de lectura no coincide con lo escrito")

        print("[test_sd] OK: {} bytes escritos y verificados en {}".format(
            len(actual), path))
        print("[test_sd] El archivo de prueba se conserva; puedes borrarlo desde el PC.")
    finally:
        if mounted:
            os.umount(MOUNT_POINT)
            print("[test_sd] filesystem desmontado")
        if spi is not None:
            deinit = getattr(spi, "deinit", None)
            if callable(deinit):
                deinit()
        lora_cs.value(1)
        sd_cs.value(1)


try:
    _run_test()
except Exception as exc:
    print("[test_sd] FALLO:", exc)
    raise
