"""Async I/O utilities for the SX1262 LoRa transceiver.

The helpers defined here only deal with radio interaction: creating the
``SX1262`` object, waiting on IRQ lines, and running non-blocking TX/RX loops.
Higher-level application choices (payload formatting, logging, etc.) live in
``mainApp``. Three ready-made presets are exposed via
``PRESET_LONG_DISTANCE``, ``PRESET_TRADEOFF`` and ``PRESET_FAST`` (long distance
is selected by default).

Example:
    >>> import loraDriver
    >>> radio = loraDriver.configure_radio(loraDriver.make_radio())
    >>> # Use ``tx_loop`` or ``rx_loop`` from an asyncio task
"""

import sys

# Driver moved to /lib, so it should be in sys.path by default
try:
    from sx1262 import SX1262
except ImportError:
    # Fallback for older structure
    _SX126X_LIB_PATH = 'micropySX126X/lib'
    if _SX126X_LIB_PATH not in sys.path:
        sys.path.append(_SX126X_LIB_PATH)
    from micropySX126X.lib.sx1262 import SX1262

from machine import Pin

try:
    import uasyncio as asyncio
except ImportError:
    import asyncio  # type: ignore

try:
    _wait_for_ms_impl = asyncio.wait_for_ms  # type: ignore[attr-defined]
except AttributeError:  # pragma: no cover - desktop lint fallback
    async def _wait_for_ms_impl(awaitable, timeout_ms):
        await asyncio.wait_for(awaitable, timeout_ms / 1000)

try:
    from _sx126x import (  # type: ignore[attr-defined]
        SX126X_IRQ_TX_DONE,
        SX126X_IRQ_RX_DONE,
        SX126X_IRQ_TIMEOUT,
        SX126X_IRQ_CRC_ERR,
        SX126X_IRQ_HEADER_ERR,
    )
except ImportError:  # pragma: no cover - desktop lint fallback
    SX126X_IRQ_TX_DONE = 0x0200
    SX126X_IRQ_RX_DONE = 0x0400
    SX126X_IRQ_TIMEOUT = 0x0100
    SX126X_IRQ_CRC_ERR = 0x2000
    SX126X_IRQ_HEADER_ERR = 0x1000

try:
    flag_factory = asyncio.ThreadSafeFlag  # type: ignore[attr-defined]
except AttributeError:  # pragma: no cover - CPython lint fallback
    class _StubFlag:
        def __init__(self):
            import threading
            self._event = threading.Event()

        def set(self):
            self._event.set()

        async def wait(self):
            while not self._event.is_set():
                await asyncio.sleep(0)
            self._event.clear()

    flag_factory = _StubFlag

import HW
import time

try:
    import deflate as _deflate_mod  # type: ignore
    _HAS_DEFLATE = True
except ImportError:  # pragma: no cover - deflate unavailable
    _deflate_mod = None  # type: ignore
    _HAS_DEFLATE = False

try:
    import uzlib as _decompress_mod  # type: ignore
except ImportError:
    try:
        import zlib as _decompress_mod  # type: ignore
    except ImportError:  # pragma: no cover - no fallback decompressor
        _decompress_mod = None  # type: ignore

try:
    import io as _io
except ImportError:  # pragma: no cover - MicroPython naming
    import uio as _io  # type: ignore

PRESET_LONG_DISTANCE = 'long_distance'
PRESET_TRADEOFF = 'tradeoff'
PRESET_FAST = 'fast'

_AVAILABLE_PRESETS = getattr(HW, 'LORA_PRESETS', {})
_DEFAULT_PRESET = getattr(HW, 'LORA_DEFAULT_PRESET', PRESET_LONG_DISTANCE)

try:
    _ticks_ms = time.ticks_ms  # type: ignore[attr-defined]
    _ticks_add = time.ticks_add  # type: ignore[attr-defined]
    _ticks_diff = time.ticks_diff  # type: ignore[attr-defined]
except AttributeError:  # pragma: no cover - desktop lint fallback
    def _ticks_ms():
        return int(time.time() * 1000)

    def _ticks_add(ticks, delta):
        return ticks + delta

    def _ticks_diff(a, b):
        return a - b

ERR_NONE = 0
ERR_RX_TIMEOUT = -6
_irq_flag = None
_dio1_pin = None


