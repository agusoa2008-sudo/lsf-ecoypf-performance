
# main.py — Heltec T190 v3: display remoto del Super Mini (eBike2026)
#
# El T190 no lee los sensores de traccion/corriente/velocidad -- todo eso
# vive en el Super Mini (ver ../SUPER MINI S3/), que hace las lecturas y los
# calculos (Wh, potencia, eficiencia) y los manda por ESP-NOW. El T190
# solo recibe, muestra en pantalla, y reenvia por LoRa (SX1262) a una base
# remota. Tambien mide su bateria interna para mostrar el estado del T190.
# Ver espnow_link.py para el protocolo de pairing (T190 = quien
# acepta, Super Mini = iniciador -- INVERTIDO respecto a la version vieja
# de este archivo, que leia sensores locales y/o mandaba a un segundo
# display tipo Ideaspark).
#
# El Super Mini envia telemetria por ESP-NOW; el T190 la muestra y retransmite
# por LoRa. El GPS y la bateria local del T190 se supervisan en tareas propias.
#
# - Display: un valor a la vez, fuente 7 segmentos blanco sobre negro.
#   Fila de arriba: estado del link ESP-NOW (antes tenia hints de
#   navegacion prev/next, se saco para dejar lugar al estado).
#
# - Dos botones (ver HW.py y ARQUITECTURA_TELEMETRIA_ECOYPF.md §5):
#     short dispara siempre al instante al soltar; double es un evento
#     ADICIONAL (no exclusivo) que se suma si el segundo tap llega dentro
#     de DOUBLE_MS -- ver buttons.py. Un doble tap rapido ejecuta short
#     y double juntos.
#     BTN0  (GPIO0)  short          -> pantalla siguiente
#     BTN0  (GPIO0)  double         -> volver a VELOCIDAD; cancela AP si activo
#     BTN0  (GPIO0)  long           -> iniciar/detener log SD; en CONFIG
#                                     inicia/detiene el AP de configuración
#     S3    (GPIO21) short          -> pantalla anterior
#                                     / cancelar AP y volver a VELOCIDAD
#     S3    (GPIO21) double         -> reset de viaje
#     S3    (GPIO21) long           -> capturar waypoint GPS
#     S3    (GPIO21) extra (>=2.2s) -> deep sleep al soltar
#
# Patron "REPL libre": toda la app corre en un _thread aparte (igual que
# uPy reference Martin/FC Upy/eBike Old/inDev/t.py). Al bootear, main.py
# arranca el hilo y retorna enseguida -- la consola queda disponible para
# llamar status() / stop() / start() / next_field() / prev_field() /
# reset_trip() / espnow_status() / espnow_repair() directo (sin
# `import main` -- ver nota en conversacion sobre por que).

import _thread
import sys
import time
import machine
import esp32
import uasyncio as asyncio
from machine import Pin, SPI

import HW
from drivers.tft170 import TFT170, rgb565
from buttons import InterruptPageButton
from telemetry import TelemetryRuntime
from espnow_link import EspNowLink, mac_str
from battery import percent_from_voltage
from gps import GPSReceiver
from sd_logger import TripLogger
from settings import T190Settings
from config_server import ConfigServer, AP_SSID, AP_IP
import seven_seg
from fonts import seven_segment_80 as SEG80
from fonts import seven_segment_40 as SEG40

try:
    from sx1262 import SX1262
except ImportError:
    SX1262 = None

BLACK = 0x0000
WHITE = 0xFFFF
GRAY = rgb565(220, 220, 220)
RED = rgb565(220, 40, 40)
GREEN = rgb565(40, 200, 40)

# ── Pantallas en orden de uso: marcha, consumo, viaje y diagnostico ─────────
# 6-element tuple: (grupo, label, codigo, unidad, fmt, getter)
# Optional 7th element: (sec_label, sec_fmt, sec_getter) — small text below label
FIELDS = [
    ("RUTA",        "VELOCIDAD",      "SPD", "km/h",  "{:.1f}", lambda s: s.speed_kmh,
     ("", "{}", lambda s: "Wh/km:{:.1f}  SAT:{}".format(
         _trip_whkm_avg(),
         _gps.satellites if _gps is not None else "--"))),
    ("EFICIENCIA",  "Wh/km PROM",     "WA",  "Wh/km", "{:.1f}", lambda s: _trip_whkm_avg()),
    ("CONSUMO",     "POT PROM 5s",    "PA",  "W",     "{:.0f}", lambda s: s.p_avg5s),
    ("CONSUMO",     "POT INSTANT",    "PI",  "W",     "{:.0f}", lambda s: s.p_inst),
    ("CONSUMO",     "CORRIENTE",      "I",   "A",     "{:.2f}", lambda s: s.i_bat),
    ("EFICIENCIA",  "Wh/km INSTANT",  "WI",  "Wh/km", "{:.1f}", lambda s: s.whkm_inst),
    ("VIAJE",       "DISTANCIA",      "DST", "m",     "{:.0f}",
     lambda s: _settings.trip_distance_m if _settings else 0.0),
    ("VIAJE",       "ENERGIA",        "WT",  "Wh",    "{:.1f}",
     lambda s: _settings.battery_used_wh if _settings else 0.0),
    ("BATERIA",     "BATERIA 1",      "B1",  "V",     "{:.2f}", lambda s: s.v_b1),
    ("BATERIA",     "BATERIA 2",      "B2",  "V",     "{:.2f}", lambda s: s.v_b2),
    ("BATERIA",     "BATERIA 3",      "B3",  "V",     "{:.2f}", lambda s: s.v_b3),
    ("BATERIA",     "BATERIA 4",      "B4",  "V",     "{:.2f}", lambda s: s.v_b4),
    ("BATERIA",     "VBATS TOTAL",    "TOT", "V",     "{:.2f}", lambda s: s.v_bats),
    ("CALIBRACION", "PULSOS",         "PLS", "",      "{}", lambda s: s.pulse_count),
]

AUTO_START = True
IDLE_SLEEP_TIMEOUT_MS = 20 * 60 * 1000
IDLE_SPEED_THRESHOLD_KMH = 0.1
IDLE_SLEEP_CHECK_INTERVAL_MS = 1000
# Si el Super Mini se duerme (o queda fuera de rango) deja de mandar ESP-NOW
# y la telemetria pasa a STALE (ver telemetry.SOURCE_STALE_MS). Pasado este
# tiempo adicional sin que vuelva, el T190 lo acompaña a deep sleep -- ya
# estaba recibiendo datos antes, no es el caso de "todavia no emparejo".
SUPERMINI_LOST_SLEEP_TIMEOUT_MS = 30 * 1000
SD_LOG_START_SPEED_KMH = 0.5
SD_LOG_SAMPLE_INTERVAL_MS = 1000
_RUNNING = False
_STOP_REQUESTED = False
_SLEEP_REQUESTED = False
_LOG_MANUAL_OVERRIDE = None
_BG_THREAD_STACK = 12288

_rt = None          # TelemetryRuntime
_en = None          # EspNowLink
_lora = None
_shared_spi = None
_sd_logger = None
_sd_error = None
_tft = None
_field_idx = 0
_dirty = True
_battery_voltage = None
_battery_percent = None
_battery_error = None
_battery_adc_raw = None
_battery_adc_pin_voltage = None
_battery_adc_read_method = None
_gps = None
_gps_start = None
_gps_clock_synced = False
_gps_time_update_seen = 0
_gps_last_rtc_sync_ms = 0
_settings = None
_CONFIG_AP_REQUESTED = False
_CONFIG_AP_STOP_REQUESTED = False
_CONFIG_AP_RUNNING = False
_supermini_config_ack_revision = None
_supermini_config_error = None
_supermini_config_error_revision = None
_charge_wh_accum = 0.0
_charge_session_active = False
_CHARGE_THRESHOLD_A = 0.5   # |I| magnitude to detect charge / discharge
_last_button_activity_ms = 0
_sleep_warn_s = None        # segundos restantes del auto-sleep en curso, o None
_sleep_warn_reason = None   # "idle" (parado) o "lost" (Super Mini ausente)
_toast_text = None          # confirmacion momentanea (waypoint, reset), o None
_toast_started_ms = 0
TOAST_DURATION_MS = 4000


