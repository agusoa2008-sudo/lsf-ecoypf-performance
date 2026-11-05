
# main.py — ESP32 IdeaSpark wheel display: receptor ESP-NOW del T190
#
# Rol: escuchar PAIR_REQ del T190, contestar PAIR_ACK, guardar la MAC
# emparejada, parsear cada linea de telemetria "TLM:..." y mostrarla igual
# que el display del T190 -- un valor grande a la vez (fuente 7 segmentos),
# ciclado con el boton BOOT (HW.PAGE_BTN_PIN, GPIO0):
#   - pulsacion CORTA  -> siguiente campo (misma tabla FIELDS que New T190)
#   - pulsacion LARGA  -> pantalla de debug (estado ESP-NOW, pps, variables
#     crudas) / otra larga vuelve a la pantalla de campos
#
# Patron "REPL libre" (igual que New T190/main.py): toda la app corre en
# un _thread aparte. Al bootear, main.py arranca el hilo y retorna enseguida
# -- la consola queda disponible con `import main` para llamar
# main.status() / main.stop() / main.start() / main.repair() /
# main.next_field() / main.prev_field() / main.toggle_debug().

import _thread
import sys
import time
import machine
import uasyncio as asyncio
from machine import Pin, SPI

import HW
from drivers.tft170 import TFT170, rgb565
from espnow_link import EspNowLink, mac_str
from buttons import PageButton
import seven_seg
from fonts import seven_segment_80 as SEG80
from fonts import seven_segment_40 as SEG40
from fonts import seven_segment_24 as SEG24

BLACK = 0x0000
WHITE = 0xFFFF
GRAY  = rgb565(140, 140, 140)
GREEN = rgb565(40, 200, 40)
RED   = rgb565(220, 40, 40)

# ── Campos mostrados en pantalla, en el orden en que cicla el boton BOOT ────
# (label largo, codigo font40, unidad font24, formato, clave en el payload TLM)
# Las claves son las mismas que arma New T190/telemetry.py:_build_payload().
FIELDS = [
    ("I BAT",       "I",   "A",     "{:.2f}", "I"),
    ("V B1",        "B1",  "V",     "{:.2f}", "B1"),
    ("V B2",        "B2",  "V",     "{:.2f}", "B2"),
    ("V B3",        "B3",  "V",     "{:.2f}", "B3"),
    ("V B4 = VBAT", "B4",  "V",     "{:.2f}", "B4"),
    ("P INST",      "PI",  "W",     "{:.0f}", "P"),
    ("P AVG 5s",    "PA",  "W",     "{:.0f}", "PA"),
    ("VELOCIDAD",   "SPD", "km/h",  "{:.1f}", "V"),
    ("DISTANCIA",   "DST", "m",     "{:.0f}", "D"),
    ("Wh/km INST",  "WI",  "Wh/km", "{:.1f}", "WI"),
    ("Wh/km AVG",   "WA",  "Wh/km", "{:.1f}", "WA"),
    ("Wh TOTAL",    "WT",  "Wh",    "{:.1f}", "WT"),
]

AUTO_START = True
_RUNNING = False
_STOP_REQUESTED = False
_BG_THREAD_STACK = 12288

_en = None          # EspNowLink
_tft = None
_tlm = {}           # ultimo payload parseado: {"I": 1.23, "B1": 12.3, ...}
_last_payload = ""
_last_rx_ms = None
_rx_times = []      # timestamps recientes (ventana de 3s) para estimar pps
_field_idx = 0
_screen_mode = "field"   # "field" | "debug"
_dirty = True


# ── Hardware ─────────────────────────────────────────────────────────────────

def make_display():
    spi = SPI(
        HW.TFT_SPI_ID, baudrate=HW.TFT_BAUDRATE, polarity=0, phase=0,
        sck=Pin(HW.TFT_SCK), mosi=Pin(HW.TFT_MOSI), miso=None,
    )
    return TFT170(
        spi,
        dc=Pin(HW.TFT_DC, Pin.OUT),
        rst=Pin(HW.TFT_RST, Pin.OUT),
        cs=Pin(HW.TFT_CS, Pin.OUT),
        bl=Pin(HW.TFT_BL, Pin.OUT),
        rotation=1,   # landscape 320x170, igual que el T190
    )


def make_espnow():
    try:
        link = EspNowLink()
        if link.paired:
            print("[espnow] OK, peer recordado:", mac_str(link.peer))
        else:
            print("[espnow] OK, esperando PAIR_REQ del T190...")
        return link
    except Exception as exc:
        print("[espnow] init error:", exc)
        return None


# ── Telemetria ───────────────────────────────────────────────────────────────

