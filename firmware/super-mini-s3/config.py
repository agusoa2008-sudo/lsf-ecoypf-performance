# config.py
# Carga config.json -- parametros de CALIBRACION/CONVERSION (lo que se
# ajusta a mano con multimetro/medicion real), separados de HW.py (que
# solo tiene pines/buses, fijos mientras no se recablee).
#
# Asi se puede tunear calibracion editando el JSON y llamando
# main.reload_config() en caliente, sin reflashear codigo.
#
# battery.tap_divider_ratio: el banco es un stack serie de 4 baterias con
# tomas ACUMULATIVAS (ver el esquema que paso el equipo):
#   A0 = B1          (tap0) -- R_top=43K
#   A1 = B2+B1       (tap1) -- R_top=87K (75K+12K -- con VDD=3.3V el canal
#                               quedaba al limite, ~99.8% de fondo de
#                               escala en reposo; ver conversacion)
#   A2 = B3+B2+B1    (tap2) -- R_top=143K
#   A3 = B4+B3+B2+B1 (tap3 = VBAT total del pack, ej. 56.0V) -- R_top=187K
#                               (175K+12K -- idem, quedaba al 91.7% en
#                               reposo sin margen para sobrecarga de carga)
# Las 4 R a masa (lado bajo de cada divisor) son 10K. ratio = (R_top +
# R_bottom) / R_bottom:
#   A0: (43+10)/10  = 5.3
#   A1: (87+10)/10  = 9.7
#   A2: (143+10)/10 = 15.3
#   A3: (187+10)/10 = 19.7
# V_tap_real[i] = V_adc_medido[i] * tap_divider_ratio[i]. Las tensiones de
# cada bateria individual salen de restar taps consecutivos ya escalados
# (ver main.py: SensorBoard.sensor_task); VBATS es la suma B1+B2+B3+B4,
# equivalente al tap3. Chequeo de sanidad con VDD=3.3V confirmado: tap3 a 56V da
# V_adc=56/19.7≈2.84V (86% de fondo de escala, incluso con 15% de
# sobrecarga de carga -64.4V- queda apenas debajo del techo); tap1 a 28V
# da V_adc=28/9.7≈2.89V (87%, mejoro desde el 99.8% con el R_top viejo de
# 75K). Igual conviene confirmar con multimetro contra el divisor real
# antes de confiar del todo -- ver HW.ADS1115_SAT_WARN_V para la deteccion
# de clipping en runtime.

import json
import math
import os

CONFIG_FILE = "config.json"
TEMP_FILE = "config.json.tmp"
BACKUP_FILE = "config.json.bak"

_DEFAULTS = {
    "speed": {
        "meters_per_pulse": 0.1,
        "debounce_us": 2000,
        "max_speed_kmh": 80.0,
    },
    "battery": {
        "tap_divider_ratio": [5.3, 9.7, 15.3, 19.7],
        "current_sens_v_per_a": 0.007813,
        "voltage_factor_milli": [1000, 1000, 1000, 1000],
        "ads_mode": "cumulative",
    },
    "sleep": {
        # Segundos con B4 ausente (GPIO11 bajo, ver HW.B4_PRESENCE_PIN)
        # antes de guardar los acumulados y entrar en deep sleep. 0 = nunca
        # dormir solo (util para pruebas de banco sin el auto).
        "b4_loss_timeout_s": 0,
    },
    "remote_config_id": 0,
}


def _merge(defaults, loaded):
    out = dict(defaults)
    for key, value in loaded.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out


def load():
    """Lee config.json y lo mergea sobre los defaults (asi un JSON
    incompleto no rompe nada -- solo pisa las claves que trae). Si falta
    el archivo o esta corrupto, cae a los defaults y avisa por print."""
    try:
        with open(CONFIG_FILE) as f:
            loaded = json.load(f)
        cfg = _merge(_DEFAULTS, loaded)
        _validate(cfg)
        return cfg
    except (OSError, ValueError, TypeError, KeyError) as exc:
        print("[config] no se pudo leer {} ({}) -- usando defaults".format(CONFIG_FILE, exc))
        cfg = _merge(_DEFAULTS, {})
        _validate(cfg)
        return cfg


