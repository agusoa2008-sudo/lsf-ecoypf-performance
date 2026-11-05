"""Persistent T190 calibration and traction-pack energy settings."""

import time
import math
import ujson
import uos


SETTINGS_FILE = "t190_settings.json"
TEMP_FILE = "t190_settings.tmp"
BACKUP_FILE = "t190_settings.bak"
ENERGY_SAVE_INTERVAL_MS = 60000

DEFAULTS = {
    "b_supermini_factors_milli": [1000, 1000, 1000, 1000],
    "ads_mode": "cumulative",
    "battery_capacity_wh": 816.0,
    "battery_capacity_configured": True,
    "idle_sleep_timeout_min": 20,
    "battery_used_wh": 0.0,
    "energy_baseline_set": False,
    "energy_source_boot": None,
    "energy_source_wh": None,
    "trip_distance_m": 0.0,
    "distance_baseline_set": False,
    "distance_source_boot": None,
    "distance_source_m": None,
    "supermini_meters_per_pulse": 0.1,
    "supermini_distance_configured": False,
    "supermini_debounce_us": 2000,
    "supermini_max_speed_kmh": 80.0,
    "supermini_config_revision": 1,
    "precharge_wh": 0.0,
}


def _valid_number(value, name, minimum, maximum):
    try:
        value = float(value)
    except (TypeError, ValueError):
        raise ValueError("{} debe ser numérico".format(name))
    if not minimum <= value <= maximum:
        raise ValueError("{} fuera de rango".format(name))
    return value


def _validated_factors(values, name):
    if not isinstance(values, (list, tuple)) or len(values) != 4:
        raise ValueError("{} debe contener cuatro factores".format(name))
    factors = []
    for value in values:
        try:
            number = float(value)
        except (TypeError, ValueError):
            raise ValueError("{} debe contener enteros".format(name))
        if (not math.isfinite(number) or number != int(number) or
                not 800 <= number <= 1200):
            raise ValueError("{} debe estar entre 800 y 1200".format(name))
        factors.append(int(number))
    return factors