# ── Hardware ─────────────────────────────────────────────────────────────────

def make_display():
    HW.display_power_on()
    time.sleep_ms(20)
    spi = SPI(
        HW.TFT_SPI_ID, baudrate=HW.TFT_BAUDRATE, polarity=0, phase=0,
        sck=machine.Pin(HW.TFT_SCK), mosi=machine.Pin(HW.TFT_MOSI), miso=None,
    )
    return TFT170(
        spi,
        dc=machine.Pin(HW.TFT_DC, machine.Pin.OUT),
        rst=machine.Pin(HW.TFT_RST, machine.Pin.OUT),
        cs=machine.Pin(HW.TFT_CS, machine.Pin.OUT),
        bl=machine.Pin(HW.TFT_BL, machine.Pin.OUT),
        rotation=1,   # landscape 320x170 -- mas ancho para la fuente de 80px
    )


def make_shared_spi():
    try:
        Pin(HW.LORA_CS, Pin.OUT, value=1)
        Pin(HW.SD_CS_PIN, Pin.OUT, value=1)
        return SPI(
            HW.SD_SPI_ID, baudrate=2_000_000, polarity=0, phase=0,
            sck=Pin(HW.SD_SCK_PIN), mosi=Pin(HW.SD_MOSI_PIN),
            miso=Pin(HW.SD_MISO_PIN),
        )
    except Exception as exc:
        print("[SPI] no se pudo crear el bus compartido LoRa/SD:", exc)
        return None


def make_lora(spi=None):
    if SX1262 is None:
        print("[LoRa] driver sx1262 no disponible")
        return None
    try:
        lora = SX1262(
            spi_bus=2,  # distinto del SPI(1) del display (ver loralcd_test.py)
            clk=HW.LORA_SCK, mosi=HW.LORA_MOSI, miso=HW.LORA_MISO,
            cs=HW.LORA_CS, irq=HW.LORA_DIO1,
            rst=HW.LORA_RST, gpio=HW.LORA_BUSY, spi=spi,
        )
        lora.begin(
            freq=HW.LORA_FREQ_MHZ,
            bw=HW.LORA_BW_KHZ,
            sf=HW.LORA_SF,
            cr=HW.LORA_CR,
            syncWord=HW.LORA_SYNC_WORD,
            power=HW.LORA_POWER_DBM,
            currentLimit=HW.LORA_CURRENT_LIMIT_MA,
            preambleLength=HW.LORA_PREAMBLE_LEN,
            tcxoVoltage=HW.LORA_TCXO_VOLTAGE,
        )
        if spi is not None and lora.spi is not spi:
            raise RuntimeError("SX1262 no conserva la instancia SPI compartida")
        print("[LoRa] OK @ {} MHz BW={} SF{} CR4/{} {} dBm".format(
            HW.LORA_FREQ_MHZ, HW.LORA_BW_KHZ, HW.LORA_SF,
            HW.LORA_CR, HW.LORA_POWER_DBM))
        return lora
    except Exception as exc:
        print("[LoRa] init error:", exc)
        return None


def make_sd_logger(spi):
    global _sd_error
    if spi is None:
        _sd_error = "bus SPI no disponible"
        print("[SD] logger inactivo: no hay bus SPI compartido")
        return None
    logger = None
    try:
        logger = TripLogger(
            spi, sd_cs_pin=HW.SD_CS_PIN, lora_cs_pin=HW.LORA_CS,
            spi_baudrate=2_000_000,
        )
        logger.mount()
        if logger.card.spi is not spi:
            raise RuntimeError("driver SD no conserva la instancia SPI compartida")
    except Exception as exc:
        _sd_error = "{}".format(exc)
        if logger is not None:
            logger.error = _sd_error
        print("[SD] inicializacion fallida:", exc)
        return logger
    _sd_error = None
    print("[SD] FAT montado: {} sectores ({:.2f} GiB)".format(
        logger.sectors, logger.sectors * 512 / (1024 * 1024 * 1024)))
    return logger


def make_espnow(on_telemetry, on_config_ack):
    try:
        link = EspNowLink(
            on_telemetry=on_telemetry, on_config_ack=on_config_ack)
        if link.paired:
            print("[espnow] OK, peer recordado:", mac_str(link.peer))
        else:
            print("[espnow] OK, esperando Super Mini...")
        return link
    except Exception as exc:
        print("[espnow] init error:", exc)
        return None


def make_gps():
    try:
        uart = machine.UART(
            HW.GPS_UART_ID, baudrate=HW.GPS_BAUDRATE,
            tx=HW.GPS_TX_PIN, rx=HW.GPS_RX_PIN, timeout=0,
        )
        print("[GPS] UART{} RX=GPIO{} TX=GPIO{} @ {} baud".format(
            HW.GPS_UART_ID, HW.GPS_RX_PIN, HW.GPS_TX_PIN, HW.GPS_BAUDRATE))
        return GPSReceiver(uart)
    except Exception as exc:
        print("[GPS] init error:", exc)
        return None


# ── UI ───────────────────────────────────────────────────────────────────────

def _espnow_link_text():
    """Texto + color del estado del link ESP-NOW con el Super Mini, para
    la fila 1 (reemplaza los hints de navegacion prev/next de antes)."""
    if _en is None:
        return "ESPNOW: no disponible", RED
    if not _en.paired:
        return "ESPNOW: esperando Super Mini...", GRAY
    if _en.fresh and _rt is not None and _rt.source_fresh():
        age_s = time.ticks_diff(time.ticks_ms(), _en.last_rx_ms) / 1000.0
        return "ESPNOW: OK ({:.1f}s)".format(age_s), GREEN
    return "ESPNOW: SIN DATOS (perdido)", RED


def _gps_status():
    if _gps is None:
        return "GPS:ERR", RED
    sats = _gps.satellites
    if _gps.has_fix():
        return "GPS:{}s".format(sats), GREEN
    return "GPS:{}--".format(sats), GRAY


def _sd_log_status():
    if _sd_logger is None:
        return ("SD:ERR", RED) if _sd_error else ("SD:--", GRAY)
    if _sd_logger.error is not None:
        return "SD:ERR", RED
    if _sd_logger.recording:
        return "SD:REC", GREEN
    if _sd_logger.ready:
        return "SD:ARM", GRAY
    return "SD:--", GRAY


def _sleep_warning_text():
    """Texto de aviso de auto-sleep inminente (ver idle_sleep_task), o
    None si no hay ningun temporizador de auto-sleep corriendo."""
    if _sleep_warn_s is None:
        return None
    detail = "Super Mini ausente" if _sleep_warn_reason == "lost" else "detenido"
    return "DUERME EN {}s ({})".format(_sleep_warn_s, detail)


def _show_toast(text):
    """Confirmacion momentanea en pantalla (waypoint capturado, reset de
    viaje, etc.) -- ui_task redibuja cada <=300ms sin necesidad de
    _dirty, asi que alcanza con guardar el texto y el instante inicial
    para que _toast_line() lo apague solo pasado TOAST_DURATION_MS."""
    global _toast_text, _toast_started_ms, _dirty
    _toast_text = text
    _toast_started_ms = time.ticks_ms()
    _dirty = True


def _toast_line():
    if _toast_text is None:
        return None
    if time.ticks_diff(time.ticks_ms(), _toast_started_ms) >= TOAST_DURATION_MS:
        return None
    return _toast_text


def _trip_whkm_avg():
    """Wh/km del periodo actual (desde el ultimo reset_trip), calculado
    aca con los deltas locales de settings.py -- no es el WA de vida
    entera que manda el Super Mini, que no se entera de resets."""
    if _settings is None:
        return 0.0
    km = _settings.trip_distance_m / 1000.0
    return (_settings.battery_used_wh / km) if km > 0.01 else 0.0