def _attach_irq():
    global _irq_flag, _dio1_pin
    if _dio1_pin is not None:
        _dio1_pin.irq(handler=None)
    _irq_flag = flag_factory()

    def _handler(_):
        try:
            _irq_flag.set()
        except Exception:
            pass

    _dio1_pin = Pin(HW.LORA_DIO1_PIN_ID, Pin.IN)
    _dio1_pin.irq(trigger=Pin.IRQ_RISING, handler=_handler)


def _detach_irq():
    global _dio1_pin, _irq_flag
    if _dio1_pin is not None:
        try:
            _dio1_pin.irq(handler=None)
        except Exception:
            pass
    _dio1_pin = None
    _irq_flag = None


def make_radio():
    """Create an ``SX1262`` driver wired to the Xiao/Wio pinout.

    Example:
        >>> radio = loraDriver.make_radio()
    """

    return SX1262(
        spi_bus=HW.LORA_SPI_ID,
        clk=HW.LORA_SCK_PIN_ID,
        mosi=HW.LORA_MOSI_PIN_ID,
        miso=HW.LORA_MISO_PIN_ID,
        cs=HW.LORA_CS_PIN_ID,
        irq=HW.LORA_DIO1_PIN_ID,
        rst=HW.LORA_RESET_PIN_ID,
        gpio=HW.LORA_BUSY_PIN_ID,
    )


def _resolve_preset(preset):
    if preset is None:
        preset_name = _DEFAULT_PRESET
    elif isinstance(preset, str):
        preset_name = preset
    else:
        return dict(preset)
    try:
        return dict(_AVAILABLE_PRESETS[preset_name])
    except KeyError:
        if preset_name == PRESET_LONG_DISTANCE:
            return {
                'freq': HW.LORA_DEFAULT_FREQ,
                'bw': HW.LORA_DEFAULT_BW,
                'sf': HW.LORA_DEFAULT_SF,
                'cr': HW.LORA_DEFAULT_CR,
                'power': HW.LORA_DEFAULT_POWER,
                'syncWord': HW.LORA_DEFAULT_SYNC_WORD,
                'preambleLength': HW.LORA_DEFAULT_PREAMBLE_LEN,
                'currentLimit': HW.LORA_DEFAULT_CURRENT_LIMIT,
                'tcxoVoltage': HW.LORA_DEFAULT_TCXO_VOLTAGE,
                'useRegulatorLDO': HW.LORA_DEFAULT_USE_LDO,
                'blocking': HW.LORA_DEFAULT_BLOCKING,
            }
        raise ValueError('Unknown LoRa preset: {}'.format(preset_name))


def _apply_setting(settings, key, value, default):
    if value is not None:
        settings[key] = value
    elif key not in settings:
        settings[key] = default


def configure_radio(
    radio,
    *,
    preset=None,
    freq=None,
    bw=None,
    sf=None,
    cr=None,
    power=None,
    blocking=None,
    preamble_len=None,
    sync_word=None,
    current_limit=None,
    tcxo_voltage=None,
    use_regulator_ldo=None,
):
    """Initialize the radio using a named preset, with optional overrides.

    Example:
        >>> radio = loraDriver.configure_radio(loraDriver.make_radio(), preset=loraDriver.PRESET_FAST)
    """

    settings = _resolve_preset(preset)
    _apply_setting(settings, 'freq', freq, HW.LORA_DEFAULT_FREQ)
    _apply_setting(settings, 'bw', bw, HW.LORA_DEFAULT_BW)
    _apply_setting(settings, 'sf', sf, HW.LORA_DEFAULT_SF)
    _apply_setting(settings, 'cr', cr, HW.LORA_DEFAULT_CR)
    _apply_setting(settings, 'power', power, HW.LORA_DEFAULT_POWER)
    _apply_setting(settings, 'blocking', blocking, HW.LORA_DEFAULT_BLOCKING)
    _apply_setting(settings, 'preambleLength', preamble_len, HW.LORA_DEFAULT_PREAMBLE_LEN)
    _apply_setting(settings, 'syncWord', sync_word, HW.LORA_DEFAULT_SYNC_WORD)
    _apply_setting(settings, 'currentLimit', current_limit, HW.LORA_DEFAULT_CURRENT_LIMIT)
    _apply_setting(settings, 'tcxoVoltage', tcxo_voltage, HW.LORA_DEFAULT_TCXO_VOLTAGE)
    _apply_setting(settings, 'useRegulatorLDO', use_regulator_ldo, HW.LORA_DEFAULT_USE_LDO)

    status = radio.begin(
        freq=settings['freq'],
        bw=settings['bw'],
        sf=settings['sf'],
        cr=settings['cr'],
        syncWord=settings['syncWord'],
        power=settings['power'],
        currentLimit=settings['currentLimit'],
        preambleLength=settings['preambleLength'],
        tcxoVoltage=settings['tcxoVoltage'],
        useRegulatorLDO=settings['useRegulatorLDO'],
        blocking=settings['blocking'],
    )
    if status != ERR_NONE:
        raise RuntimeError('SX1262.begin failed: {}'.format(status))
    # Keep DIO2 as input for boards that route the RF switch to it.
    Pin(HW.LORA_DIO2_PIN_ID, Pin.IN)
    _attach_irq()
    try:
        radio.clearIrqStatus()
    except Exception:
        pass
    return radio