def _validate(cfg):
    speed = cfg["speed"]
    battery = cfg["battery"]
    try:
        meters_per_pulse = float(speed["meters_per_pulse"])
        debounce_value = float(speed["debounce_us"])
        max_speed_kmh = float(speed["max_speed_kmh"])
    except (TypeError, ValueError, KeyError):
        raise ValueError("invalid speed settings")
    if (not math.isfinite(meters_per_pulse) or
            not math.isfinite(debounce_value) or
            not math.isfinite(max_speed_kmh) or
            not 0.01 <= meters_per_pulse <= 100 or
            not 0 <= debounce_value <= 1000000 or
            debounce_value != int(debounce_value) or
            not 1 <= max_speed_kmh <= 200):
        raise ValueError("speed settings out of range")
    speed["meters_per_pulse"] = meters_per_pulse
    speed["debounce_us"] = int(debounce_value)
    speed["max_speed_kmh"] = max_speed_kmh

    ratios = battery["tap_divider_ratio"]
    if not isinstance(ratios, (list, tuple)) or len(ratios) != 4:
        raise ValueError("tap_divider_ratio must contain four values")
    ratios = [float(value) for value in ratios]
    if any(not math.isfinite(value) or not 0 < value <= 100 for value in ratios):
        raise ValueError("tap_divider_ratio out of range")
    battery["tap_divider_ratio"] = ratios

    factors = battery.get("voltage_factor_milli", [1000] * 4)
    if not isinstance(factors, (list, tuple)) or len(factors) != 4:
        raise ValueError("voltage_factor_milli must contain four values")
    normalized = []
    for value in factors:
        number = float(value)
        if (not math.isfinite(number) or number != int(number) or
                not 800 <= number <= 1200):
            raise ValueError("voltage_factor_milli must be 800..1200")
        normalized.append(int(number))
    battery["voltage_factor_milli"] = normalized

    ads_mode = battery.get("ads_mode", "cumulative")
    if ads_mode not in ("cumulative", "individual"):
        raise ValueError("ads_mode must be 'cumulative' or 'individual'")
    battery["ads_mode"] = ads_mode

    sensitivity = float(battery["current_sens_v_per_a"])
    if not math.isfinite(sensitivity) or not 0 < sensitivity <= 1:
        raise ValueError("current_sens_v_per_a out of range")
    battery["current_sens_v_per_a"] = sensitivity

    sleep_cfg = cfg["sleep"]
    try:
        timeout_s = float(sleep_cfg["b4_loss_timeout_s"])
    except (TypeError, ValueError, KeyError):
        raise ValueError("invalid sleep settings")
    if not math.isfinite(timeout_s) or not 0 <= timeout_s <= 3600:
        raise ValueError("sleep.b4_loss_timeout_s out of range")
    sleep_cfg["b4_loss_timeout_s"] = timeout_s

    revision = float(cfg.get("remote_config_id", 0))
    if (not math.isfinite(revision) or revision != int(revision) or
            not 0 <= revision <= 0xFFFFFFFF):
        raise ValueError("remote_config_id out of range")
    cfg["remote_config_id"] = int(revision)


def apply_remote_configuration(revision, meters_per_pulse, debounce_us,
                               max_speed_kmh, voltage_factors_milli,
                               ads_mode="cumulative"):
    """Persist one validated T190 calibration update on the Super Mini."""
    try:
        revision = int(revision)
    except (TypeError, ValueError):
        raise ValueError("configuration revision must be an integer")
    if not 1 <= revision <= 0xFFFFFFFF:
        raise ValueError("configuration revision out of range")

    cfg = load()
    candidate = _merge(_DEFAULTS, cfg)
    candidate["speed"].update({
        "meters_per_pulse": meters_per_pulse,
        "debounce_us": debounce_us,
        "max_speed_kmh": max_speed_kmh,
    })
    candidate["battery"]["voltage_factor_milli"] = list(
        voltage_factors_milli)
    candidate["battery"]["ads_mode"] = ads_mode
    candidate["remote_config_id"] = revision
    _validate(candidate)

    current_id = cfg["remote_config_id"]
    if revision == current_id:
        if candidate == cfg:
            return False

    with open(TEMP_FILE, "w") as file:
        file.write(json.dumps(candidate))
        file.flush()
    sync = getattr(os, "sync", None)
    if callable(sync):
        sync()

    try:
        os.remove(BACKUP_FILE)
    except OSError:
        pass
    try:
        os.rename(CONFIG_FILE, BACKUP_FILE)
    except OSError:
        pass
    try:
        os.rename(TEMP_FILE, CONFIG_FILE)
    except Exception:
        try:
            os.rename(BACKUP_FILE, CONFIG_FILE)
        except OSError:
            pass
        raise
    try:
        os.remove(BACKUP_FILE)
    except OSError:
        pass
    return True