def _parse_tlm(payload_str):
    """'I=1.23;B1=12.30;...' -> {'I': 1.23, 'B1': 12.3, ...}.
    Claves/formato definidos en New T190/telemetry.py:_build_payload()."""
    out = {}
    for part in payload_str.split(";"):
        if "=" not in part:
            continue
        k, v = part.split("=", 1)
        try:
            out[k] = float(v)
        except ValueError:
            pass
    return out


def _compute_pps():
    """Paquetes/seg estimados sobre la ventana de _rx_times (ver _on_payload)."""
    if len(_rx_times) < 2:
        return 0.0
    span_ms = time.ticks_diff(_rx_times[-1], _rx_times[0])
    if span_ms <= 0:
        return 0.0
    return (len(_rx_times) - 1) * 1000.0 / span_ms


def _on_payload(payload_str):
    global _last_payload, _last_rx_ms, _dirty, _tlm, _rx_times
    _last_payload = payload_str
    _tlm = _parse_tlm(payload_str)
    now = time.ticks_ms()
    _last_rx_ms = now
    _rx_times.append(now)
    _rx_times = [t for t in _rx_times if time.ticks_diff(now, t) <= 3000]
    _dirty = True


# ── UI: pantalla de campos (formato T190) ───────────────────────────────────

def _draw_field(tft):
    idx = _field_idx
    label, code, unit, fmt, key = FIELDS[idx]
    val = _tlm.get(key)
    value_str = fmt.format(val) if val is not None else "---"

    prev_label = FIELDS[(idx - 1) % len(FIELDS)][0]
    next_label = FIELDS[(idx + 1) % len(FIELDS)][0]

    tft.fill(BLACK)

    # --- fila 1: navegacion anterior/proximo ---
    tft.text(("<" + prev_label)[:18], 2, 4, GRAY)
    next_txt = (next_label + ">")[:18]
    tft.text(next_txt, tft.width - len(next_txt) * 8 - 2, 4, GRAY)

    # --- fila 2: codigo (font40) + valor (font80) + unidad (font24) ---
    code_w = seven_seg.text_width(SEG40, code)
    unit_w = seven_seg.text_width(SEG24, unit)
    value_w = seven_seg.text_width(SEG80, value_str)
    gap = 8
    left_bound = 8 + code_w + gap
    right_bound = tft.width - 8 - unit_w - gap
    free_w = right_bound - left_bound
    value_x = left_bound + (free_w - value_w) // 2

    seven_seg.draw_text(tft, SEG40, code, 8, 60, WHITE, BLACK)
    seven_seg.draw_text(tft, SEG80, value_str, value_x, 24, WHITE, BLACK)
    seven_seg.draw_text(tft, SEG24, unit, tft.width - unit_w - 8, 76, WHITE, BLACK)

    # --- fila 3: estado ---
    tft.hline(0, 120, tft.width, rgb565(50, 50, 50))
    status = "EN:{}#{} pps:{:.1f}".format(
        "OK" if (_en is not None and _en.paired) else "--",
        _en.rx_count if _en is not None else 0,
        _compute_pps(),
    )
    tft.text(status[:34], 2, 128, GRAY)
    tft.text("{}/{}".format(idx + 1, len(FIELDS)), tft.width - 42, 128,
              GREEN if _tlm else RED)
    tft.text("hold=debug", tft.width - 88, 140, GRAY)

    tft.show()


# ── UI: pantalla de debug (long-press) ──────────────────────────────────────

def _draw_debug(tft):
    tft.fill(BLACK)
    tft.text("DEBUG ESP-NOW", 4, 4, WHITE)
    tft.hline(0, 16, tft.width, GRAY)

    if _en is None:
        tft.text("error de init", 4, 26, RED)
    else:
        tft.text("paired: {}".format(_en.paired), 4, 26,
                  GREEN if _en.paired else GRAY)
        tft.text("peer:   {}".format(mac_str(_en.peer)), 4, 38, GRAY)
        tft.text("rx_count: {}".format(_en.rx_count), 4, 50, WHITE)
        tft.text("pps: {:.2f}".format(_compute_pps()), 4, 62, WHITE)
        if _last_rx_ms is not None:
            age_s = time.ticks_diff(time.ticks_ms(), _last_rx_ms) / 1000.0
            tft.text("ultimo rx: hace {:.1f}s".format(age_s), 4, 74, WHITE)
        else:
            tft.text("ultimo rx: nunca", 4, 74, GRAY)
        # El modulo 'espnow' de MicroPython no expone RSSI por paquete en
        # recv() -- no hay forma de mostrar nivel de senal real sin tocar
        # firmware/C. pps + edad del ultimo rx son el proxy disponible.
        tft.text("RSSI: no disponible (API espnow)", 4, 86, GRAY)

    tft.hline(0, 100, tft.width, GRAY)
    tft.text("variables del auto:", 4, 106, WHITE)
    y = 116
    for _, code, unit, fmt, key in FIELDS:
        if y > tft.height - 10:
            break
        val = _tlm.get(key)
        val_str = fmt.format(val) if val is not None else "--"
        tft.text("{:<4s}{:>9s} {}".format(code, val_str, unit)[:36], 4, y, GRAY)
        y += 10

    tft.show()