def _art_timestamp():
    if not _gps_clock_synced:
        return None
    tm = time.localtime()
    return "{:04d}-{:02d}-{:02d} {:02d}:{:02d}:{:02d}".format(
        tm[0], tm[1], tm[2], tm[3], tm[4], tm[5])


def _page_count():
    return len(FIELDS) + 4


def _page_label(idx):
    if idx == len(FIELDS):
        return "DIAGNOSTICO"
    if idx == len(FIELDS) + 1:
        return "AYUDA BOTONES"
    if idx == len(FIELDS) + 2:
        return "CONFIGURACION"
    if idx == len(FIELDS) + 3:
        return "CARGA"
    return "{} / {}".format(FIELDS[idx][0], FIELDS[idx][1])


def _draw_diagnostics(tft, idx):
    tft.fill(BLACK)
    tft.text("DIAGNOSTICO  {}/{}".format(idx + 1, _page_count()), 8, 4, WHITE)
    tft.hline(0, 20, tft.width, rgb565(70, 80, 90))

    state = _rt.state if _rt is not None else None
    source_fresh = _rt is not None and _rt.source_fresh()
    if state is None or not source_fresh:
        ads_text, ads_color = "ADS: sin telemetria fresca", RED
    else:
        ads_text = "ADS V:{}  I:{}  RX:{}#{}".format(
            "OK" if state.adc_valid else "ERR",
            "OK" if state.current_valid else "ERR",
            state.espnow_rx_count, state.source_seq)
        ads_color = GREEN if state.adc_valid and state.current_valid else RED
    tft.text(ads_text[:39], 8, 30, ads_color)

    if _sd_logger is None:
        sd_detail = _sd_error or "no inicializada"
        sd_color = RED if _sd_error else GRAY
    elif _sd_logger.error:
        sd_detail = _sd_logger.error
        sd_color = RED
    elif _sd_logger.recording:
        sd_detail = "REC {}".format(_sd_logger.path)
        sd_color = GREEN
    elif _sd_logger.ready:
        sd_detail = "OK {:.1f} GiB".format(
            _sd_logger.sectors * 512 / (1024 * 1024 * 1024))
        sd_color = WHITE
    else:
        sd_detail = "no montada"
        sd_color = RED
    tft.text(("SD: " + sd_detail)[:39], 8, 53, sd_color)

    if _gps is None:
        gps_text, gps_color = "GPS: no inicializado", RED
    elif _gps.has_fix():
        gps_text = "GPS FIX sats:{}".format(_gps.satellites)
        gps_color = GREEN
    else:
        gps_text = "GPS sin fix sats:{}".format(_gps.satellites)
        gps_color = GRAY
    tft.text(gps_text[:39], 8, 76, gps_color)

    timestamp = _art_timestamp()
    clock_text = "ART: {}".format(timestamp) if timestamp else "ART: esperando hora GPS"
    tft.text(clock_text[:39], 8, 99, WHITE if timestamp else GRAY)
    tft.text("GPS bytes invalidos: {}".format(
        _gps.invalid_bytes if _gps is not None else "--"), 8, 119, GRAY)
    if _battery_voltage is None:
        battery_text, battery_color = "T190 BAT: lectura no valida", RED
    else:
        battery_text = "T190 {:.2f}V  {}%  ADC:{}".format(
            _battery_voltage, _battery_percent, _battery_adc_raw)
        battery_color = GREEN
    tft.text(battery_text[:39], 8, 132, battery_color)
    if (_settings is not None and _settings.battery_percent is not None):
        pack_text = "PACK {}%  {:.0f}/{:.0f}Wh".format(
            _settings.battery_percent, _settings.battery_remaining_wh,
            _settings.battery_capacity_wh)
        pack_color = GREEN
    elif _settings is not None and _settings.battery_capacity_wh > 0:
        pack_text, pack_color = "PACK: marca carga completa", GRAY
    else:
        pack_text, pack_color = "PACK: capacidad sin configurar", GRAY
    tft.text(pack_text[:39], 8, 150, pack_color)
    tft.show()


def _draw_configuration(tft, idx):
    tft.fill(BLACK)
    tft.text("CONFIGURACION  {}/{}".format(idx + 1, _page_count()), 8, 4, WHITE)
    tft.hline(0, 22, tft.width, rgb565(70, 80, 90))
    tft.text("AJUSTES DESDE EL TELEFONO", 8, 37, WHITE)
    if _CONFIG_AP_RUNNING:
        tft.text("BTN0 1.2-<2.2s: AP ON/OFF", 8, 62, WHITE)
        tft.text("S3 corto/BTN0 doble: cancelar", 8, 83, WHITE)
        tft.text("SSID: {}".format(AP_SSID), 8, 105, GREEN)
        tft.text("http://{}/".format(AP_IP), 8, 127, GREEN)
        tft.text("WPA2: lasalle2026", 8, 149, WHITE)
    else:
        tft.text("VELOCIDAD: S3 corto -> CONFIG", 8, 62, WHITE)
        tft.text("BTN0 1.2-<2.2s: iniciar AP", 8, 83, WHITE)
        tft.text("BTN0 doble: volver VELOCIDAD", 8, 105, GRAY)
        if _settings is not None:
            factors = _settings.b_supermini_factors_milli
            tft.text("Factores B1..4: {} {} {} {}".format(
                factors[0], factors[1], factors[2], factors[3]),
                8, 127, WHITE)
            if _settings.battery_capacity_wh > 0:
                tft.text("Pack {:.0f} Wh".format(
                    _settings.battery_capacity_wh), 8, 149, WHITE)
    tft.show()


def _draw_carga(tft, idx):
    tft.fill(BLACK)
    tft.text("CARGA  {}/{}".format(idx + 1, _page_count()), 8, 4, WHITE)
    tft.hline(0, 17, tft.width, rgb565(70, 80, 90))

    state = _rt.state if _rt is not None else None
    fresh = _rt is not None and _rt.source_fresh()
    if state is None or not fresh:
        tft.text("Sin telemetria fresca del Super Mini", 8, 30, RED)
        tft.show()
        return

    i = state.i_bat
    if i < -_CHARGE_THRESHOLD_A:
        dir_text, dir_color = "CARGANDO   +", GREEN
    elif i > _CHARGE_THRESHOLD_A:
        dir_text, dir_color = "DESCARGANDO  -", RED
    else:
        dir_text, dir_color = "REPOSO", GRAY

    tft.text(dir_text, 8, 22, dir_color)

    i_str = "{:.2f}".format(abs(i))
    a_w = seven_seg.text_width(SEG40, "A")
    i_w = seven_seg.text_width(SEG40, i_str)
    free_w = tft.width - 16 - a_w - 8
    i_x = 8 + (free_w - i_w) // 2
    seven_seg.draw_text(tft, SEG40, i_str, i_x, 34, dir_color, BLACK)
    seven_seg.draw_text(tft, SEG40, "A", tft.width - a_w - 8, 34, WHITE, BLACK)

    tft.text("B1:{:.2f}V  B2:{:.2f}V".format(state.v_b1, state.v_b2), 8, 82, WHITE)
    tft.text("B3:{:.2f}V  B4:{:.2f}V".format(state.v_b3, state.v_b4), 8, 94, WHITE)
    tft.text("VBATS: {:.2f}V".format(state.v_bats), 8, 106, WHITE)

    tft.hline(0, 118, tft.width, rgb565(50, 50, 50))

    precharge = _settings.precharge_wh if _settings is not None else 0.0
    wh_shown = precharge + _charge_wh_accum
    tft.text("Wh+: {:.1f}   base: {:.0f}Wh".format(wh_shown, precharge), 8, 126, WHITE)
    if _charge_session_active:
        tft.text(("Sesion: {:.1f}Wh  BTN0 largo=reset".format(
            _charge_wh_accum))[:38], 8, 138, GREEN)
    else:
        tft.text("Esperando carga...  BTN0 largo=reset", 8, 138, GRAY)
    tft.show()


