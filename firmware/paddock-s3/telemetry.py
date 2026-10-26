"""Decode and retain the latest T190 LoRa telemetry frame."""

import math
import time


FIELD_LABELS = {
    "I": ("current_a", "Corriente", "A"),
    "B1": ("battery_1_v", "Batería 1", "V"),
    "B2": ("battery_2_v", "Batería 2", "V"),
    "B3": ("battery_3_v", "Batería 3", "V"),
    "B4": ("battery_4_v", "Batería 4", "V"),
    "VBATS": ("battery_pack_v", "VBATS total", "V"),
    "P": ("power_w", "Potencia", "W"),
    "PA": ("power_avg_w", "Potencia media", "W"),
    "V": ("speed_kmh", "Velocidad", "km/h"),
    "D": ("distance_m", "Distancia", "m"),
    "WI": ("whkm_inst", "Consumo instantáneo", "Wh/km"),
    "WA": ("whkm_avg", "Consumo medio", "Wh/km"),
    "WT": ("wh_total", "Energía", "Wh"),
}


class TelemetryState:
    def __init__(self):
        self.values = {}
        self.extra = {}
        self.rx_count = 0
        self.last_rx_ms = 0
        self.source_age_ms_at_rx = None
        self.source_seq = None
        self.source_boot = None
        self.adc_valid = False
        self.current_valid = False
        self.pulse_count = 0
        self.last_error = ""
        self.radio_ok = False
        self.radio_error = ""

    def update(self, payload):
        if isinstance(payload, bytes):
            try:
                payload = payload.decode("utf-8")
            except UnicodeError as exc:
                raise ValueError("el paquete no es texto UTF-8") from exc
        if not isinstance(payload, str):
            raise ValueError("el paquete LoRa no es texto")

        text = payload.strip()
        if text.startswith("TLM:"):
            text = text[4:]

        values = {}
        extra = {}
        for part in text.split(";"):
            part = part.strip()
            if not part:
                continue
            key, separator, raw_value = part.partition("=")
            key = key.strip()
            raw_value = raw_value.strip()
            if not separator or not key or not raw_value:
                raise ValueError("campo LoRa inválido: {!r}".format(part))
            try:
                number = float(raw_value)
            except ValueError:
                if key in FIELD_LABELS:
                    raise ValueError("valor no numérico para {}: {!r}".format(
                        key, raw_value))
                extra[key] = raw_value
            else:
                if key in FIELD_LABELS:
                    values[FIELD_LABELS[key][0]] = number
                else:
                    extra[key] = number

        required = ("VER", "BOOT", "Q", "AGE", "AV", "IV", "PC") + tuple(
            key for key in FIELD_LABELS)
        parsed = {}
        for part in text.split(";"):
            key, separator, raw_value = part.strip().partition("=")
            if not separator or not key or not raw_value:
                raise ValueError("campo LoRa inválido: {!r}".format(part))
            if key in parsed:
                raise ValueError("campo LoRa duplicado: {}".format(key))
            parsed[key] = raw_value
        missing = [key for key in required if key not in parsed]
        if missing:
            raise ValueError("faltan campos LoRa: {}".format(",".join(missing)))
        if parsed["VER"] != "3":
            raise ValueError("versión LoRa no soportada: {}".format(parsed["VER"]))
        try:
            seq = int(parsed["Q"])
            boot_id = int(parsed["BOOT"])
            source_age = int(parsed["AGE"])
            adc_valid = int(parsed["AV"])
            current_valid = int(parsed["IV"])
            pulse_count = int(parsed["PC"])
        except ValueError as exc:
            raise ValueError("metadato LoRa no numérico: {}".format(exc))
        if (not 0 <= boot_id <= 0xFFFFFFFF or not 1 <= seq <= 65535 or source_age < 0 or
                adc_valid not in (0, 1) or current_valid not in (0, 1) or
                pulse_count < 0):
            raise ValueError("metadato LoRa fuera de rango")
        if any(not math.isfinite(value) for value in values.values()):
            raise ValueError("valor LoRa no finito")

        if not values:
            raise ValueError("el paquete no contiene campos de telemetría conocidos")

        self.values = values
        self.extra = extra
        self.source_seq = seq
        self.source_boot = boot_id
        self.source_age_ms_at_rx = source_age
        self.adc_valid = bool(adc_valid)
        self.current_valid = bool(current_valid)
        self.pulse_count = pulse_count
        self.rx_count += 1
        self.last_rx_ms = time.ticks_ms()
        self.last_error = ""

    def packet_age_ms(self):
        if self.rx_count == 0:
            return None
        return time.ticks_diff(time.ticks_ms(), self.last_rx_ms)

    def source_age_ms(self):
        if self.source_age_ms_at_rx is None:
            return None
        return self.source_age_ms_at_rx + (self.packet_age_ms() or 0)

    def as_dict(self):
        source_age = self.source_age_ms()
        return {
            "values": self.values,
            "extra": self.extra,
            "rx_count": self.rx_count,
            "packet_age_ms": self.packet_age_ms(),
            "source_age_ms": source_age,
            "source_fresh": source_age is not None and source_age <= 5000,
            "source_seq": self.source_seq,
            "adc_valid": self.adc_valid,
            "current_valid": self.current_valid,
            "pulse_count": self.pulse_count,
            "radio_ok": self.radio_ok,
            "radio_error": self.radio_error,
            "last_error": self.last_error,
        }