async def ui_task(tft):
    global _dirty
    last_draw_ms = 0
    while True:
        now = time.ticks_ms()
        period = 300 if _screen_mode == "debug" else 500
        if _dirty or time.ticks_diff(now, last_draw_ms) >= period:
            if _screen_mode == "debug":
                _draw_debug(tft)
            else:
                _draw_field(tft)
            _dirty = False
            last_draw_ms = now
        await asyncio.sleep_ms(100)


# ── Boton BOOT (GPIO0): corto = siguiente campo, largo = toggle debug ──────

def _on_short():
    global _field_idx, _dirty
    if _screen_mode == "field":
        _field_idx = (_field_idx + 1) % len(FIELDS)
        _dirty = True


def _on_long():
    global _screen_mode, _dirty
    _screen_mode = "debug" if _screen_mode == "field" else "field"
    _dirty = True


# ── Arranque asyncio (corre dentro del thread de fondo) ─────────────────────

async def _main_async():
    global _en, _tft, _dirty
    print("[main] arrancando...")

    _tft = make_display()
    print("[main] display OK {}x{}".format(_tft.width, _tft.height))

    _en = make_espnow()

    page_btn = PageButton(
        Pin(HW.PAGE_BTN_PIN, Pin.IN, Pin.PULL_UP),
        short=_on_short, long=_on_long, label="BOOT",
    )

    _dirty = True
    tasks = [
        asyncio.create_task(ui_task(_tft)),
        asyncio.create_task(page_btn.task()),
    ]
    if _en is not None:
        tasks.append(asyncio.create_task(_en.rx_task(_on_payload)))

    try:
        while not _STOP_REQUESTED:
            await asyncio.sleep_ms(200)
    finally:
        for t in tasks:
            try:
                t.cancel()
            except Exception:
                pass
        print("[main] detenido")


def _bg():
    global _RUNNING, _STOP_REQUESTED
    try:
        asyncio.run(_main_async())
    except Exception as exc:
        print("[main] error fatal en hilo de fondo:", exc)
        try:
            sys.print_exception(exc)
        except Exception:
            pass
    finally:
        _RUNNING = False
        _STOP_REQUESTED = False


def start():
    """Arranca la app en un thread de fondo. No bloquea -> REPL libre."""
    global _RUNNING, _STOP_REQUESTED
    if _RUNNING:
        print("[main] ya esta corriendo")
        return False
    _STOP_REQUESTED = False
    _RUNNING = True
    try:
        _thread.stack_size(_BG_THREAD_STACK)
    except Exception as exc:
        print("[main] stack size error:", exc)
    _thread.start_new_thread(_bg, ())
    return True


def stop(wait_ms=0):
    """Pide apagar la app. Con wait_ms>0 espera (bloqueante) a que termine."""
    global _STOP_REQUESTED
    if not _RUNNING:
        print("[main] no esta corriendo")
        return False
    _STOP_REQUESTED = True
    remaining = int(wait_ms)
    while _RUNNING and remaining > 0:
        time.sleep_ms(10)
        remaining -= 10
    return True


def repair():
    """Olvida el T190 emparejado y vuelve a esperar un PAIR_REQ nuevo.
    Usar si cambiaste de unidad T190 o la MAC dejo de responder."""
    if _en is None:
        print("[espnow] no inicializado")
        return
    _en.repair()


def next_field():
    """Avanza al siguiente valor en pantalla (equivalente a pulsacion corta)."""
    _on_short()
    print("[main] campo ->", FIELDS[_field_idx][0])


def prev_field():
    """Retrocede al valor anterior (sin boton fisico, solo desde el REPL)."""
    global _field_idx, _dirty
    _field_idx = (_field_idx - 1) % len(FIELDS)
    _dirty = True
    print("[main] campo ->", FIELDS[_field_idx][0])


def toggle_debug():
    """Alterna entre pantalla de campos y pantalla de debug (equivalente a
    la pulsacion larga)."""
    _on_long()
    print("[main] modo ->", _screen_mode)


def status():
    """Snapshot on-demand del estado de pairing/telemetria (REPL)."""
    if _en is None:
        print("[main] espnow no inicializado")
        return
    label, code, unit, fmt, key = FIELDS[_field_idx]
    val = _tlm.get(key)
    print("[STATUS] modo={} pantalla={}({}) paired={} peer={} rx_count={} "
          "pps={:.2f} tlm={}".format(
        _screen_mode, label, fmt.format(val) if val is not None else "--",
        _en.paired, mac_str(_en.peer), _en.rx_count, _compute_pps(), _tlm))


if AUTO_START:
    start()