def _draw_help(tft, idx):
    C = 160   # column separator x
    G = rgb565(70, 80, 90)
    D = rgb565(50, 50, 50)
    tft.fill(BLACK)
    tft.text("AYUDA BOTONES  {}/{}".format(idx + 1, _page_count()), 8, 4, WHITE)
    tft.hline(0, 17, tft.width, G)

    # Column headers
    tft.text("BTN0 / GPIO0", 4, 24, GREEN)
    tft.text("S3 / GPIO21", C + 4, 24, GREEN)
    tft.hline(0, 35, tft.width, D)
    tft.vline(C, 17, 88, D)

    # Gesture rows  — label x=4/C+4, action x=52/C+52
    LBL = 4
    ACT = 52
    def row(y, gesture, left_action, right_action):
        tft.text(gesture, LBL, y, GRAY)
        tft.text(left_action,  ACT,      y, WHITE)
        tft.text(gesture, C + LBL, y, GRAY)
        tft.text(right_action, C + ACT,  y, WHITE)

    row(42, "corto", "siguiente",    "anterior")
    row(54, "doble", "VELOCIDAD",    "reset viaje")
    row(66, "largo", "AP / log SD",  "waypoint GPS")
    row(78, "extra", "(nada)",        "deep sleep")

    tft.hline(0, 92, tft.width, D)

    # Footer hints
    tft.text("AP: ir a CONFIG -> BTN0 largo 1.2-2.2s", 4, 98, GRAY)
    tft.text("Sleep: S3 extra >=2.2s soltar; wake S3", 4, 110, GRAY)
    tft.text("Auto-sleep: configurar en CONFIGURACION", 4, 122, GRAY)
    tft.show()


def _draw_battery(tft):
    if _battery_percent is None:
        color = GRAY
        label = "--%"
        fill_width = 0
    else:
        label = "{}%".format(_battery_percent)
        color = GREEN if _battery_percent > 25 else RED
        fill_width = 18 * _battery_percent // 100
    tft.rect(258, 2, 22, 12, color)
    tft.fill_rect(282, 5, 2, 6, color)
    if fill_width:
        tft.fill_rect(260, 4, fill_width, 8, color)
    tft.text(label, 287, 4, color)


def _draw_field(tft, idx):
    if idx == len(FIELDS):
        _draw_diagnostics(tft, idx)
        return
    if idx == len(FIELDS) + 1:
        _draw_help(tft, idx)
        return
    if idx == len(FIELDS) + 2:
        _draw_configuration(tft, idx)
        return
    if idx == len(FIELDS) + 3:
        _draw_carga(tft, idx)
        return

    # Layout landscape 320x170 (rotation=1), 3 filas:
    #  1) estado del link ESP-NOW con el Super Mini
    #  2) cifra: codigo font40 (izq) + valor font80 (centro) + unidad font40 (der)
    #  3) estado: LoRa + indice
    field = FIELDS[idx]
    group, label, code, unit, fmt, getter = field[:6]
    secondary = field[6] if len(field) > 6 else None
    st = _rt.state
    fresh = _rt.source_fresh()
    value_str = fmt.format(getter(st)) if fresh else "--"
    value_color = WHITE if fresh else GRAY

    tft.fill(BLACK)

    # --- fila 1: estado del link ESP-NOW ---
    link_text, link_color = _espnow_link_text()
    tft.text(link_text[:19], 2, 4, link_color)
    log_text, log_color = _sd_log_status()
    tft.text(log_text, 158, 4, log_color)
    gps_text, gps_color = _gps_status()
    tft.text(gps_text, 210, 4, gps_color)
    _draw_battery(tft)

    # --- fila 2: codigo (font40) + valor (font80) + unidad (font40) ---
    # El valor se centra en el hueco libre entre codigo y unidad (no en el
    # ancho total): "Wh/km"/"km/h" de unidad o 5 digitos de distancia
    # pueden ser mas anchos que el margen fijo y pisar al valor centrado
    # a lo bestia contra el ancho completo.
    code_w = seven_seg.text_width(SEG40, code)
    unit_w = seven_seg.text_width(SEG40, unit)
    value_w = seven_seg.text_width(SEG80, value_str)
    gap = 8
    left_bound = 8 + code_w + gap
    right_bound = tft.width - 8 - unit_w - gap
    free_w = right_bound - left_bound
    # Centrar en el hueco libre, incluso si el valor es mas ancho que el
    # hueco (caso raro: unidad larga + valor largo a la vez) -- la unidad
    # se dibuja despues y queda arriba en el solape, el codigo es lo unico
    # que puede perder un par de px contra el borde del valor.
    value_x = left_bound + (free_w - value_w) // 2

    seven_seg.draw_text(tft, SEG40, code, 8, 60, WHITE, BLACK)
    seven_seg.draw_text(tft, SEG80, value_str, value_x, 24, value_color, BLACK)
    seven_seg.draw_text(tft, SEG40, unit, tft.width - unit_w - 8, 60, WHITE, BLACK)
    tft.text("{} / {}".format(group, label), 8, 104, WHITE)
    if secondary is not None:
        sec_label, sec_fmt, sec_getter = secondary
        sec_val = sec_fmt.format(sec_getter(st))
        sec_text = ("{}: {}".format(sec_label, sec_val) if sec_label
                    else sec_val)
        tft.text(sec_text[:36], 8, 112, GRAY)

    # --- fila 3: LoRa + indice ---
    tft.hline(0, 120, tft.width, rgb565(50, 50, 50))
    src = "SRC:OK" if _rt.source_fresh() else "SRC:STALE"
    validity = "V{}I{}".format(
        int(st.adc_valid and _rt.source_fresh()),
        int(st.current_valid and _rt.source_fresh()))
    gps_state = "GPS:OK" if _gps is not None and _gps.has_fix() else "GPS:--"
    status = "TX:{}#{} {} {} {} RX:{}".format(
        "OK" if st.lora_ok else "--", st.lora_tx_count, src, validity,
        gps_state, st.espnow_rx_count,
    )
    tft.text(status[:32], 2, 128, WHITE)
    tft.text("{}/{}".format(idx + 1, _page_count()), tft.width - 42, 128,
              GREEN if (_en is not None and _en.fresh) else RED)

    warn_text = _sleep_warning_text()
    if warn_text is not None:
        tft.text(warn_text[:38], 2, 144, RED)
    else:
        toast_text = _toast_line()
        if toast_text is not None:
            tft.text(toast_text[:38], 2, 144, GREEN)
    tft.show()


async def ui_task(tft):
    global _dirty
    last_draw_ms = 0
    while True:
        now = time.ticks_ms()
        if _dirty or time.ticks_diff(now, last_draw_ms) >= 300:
            _draw_field(tft, _field_idx)
            _dirty = False
            last_draw_ms = now
        await asyncio.sleep_ms(50)


async def battery_task(interval_ms=10000):
    global _battery_voltage, _battery_percent, _battery_error, _dirty
    global _battery_adc_raw, _battery_adc_pin_voltage
    global _battery_adc_read_method
    while True:
        try:
            sample = HW.read_system_battery_sample()
            voltage = sample["voltage_v"]
            percent = percent_from_voltage(voltage)
        except Exception as exc:
            _battery_voltage = None
            _battery_percent = None
            _battery_error = "{}".format(exc)
            _battery_adc_raw = None
            _battery_adc_pin_voltage = None
            _battery_adc_read_method = None
            print("[battery] read error:", exc)
        else:
            _battery_voltage = voltage
            _battery_percent = percent
            _battery_error = None
            _battery_adc_raw = sample["raw_median"]
            _battery_adc_pin_voltage = sample["pin_voltage_v"]
            _battery_adc_read_method = sample["read_method"]
        _dirty = True
        await asyncio.sleep_ms(interval_ms)


