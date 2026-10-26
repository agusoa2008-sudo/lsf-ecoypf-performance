"""Paddock receiver: LoRa telemetry + Wi-Fi dashboard, with a free REPL."""

import _thread
import sys
import time
import uasyncio as asyncio

import HW
import loraDriver
from telemetry import TelemetryState
from web_server import DashboardServer

AUTO_START = True
_BG_THREAD_STACK = 12288
_RUNNING = False
_STOP_REQUESTED = False
_state = None
_dashboard = None


def _on_message(info):
    try:
        _state.update(info["data"])
        print("[LoRa] RX #{}: {}".format(
            _state.rx_count, info["data"].decode("utf-8")))
        if _dashboard is not None:
            asyncio.create_task(_dashboard.broadcast())
    except (KeyError, UnicodeError, ValueError) as exc:
        _state.last_error = str(exc)
        print("[LoRa] paquete descartado:", exc)


def _on_radio_error(info):
    error = info.get("error")
    if error:
        _state.last_error = str(error)
        print("[LoRa] RX error:", error)


def _make_radio():
    radio = loraDriver.make_radio()
    loraDriver.configure_radio(radio, preset="tradeoff", blocking=False)
    return radio


async def _radio_task():
    while not _STOP_REQUESTED:
        radio = None
        try:
            radio = _make_radio()
            _state.radio_ok = True
            _state.radio_error = ""
            print("[LoRa] RX listo: {} MHz BW={} SF{} CR4/{} {} dBm SW=0x{:02X}".format(
                HW.LORA_DEFAULT_FREQ, HW.LORA_DEFAULT_BW,
                HW.LORA_DEFAULT_SF, HW.LORA_DEFAULT_CR,
                HW.LORA_DEFAULT_POWER,
                HW.LORA_DEFAULT_SYNC_WORD))
            await loraDriver.rx_loop(
                radio,
                timeout_ms=1000,
                on_message=_on_message,
                on_error=_on_radio_error,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            _state.radio_ok = False
            _state.radio_error = str(exc)
            print("[LoRa] inicialización/recepción falló:", exc)
            await asyncio.sleep(2)
        finally:
            if radio is not None:
                try:
                    radio.standby()
                except Exception as exc:
                    print("[LoRa] standby error:", exc)


async def _main_async():
    global _state, _dashboard
    _state = TelemetryState()
    _dashboard = DashboardServer(_state)
    await _dashboard.start()
    radio_task = asyncio.create_task(_radio_task())
    try:
        while not _STOP_REQUESTED:
            await asyncio.sleep_ms(200)
    finally:
        radio_task.cancel()
        try:
            await radio_task
        except asyncio.CancelledError:
            pass
        await _dashboard.stop()
        _dashboard = None


def _background():
    global _RUNNING, _STOP_REQUESTED
    try:
        asyncio.run(_main_async())
    except Exception as exc:
        print("[main] error fatal:", exc)
        try:
            sys.print_exception(exc)
        except AttributeError:
            pass
    finally:
        _RUNNING = False
        _STOP_REQUESTED = False


def start():
    """Start the app on a background thread; return immediately to the REPL."""
    global _RUNNING, _STOP_REQUESTED
    if _RUNNING:
        print("[main] ya está corriendo")
        return False
    _STOP_REQUESTED = False
    _RUNNING = True
    try:
        _thread.stack_size(_BG_THREAD_STACK)
    except (AttributeError, OSError) as exc:
        print("[main] no se pudo fijar el stack del hilo:", exc)
    try:
        _thread.start_new_thread(_background, ())
    except Exception as exc:
        _RUNNING = False
        print("[main] no se pudo crear el hilo:", exc)
        return False
    return True


def stop(wait_ms=0):
    """Request shutdown; optionally wait while the AP and radio are stopped."""
    global _STOP_REQUESTED
    if not _RUNNING:
        print("[main] no está corriendo")
        return False
    _STOP_REQUESTED = True
    remaining = int(wait_ms)
    while _RUNNING and remaining > 0:
        time.sleep_ms(10)
        remaining -= 10
    return True


def status():
    """Print the current LoRa and telemetry state from the REPL."""
    if _state is None:
        print("[main] todavía no inicializado")
        return
    print("[STATUS] radio={} error={!r} rx={} packet_age_ms={} source_age_ms={} "
          "seq={} adc_valid={} current_valid={} packet_error={!r} fields={}".format(
        _state.radio_ok, _state.radio_error, _state.rx_count,
        _state.packet_age_ms(), _state.source_age_ms(), _state.source_seq,
        _state.adc_valid, _state.current_valid, _state.last_error, _state.values))


if AUTO_START:
    start()
