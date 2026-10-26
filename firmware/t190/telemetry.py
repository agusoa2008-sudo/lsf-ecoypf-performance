# telemetry.py
# Estado de telemetria eBike2026 -- el T190 ya NO lee sensores propios
# (ni ADS1115, ni ADS1220, ni pulso de velocidad para telemetria): todo
# llega por ESP-NOW desde el Super Mini, que hace la lectura + los
# calculos (Wh, potencia, eficiencia). Esta clase solo guarda el ultimo
# valor recibido y lo reenvia por LoRa a la base.
#
# Si el Super Mini todavia no manda algun campo (ej. P/Wh, mientras no
# esten implementados alla), ese campo del estado simplemente se queda en
# su ultimo valor -- no se inventa ni se recalcula nada aca.

import math
import time
import uasyncio as asyncio

SOURCE_STALE_MS = 5000


class TelemetryState:
    def __init__(self):
        self.i_bat = 0.0
        self.v_b1 = 0.0
        self.v_b2 = 0.0
        self.v_b3 = 0.0
        self.v_b4 = 0.0
        self.v_bats = 0.0       # tension total del pack, suma de B1..B4
        self.p_inst = 0.0
        self.p_avg5s = 0.0
        self.speed_kmh = 0.0
        self.dist_m = 0.0
        self.whkm_inst = 0.0
        self.whkm_avg = 0.0
        self.wh_total = 0.0

        self.lora_ok = False
        self.lora_tx_count = 0
        self.lora_last_error = ""
        self.espnow_rx_count = 0
        self.source_seq = None
        self.source_boot = None
        self.source_last_rx_ms = 0
        self.adc_valid = False
        self.current_valid = False
        self.pulse_count = 0