async def gps_task():
    global _dirty, _gps_clock_synced, _gps_time_update_seen
    global _gps_last_rtc_sync_ms
    while True:
        if _gps is not None:
            if _gps.poll():
                _dirty = True
            update_count = _gps.time_update_count
            now = time.ticks_ms()
            if (update_count != _gps_time_update_seen and
                    (not _gps_clock_synced or time.ticks_diff(
                        now, _gps_last_rtc_sync_ms) >= 60000)):
                rtc_datetime = _gps.latest_rtc_datetime()
                if rtc_datetime is not None:
                    machine.RTC().datetime(rtc_datetime)
                    _gps_clock_synced = True
                    _gps_last_rtc_sync_ms = now
                    print("[GPS] RTC T190 sincronizado a ART:", _art_timestamp())
                    _dirty = True
            _gps_time_update_seen = update_count
        await asyncio.sleep_ms(20)


async def charge_monitor_task(interval_ms=1000):
    """Detecta sesiones de carga por signo de corriente y acumula Wh cargados."""
    global _charge_wh_accum, _charge_session_active
    while True:
        await asyncio.sleep_ms(interval_ms)
        if _rt is None or not _rt.source_fresh():
            continue
        st = _rt.state
        if not st.current_valid:
            continue
        i = st.i_bat
        if i < -_CHARGE_THRESHOLD_A:
            if not _charge_session_active:
                _charge_session_active = True
                _charge_wh_accum = 0.0
            _charge_wh_accum += abs(i) * st.v_bats / 3600.0
        else:
            _charge_session_active = False