async def _wait_for_irq(radio, *, timeout_ms=None):
    global _irq_flag
    if _irq_flag is None:
        if timeout_ms is not None:
            await asyncio.sleep_ms(timeout_ms)
            return 0
        await asyncio.sleep_ms(0)
        return 0
    if timeout_ms is None:
        await _irq_flag.wait()
    else:
        deadline = _ticks_add(_ticks_ms(), timeout_ms)
        while True:
            remaining = _ticks_diff(deadline, _ticks_ms())
            if remaining <= 0:
                return 0
            try:
                await _wait_for_ms_impl(_irq_flag.wait(), remaining)
                break
            except asyncio.TimeoutError:
                return 0
    irq = radio.getIrqStatus()
    if irq:
        radio.clearIrqStatus(irq)
    return irq


def _normalize_payload(payload):
    meta = None
    raw = payload
    if callable(payload):
        result = payload()
        if isinstance(result, tuple) and len(result) == 2:
            raw, meta = result
        else:
            raw = result
    if isinstance(raw, bytearray):
        raw = bytes(raw)
    if not isinstance(raw, (bytes, bytearray)):
        raise TypeError('LoRa payload must be bytes-like, got {!r}'.format(type(raw)))
    return raw, meta


async def tx_loop(
    radio,
    *,
    interval_s,
    payload,
    tx_timeout_ms=None,
    on_sent=None,
):
    """Continuously transmit frames with non-blocking IRQ handling.

    The ``payload`` parameter accepts either bytes or a callable returning
    ``bytes`` (optionally ``(bytes, meta)``). ``on_sent`` is notified after each
    send with a dictionary that always contains ``payload``, ``length`` and
    ``status`` keys. ``tx_timeout_ms`` defines how long to wait for the
    ``TX_DONE`` IRQ before reporting a ``timeout`` error.

    Example:
        >>> await loraDriver.tx_loop(radio, interval_s=5, payload=b"PING")
    """

    try:
        while True:
            radio.clearIrqStatus()
            raw_payload, meta = _normalize_payload(payload)
            length, status = radio.send(raw_payload)
            info = {
                'payload': raw_payload,
                'length': length,
                'status': status,
                'meta': meta,
            }
            if status == ERR_NONE:
                irq = await _wait_for_irq(radio, timeout_ms=tx_timeout_ms)
                info['irq'] = irq
                if irq:
                    if not (irq & SX126X_IRQ_TX_DONE):
                        info['error'] = 'unexpected_irq'
                elif tx_timeout_ms is not None:
                    info['error'] = 'timeout'
            else:
                info['error'] = 'send_failed'
            if on_sent is not None:
                try:
                    on_sent(info)
                except Exception:
                    pass
            await asyncio.sleep(interval_s)
    finally:
        try:
            radio.standby()
        except Exception:
            pass