def _validated_values(data):
    if not isinstance(data, dict):
        raise ValueError("la configuración T190 debe ser un objeto JSON")
    merged = dict(DEFAULTS)
    merged.update(data)

    # Migration from old format (fine_voltage_factors_milli + supermini_voltage_factors_milli)
    if (("fine_voltage_factors_milli" in data or
            "supermini_voltage_factors_milli" in data) and
            "b_supermini_factors_milli" not in data):
        print("[settings] migración: formato de factores obsoleto; "
              "recalibrar tensiones desde el AP")
        merged["b_supermini_factors_milli"] = [1000, 1000, 1000, 1000]
    # Remove legacy keys
    for legacy in ("fine_voltage_factors_milli", "supermini_voltage_factors_milli",
                   "voltage_factor_milli"):
        merged.pop(legacy, None)

    merged["b_supermini_factors_milli"] = _validated_factors(
        merged.get("b_supermini_factors_milli", [1000, 1000, 1000, 1000]),
        "b_supermini_factors_milli")

    ads_mode = merged.get("ads_mode", "cumulative")
    if ads_mode not in ("cumulative", "individual"):
        raise ValueError("ads_mode debe ser 'cumulative' o 'individual'")
    merged["ads_mode"] = ads_mode

    merged["battery_capacity_wh"] = _valid_number(
        merged["battery_capacity_wh"], "battery_capacity_wh", 0, 200000)
    configured_capacity = data.get("battery_capacity_configured", False)
    if not isinstance(configured_capacity, bool):
        raise ValueError("battery_capacity_configured debe ser booleano")
    if not configured_capacity and merged["battery_capacity_wh"] == 0:
        merged["battery_capacity_wh"] = 816.0
    merged["battery_capacity_configured"] = True
    sleep_timeout = merged["idle_sleep_timeout_min"]
    try:
        sleep_value = float(sleep_timeout)
    except (TypeError, ValueError):
        raise ValueError("idle_sleep_timeout_min debe ser entero")
    if (not math.isfinite(sleep_value) or sleep_value != int(sleep_value) or
            not 0 <= sleep_value <= 240):
        raise ValueError("idle_sleep_timeout_min debe estar entre 0 y 240")
    merged["idle_sleep_timeout_min"] = int(sleep_value)
    merged["battery_used_wh"] = _valid_number(
        merged["battery_used_wh"], "battery_used_wh", 0, 10000000)
    if not isinstance(merged["energy_baseline_set"], bool):
        raise ValueError("energy_baseline_set debe ser booleano")
    source_boot = merged["energy_source_boot"]
    if source_boot is not None:
        try:
            boot_value = float(source_boot)
        except (TypeError, ValueError):
            raise ValueError("energy_source_boot debe ser entero")
        if (not math.isfinite(boot_value) or boot_value != int(boot_value) or
                not 0 <= boot_value <= 0xFFFFFFFF):
            raise ValueError("energy_source_boot fuera de rango")
        merged["energy_source_boot"] = int(boot_value)
    source_wh = merged["energy_source_wh"]
    if source_wh is not None:
        merged["energy_source_wh"] = _valid_number(
            source_wh, "energy_source_wh", 0, 10000000)
    merged["trip_distance_m"] = _valid_number(
        merged["trip_distance_m"], "trip_distance_m", 0, 100000000)
    if not isinstance(merged["distance_baseline_set"], bool):
        raise ValueError("distance_baseline_set debe ser booleano")
    distance_boot = merged["distance_source_boot"]
    if distance_boot is not None:
        try:
            distance_boot_value = float(distance_boot)
        except (TypeError, ValueError):
            raise ValueError("distance_source_boot debe ser entero")
        if (not math.isfinite(distance_boot_value) or
                distance_boot_value != int(distance_boot_value) or
                not 0 <= distance_boot_value <= 0xFFFFFFFF):
            raise ValueError("distance_source_boot fuera de rango")
        merged["distance_source_boot"] = int(distance_boot_value)
    distance_source_m = merged["distance_source_m"]
    if distance_source_m is not None:
        merged["distance_source_m"] = _valid_number(
            distance_source_m, "distance_source_m", 0, 100000000)
    distance_configured = data.get("supermini_distance_configured", False)
    if not isinstance(distance_configured, bool):
        raise ValueError("supermini_distance_configured debe ser booleano")
    distance_migrated = (
        not distance_configured and
        data.get("supermini_meters_per_pulse") == 2.07)
    if distance_migrated:
        merged["supermini_meters_per_pulse"] = 0.1
    merged["supermini_distance_configured"] = distance_configured
    merged["supermini_meters_per_pulse"] = _valid_number(
        merged["supermini_meters_per_pulse"], "supermini_meters_per_pulse",
        0.01, 100)
    debounce = merged["supermini_debounce_us"]
    try:
        debounce_value = float(debounce)
    except (TypeError, ValueError):
        raise ValueError("supermini_debounce_us debe ser entero")
    if (not math.isfinite(debounce_value) or
            debounce_value != int(debounce_value) or
            not 0 <= debounce_value <= 1000000):
        raise ValueError("supermini_debounce_us debe estar entre 0 y 1000000")
    merged["supermini_debounce_us"] = int(debounce_value)
    merged["supermini_max_speed_kmh"] = _valid_number(
        merged["supermini_max_speed_kmh"], "supermini_max_speed_kmh", 1, 200)
    revision = merged["supermini_config_revision"]
    try:
        revision_value = float(revision)
    except (TypeError, ValueError):
        raise ValueError("supermini_config_revision debe ser entero")
    if (not math.isfinite(revision_value) or
            revision_value != int(revision_value) or
            not 1 <= revision_value <= 0xFFFFFFFF):
        raise ValueError("supermini_config_revision fuera de rango")
    if distance_migrated:
        revision_value += 1
        if revision_value > 0xFFFFFFFF:
            revision_value = 1
    merged["supermini_config_revision"] = int(revision_value)
    merged["precharge_wh"] = _valid_number(
        merged.get("precharge_wh", 0.0), "precharge_wh", 0, 5000)
    return merged