async def idle_sleep_task():
    """Solicita deep sleep tras el tiempo configurado a velocidad cero, o
    si el Super Mini se duerme (deja de mandar ESP-NOW tras haber estado
    emparejado) y no vuelve en SUPERMINI_LOST_SLEEP_TIMEOUT_MS -- el T190
    lo acompaña a dormir en vez de quedarse despierto sin fuente de datos.
    Cualquier gesto de boton (ver _note_button_activity) reinicia el
    temporizador que este corriendo -- el equipo sigue en uso, no
    abandonado. Mientras hay un temporizador activo, los segundos que
    faltan quedan en _sleep_warn_s/_sleep_warn_reason para que ui_task
    avise en pantalla."""
    global _SLEEP_REQUESTED, _sleep_warn_s, _sleep_warn_reason
    idle_since_ms = None
    lost_since_ms = None
    last_seen_activity_ms = _last_button_activity_ms

    while True:
        if _last_button_activity_ms != last_seen_activity_ms:
            last_seen_activity_ms = _last_button_activity_ms
            if idle_since_ms is not None or lost_since_ms is not None:
                print("[sleep] boton presionado; temporizador de auto-sleep reiniciado")
            idle_since_ms = None
            lost_since_ms = None

        if IDLE_SLEEP_TIMEOUT_MS <= 0:
            idle_since_ms = None
            lost_since_ms = None
            _sleep_warn_s = None
            _sleep_warn_reason = None
            await asyncio.sleep_ms(IDLE_SLEEP_CHECK_INTERVAL_MS)
            continue
        now = time.ticks_ms()
        ever_paired = _rt is not None and _rt.state.source_seq is not None
        fresh = _rt is not None and _rt.source_fresh()

        if ever_paired and not fresh:
            idle_since_ms = None
            if lost_since_ms is None:
                lost_since_ms = now
                print("[sleep] Super Mini sin telemetria; lo acompaña a dormir "
                      "en {:.0f}s si no vuelve".format(
                          SUPERMINI_LOST_SLEEP_TIMEOUT_MS / 1000))
            remaining_ms = SUPERMINI_LOST_SLEEP_TIMEOUT_MS - time.ticks_diff(now, lost_since_ms)
            if remaining_ms <= 0:
                _SLEEP_REQUESTED = True
                _sleep_warn_s = None
                _sleep_warn_reason = None
                print("[sleep] Super Mini ausente; solicitando deep sleep del T190")
                return
            _sleep_warn_s = remaining_ms // 1000
            _sleep_warn_reason = "lost"
        elif not ever_paired:
            # Todavia no emparejo nunca -- no es "se fue a dormir", es
            # arranque normal esperando al Super Mini; no cuenta para sleep.
            idle_since_ms = None
            lost_since_ms = None
            _sleep_warn_s = None
            _sleep_warn_reason = None
        else:
            if lost_since_ms is not None:
                print("[sleep] telemetria del Super Mini recuperada; "
                      "temporizador de ausencia cancelado")
            lost_since_ms = None
            if abs(_rt.state.speed_kmh) <= IDLE_SPEED_THRESHOLD_KMH:
                if idle_since_ms is None:
                    idle_since_ms = now
                    print("[sleep] velocidad estacionaria; comienza temporizador de {} min".format(
                        IDLE_SLEEP_TIMEOUT_MS // 60000))
                remaining_ms = IDLE_SLEEP_TIMEOUT_MS - time.ticks_diff(now, idle_since_ms)
                if remaining_ms <= 0:
                    _SLEEP_REQUESTED = True
                    _sleep_warn_s = None
                    _sleep_warn_reason = None
                    print("[sleep] detenido el tiempo configurado; solicitando deep sleep")
                    return
                _sleep_warn_s = remaining_ms // 1000
                _sleep_warn_reason = "idle"
            else:
                if idle_since_ms is not None:
                    print("[sleep] movimiento detectado ({:.2f} km/h); temporizador cancelado".format(
                        _rt.state.speed_kmh))
                idle_since_ms = None
                _sleep_warn_s = None
                _sleep_warn_reason = None

        await asyncio.sleep_ms(IDLE_SLEEP_CHECK_INTERVAL_MS)


async def sd_log_task():
    global _dirty
    global _sd_logger
    logger = _sd_logger
    if logger is None or not logger.ready:
        while True:
            await asyncio.sleep_ms(1000)

    last_sample_ms = None
    while True:
        now = time.ticks_ms()
        fresh = _rt is not None and _rt.source_fresh()
        moving = fresh and abs(_rt.state.speed_kmh) >= SD_LOG_START_SPEED_KMH

        try:
            if _LOG_MANUAL_OVERRIDE is True and not logger.recording:
                logger.start(timestamp_art=_art_timestamp())
                last_sample_ms = None
            elif _LOG_MANUAL_OVERRIDE is False and logger.recording:
                logger.stop()
                last_sample_ms = None
            elif _LOG_MANUAL_OVERRIDE is None and moving and not logger.recording:
                logger.start(timestamp_art=_art_timestamp())
                last_sample_ms = None

            if (logger.recording and fresh and
                    (last_sample_ms is None or time.ticks_diff(
                        now, last_sample_ms) >= SD_LOG_SAMPLE_INTERVAL_MS)):
                fix = _gps.latest_fix() if _gps is not None else None
                logger.write_sample(
                    _rt.state, fix, timestamp_art=_art_timestamp())
                last_sample_ms = now
                _dirty = True
        except Exception as exc:
            logger.abort(exc)
            _dirty = True
            return

        await asyncio.sleep_ms(100)


def _apply_configuration(b_supermini_factors, ads_mode, capacity_wh, mark_charged,
                         source_boot, source_wh, meters_per_pulse,
                         debounce_us, max_speed_kmh, sleep_timeout_min,
                         precharge_wh=0.0):
    global _dirty, _supermini_config_error, _supermini_config_error_revision
    global IDLE_SLEEP_TIMEOUT_MS
    _settings.update_configuration(
        b_supermini_factors, ads_mode, capacity_wh, meters_per_pulse, debounce_us,
        max_speed_kmh, sleep_timeout_min, mark_charged,
        source_boot=source_boot, source_wh=source_wh, precharge_wh=precharge_wh)
    IDLE_SLEEP_TIMEOUT_MS = sleep_timeout_min * 60 * 1000
    _supermini_config_error = None
    _supermini_config_error_revision = None
    _dirty = True


def _current_source_cursor():
    if _rt is None:
        return None, None
    return _rt.state.source_boot, _rt.raw_wh_total


def _current_raw_batteries():
    if (_rt is None or not _rt.source_fresh() or
            not _rt.state.adc_valid):
        return None
    return _rt.raw_battery_voltages


def _current_sd_logger():
    return _sd_logger


def _supermini_feedback_status():
    if _en is None or not _en.paired:
        return "Sin emparejar"
    if (_supermini_config_error is not None and
            _supermini_config_error_revision ==
            _settings.supermini_config_revision):
        return "Rechazado: {}".format(_supermini_config_error)
    if _supermini_config_ack_revision == _settings.supermini_config_revision:
        return "Confirmado (ID {})".format(_supermini_config_ack_revision)
    return "Pendiente (ID {})".format(_settings.supermini_config_revision)


def _on_supermini_config_ack(revision, accepted):
    global _supermini_config_ack_revision, _supermini_config_error
    global _supermini_config_error_revision, _dirty
    if _settings is None or revision != _settings.supermini_config_revision:
        print("[config] ACK de Super Mini ignorado para ID", revision)
        return
    if accepted:
        _supermini_config_ack_revision = revision
        _supermini_config_error = None
        _supermini_config_error_revision = None
        print("[config] Super Mini confirmó ajustes, ID={}".format(revision))
    else:
        _supermini_config_error = "ID {}".format(revision)
        _supermini_config_error_revision = revision
        print("[config] Super Mini rechazó ajustes, ID={}".format(revision))
    _dirty = True


async def supermini_config_task(interval_ms=2500):
    last_sent_revision = None
    while True:
        revision = _settings.supermini_config_revision
        if (_en is not None and _en.paired and
                _supermini_config_ack_revision != revision):
            if _en.send_configuration(
                    revision, _settings.supermini_meters_per_pulse,
                    _settings.supermini_debounce_us,
                    _settings.supermini_max_speed_kmh,
                    _settings.b_supermini_factors_milli,
                    _settings.ads_mode):
                if last_sent_revision != revision:
                    print("[config] enviando ajustes al Super Mini, ID={}".format(
                        revision))
                    last_sent_revision = revision
        await asyncio.sleep_ms(interval_ms)


def _on_config_saved():
    global _CONFIG_AP_STOP_REQUESTED
    _CONFIG_AP_STOP_REQUESTED = True


async def config_ap_task():
    global _CONFIG_AP_REQUESTED, _CONFIG_AP_STOP_REQUESTED
    global _CONFIG_AP_RUNNING, _dirty, _field_idx
    while True:
        if _CONFIG_AP_REQUESTED:
            _CONFIG_AP_REQUESTED = False
            _CONFIG_AP_STOP_REQUESTED = False
            server = ConfigServer(
                _settings, _current_raw_batteries, _current_source_cursor,
                _supermini_feedback_status,
                _apply_configuration, _on_config_saved, _current_sd_logger)
            try:
                await server.start()
            except Exception as exc:
                print("[config] no se pudo iniciar el AP:", exc)
                try:
                    await server.stop()
                except Exception as stop_exc:
                    print("[config] no se pudo limpiar el AP:", stop_exc)
                _CONFIG_AP_RUNNING = False
                _dirty = True
                await asyncio.sleep_ms(250)
                continue
            _CONFIG_AP_RUNNING = True
            _dirty = True
            try:
                while (not _CONFIG_AP_STOP_REQUESTED and
                       not _STOP_REQUESTED and not _SLEEP_REQUESTED):
                    await asyncio.sleep_ms(100)
            finally:
                await server.stop()
                _CONFIG_AP_RUNNING = False
                _CONFIG_AP_STOP_REQUESTED = False
                _field_idx = 0
                _dirty = True
        await asyncio.sleep_ms(100)


# ── Botones ──────────────────────────────────────────────────────────────────

def _note_button_activity():
    """Cualquier gesto de botón reinicia los temporizadores de auto-sleep
    (ver idle_sleep_task) -- si el usuario sigue interactuando con el
    equipo, no tiene sentido contar eso como "parado"/"abandonado"."""
    global _last_button_activity_ms
    _last_button_activity_ms = time.ticks_ms()


def _with_activity(fn):
    def wrapped():
        _note_button_activity()
        fn()
    return wrapped


def _on_next():
    global _field_idx, _dirty
    _field_idx = (_field_idx + 1) % _page_count()
    _dirty = True


def _on_home():
    global _field_idx, _dirty, _CONFIG_AP_REQUESTED
    global _CONFIG_AP_STOP_REQUESTED
    _field_idx = 0
    if _CONFIG_AP_RUNNING or _CONFIG_AP_REQUESTED:
        _CONFIG_AP_REQUESTED = False
        _CONFIG_AP_STOP_REQUESTED = True
        print("[config] cerrando AP sin guardar; regreso a VELOCIDAD")
    _dirty = True


def _on_prev():
    global _field_idx, _dirty
    if _CONFIG_AP_RUNNING or _CONFIG_AP_REQUESTED:
        _on_home()
        return
    _field_idx = (_field_idx - 1) % _page_count()
    _dirty = True


def _on_reset_trip():
    """Marca el inicio del periodo a considerar (tipicamente post-recarga):
    pone en cero Wh usados y distancia de viaje, anclando ambos al dato
    crudo actual del Super Mini. El Super Mini no se entera -- sigue
    mandando sus totales de vida entera, el offset vive solo aca."""
    global _dirty
    if _rt is None or _settings is None:
        return
    if _rt.state.source_boot is None:
        print("[trip] sin telemetria del Super Mini todavia; no se puede "
              "marcar el inicio del periodo")
        _show_toast("Reset: sin telemetria Super Mini")
        return
    _settings.mark_pack_charged(
        source_boot=_rt.state.source_boot, source_wh=_rt.raw_wh_total)
    _settings.reset_trip_distance(
        source_boot=_rt.state.source_boot, source_dist_m=_rt.state.dist_m)
    print("[trip] reset: inicio de periodo marcado (Wh usados y distancia en 0)")
    _show_toast("Periodo reiniciado: Wh y distancia en 0")
    _dirty = True


def _on_deep_sleep():
    global _SLEEP_REQUESTED
    _SLEEP_REQUESTED = True
    print("[btn] S3 EXTRA largo (>=2.2s) -- solicitando deep sleep")


def _on_log_toggle():
    global _CONFIG_AP_REQUESTED, _CONFIG_AP_STOP_REQUESTED
    global _charge_wh_accum, _charge_session_active, _dirty
    if _field_idx == len(FIELDS) + 3:
        _charge_wh_accum = 0.0
        _charge_session_active = False
        _dirty = True
        print("[carga] sesion reiniciada (Wh+ = 0)")
        return
    if _field_idx == len(FIELDS) + 2:
        if _CONFIG_AP_RUNNING or _CONFIG_AP_REQUESTED:
            _CONFIG_AP_REQUESTED = False
            _CONFIG_AP_STOP_REQUESTED = True
            print("[config] cerrando AP sin guardar")
        else:
            _CONFIG_AP_REQUESTED = True
            print("[config] iniciando AP; conecta el teléfono a", AP_SSID)
        return
    if _sd_logger is None or not _sd_logger.ready:
        detail = _sd_error if _sd_logger is None else _sd_logger.error
        print("[SD] no se puede cambiar el registro:", detail or "no disponible")
        return
    if _sd_logger.recording or _LOG_MANUAL_OVERRIDE is True:
        log_stop()
    else:
        log_start()


def _enter_deep_sleep():
    if _lora is not None:
        try:
            _lora.sleep()
        except Exception as exc:
            print("[sleep] no se pudo dormir el SX1262:", exc)
    try:
        HW.backlight_off()
        HW.display_power_off()
    except Exception as exc:
        print("[sleep] no se pudo apagar el display:", exc)
    try:
        HW.vext_disable()
    except Exception as exc:
        print("[sleep] no se pudo apagar VEXT/GPS:", exc)

    wake_pin = Pin(HW.MAIN_WAKE_PIN, Pin.IN, Pin.PULL_UP)
    time.sleep_ms(50)
    if wake_pin.value() == 0:
        raise RuntimeError("S3 sigue presionado; sueltalo antes de entrar en deep sleep")
    esp32.wake_on_ext0(wake_pin, 0)
    print("[sleep] deep sleep; presiona S3 (GPIO{}) para despertar".format(
        HW.MAIN_WAKE_PIN))
    machine.deepsleep()


def _on_start_waypoint():
    global _gps_start, _dirty
    if _gps is None:
        print("[GPS] no disponible; revisar UART y alimentacion VEXT")
        _show_toast("Waypoint: GPS no disponible")
        return
    fix = _gps.latest_fix()
    if fix is None:
        print("[GPS] sin fix reciente; waypoint no capturado")
        _show_toast("Waypoint: sin fix GPS")
        return
    _gps_start = (fix["latitude"], fix["longitude"])
    print("[GPS] waypoint Start: lat={:.6f} lon={:.6f} sats={}".format(
        _gps_start[0], _gps_start[1], fix["satellites"]))
    _show_toast("Waypoint OK sat{}: {:.5f},{:.5f}".format(
        fix["satellites"], _gps_start[0], _gps_start[1]))
    _dirty = True


# ── Arranque asyncio (corre dentro del thread de fondo) ─────────────────────

async def _main_async():
    global _rt, _en, _lora, _shared_spi, _sd_logger, _tft, _gps, _dirty
    global _settings
    global IDLE_SLEEP_TIMEOUT_MS
    print("[main] arrancando...")
    print("[power] reset_cause={} wake_reason={}".format(
        machine.reset_cause(), machine.wake_reason()))

    try:
        HW.vext_enable()
        print("[HW] VEXT habilitado para QuickLink/GPS")
    except Exception as exc:
        print("[HW] no se pudo habilitar VEXT:", exc)
    _gps = make_gps()

    _tft = make_display()
    print("[main] display OK {}x{}".format(_tft.width, _tft.height))

    _shared_spi = make_shared_spi()
    _lora = make_lora(_shared_spi)
    _sd_logger = make_sd_logger(_shared_spi)
    try:
        _settings = T190Settings()
    except (OSError, ValueError) as exc:
        print("[config] archivo de ajustes inválido; se usarán defaults:", exc)
        _settings = T190Settings(load_existing=False)
    IDLE_SLEEP_TIMEOUT_MS = _settings.idle_sleep_timeout_min * 60 * 1000
    _rt = TelemetryRuntime(lora=_lora)

    def on_telemetry(payload):
        accepted = _rt.on_telemetry(payload)
        if accepted:
            try:
                _settings.note_source_energy(
                    _rt.state.source_boot, _rt.raw_wh_total,
                    _rt.pack_voltage_ratio)
                _settings.note_source_distance(
                    _rt.state.source_boot, _rt.state.dist_m)
            except (OSError, ValueError) as exc:
                print("[energy] no se pudo guardar el estado del pack:", exc)
        return accepted

    _en = make_espnow(on_telemetry, _on_supermini_config_ack)

    # S3 (GPIO21): short = anterior, double = reset, long = waypoint GPS,
    # extra (>=2.2s) = deep sleep; la accion se ejecuta al soltar el boton.
    irq_trigger = Pin.IRQ_FALLING | Pin.IRQ_RISING
    page_btn = InterruptPageButton(
        Pin(HW.PAGE_BTN_PIN, Pin.IN, Pin.PULL_UP),
        short=_with_activity(_on_prev), double=_with_activity(_on_reset_trip),
        long=_with_activity(_on_start_waypoint),
        extra=_with_activity(_on_deep_sleep), label="S3",
        irq_trigger=irq_trigger, debounce_ms=25,
    )
    # BTN0: short avanza; double vuelve a VELOCIDAD; long gestiona el AP en
    # CONFIGURACION o alterna el log SD en las demas pantallas.
    btn0 = InterruptPageButton(
        Pin(HW.BTN0_PIN, Pin.IN, Pin.PULL_UP),
        short=_with_activity(_on_next), double=_with_activity(_on_home),
        long=_with_activity(_on_log_toggle), label="BTN0",
        irq_trigger=irq_trigger, debounce_ms=25,
    )
    _dirty = True
    tasks = [
        asyncio.create_task(_rt.lora_task()),
        asyncio.create_task(ui_task(_tft)),
        asyncio.create_task(battery_task()),
        asyncio.create_task(gps_task()),
        asyncio.create_task(page_btn.task()),
        asyncio.create_task(btn0.task()),
        asyncio.create_task(config_ap_task()),
        asyncio.create_task(supermini_config_task()),
    ]
    tasks.append(asyncio.create_task(idle_sleep_task()))
    tasks.append(asyncio.create_task(sd_log_task()))
    tasks.append(asyncio.create_task(charge_monitor_task()))

    if _en is not None:
        tasks.append(asyncio.create_task(_en.listen_task()))

    try:
        while not _STOP_REQUESTED and not _SLEEP_REQUESTED:
            await asyncio.sleep_ms(200)
    finally:
        for t in tasks:
            try:
                t.cancel()
            except Exception:
                pass
        page_btn.close()
        btn0.close()
        print("[main] detenido")


def _bg():
    global _RUNNING, _STOP_REQUESTED, _SLEEP_REQUESTED
    try:
        asyncio.run(_main_async())
    except Exception as exc:
        print("[main] error fatal en hilo de fondo:", exc)
        try:
            sys.print_exception(exc)
        except Exception:
            pass
    finally:
        if _settings is not None:
            try:
                _settings.save()
            except Exception as exc:
                print("[config] error al persistir ajustes:", exc)
        if _sd_logger is not None:
            try:
                _sd_logger.deinit()
            except Exception as exc:
                print("[SD] error al cerrar/desmontar:", exc)
        if _gps is not None:
            try:
                _gps.deinit()
            except Exception as exc:
                print("[GPS] error al cerrar UART:", exc)
        try:
            HW.vext_disable()
        except Exception as exc:
            print("[HW] no se pudo deshabilitar VEXT:", exc)
        if _SLEEP_REQUESTED:
            try:
                _enter_deep_sleep()
            except Exception as exc:
                print("[sleep] deep sleep fallo:", exc)
                try:
                    sys.print_exception(exc)
                except Exception:
                    pass
        _RUNNING = False
        _STOP_REQUESTED = False
        _SLEEP_REQUESTED = False


def start():
    """Arranca la app en un thread de fondo. No bloquea -> REPL libre."""
    global _RUNNING, _STOP_REQUESTED, _SLEEP_REQUESTED, _LOG_MANUAL_OVERRIDE
    if _RUNNING:
        print("[main] ya esta corriendo")
        return False
    _STOP_REQUESTED = False
    _SLEEP_REQUESTED = False
    _LOG_MANUAL_OVERRIDE = None
    _CONFIG_AP_REQUESTED = False
    _CONFIG_AP_STOP_REQUESTED = False
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


def next_field():
    """Avanza a la siguiente pantalla (equivalente a BTN0 corto)."""
    _on_next()
    print("[main] campo ->", _page_label(_field_idx))


def prev_field():
    """Retrocede a la pantalla anterior (equivalente a S3 corto)."""
    _on_prev()
    print("[main] campo ->", _page_label(_field_idx))


def reset_trip():
    """Resetea distancia y Wh de viaje (equivalente al reset de boton)."""
    _on_reset_trip()


def espnow_status():
    """Estado del enlace ESP-NOW con el Super Mini (llamar desde el REPL)."""
    if _en is None:
        print("[espnow] no inicializado")
        return
    print("[espnow] emparejado={} peer={} fresh={} rx_count={} seq={} adc={} current={}".format(
        _en.paired, mac_str(_en.peer), _en.fresh,
        _rt.state.espnow_rx_count if _rt else 0,
        _rt.state.source_seq if _rt else None,
        _rt.state.adc_valid if _rt else False,
        _rt.state.current_valid if _rt else False))


def espnow_repair():
    """Olvida el peer ESP-NOW actual y vuelve a modo pairing (escucha
    broadcast). Usar si cambiaste de Super Mini o la MAC dejo de responder."""
    global _supermini_config_ack_revision, _supermini_config_error
    global _supermini_config_error_revision
    if _en is None:
        print("[espnow] no inicializado")
        return
    _supermini_config_ack_revision = None
    _supermini_config_error = None
    _supermini_config_error_revision = None
    _en.repair()


def status():
    """Snapshot on-demand de la telemetria actual (llamar desde el REPL)."""
    if _rt is None:
        print("[main] aun no inicializado")
        return
    st = _rt.state
    if _field_idx == len(FIELDS):
        page_text, value_text = "DIAGNOSTICO", "--"
    elif _field_idx == len(FIELDS) + 2:
        page_text, value_text = "CONFIGURACION", (
            "AP activo" if _CONFIG_AP_RUNNING else "AP apagado")
    elif _field_idx == len(FIELDS) + 1:
        page_text, value_text = "AYUDA BOTONES", "BTN0 / B21"
    elif _field_idx == len(FIELDS) + 3:
        st = _rt.state
        page_text = "CARGA"
        value_text = "I={:.2f}A Wh+={:.1f}".format(
            st.i_bat,
            (_settings.precharge_wh if _settings else 0.0) + _charge_wh_accum)
    else:
        group, label, code, unit, fmt, getter = FIELDS[_field_idx][:6]
        page_text, value_text = "{} / {}".format(group, label), fmt.format(getter(st))
    battery_text = "n/a" if _battery_voltage is None else (
        "{:.2f}V/{}% ADC={} pin={:.3f}V {}".format(
            _battery_voltage, _battery_percent, _battery_adc_raw,
            _battery_adc_pin_voltage, _battery_adc_read_method))
    gps_fix = _gps.latest_fix() if _gps is not None else None
    gps_text = "sin fix" if gps_fix is None else "{:.6f},{:.6f}".format(
        gps_fix["latitude"], gps_fix["longitude"])
    print("[STATUS] pantalla={}({}) T190_BAT={} GPS={} I={:.2f}A "
          "B1={:.2f} B2={:.2f} B3={:.2f} B4={:.2f} VBATS={:.2f}V "
          "P={:.0f}W PA={:.0f}W V={:.1f}km/h D={:.0f}m "
          "WI={:.1f} WA={:.1f} WT={:.1f}Wh PACK={}% REM={}/{}Wh "
          "VF={} AV={} IV={} AGE={}ms LoRaTXlocal={}#{} "
          "ESPNOW={}#{}".format(
        page_text, value_text, battery_text, gps_text,
        st.i_bat, st.v_b1, st.v_b2, st.v_b3, st.v_b4, st.v_bats,
        st.p_inst, st.p_avg5s, st.speed_kmh, st.dist_m,
        st.whkm_inst, st.whkm_avg, st.wh_total,
        _settings.battery_percent if _settings else None,
        _settings.battery_remaining_wh if _settings else None,
        _settings.battery_capacity_wh if _settings else None,
        _settings.b_supermini_factors_milli if _settings else None,
        st.adc_valid, st.current_valid, _rt.source_age_ms(),
        st.lora_ok, st.lora_tx_count,
        _en.fresh if _en else False, st.espnow_rx_count,
    ))


def config_status():
    """Muestra si el Super Mini recibió y guardó los ajustes del T190."""
    if _settings is None:
        print("[config] todavía no inicializado")
        return
    print("[config] Super Mini: {}; revision={}; recorrido={:.1f}cm/pulso "
          "anti-rebote={}us; max={}km/h; factores gruesos={}".format(
        _supermini_feedback_status(), _settings.supermini_config_revision,
        _settings.supermini_meters_per_pulse * 100.0,
        _settings.supermini_debounce_us,
        _settings.supermini_max_speed_kmh,
        _settings.b_supermini_factors_milli))


def battery_status():
    """Lee VBAT ahora y muestra tension, ADC crudo y SOC por REPL."""
    global _battery_voltage, _battery_percent, _battery_error
    global _battery_adc_raw, _battery_adc_pin_voltage
    global _battery_adc_read_method
    try:
        sample = HW.read_system_battery_sample()
        _battery_voltage = sample["voltage_v"]
        _battery_percent = percent_from_voltage(_battery_voltage)
        _battery_adc_raw = sample["raw_median"]
        _battery_adc_pin_voltage = sample["pin_voltage_v"]
        _battery_adc_read_method = sample["read_method"]
        _battery_error = None
    except Exception as exc:
        _battery_voltage = None
        _battery_percent = None
        _battery_adc_raw = None
        _battery_adc_pin_voltage = None
        _battery_adc_read_method = None
        _battery_error = "{}".format(exc)
        print("[battery] error de lectura:", exc)
        return
    print("[battery] {:.3f} V, {}%, GPIO6={:.4f} V, ADC raw={}, metodo={}".format(
        _battery_voltage, _battery_percent, _battery_adc_pin_voltage,
        _battery_adc_raw, _battery_adc_read_method))


def log_start():
    """Solicita inicio manual del log; la escritura la hace la tarea asyncio."""
    global _LOG_MANUAL_OVERRIDE
    if _sd_logger is None or not _sd_logger.ready:
        detail = _sd_error if _sd_logger is None else _sd_logger.error
        print("[SD] no disponible:", detail or "sin tarjeta montada")
        return False
    _LOG_MANUAL_OVERRIDE = True
    print("[SD] inicio manual solicitado")
    return True


def log_stop():
    """Solicita detener el log sin escribir desde el hilo del REPL."""
    global _LOG_MANUAL_OVERRIDE
    if _sd_logger is None:
        print("[SD] logger no inicializado")
        return False
    _LOG_MANUAL_OVERRIDE = False
    print("[SD] detencion manual solicitada")
    return True


def log_auto():
    """Vuelve al modo automatico: iniciar al detectar movimiento."""
    global _LOG_MANUAL_OVERRIDE
    if _sd_logger is None or not _sd_logger.ready:
        detail = _sd_error if _sd_logger is None else _sd_logger.error
        print("[SD] no disponible:", detail or "sin tarjeta montada")
        return False
    _LOG_MANUAL_OVERRIDE = None
    print("[SD] modo automatico habilitado")
    return True


def log_status():
    """Muestra estado del montaje y archivo de registro."""
    if _sd_logger is None:
        print("[SD] no inicializado:", _sd_error or "sin bus compartido")
        return
    print("[SD] ready={} recording={} file={} mode={} error={}".format(
        _sd_logger.ready, _sd_logger.recording, _sd_logger.path,
        "auto" if _LOG_MANUAL_OVERRIDE is None else
        ("manual-on" if _LOG_MANUAL_OVERRIDE else "manual-off"),
        _sd_logger.error))


def deep_sleep():
    """Solicita deep sleep; S3/GPIO21 en nivel bajo es la fuente de despertar."""
    global _SLEEP_REQUESTED, _STOP_REQUESTED
    _SLEEP_REQUESTED = True
    if _RUNNING:
        _STOP_REQUESTED = True
        print("[sleep] solicitud aceptada; cerrando tareas antes de dormir")
        return True
    _enter_deep_sleep()
    return True


def gps_status():
    """Muestra por REPL el ultimo fix GPS y el waypoint Start capturado."""
    if _gps is None:
        print("[GPS] no inicializado")
        return
    fix = _gps.latest_fix()
    if fix is None:
        print("[GPS] sin fix reciente; satelites={} bytes_invalidos={}".format(
            _gps.satellites, _gps.invalid_bytes))
        return
    print("[GPS] fix lat={:.6f} lon={:.6f} sats={} speed={:.1f}km/h "
          "bytes_invalidos={} Start={}".format(
        fix["latitude"], fix["longitude"], fix["satellites"],
        fix["speed_kmh"], _gps.invalid_bytes, _gps_start))


if AUTO_START:
    start()