async def rx_loop(
    radio,
    *,
    timeout_ms=None,
    message_parser=None,
    on_message=None,
    on_timeout=None,
    on_error=None,
):
    """Await incoming frames and deliver them through callbacks.

    ``on_message`` recibe un diccionario con ``data``, ``irq``, ``status`` y
    un valor opcional ``meta`` retornado por ``message_parser``. Set
    ``on_timeout`` para ser notificado cuando expire la espera configurada, y
    ``on_error`` para manejar condiciones de error CRC u otros IRQ.
    """

    import binascii
    try:
        try:
            radio.setBlockingCallback(False)
        except Exception:
            pass
        while True:
            irq = await _wait_for_irq(radio, timeout_ms=timeout_ms)
            if irq == 0:
                if timeout_ms is not None and on_timeout is not None:
                    try:
                        on_timeout()
                    except Exception:
                        pass
                continue
            if irq & SX126X_IRQ_RX_DONE:
                data, status = radio.recv()
                # Log hexadecimal del payload crudo
                print('[rx] RAW payload:', binascii.hexlify(data))
                info = {'data': data, 'status': status, 'irq': irq}
                if status == ERR_NONE and data:
                    meta = message_parser(data) if message_parser else None
                    if meta is not None:
                        info['meta'] = meta
                    if on_message is not None:
                        try:
                            on_message(info)
                        except Exception:
                            pass
                else:
                    if on_error is not None:
                        info['error'] = 'recv_failed'
                        try:
                            on_error(info)
                        except Exception:
                            pass
            elif irq & SX126X_IRQ_TIMEOUT:
                if on_error is not None:
                    try:
                        on_error({'error': 'radio_timeout', 'irq': irq})
                    except Exception:
                        pass
            elif irq & SX126X_IRQ_CRC_ERR:
                if on_error is not None:
                    try:
                        on_error({'error': 'crc', 'irq': irq})
                    except Exception:
                        pass
            elif irq & SX126X_IRQ_HEADER_ERR:
                if on_error is not None:
                    try:
                        on_error({'error': 'header', 'irq': irq})
                    except Exception:
                        pass
            else:
                if on_error is not None:
                    try:
                        on_error({'error': 'unknown_irq', 'irq': irq})
                    except Exception:
                        pass
    finally:
        try:
            radio.standby()
        except Exception:
            pass


def standby_radio(radio):
    """Return the radio to standby mode and release IRQ resources."""

    try:
        radio.standby()
    except Exception:
        pass
    _detach_irq()


_MSG_SIZE = 14  # 2-byte id + 4-byte timestamp + 4-byte lat + 4-byte lon
_COORD_SCALE = 100_000  # 1e-5 degree increments (~1.1 m)

_FORMAT_CODES = {
    'plain': 0,
    'packed': 1,
}
_FORMAT_NAMES = {value: key for key, value in _FORMAT_CODES.items()}
_FLAG_COMPRESSED = 0x10
_FLAG_CHECKSUM = 0x20
_HEADER_BASE = 0x40  # ensures header != legacy 14-byte payload


def _pack_u16(value, target, offset):
    target[offset] = value & 0xFF
    target[offset + 1] = (value >> 8) & 0xFF


def _pack_u32(value, target, offset):
    masked = value & 0xFFFFFFFF
    for idx in range(4):
        target[offset + idx] = (masked >> (8 * idx)) & 0xFF


def _pack_i32(value, target, offset):
    _pack_u32(value & 0xFFFFFFFF, target, offset)


def _unpack_u16(source, offset):
    return source[offset] | (source[offset + 1] << 8)


def _unpack_u32(source, offset):
    return (
        source[offset]
        | (source[offset + 1] << 8)
        | (source[offset + 2] << 16)
        | (source[offset + 3] << 24)
    )


def _unpack_i32(source, offset):
    unsigned = _unpack_u32(source, offset)
    if unsigned & 0x80000000:
        unsigned -= 0x100000000
    return unsigned


def _unpack_u32_be(source, offset):
    value = 0
    for idx in range(4):
        value = (value << 8) | source[offset + idx]
    return value


def _unpack_i32_be(source, offset):
    unsigned = _unpack_u32_be(source, offset)
    if unsigned & 0x80000000:
        unsigned -= 0x100000000
    return unsigned


def _normalize_coord(raw_value):
    value = raw_value / _COORD_SCALE
    adjustment = 1
    while abs(value) > 180 and adjustment < 1000:
        value /= 10
        adjustment *= 10
    return value, adjustment


def _encode_packed(meta):
    device_part = int(meta.get('device_id', 0)) & 0xFFFF
    stamp_part = int(meta.get('timestamp_min', 0)) & 0xFFFFFFFF
    lat_part = int(round(meta.get('lat', 0.0) * _COORD_SCALE))
    lon_part = int(round(meta.get('lon', 0.0) * _COORD_SCALE))

    payload = bytearray(_MSG_SIZE)
    _pack_u16(device_part, payload, 0)
    _pack_u32(stamp_part, payload, 2)
    _pack_i32(lat_part, payload, 6)
    _pack_i32(lon_part, payload, 10)
    return bytes(payload)