class T190Settings:
    def __init__(self, path=SETTINGS_FILE, load_existing=True):
        self.path = path
        self.temp_path = path + ".tmp"
        self.backup_path = path + ".bak"
        self.values = dict(DEFAULTS)
        self._dirty = False
        self._loaded_from_backup = False
        self._last_save_ms = time.ticks_ms()
        if load_existing:
            self.load()

    def load(self):
        primary_error = None
        for path in (self.path, self.backup_path):
            try:
                with open(path, "r") as file:
                    data = ujson.loads(file.read())
            except OSError:
                continue
            except (TypeError, ValueError) as exc:
                if path == self.path:
                    primary_error = exc
                    continue
                raise ValueError("configuración T190 inválida: {}".format(exc))
            try:
                self.values = _validated_values(data)
            except (TypeError, ValueError) as exc:
                if path == self.path:
                    primary_error = exc
                    continue
                raise ValueError(
                    "configuración T190 inválida: {}".format(exc))
            self._loaded_from_backup = path == self.backup_path
            self._last_save_ms = time.ticks_ms()
            return
        if primary_error is not None:
            raise ValueError(
                "configuración T190 inválida: {}".format(primary_error))
        self.values = dict(DEFAULTS)
        self._loaded_from_backup = False

    def _persist(self):
        with open(self.temp_path, "w") as file:
            file.write(ujson.dumps(self.values))
            file.flush()
        sync = getattr(uos, "sync", None)
        if callable(sync):
            sync()

        if self._loaded_from_backup:
            try:
                uos.remove(self.path)
            except OSError:
                pass
            uos.rename(self.temp_path, self.path)
            self._loaded_from_backup = False
            self._dirty = False
            self._last_save_ms = time.ticks_ms()
            return

        try:
            uos.remove(self.backup_path)
        except OSError:
            pass
        try:
            uos.rename(self.path, self.backup_path)
        except OSError:
            pass
        try:
            uos.rename(self.temp_path, self.path)
        except Exception:
            try:
                uos.rename(self.backup_path, self.path)
            except OSError:
                pass
            raise
        try:
            uos.remove(self.backup_path)
        except OSError:
            pass
        self._dirty = False
        self._loaded_from_backup = False
        self._last_save_ms = time.ticks_ms()

    def save(self):
        self._persist()

    @property
    def b_supermini_factors_milli(self):
        return list(self.values["b_supermini_factors_milli"])

    @property
    def ads_mode(self):
        return self.values.get("ads_mode", "cumulative")

    @property
    def battery_capacity_wh(self):
        return self.values["battery_capacity_wh"]

    @property
    def idle_sleep_timeout_min(self):
        return self.values["idle_sleep_timeout_min"]

    @property
    def supermini_meters_per_pulse(self):
        return self.values["supermini_meters_per_pulse"]

    @property
    def supermini_debounce_us(self):
        return self.values["supermini_debounce_us"]

    @property
    def supermini_max_speed_kmh(self):
        return self.values["supermini_max_speed_kmh"]

    @property
    def supermini_config_revision(self):
        return self.values["supermini_config_revision"]

    @property
    def battery_used_wh(self):
        return self.values["battery_used_wh"]

    @property
    def energy_baseline_set(self):
        return self.values["energy_baseline_set"]

    @property
    def trip_distance_m(self):
        return self.values["trip_distance_m"]

    @property
    def battery_remaining_wh(self):
        if not self.energy_baseline_set or self.battery_capacity_wh <= 0:
            return None
        return max(0.0, self.battery_capacity_wh - self.battery_used_wh)

    @property
    def battery_percent(self):
        remaining = self.battery_remaining_wh
        if remaining is None:
            return None
        percent = remaining * 100.0 / self.battery_capacity_wh
        return max(0, min(100, int(percent + 0.5)))

    @property
    def precharge_wh(self):
        return self.values.get("precharge_wh", 0.0)

    def update_configuration(self, b_supermini_factors_milli, ads_mode,
                             battery_capacity_wh, meters_per_pulse,
                             debounce_us, max_speed_kmh,
                             idle_sleep_timeout_min,
                             mark_charged=False, source_boot=None,
                             source_wh=None, precharge_wh=0.0):
        new_factors = _validated_factors(
            b_supermini_factors_milli, "factores de tensión Super Mini")
        if ads_mode not in ("cumulative", "individual"):
            raise ValueError("ads_mode debe ser 'cumulative' o 'individual'")
        capacity = _valid_number(
            battery_capacity_wh, "capacidad del pack", 0, 200000)
        meters_per_pulse = _valid_number(
            meters_per_pulse, "metros por pulso", 0.01, 100)
        debounce_value = _valid_number(
            debounce_us, "anti-rebote", 0, 1000000)
        if debounce_value != int(debounce_value):
            raise ValueError("anti-rebote debe ser entero")
        max_speed = _valid_number(
            max_speed_kmh, "velocidad máxima", 1, 200)
        sleep_value = _valid_number(
            idle_sleep_timeout_min, "tiempo para deep sleep", 0, 240)
        if sleep_value != int(sleep_value):
            raise ValueError("tiempo para deep sleep debe ser entero")

        supermini_changed = (
            meters_per_pulse != self.supermini_meters_per_pulse or
            int(debounce_value) != self.supermini_debounce_us or
            max_speed != self.supermini_max_speed_kmh or
            new_factors != self.b_supermini_factors_milli or
            ads_mode != self.ads_mode)
        self.values["b_supermini_factors_milli"] = new_factors
        self.values["ads_mode"] = ads_mode
        self.values["battery_capacity_wh"] = capacity
        self.values["battery_capacity_configured"] = True
        self.values["supermini_meters_per_pulse"] = meters_per_pulse
        self.values["supermini_distance_configured"] = True
        self.values["supermini_debounce_us"] = int(debounce_value)
        self.values["supermini_max_speed_kmh"] = max_speed
        self.values["idle_sleep_timeout_min"] = int(sleep_value)
        if supermini_changed:
            revision = self.supermini_config_revision + 1
            self.values["supermini_config_revision"] = (
                1 if revision > 0xFFFFFFFF else revision)
        if mark_charged:
            self.values["battery_used_wh"] = 0.0
            self.values["energy_baseline_set"] = True
            self.values["energy_source_boot"] = source_boot
            self.values["energy_source_wh"] = source_wh
        self.values["precharge_wh"] = _valid_number(
            precharge_wh, "Wh de precarga", 0, 5000)
        self._persist()

    def mark_pack_charged(self, source_boot=None, source_wh=None):
        self.values["battery_used_wh"] = 0.0
        self.values["energy_baseline_set"] = True
        self.values["energy_source_boot"] = source_boot
        self.values["energy_source_wh"] = source_wh
        self._persist()

    def reset_trip_distance(self, source_boot=None, source_dist_m=None):
        self.values["trip_distance_m"] = 0.0
        self.values["distance_baseline_set"] = True
        self.values["distance_source_boot"] = source_boot
        self.values["distance_source_m"] = source_dist_m
        self._persist()

    def note_source_distance(self, source_boot, source_dist_m):
        """Igual patron que note_source_energy: el Super Mini manda su
        odometro de vida entera (sobrevive sus propios reboots via
        trip_store.py); aca se suma solo el delta desde el ultimo dato
        visto, asi un reset_trip_distance() local no necesita que el
        Super Mini sepa nada de "viajes"."""
        if source_boot is None or source_dist_m is None:
            return
        source_dist_m = _valid_number(
            source_dist_m, "distancia recibida", 0, 100000000)
        previous_boot = self.values["distance_source_boot"]
        previous_dist_m = self.values["distance_source_m"]
        if (self.values["distance_baseline_set"] and
                previous_boot == source_boot and
                previous_dist_m is not None and
                source_dist_m >= previous_dist_m):
            delta_m = source_dist_m - previous_dist_m
            self.values["trip_distance_m"] += delta_m
            self._dirty = self._dirty or delta_m > 0
        self.values["distance_source_boot"] = source_boot
        self.values["distance_source_m"] = source_dist_m

        now = time.ticks_ms()
        if (self._dirty and time.ticks_diff(
                now, self._last_save_ms) >= ENERGY_SAVE_INTERVAL_MS):
            self._persist()

    def note_source_energy(self, source_boot, source_wh, pack_voltage_ratio):
        if source_boot is None or source_wh is None:
            return
        source_wh = _valid_number(source_wh, "energía recibida", 0, 10000000)
        previous_boot = self.values["energy_source_boot"]
        previous_wh = self.values["energy_source_wh"]
        if (self.energy_baseline_set and previous_boot == source_boot and
                previous_wh is not None and source_wh >= previous_wh):
            delta_wh = source_wh - previous_wh
            self.values["battery_used_wh"] += (
                delta_wh * pack_voltage_ratio)
            self._dirty = self._dirty or delta_wh > 0
        self.values["energy_source_boot"] = source_boot
        self.values["energy_source_wh"] = source_wh

        now = time.ticks_ms()
        if (self._dirty and time.ticks_diff(
                now, self._last_save_ms) >= ENERGY_SAVE_INTERVAL_MS):
            self._persist()
