"""Append-only CSV trip logger for the T190 shared LoRa/SD SPI bus."""

import os
import time

import sdcard
from machine import Pin


MOUNT_POINT = "/sd"
SPI_BAUDRATE = 2_000_000
# SD es la prioridad mas baja del loop compartido (UI y ESPNOW primero, LoRa
# despues): se bufferea en RAM y se vuelca una sola vez por intervalo en vez
# de un write+flush por muestra, para minimizar cuantas veces el bus SPI
# queda bloqueado en el busy-wait de la tarjeta (ver sdcard.py write()).
COMMIT_INTERVAL_MS = 30000
CSV_HEADER = (
    "elapsed_ms,timestamp_art,boot,seq,adc_valid,current_valid,pulse_count,"
    "i_bat_a,v_b1_v,v_b2_v,v_b3_v,v_b4_v,vbats_v,p_inst_w,p_avg5s_w,"
    "speed_kmh,dist_m,whkm_inst,whkm_avg,wh_total_wh,"
    "gps_lat,gps_lon,gps_sats,crc16"
)


def crc16_ccitt(data):
    """CRC-16/CCITT-FALSE used to detect a torn or damaged CSV row."""
    crc = 0xFFFF
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc


def encode_sample(elapsed_ms, state, gps_fix=None, timestamp_art=None):
    if gps_fix is None:
        latitude = longitude = satellites = ""
    else:
        latitude = "{:.6f}".format(gps_fix["latitude"])
        longitude = "{:.6f}".format(gps_fix["longitude"])
        satellites = str(gps_fix["satellites"])

    body = (
        "{},{},{},{},{},{},{},{:.3f},{:.3f},{:.3f},{:.3f},{:.3f},{:.3f},"
        "{:.1f},{:.1f},{:.2f},{:.1f},{:.2f},{:.2f},{:.1f},{},{},{},"
    ).format(
        elapsed_ms, timestamp_art or "", state.source_boot, state.source_seq,
        int(state.adc_valid), int(state.current_valid), state.pulse_count,
        state.i_bat, state.v_b1, state.v_b2, state.v_b3, state.v_b4, state.v_bats,
        state.p_inst, state.p_avg5s, state.speed_kmh, state.dist_m,
        state.whkm_inst, state.whkm_avg, state.wh_total,
        latitude, longitude, satellites,
    )
    checksum = crc16_ccitt(body.encode("ascii"))
    return "{}{:04X}\n".format(body, checksum)