def _decode_packed(payload):
    if len(payload) != _MSG_SIZE:
        return {
            'error': 'length',
            'expected': _MSG_SIZE,
            'actual': len(payload),
        }
    device_id = _unpack_u16(payload, 0)
    timestamp_raw = _unpack_u32(payload, 2)
    lat_raw = _unpack_i32(payload, 6)
    lon_raw = _unpack_i32(payload, 10)
    lat, lat_adjust = _normalize_coord(lat_raw)
    lon, lon_adjust = _normalize_coord(lon_raw)
    meta = {
        'device_id': device_id,
        'timestamp_min': timestamp_raw,
        'lat': lat,
        'lon': lon,
    }
    if lat_adjust > 1:
        meta['lat_correction'] = lat_adjust
    if lon_adjust > 1:
        meta['lon_correction'] = lon_adjust
    if abs(lat) > 180 or abs(lon) > 180:
        lat_be_raw = _unpack_i32_be(payload, 6)
        lon_be_raw = _unpack_i32_be(payload, 10)
        lat_be, lat_be_adj = _normalize_coord(lat_be_raw)
        lon_be, lon_be_adj = _normalize_coord(lon_be_raw)
        if abs(lat_be) <= 180 and abs(lon_be) <= 180:
            meta['lat'] = lat_be
            meta['lon'] = lon_be
            meta['format_hint'] = 'big'
            if lat_be_adj > 1:
                meta['lat_correction'] = lat_be_adj
            if lon_be_adj > 1:
                meta['lon_correction'] = lon_be_adj
        else:
            meta['lat_raw'] = lat_raw
            meta['lon_raw'] = lon_raw
    return meta


def _encode_plain(meta):
    device_part = int(meta.get('device_id', 0)) & 0xFFFF
    timestamp = int(meta.get('timestamp_min', 0))
    lat = float(meta.get('lat', 0.0))
    lon = float(meta.get('lon', 0.0))
    text = '{:04X}|{}|{:.5f}|{:.5f}'.format(device_part, timestamp, lat, lon)
    return text.encode('ascii')


def _decode_plain(payload):
    try:
        text = payload.decode('ascii').strip()
    except Exception:
        return {'error': 'plain_decode'}
    if not text:
        return {'error': 'plain_empty'}
    parts = text.split('|')
    if len(parts) != 4:
        parts = text.split(',')
    if len(parts) != 4:
        return {'error': 'plain_format', 'raw': text}
    try:
        device_id = int(parts[0], 16)
        timestamp = int(parts[1])
        lat = float(parts[2])
        lon = float(parts[3])
    except Exception:
        return {'error': 'plain_parse', 'raw': text}
    return {
        'device_id': device_id & 0xFFFF,
        'timestamp_min': timestamp,
        'lat': lat,
        'lon': lon,
    }


def _crc16(data, initial=0xFFFF, poly=0x1021):
    crc = initial
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            if crc & 0x8000:
                crc = ((crc << 1) ^ poly) & 0xFFFF
            else:
                crc = (crc << 1) & 0xFFFF
    return crc & 0xFFFF


def _compress_data(data):
    if _HAS_DEFLATE and _deflate_mod is not None:
        buf = _io.BytesIO()
        try:
            stream = _deflate_mod.DeflateIO(buf, _deflate_mod.RAW, 8)  # type: ignore[attr-defined]
            if not hasattr(stream, 'write'):
                stream.close()
                raise RuntimeError('deflate_compress_unsupported')
            try:
                stream.write(data)
            finally:
                stream.close()
            return buf.getvalue()
        except Exception as exc:
            raise RuntimeError('deflate_compress_failed: {}'.format(exc))
    raise RuntimeError('Compression not available on this firmware')


def _decompress_data(data):
    last_exc = None
    if _HAS_DEFLATE and _deflate_mod is not None:
        try:
            buf = _io.BytesIO(data)
            stream = _deflate_mod.DeflateIO(buf, _deflate_mod.RAW, 8)  # type: ignore[attr-defined]
            try:
                return stream.read()
            finally:
                stream.close()
        except Exception as exc:
            last_exc = exc
    if _decompress_mod is not None:
        try:
            return _decompress_mod.decompress(data)  # type: ignore[attr-defined]
        except TypeError:
            return _decompress_mod.decompress(data, 0)  # type: ignore[attr-defined]
        except Exception as exc:
            last_exc = exc
    if last_exc is None:
        raise RuntimeError('Compression not available on this firmware')
    raise last_exc


