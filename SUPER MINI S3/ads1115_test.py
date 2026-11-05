# ads1115_test.py — ESP32-S3 Super Mini: bring-up del ADC de tensiones ADS1115
#
# Prueba aislada del ADS1115 (I2C) -- voltaje individual B1..B4 y VBATS
# total, desde 4 tomas acumulativas. NO toca main.py (que sigue siendo el test de
# ADS1220 ya validado) -- se importa directo desde el REPL ya booteado:
#   >>> import ads1115_test
#   >>> ads1115_test.status()
#
# Mismo patron "REPL libre" que main.py: la lectura corre en un _thread
# aparte con asyncio adentro, asi el REPL queda libre mientras lee en
# background. Como este archivo nunca corre como script de boot (solo via
# `import`), no tiene el gotcha de re-ejecutarse al reimportar -- MicroPython
# lo cachea en sys.modules como cualquier modulo normal.

import _thread
import sys
import time
import uasyncio as asyncio

import HW
from drivers.ads1115 import ADS1115

INTERVAL_MS = 500

AUTO_START = True
_RUNNING = False
_STOP_REQUESTED = False
_BG_THREAD_STACK = 8192

_adc = None   # ADS1115, creado dentro del thread de fondo


class VoltState:
    def __init__(self):
        self.v_b1 = 0.0
        self.v_b2 = 0.0
        self.v_b3 = 0.0
        self.v_b4 = 0.0
        self.v_bats = 0.0
        self.adc_ok = False


_state = VoltState()


async def volt_task(interval_ms=INTERVAL_MS):
    st = _state
    ratio = HW.BATT_DIVIDER_RATIO
    was_ok = True   # para solo loguear la transicion OK->error, no cada ciclo
    while True:
        try:
            raw = _adc.read_all_volts()
            taps = [raw[index] * ratio[index] for index in range(4)]
            st.v_b1 = taps[0]
            st.v_b2 = taps[1] - taps[0]
            st.v_b3 = taps[2] - taps[1]
            st.v_b4 = taps[3] - taps[2]
            st.v_bats = st.v_b1 + st.v_b2 + st.v_b3 + st.v_b4
            st.adc_ok = True
            if not was_ok:
                print("[ads1115_test] lectura recuperada")
            was_ok = True
        except Exception as exc:
            st.adc_ok = False
            if was_ok:
                print("[ads1115_test] error de lectura:", exc, "(no se repite el log hasta que se recupere)")
            was_ok = False
        await asyncio.sleep_ms(interval_ms)


# ── Arranque asyncio (corre dentro del thread de fondo) ─────────────────────

async def _main_async():
    global _adc
    i2c = HW.make_i2c()
    _adc = ADS1115(i2c, addr=HW.ADS1115_ADDR)
    print("[ADS1115] OK")

    task = asyncio.create_task(volt_task())
    try:
        while not _STOP_REQUESTED:
            await asyncio.sleep_ms(200)
    finally:
        task.cancel()
        print("[ads1115_test] detenido")


def _bg():
    global _RUNNING, _STOP_REQUESTED
    try:
        asyncio.run(_main_async())
    except Exception as exc:
        print("[ads1115_test] error fatal en hilo de fondo:", exc)
        try:
            sys.print_exception(exc)
        except Exception:
            pass
    finally:
        _RUNNING = False
        _STOP_REQUESTED = False


def start():
    """Arranca la lectura del ADS1115 en un thread de fondo. No bloquea -> REPL libre."""
    global _RUNNING, _STOP_REQUESTED
    if _RUNNING:
        print("[ads1115_test] ya esta corriendo")
        return False
    _STOP_REQUESTED = False
    _RUNNING = True
    try:
        _thread.stack_size(_BG_THREAD_STACK)
    except Exception as exc:
        print("[ads1115_test] stack size error:", exc)
    _thread.start_new_thread(_bg, ())
    return True


def stop(wait_ms=0):
    """Pide detener la lectura. Con wait_ms>0 espera (bloqueante) a que termine."""
    global _STOP_REQUESTED
    if not _RUNNING:
        print("[ads1115_test] no esta corriendo")
        return False
    _STOP_REQUESTED = True
    remaining = int(wait_ms)
    while _RUNNING and remaining > 0:
        time.sleep_ms(10)
        remaining -= 10
    return True


def status():
    """Snapshot on-demand de las ultimas lecturas (llamar desde el REPL)."""
    st = _state
    print("[STATUS] B1={:.2f}V B2={:.2f}V B3={:.2f}V B4={:.2f}V "
          "VBATS={:.2f}V ADC_OK={}".format(
        st.v_b1, st.v_b2, st.v_b3, st.v_b4, st.v_bats, st.adc_ok,
    ))


if AUTO_START:
    start()
