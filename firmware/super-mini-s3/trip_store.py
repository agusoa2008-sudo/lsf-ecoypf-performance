# trip_store.py
# Persistencia de los acumulados de viaje (Wh, distancia) para que
# sobrevivan al deep sleep por perdida de B4 -- ver main.py:
# SensorBoard.power_task / _enter_deep_sleep. Mismo patron de escritura
# atomica que config.py (archivo temporal + backup + rename) para no
# corromper el dato si se corta la alimentacion a mitad de la escritura.

import json
import os

TRIP_FILE = "trip.json"
TEMP_FILE = "trip.json.tmp"
BACKUP_FILE = "trip.json.bak"

_DEFAULTS = {
    "wh_total": 0.0,
    "dist_m": 0.0,
}


def load():
    """Lee trip.json; si falta o esta corrupto, arranca en cero (sin
    acumulado previo -- primer boot o storage vacio)."""
    try:
        with open(TRIP_FILE) as f:
            loaded = json.load(f)
        return {
            "wh_total": float(loaded.get("wh_total", 0.0)),
            "dist_m": float(loaded.get("dist_m", 0.0)),
        }
    except (OSError, ValueError, TypeError, AttributeError):
        return dict(_DEFAULTS)


def save(wh_total, dist_m):
    """Escritura atomica de los acumulados -- llamar justo antes de
    machine.deepsleep() (ver main.py: _enter_deep_sleep)."""
    data = {"wh_total": float(wh_total), "dist_m": float(dist_m)}
    with open(TEMP_FILE, "w") as f:
        f.write(json.dumps(data))
        f.flush()
    sync = getattr(os, "sync", None)
    if callable(sync):
        sync()

    try:
        os.remove(BACKUP_FILE)
    except OSError:
        pass
    try:
        os.rename(TRIP_FILE, BACKUP_FILE)
    except OSError:
        pass
    try:
        os.rename(TEMP_FILE, TRIP_FILE)
    except Exception:
        try:
            os.rename(BACKUP_FILE, TRIP_FILE)
        except OSError:
            pass
        raise
    try:
        os.remove(BACKUP_FILE)
    except OSError:
        pass