def encode_payload(
    meta,
    *,
    mode='packed',
    compression=False,
    checksum=False,
):
    mode = (mode or 'packed').lower()
    if mode in ('legacy', 'legacy_raw', 'raw'):
        if compression or checksum:
            raise ValueError('legacy_raw mode does not support compression or checksum')
        return _encode_packed(meta)
    if mode not in _FORMAT_CODES:
        raise ValueError('Unsupported payload mode: {}'.format(mode))
    if mode == 'packed':
        raw_body = _encode_packed(meta)
    else:
        raw_body = _encode_plain(meta)
    header = _HEADER_BASE | _FORMAT_CODES[mode]
    body = raw_body
    if compression:
        body = _compress_data(raw_body)
        header |= _FLAG_COMPRESSED
    if checksum:
        crc = _crc16(raw_body)
        body = body + bytes((crc & 0xFF, (crc >> 8) & 0xFF))
        header |= _FLAG_CHECKSUM
    return bytes((header,)) + body


def decode_payload(payload, *, mode='auto'):
    if not payload:
        return None
    if mode in ('legacy', 'legacy_raw', 'raw') or (mode == 'auto' and len(payload) == _MSG_SIZE):
        meta = _decode_packed(payload)
        if meta is None:
            return None
        meta.update({
            'mode': 'legacy_raw',
            'compressed': False,
            'checksum': False,
            'checksum_ok': True,
        })
        return meta
    header = payload[0]
    body = payload[1:]
    fmt_code = header & 0x0F
    compressed = bool(header & _FLAG_COMPRESSED)
    checksum_flag = bool(header & _FLAG_CHECKSUM)
    mode_name = _FORMAT_NAMES.get(fmt_code, 'unknown')
    if checksum_flag and len(body) < 2:
        return {
            'error': 'checksum_truncated',
            'mode': mode_name,
            'compressed': compressed,
            'checksum': True,
            'checksum_ok': False,
        }
    if checksum_flag:
        data_part, trailer = body[:-2], body[-2:]
        received_crc = trailer[0] | (trailer[1] << 8)
    else:
        data_part = body
        received_crc = None
    if compressed:
        try:
            decoded_body = _decompress_data(data_part)
        except Exception as exc:
            return {
                'error': 'decompress_failed',
                'mode': mode_name,
                'compressed': True,
                'checksum': checksum_flag,
                'checksum_ok': False,
                'exception': str(exc),
            }
    else:
        decoded_body = data_part
    if checksum_flag:
        computed_crc = _crc16(decoded_body)
        if received_crc != computed_crc:
            return {
                'error': 'checksum_mismatch',
                'mode': mode_name,
                'compressed': compressed,
                'checksum': True,
                'checksum_ok': False,
            }
    if mode_name == 'packed':
        meta = _decode_packed(decoded_body)
    elif mode_name == 'plain':
        meta = _decode_plain(decoded_body)
    else:
        return {
            'error': 'unknown_mode',
            'mode': mode_name,
        }
    if meta is None:
        return {
            'error': 'decode_failed',
            'mode': mode_name,
            'compressed': compressed,
            'checksum': checksum_flag,
            'checksum_ok': False if checksum_flag else True,
        }
    meta['mode'] = mode_name
    meta['compressed'] = compressed
    meta['checksum'] = checksum_flag
    meta['checksum_ok'] = True
    return meta


def encode_lora_message(
    *,
    device_id,
    timestamp_min,
    lat,
    lon,
    mode='legacy_raw',
    compression=False,
    checksum=False,
):
    """Serialize telemetry according to the requested mode.

    ``mode='legacy_raw'`` keeps the historical 14-byte structure. Use
    ``mode='packed'`` or ``mode='plain'`` to include a small header that enables
    optional compression and checksum support.
    """

    meta = {
        'device_id': device_id,
        'timestamp_min': timestamp_min,
        'lat': lat,
        'lon': lon,
    }
    return encode_payload(meta, mode=mode, compression=compression, checksum=checksum)


def decode_lora_message(payload, *, mode='auto'):
    """Decode telemetry payloads produced by :func:`encode_lora_message`."""

    meta = decode_payload(payload, mode=mode)
    return meta


__all__ = [
    'ERR_NONE',
    'ERR_RX_TIMEOUT',
    'configure_radio',
    'make_radio',
    'rx_loop',
    'tx_loop',
    'standby_radio',
    'encode_lora_message',
    'decode_lora_message',
    'encode_payload',
    'decode_payload',
    'PRESET_LONG_DISTANCE',
    'PRESET_TRADEOFF',
    'PRESET_FAST',
]