class TripLogger:
    def __init__(
        self, spi, *, sd_cs_pin, lora_cs_pin, mount_point=MOUNT_POINT,
        spi_baudrate=SPI_BAUDRATE,
    ):
        self.spi = spi
        self.mount_point = mount_point
        self.spi_baudrate = spi_baudrate
        self.sd_cs = Pin(sd_cs_pin, Pin.OUT, value=1)
        self.lora_cs = Pin(lora_cs_pin, Pin.OUT, value=1)
        self.card = None
        self.file = None
        self.path = None
        self.started_ms = None
        self.last_commit_ms = None
        self._buffer = []
        self.recording = False
        self.mounted = False
        self.error = None

    @property
    def ready(self):
        return self.mounted and self.error is None

    @property
    def sectors(self):
        return 0 if self.card is None else self.card.sectors

    def mount(self):
        if self.mounted:
            return
        self.lora_cs.value(1)
        self.sd_cs.value(1)
        try:
            self.card = sdcard.SDCard(
                self.spi, self.sd_cs, baudrate=self.spi_baudrate)
            os.mount(self.card, self.mount_point)
        except Exception:
            self.sd_cs.value(1)
            self.lora_cs.value(1)
            raise
        self.mounted = True

    @staticmethod
    def _ensure_dir(path):
        try:
            os.mkdir(path)
        except OSError:
            pass

    def _next_path(self, timestamp_art=None):
        # Carpeta por dia (YYYY-MM-DD, del reloj ART sincronizado por GPS);
        # sin fix GPS todavia no hay fecha confiable, va a SINFECHA.
        day_name = timestamp_art.split(" ")[0] if timestamp_art else "SINFECHA"
        day_path = "{}/{}".format(self.mount_point, day_name)
        self._ensure_dir(day_path)
        existing = os.listdir(day_path)
        if timestamp_art:
            stamp = timestamp_art.replace("-", "").replace(":", "").replace(" ", "_")
            base = "RIDE_{}".format(stamp)
            for suffix in range(100):
                name = "{}{}.CSV".format(
                    base, "" if suffix == 0 else "_{:02d}".format(suffix))
                if name not in existing:
                    return "{}/{}".format(day_path, name)
            raise OSError("no hay nombres libres para el timestamp {}".format(stamp))
        for index in range(1, 10000):
            name = "RIDE{:04d}.CSV".format(index)
            if name not in existing:
                return "{}/{}".format(day_path, name)
        raise OSError("no hay nombres libres RIDE0001.CSV-RIDE9999.CSV")

    @staticmethod
    def _sync():
        sync = getattr(os, "sync", None)
        if callable(sync):
            sync()

    def _write_line(self, line):
        self.lora_cs.value(1)
        self.sd_cs.value(1)
        written = self.file.write(line)
        if written != len(line):
            raise OSError("escritura SD incompleta: {} de {} bytes".format(
                written, len(line)))
        self.file.flush()

    def start(self, timestamp_art=None):
        if not self.ready:
            raise OSError(self.error or "microSD no montada")
        if self.recording:
            return False

        self.path = self._next_path(timestamp_art)
        self.started_ms = time.ticks_ms()
        self.file = open(self.path, "w")
        try:
            self._write_line("# eBike T190 log v1\n")
            self._write_line(CSV_HEADER + "\n")
            self.file.close()
            self.file = None
            self._sync()
            self.file = open(self.path, "a")
        except Exception:
            if self.file is not None:
                self.file.close()
                self.file = None
            raise

        self._buffer = []
        self.last_commit_ms = self.started_ms
        self.recording = True
        print("[SD] grabando", self.path)
        return True

    def _flush_buffer(self):
        if not self._buffer:
            return
        lines = "".join(self._buffer)
        self._buffer = []
        self._write_line(lines)

    def write_sample(self, state, gps_fix=None, timestamp_art=None):
        if not self.recording or self.file is None:
            return False
        now = time.ticks_ms()
        elapsed = time.ticks_diff(now, self.started_ms)
        self._buffer.append(encode_sample(
            elapsed, state, gps_fix, timestamp_art=timestamp_art))
        if time.ticks_diff(now, self.last_commit_ms) >= COMMIT_INTERVAL_MS:
            self._flush_buffer()
            self.file.close()
            self.file = None
            self._sync()
            self.file = open(self.path, "a")
            self.last_commit_ms = now
        return True

    def stop(self):
        if not self.recording:
            return False
        now = time.ticks_ms()
        elapsed = time.ticks_diff(now, self.started_ms)
        body = "END,{}".format(elapsed)
        line = "{}*{:04X}\n".format(
            body, crc16_ccitt(body.encode("ascii")))
        try:
            self._flush_buffer()
            self._write_line(line)
            self.file.close()
            self.file = None
            self._sync()
        except Exception:
            if self.file is not None:
                try:
                    self.file.close()
                except Exception as close_error:
                    print("[SD] error al cerrar archivo:", close_error)
                self.file = None
            raise
        finally:
            self.recording = False
        print("[SD] archivo cerrado", self.path)
        return True

    def abort(self, error):
        self.error = "{}".format(error)
        print("[SD] error de registro:", self.error)
        self.recording = False
        if self.file is not None:
            try:
                self._flush_buffer()
            except Exception as flush_error:
                print("[SD] error al volcar buffer:", flush_error)
            try:
                self.file.close()
            except Exception as close_error:
                print("[SD] error al cerrar archivo:", close_error)
            self.file = None
        if self.mounted:
            try:
                os.umount(self.mount_point)
            except Exception as unmount_error:
                print("[SD] error al desmontar:", unmount_error)
            self.mounted = False
        self.sd_cs.value(1)
        self.lora_cs.value(1)

    def deinit(self):
        error = None
        try:
            self.stop()
        except Exception as exc:
            error = exc
        if self.mounted:
            try:
                os.umount(self.mount_point)
                self.mounted = False
                self._sync()
            except Exception as exc:
                if error is None:
                    error = exc
        self.sd_cs.value(1)
        self.lora_cs.value(1)
        if error is not None:
            raise error