class TelemetryRuntime:
    """Agrupa el estado + las tareas asyncio que lo alimentan."""

    # Claves del payload compacto ("I=..;B1=..;...") -> atributo de
    # TelemetryState. Mismo formato que arma _build_payload, asi el
    # Super Mini y el T190 hablan el mismo "idioma" sin traducir dos veces.
    _FIELD_MAP = {
        "I": "i_bat", "B1": "v_b1", "B2": "v_b2", "B3": "v_b3",
        "B4": "v_b4", "VBATS": "v_bats",
        "P": "p_inst", "PA": "p_avg5s", "V": "speed_kmh", "D": "dist_m",
        "WI": "whkm_inst", "WA": "whkm_avg", "WT": "wh_total",
    }

    def __init__(self, lora=None):
        self.state = TelemetryState()
        self._lora = lora
        self.pack_voltage_ratio = 1.0  # always 1.0; correction lives in Super Mini
        self._raw_values = None

    @property
    def raw_vbats(self):
        return None if self._raw_values is None else self._raw_values["VBATS"]

    @property
    def raw_battery_voltages(self):
        if self._raw_values is None:
            return None
        return [self._raw_values["B{}".format(index)] for index in range(1, 5)]

    @property
    def raw_wh_total(self):
        return None if self._raw_values is None else self._raw_values["WT"]

    def _apply_values(self):
        if self._raw_values is None:
            return
        st = self.state
        st.v_b1 = self._raw_values["B1"]
        st.v_b2 = self._raw_values["B2"]
        st.v_b3 = self._raw_values["B3"]
        st.v_b4 = self._raw_values["B4"]
        st.v_bats = st.v_b1 + st.v_b2 + st.v_b3 + st.v_b4
        for key, attr in self._FIELD_MAP.items():
            if key in ("B1", "B2", "B3", "B4", "VBATS"):
                continue
            setattr(st, attr, self._raw_values[key])

    def on_telemetry(self, payload_str):
        """Validate and atomically apply one versioned Super Mini frame."""
        parsed = {}
        for part in payload_str.split(";"):
            key, separator, raw_value = part.partition("=")
            if not separator or not key or not raw_value:
                raise ValueError("campo ESP-NOW inválido: {!r}".format(part))
            if key in parsed:
                raise ValueError("campo ESP-NOW duplicado: {}".format(key))
            parsed[key] = raw_value

        required = ("VER", "BOOT", "Q", "AV", "IV", "PC") + tuple(self._FIELD_MAP)
        missing = [key for key in required if key not in parsed]
        if missing:
            raise ValueError("faltan campos ESP-NOW: {}".format(",".join(missing)))
        if parsed["VER"] != "3":
            raise ValueError("versión ESP-NOW no soportada: {}".format(parsed["VER"]))

        try:
            seq = int(parsed["Q"])
            boot_id = int(parsed["BOOT"])
            adc_valid = int(parsed["AV"])
            current_valid = int(parsed["IV"])
            pulse_count = int(parsed["PC"])
            values = {key: float(parsed[key]) for key in self._FIELD_MAP}
        except ValueError as exc:
            raise ValueError("valor ESP-NOW no numérico: {}".format(exc))
        if (not 0 <= boot_id <= 0xFFFFFFFF or not 1 <= seq <= 65535 or
                adc_valid not in (0, 1) or current_valid not in (0, 1)):
            raise ValueError("secuencia o flags ESP-NOW fuera de rango")
        if pulse_count < 0:
            raise ValueError("contador de pulsos negativo")
        if any(not math.isfinite(value) for value in values.values()):
            raise ValueError("valor ESP-NOW no finito")

        st = self.state
        if st.source_seq is not None and st.source_boot == boot_id:
            seq_delta = (seq - st.source_seq) & 0xFFFF
            if seq_delta == 0 or seq_delta >= 0x8000:
                return False
        self._raw_values = values
        self._apply_values()
        st.adc_valid = bool(adc_valid)
        st.current_valid = bool(current_valid)
        st.pulse_count = pulse_count
        st.source_seq = seq
        st.source_boot = boot_id
        st.source_last_rx_ms = time.ticks_ms()
        st.espnow_rx_count += 1
        return True

    def source_age_ms(self):
        if self.state.source_seq is None:
            return None
        return time.ticks_diff(time.ticks_ms(), self.state.source_last_rx_ms)

    def source_fresh(self):
        age = self.source_age_ms()
        return age is not None and age <= SOURCE_STALE_MS

    @staticmethod
    def _build_payload(st):
        """Build LoRa frame with source sequence, age, and validity flags."""
        if st.source_seq is None:
            return None
        age_ms = time.ticks_diff(time.ticks_ms(), st.source_last_rx_ms)
        source_fresh = age_ms <= SOURCE_STALE_MS
        return (
            "VER=3;BOOT={};Q={};AGE={};AV={};IV={};PC={};"
            "I={:.2f};B1={:.2f};B2={:.2f};B3={:.2f};B4={:.2f};VBATS={:.2f};"
            "P={:.0f};PA={:.0f};V={:.1f};D={:.0f};"
            "WI={:.1f};WA={:.1f};WT={:.1f}"
        ).format(
            st.source_boot, st.source_seq, age_ms,
            int(st.adc_valid and source_fresh),
            int(st.current_valid and source_fresh), st.pulse_count,
            st.i_bat, st.v_b1, st.v_b2, st.v_b3, st.v_b4, st.v_bats,
            st.p_inst, st.p_avg5s, st.speed_kmh, st.dist_m,
            st.whkm_inst, st.whkm_avg, st.wh_total,
        )

    async def lora_task(self, interval_ms=2000):
        """Reenvia por LoRa la ultima telemetria recibida del Super Mini."""
        st = self.state
        if self._lora is None:
            print("[telemetry] LoRa no inicializado; tarea de envio inactiva")
            return
        while True:
            payload = self._build_payload(st)
            if payload is None:
                st.lora_ok = False
                await asyncio.sleep_ms(interval_ms)
                continue
            try:
                _, status = self._lora.send(payload.encode())
                if status != 0:
                    raise RuntimeError("SX1262 send status {}".format(status))
                st.lora_ok = True
                st.lora_tx_count += 1
                st.lora_last_error = ""
            except Exception as exc:
                st.lora_ok = False
                st.lora_last_error = "{}".format(exc)
                print("[LoRa] send error:", exc)
            await asyncio.sleep_ms(interval_ms)
