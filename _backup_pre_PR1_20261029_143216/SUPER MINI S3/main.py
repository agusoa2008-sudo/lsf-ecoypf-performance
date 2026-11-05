# main.py — ESP32-S3 Super Mini: sensores de bateria + pulso de velocidad
#
# - ADS1220 (SPI) -> I_BAT, sensor Hall toroidal (placa "LSF").
# - ADS1115 (I2C) -> V_B1..V_B4 individuales y VBATS (total). El banco es un
#   stack serie de 4 baterias con TOMAS ACUMULATIVAS:
#     A0 = B1          (tap0)
#     A1 = B2+B1       (tap1)
#     A2 = B3+B2+B1    (tap2)
#     A3 = B4+B3+B2+B1 (tap3 = VBAT total del pack, ej. 56.0V)
#   Cada tap tiene su propio divisor resistivo -> config.json tiene un
#   ratio por canal. Cada segmento sale de restar taps consecutivos ya
#   escalados; VBATS es la suma B1+B2+B3+B4 (igual al tap3).
# - HW.SPEED_PULSE_PIN -> conteo de pulsos de velocidad del motor (IRQ).
#   Crudo por ahora: SIN acondicionamiento analogico/filtrado todavia --
#   sirve para arrancar a probar el pipeline de distancia/velocidad
#   mientras tanto.
# - LED RGB onboard (NeoPixel, GPIO48) como indicador de estado por color
#   (ver status_led.py): verde = todo OK, amarillo = falta algun sensor,
#   rojo = ninguno responde, azul = arrancando.
#
# Calibracion/conversion (ratios de divisor, sensibilidad de corriente,
# metros por pulso) vive en config.json, NO en este archivo ni en HW.py --
# ver config.py. Editar el JSON y llamar reload_config() desde el REPL para
# probar valores nuevos sin reflashear.
#
# Esta placa hace todas las cuentas (Wh, potencia, eficiencia Wh/km) y las
# manda por ESP-NOW al T190 (display remoto) -- ver espnow_link.py para el
# protocolo de pairing (Super Mini = iniciador, T190 = quien acepta). A
# ~1m de distancia el enlace ESP-NOW va a andar con margen de sobra, no es
# una restriccion de diseño.
#
# Patron "REPL libre" (igual que los demas main.py del proyecto): toda la
# lectura corre en un _thread aparte con asyncio adentro. Al bootear,
# main.py arranca el hilo y retorna enseguida -- la consola queda
# disponible para llamar status() / stop() / start() / reload_config() /
# dump_config() / debug() directo (sin `import main`).

import _thread
import sys
import time
import math
import machine
import esp32
import os
import uasyncio as asyncio

import HW
import config
import trip_store
from drivers.ads1115 import ADS1115
from drivers.ads1220 import ADS1220
from status_led import StatusLed
from espnow_link import EspNowLink, mac_str

INTERVAL_MS = 250
ESPNOW_INTERVAL_MS = 1000
CURRENT_RETRY_MS = 5000
_BOOT_ID = int.from_bytes(os.urandom(4), "little")

AUTO_START = True
_RUNNING = False
_STOP_REQUESTED = False
_BG_THREAD_STACK = 10240
_verbose = False   # debug(True) activa impresion continua de cada lectura

_board = None   # SensorBoard, creado dentro del thread de fondo
_en = None       # EspNowLink, creado dentro del thread de fondo

# Traduccion de errno de OSError (I2C/SPI) a una pista en texto plano --
# MicroPython ya imprime "[Errno N] NOMBRE" en el str(exc), esto solo
# agrega el "por que" tipico para no tener que buscarlo cada vez.
_ERRNO_HINTS = {
    5:   "EIO: el bus respondio pero corto la transaccion a mitad de camino "
         "(NACK inesperado). Revisar alimentacion estable del breakout.",
    19:  "ENODEV: nadie contesto en esa direccion I2C. Revisar VDD/GND del "
         "breakout, que SDA/SCL no esten invertidos, y la direccion (0x48 default).",
    110: "ETIMEDOUT: el I2C no termino la transaccion a tiempo -- tipicamente "
         "bus trabado (SDA o SCL pegados en 0). Probar power-cycle del "
         "breakout, o medir con multimetro que SDA/SCL esten en ~3.3V en reposo.",
    116: "ETIMEDOUT: el I2C no termino la transaccion a tiempo -- tipicamente "
         "bus trabado (SDA o SCL pegados en 0). Probar power-cycle del "
         "breakout, o medir con multimetro que SDA/SCL esten en ~3.3V en reposo.",
}


def _diag_hint(exc):
    code = exc.args[0] if getattr(exc, "args", None) else None
    return _ERRNO_HINTS.get(code, "sin hint conocido para este errno -- ver str(exc) arriba")


class SensorState:
    def __init__(self):
        self.v_b1 = 0.0
        self.v_b2 = 0.0
        self.v_b3 = 0.0
        self.v_b4 = 0.0
        self.v_bats = 0.0
        self.i_bat = 0.0
        self.adc_ok = False
        self.current_ok = False
        self.current_error = ""
        self.pulse_count = 0
        self.pulse_rejected = 0
        self.speed_kmh = 0.0
        self.v_clip = [False, False, False, False]   # canal cerca/en saturacion (ver HW.ADS1115_SAT_WARN_V)

        # Potencia/energia -- calculadas aca (el Super Mini "hace todas las
        # cuentas") y mandadas por ESP-NOW al T190.
        self.p_inst = 0.0     # W, = v_bats (pack total) * i_bat
        self.p_avg5s = 0.0    # W, EMA de 5s
        self.dist_m = 0.0     # distancia acumulada desde el boot (sin reset de trip todavia)
        self.whkm_inst = 0.0
        self.whkm_avg = 0.0
        self.wh_total = 0.0   # Wh acumulados desde el boot

        self.espnow_ok = False
        self.espnow_tx_count = 0
        self.espnow_tx_fail_count = 0


class PulseCounter:
    """Cuenta pulsos del sensor de velocidad via IRQ y estima velocidad
    instantanea desde el periodo entre pulsos. Rechaza intervalos que
    implicarian superar max_speed_kmh y cuenta esos pulsos como ruido."""

    def __init__(self, meters_per_pulse, debounce_us, max_speed_kmh):
        self.meters_per_pulse = meters_per_pulse
        self.debounce_us = debounce_us
        self.max_speed_kmh = max_speed_kmh
        self._min_period_us = self._calculate_min_period_us()
        self._count = 0
        self._rejected_count = 0
        self._last_us = None
        self._last_period_us = 0
        self._pin = HW.make_speed_pulse_pin()
        trigger = (machine.Pin.IRQ_RISING if HW.SPEED_PULSE_EDGE == "RISING"
                   else machine.Pin.IRQ_FALLING)
        self._pin.irq(trigger=trigger, handler=self._on_pulse)

    def _calculate_min_period_us(self):
        if self.meters_per_pulse <= 0 or self.max_speed_kmh <= 0:
            raise ValueError("metros/pulso y velocidad maxima deben ser positivos")
        speed_period_us = int(math.ceil(
            self.meters_per_pulse * 3_600_000 / self.max_speed_kmh))
        return max(int(self.debounce_us), speed_period_us)

    def _on_pulse(self, pin):
        now = time.ticks_us()
        if self._last_us is None:
            self._last_us = now
            self._count += 1
            return
        dt = time.ticks_diff(now, self._last_us)
        if dt < self._min_period_us:
            self._rejected_count += 1
            return
        self._last_period_us = dt
        self._last_us = now
        self._count += 1

    def pulse_count(self):
        return self._count

    def rejected_count(self):
        return self._rejected_count

    def speed_kmh(self):
        if self._last_period_us <= 0:
            return 0.0
        if time.ticks_diff(time.ticks_us(), self._last_us) > 2_000_000:
            return 0.0
        period_s = self._last_period_us / 1_000_000.0
        return (self.meters_per_pulse / period_s) * 3.6


class SensorBoard:
    def __init__(self):
        self._cfg = config.load()
        self.state = SensorState()
        self._led = StatusLed(HW.make_status_led())

        # Restaura Wh/distancia acumulados de antes del ultimo deep sleep
        # (ver trip_store.py y power_task/_enter_deep_sleep mas abajo).
        # _trip_dist_base_m es la base sobre la que se suman los pulsos de
        # esta sesion -- reload_config() la respeta al recalcular dist_m.
        trip = trip_store.load()
        self.state.wh_total = trip["wh_total"]
        self.state.dist_m = trip["dist_m"]
        self._trip_dist_base_m = trip["dist_m"]
        if machine.reset_cause() == machine.DEEPSLEEP_RESET:
            print("[power] wake desde deep sleep (B4 recuperado) -- "
                  "acumulados restaurados: Wh={:.1f} D={:.0f}m".format(
                self.state.wh_total, self.state.dist_m))

        self._b4_pin = HW.make_b4_presence_pin()
        self._b4_lost_since_ms = None

        i2c = HW.make_i2c()
        self._ads1115 = ADS1115(i2c, addr=HW.ADS1115_ADDR)

        spi = HW.make_current_spi()
        sens = self._cfg["battery"]["current_sens_v_per_a"]
        self._ads1220 = ADS1220(spi, HW.CURRENT_CS_PIN, sens_v_per_a=sens)
        self.state.current_ok = self._ads1220.init()
        if self.state.current_ok:
            self._ads1220.calibrate_zero()
            self._current_calibrated = True
            self._current_hw_ready = True
            print("[ADS1220] OK")
        else:
            self._current_calibrated = False
            self._current_hw_ready = False
            print("[ADS1220] config no confirmada por el ADC -- revisar cableado SPI")
        self._current_retry_ms = time.ticks_ms()

        self._pulses = PulseCounter(
            meters_per_pulse=self._cfg["speed"]["meters_per_pulse"],
            debounce_us=self._cfg["speed"]["debounce_us"],
            max_speed_kmh=self._cfg["speed"]["max_speed_kmh"],
        )

    def reload_config(self):
        """Re-lee config.json en caliente -- para ajustar ratios de
        divisor, sensibilidad de corriente o metros/pulso sin reflashear
        ni perder el conteo de pulsos acumulado."""
        cfg = config.load()
        previous_sensitivity = self._cfg["battery"]["current_sens_v_per_a"]
        new_sensitivity = cfg["battery"]["current_sens_v_per_a"]
        if new_sensitivity != previous_sensitivity:
            set_sensitivity = getattr(self._ads1220, "set_sensitivity", None)
            if not callable(set_sensitivity):
                raise RuntimeError(
                    "el driver ADS1220 no permite cambiar sensibilidad en caliente")
            set_sensitivity(new_sensitivity)

        self._cfg = cfg
        self._pulses.meters_per_pulse = cfg["speed"]["meters_per_pulse"]
        self._pulses.debounce_us = cfg["speed"]["debounce_us"]
        self._pulses.max_speed_kmh = cfg["speed"]["max_speed_kmh"]
        self._pulses._min_period_us = self._pulses._calculate_min_period_us()
        self._pulses._last_period_us = 0
        self._pulses._last_us = None
        self.state.dist_m = self._trip_dist_base_m + (
            self._pulses.pulse_count() * self._pulses.meters_per_pulse)
        print("[config] recargado")

    def calibrate_current_zero(self):
        """Calibrate current offset only when the vehicle draws no current."""
        if not self._current_hw_ready:
            raise RuntimeError("ADS1220 no inicializado")
        self._ads1220.calibrate_zero()
        self._current_calibrated = True
        self.state.current_ok = True
        self.state.current_error = ""
        print("[ADS1220] cero calibrado; confirmar con la bateria en reposo")

    async def sensor_task(self, interval_ms=INTERVAL_MS):
        st = self.state
        was_adc_ok = True      # para solo loguear la transicion OK->error, no cada ciclo
        was_current_ok = True  # idem, independiente del ADS1115
        was_clipped = False    # idem para el aviso de saturacion
        tau_s = 5.0             # constante de la EMA de potencia promedio
        last_ms = time.ticks_ms()
        last_pulse_count = self._pulses.pulse_count()
        while True:
            now_ms = time.ticks_ms()
            dt_s = time.ticks_diff(now_ms, last_ms) / 1000.0
            last_ms = now_ms
            if dt_s <= 0:
                dt_s = interval_ms / 1000.0

            # --- ADS1115 (I2C, tensiones) -- independiente del ADS1220 ---
            try:
                ratio = self._cfg["battery"]["tap_divider_ratio"]
                raw = self._ads1115.read_all_volts()
                st.v_clip = [v > HW.ADS1115_SAT_WARN_V for v in raw]
                is_clipped = any(st.v_clip)
                if is_clipped and not was_clipped:
                    chans = [i for i, c in enumerate(st.v_clip) if c]
                    print("[ADS1115] canal(es) {} cerca de VDD ({:.2f}V) -- lectura probablemente clipeada".format(
                        chans, HW.ADS1115_VDD))
                was_clipped = is_clipped

                taps = [raw[i] * ratio[i] for i in range(4)]
                if self._cfg["battery"].get("ads_mode", "cumulative") == "individual":
                    battery_raw = tuple(taps)
                else:
                    battery_raw = (
                        taps[0], taps[1] - taps[0],
                        taps[2] - taps[1], taps[3] - taps[2])
                voltage_factors = self._cfg["battery"]["voltage_factor_milli"]
                st.v_b1 = battery_raw[0] * voltage_factors[0] / 1000.0
                st.v_b2 = battery_raw[1] * voltage_factors[1] / 1000.0
                st.v_b3 = battery_raw[2] * voltage_factors[2] / 1000.0
                st.v_b4 = battery_raw[3] * voltage_factors[3] / 1000.0
                st.v_bats = st.v_b1 + st.v_b2 + st.v_b3 + st.v_b4
                st.adc_ok = True
                if not was_adc_ok:
                    print("[ADS1115] recuperado")
                was_adc_ok = True
            except Exception as exc:
                st.adc_ok = False
                if was_adc_ok:
                    print("[ADS1115] error:", exc, "--", _diag_hint(exc),
                          "(no se repite el log hasta que se recupere; probar main.diag())")
                was_adc_ok = False

            # --- ADS1220 (SPI, corriente) -- independiente del ADS1115 ---
            if st.current_ok:
                try:
                    st.i_bat = self._ads1220.read_current()
                    st.current_error = ""
                    if not was_current_ok:
                        print("[ADS1220] recuperado")
                    was_current_ok = True
                except Exception as exc:
                    st.current_ok = False
                    st.i_bat = 0.0
                    st.current_error = "{}".format(exc)
                    self._current_retry_ms = now_ms
                    self._current_hw_ready = False
                    was_current_ok = False
                    print("[ADS1220] error:", exc, "--", _diag_hint(exc))
            elif (not self._current_hw_ready and
                  time.ticks_diff(now_ms, self._current_retry_ms) >= CURRENT_RETRY_MS):
                self._current_retry_ms = now_ms
                try:
                    if self._ads1220.init():
                        self._current_hw_ready = True
                        if not self._current_calibrated:
                            st.current_error = "cero pendiente; usar main.calibrate_current_zero() en reposo"
                            print("[ADS1220] reinicializado; falta calibrar cero con corriente nula")
                        else:
                            st.current_ok = True
                            st.current_error = ""
                            was_current_ok = False
                            print("[ADS1220] reinicializado")
                    else:
                        st.current_error = "configuracion no confirmada"
                except Exception as exc:
                    st.current_error = "{}".format(exc)
                    print("[ADS1220] reintento de inicializacion fallo:", exc)

            st.pulse_count = self._pulses.pulse_count()
            st.pulse_rejected = self._pulses.rejected_count()
            st.speed_kmh = self._pulses.speed_kmh()
            pulse_delta = st.pulse_count - last_pulse_count
            last_pulse_count = st.pulse_count
            if pulse_delta > 0:
                st.dist_m += pulse_delta * self._pulses.meters_per_pulse

            # --- Potencia/energia (solo si hay V e I validos) ---
            if st.adc_ok and st.current_ok:
                st.p_inst = st.v_bats * st.i_bat
                alpha = dt_s / tau_s if dt_s < tau_s else 1.0
                st.p_avg5s += (st.p_inst - st.p_avg5s) * alpha
                st.wh_total += st.p_inst * (dt_s / 3600.0)
                st.whkm_inst = (st.p_inst / st.speed_kmh) if st.speed_kmh > 0.5 else 0.0
                km_total = st.dist_m / 1000.0
                st.whkm_avg = (st.wh_total / km_total) if km_total > 0.01 else 0.0
            else:
                st.p_inst = 0.0
                st.whkm_inst = 0.0

            self._led.update_health(st.adc_ok, st.current_ok)
            if _verbose:
                _print_status(st)
            await asyncio.sleep_ms(interval_ms)

    async def led_task(self, interval_ms=300):
        """Hace parpadear el status LED a ritmo fijo, independiente de
        cada cuanto se leen los sensores (ver status_led.py: tick)."""
        while True:
            self._led.tick()
            await asyncio.sleep_ms(interval_ms)

    def b4_present(self):
        """True si GPIO11 lee alto (B4 presente, ver HW.B4_PRESENCE_PIN)."""
        return bool(self._b4_pin.value())

    async def power_task(self, interval_ms=1000):
        """Vigila la presencia de B4 (GPIO11) y los pulsos de velocidad
        (GPIO10). Si el auto se apaga (B4 ausente) y se mantiene asi
        durante config.sleep.b4_loss_timeout_s sin volver, guarda
        Wh/distancia acumulados y entra en deep sleep (ver
        _enter_deep_sleep). Un retorno de B4 O un pulso de velocidad
        (rueda girando -- el auto esta en movimiento, no puede estar sin
        B4 de verdad) cancelan la cuenta regresiva. timeout 0 desactiva
        el sleep automatico (util en banco sin el auto)."""
        last_pulse_count = self._pulses.pulse_count()
        while True:
            timeout_s = self._cfg["sleep"]["b4_loss_timeout_s"]
            pulse_count = self._pulses.pulse_count()
            moving = pulse_count != last_pulse_count
            last_pulse_count = pulse_count

            if timeout_s <= 0:
                self._b4_lost_since_ms = None
                await asyncio.sleep_ms(interval_ms)
                continue

            now_ms = time.ticks_ms()
            if self.b4_present() or moving:
                if self._b4_lost_since_ms is not None:
                    reason = "B4 recuperado" if self.b4_present() else \
                        "pulso de velocidad (auto en movimiento)"
                    print("[power] {} -- se cancela el sleep".format(reason))
                self._b4_lost_since_ms = None
            else:
                if self._b4_lost_since_ms is None:
                    self._b4_lost_since_ms = now_ms
                    print("[power] B4 ausente -- sleep en {:.0f}s si no vuelve".format(timeout_s))
                elif time.ticks_diff(now_ms, self._b4_lost_since_ms) >= int(timeout_s * 1000):
                    self._enter_deep_sleep()
                    return   # no deberia llegar aca (deepsleep reinicia la placa)
            await asyncio.sleep_ms(interval_ms)

    def _enter_deep_sleep(self):
        """Persiste Wh/distancia (trip_store.save), apaga el LED y entra
        en deep sleep con wake en GPIO11 alto (B4 de vuelta).
        machine.deepsleep() reinicia la placa al despertar --
        SensorBoard.__init__ restaura los acumulados leyendo trip.json."""
        print("[power] guardando acumulados y durmiendo "
              "(Wh={:.1f} D={:.0f}m) -- despierta con B4 (GPIO{} alto)".format(
            self.state.wh_total, self.state.dist_m, HW.B4_PRESENCE_PIN))
        trip_store.save(self.state.wh_total, self.state.dist_m)
        esp32.wake_on_ext1((self._b4_pin,), esp32.WAKEUP_ANY_HIGH)
        # El NeoPixel retiene el ultimo color escrito aunque el CPU se
        # duerma -- apagarlo antes, si no queda prendido drenando
        # corriente durante todo el deep sleep.
        self._led.off()
        machine.deepsleep()


def _print_status(st):
    i_str = "{:.3f}A".format(st.i_bat) if st.current_ok else "--"
    clip_str = "".join("A{}".format(i) for i, c in enumerate(st.v_clip) if c) or "--"
    print("[STATUS] B1={:.2f}V B2={:.2f}V B3={:.2f}V B4={:.2f}V "
          "VBATS={:.2f}V I={} "
          "pulsos={} rechazados={} v={:.1f}km/h ADC={} CURR={} CLIP={}".format(
        st.v_b1, st.v_b2, st.v_b3, st.v_b4, st.v_bats, i_str,
        st.pulse_count, st.pulse_rejected, st.speed_kmh,
        st.adc_ok, st.current_ok, clip_str,
    ))


# ── ESP-NOW (Super Mini = iniciador, ver espnow_link.py) ────────────────────

def _apply_remote_configuration(payload):
    fields = {}
    for part in payload.split(";"):
        key, separator, value = part.partition("=")
        if not separator or not key or not value or key in fields:
            raise ValueError("campo de configuración ESP-NOW inválido")
        fields[key] = value
    required = ("V", "ID", "MP", "DB", "MAX", "F1", "F2", "F3", "F4", "AM")
    missing = [key for key in required if key not in fields]
    if missing or fields.get("V") != "1":
        raise ValueError("versión o campos de configuración ESP-NOW inválidos")
    config_id = int(fields["ID"])
    if config_id < 1 or config_id > 0xFFFFFFFF:
        raise ValueError("ID de configuración fuera de rango")
    am_field = fields.get("AM", "C")
    ads_mode = "individual" if am_field == "I" else "cumulative"
    changed = config.apply_remote_configuration(
        config_id, float(fields["MP"]), int(fields["DB"]),
        float(fields["MAX"]),
        [int(fields["F{}".format(index)]) for index in range(1, 5)],
        ads_mode)
    if _board is not None:
        _board.reload_config()
    if changed:
        print("[config] actualización remota aplicada, ID={}".format(config_id))
    else:
        print("[config] actualización remota ya aplicada, ID={}".format(config_id))
    return True


def _build_payload(st, seq):
    """Versioned snapshot including sensor validity and the pulse counter."""
    return (
        "VER=3;BOOT={};Q={};AV={};IV={};PC={};"
        "I={:.2f};B1={:.2f};B2={:.2f};B3={:.2f};B4={:.2f};VBATS={:.2f};"
        "P={:.0f};PA={:.0f};V={:.1f};D={:.0f};"
        "WI={:.1f};WA={:.1f};WT={:.1f}"
    ).format(
        _BOOT_ID, seq, int(st.adc_ok and not any(st.v_clip)), int(st.current_ok),
        st.pulse_count, st.i_bat, st.v_b1, st.v_b2, st.v_b3, st.v_b4, st.v_bats,
        st.p_inst, st.p_avg5s, st.speed_kmh, st.dist_m,
        st.whkm_inst, st.whkm_avg, st.wh_total,
    )


def make_espnow():
    try:
        link = EspNowLink(on_configuration=_apply_remote_configuration)
        if link.paired:
            print("[espnow] OK, peer recordado:", mac_str(link.peer))
        else:
            print("[espnow] OK, buscando T190 (broadcast pairing)...")
        return link
    except Exception as exc:
        print("[espnow] init error:", exc)
        return None


async def espnow_task(interval_ms=ESPNOW_INTERVAL_MS):
    """Manda la telemetria actual al T190 por ESP-NOW (si ya esta
    emparejado) y refleja el estado del link en el status LED (verde/azul
    alternando -- ver status_led.py: set_espnow_connected)."""
    if _en is None or _board is None:
        print("[main] ESP-NOW no inicializado; tarea de envio inactiva")
        return
    seq = 0
    while True:
        st = _board.state
        if _en.paired:
            seq = (seq % 65535) + 1
            payload = _build_payload(st, seq)
            ok = _en.send_telemetry(payload)
            st.espnow_ok = ok
            if ok:
                st.espnow_tx_count += 1
            else:
                st.espnow_tx_fail_count += 1
        else:
            st.espnow_ok = False
        _board._led.set_espnow_connected(_en.paired)
        await asyncio.sleep_ms(interval_ms)


# ── Arranque asyncio (corre dentro del thread de fondo) ─────────────────────

async def _main_async():
    global _board, _en
    _board = SensorBoard()
    _en = make_espnow()
    tasks = [
        asyncio.create_task(_board.sensor_task()),
        asyncio.create_task(_board.led_task()),
        asyncio.create_task(_board.power_task()),
    ]
    if _en is not None:
        tasks.append(asyncio.create_task(_en.pairing_task()))
        tasks.append(asyncio.create_task(espnow_task()))
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
    """Arranca la lectura de sensores en un thread de fondo. No bloquea -> REPL libre."""
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
    """Pide detener la lectura. Con wait_ms>0 espera (bloqueante) a que termine."""
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


def status():
    """Snapshot on-demand de las ultimas lecturas (llamar desde el REPL)."""
    if _board is None:
        print("[main] aun no inicializado")
        return
    _print_status(_board.state)


def _print_values(st):
    i_str = "{:7.3f} A".format(st.i_bat) if st.current_ok else "   --  "
    print("=" * 38)
    print("  TELEMETRIA Super Mini")
    print("=" * 38)
    print("  Corriente (I)     {}".format(i_str))
    print("  Tension B1        {:7.2f} V".format(st.v_b1))
    print("  Tension B2        {:7.2f} V".format(st.v_b2))
    print("  Tension B3        {:7.2f} V".format(st.v_b3))
    print("  Tension B4        {:7.2f} V".format(st.v_b4))
    print("  VBATS total       {:7.2f} V".format(st.v_bats))
    print("-" * 38)
    print("  Potencia inst.    {:7.1f} W".format(st.p_inst))
    print("  Potencia avg 5s   {:7.1f} W".format(st.p_avg5s))
    print("  Velocidad         {:7.1f} km/h".format(st.speed_kmh))
    print("  Distancia         {:7.0f} m".format(st.dist_m))
    print("-" * 38)
    print("  Wh/km inst.       {:7.1f} Wh/km".format(st.whkm_inst))
    print("  Wh/km promedio    {:7.1f} Wh/km".format(st.whkm_avg))
    print("  Wh total          {:7.1f} Wh".format(st.wh_total))
    print("=" * 38)
    clip_str = "".join("A{}".format(i) for i, c in enumerate(st.v_clip) if c) or "--"
    print("  ADC={}  CURR={}  pulsos={} rechazados={}  CLIP={}".format(
        st.adc_ok, st.current_ok, st.pulse_count, st.pulse_rejected, clip_str))
    espnow_str = ("OK #{}".format(st.espnow_tx_count) if (_en and _en.paired)
                  else "esperando T190...")
    print("  ESPNOW={}".format(espnow_str))
    print("=" * 38)


def values(seconds=None):
    """Consola prolija con todos los valores actuales -- I, V, W, km/h,
    Wh, etc (version 'dashboard' de status(), mas facil de leer de un
    vistazo que la linea compacta).

    Sin argumento: una sola foto. values(10): repite 1 vez por segundo
    durante 10s (bloquea el REPL ese rato -- el hilo de fondo sigue
    leyendo sensores igual, esto solo repite el print)."""
    if _board is None:
        print("[main] aun no inicializado")
        return
    if seconds is None:
        _print_values(_board.state)
        return
    n = max(1, int(seconds))
    for i in range(n):
        _print_values(_board.state)
        if i < n - 1:
            time.sleep_ms(1000)


def diag():
    """Diagnostico manual -- llamar desde el REPL cuando algo da error raro
    (ej. ETIMEDOUT/ENODEV). Hace un scan de I2C y resume el estado de cada
    sensor; no toca el SPI del ADS1220 (no tiene scan, solo CS fijo)."""
    print("--- I2C (ADS1115, SDA={} SCL={}) ---".format(HW.I2C_SDA, HW.I2C_SCL))
    try:
        i2c = HW.make_i2c()
        found = i2c.scan()
        if found:
            print("  dispositivos: {} (esperado: 0x{:02X})".format(
                ["0x{:02X}".format(a) for a in found], HW.ADS1115_ADDR))
        else:
            print("  scan vacio -- nadie responde. Revisar VDD/GND del "
                  "breakout y continuidad de SDA/SCL.")
    except Exception as exc:
        print("  scan fallo:", exc, "--", _diag_hint(exc))

    print("--- Estado actual ---")
    if _board is None:
        print("  board no inicializado todavia")
        return
    st = _board.state
    print("  ADS1115: adc_ok={} v_clip={}".format(st.adc_ok, st.v_clip))
    print("  ADS1220: current_ok={} i_bat={:.3f}A".format(st.current_ok, st.i_bat))
    print("  pulso: pin=GPIO{} count={} rechazados={} min_dt={}us "
          "max={}km/h speed={:.1f}km/h".format(
        HW.SPEED_PULSE_PIN, st.pulse_count, st.pulse_rejected,
        _board._pulses._min_period_us, _board._pulses.max_speed_kmh,
        st.speed_kmh))
    if _en is None:
        print("  ESPNOW: no inicializado")
    else:
        print("  ESPNOW: paired={} peer={} tx_count={}".format(
            _en.paired, mac_str(_en.peer), st.espnow_tx_count))


def debug(on=True):
    """Prende/apaga impresion continua de cada lectura (apagado por
    defecto para no ensuciar el REPL). debug(True) para ver el stream en
    vivo, debug(False) para volver a silencioso -- status() sigue andando
    en cualquier momento para un snapshot puntual."""
    global _verbose
    _verbose = on
    print("[main] debug", "ON" if on else "OFF")


def calibrate_current_zero():
    """Calibra el offset del ADS1220; llamar solo con corriente de bateria cero."""
    if _board is None:
        print("[main] aun no inicializado")
        return
    try:
        _board.calibrate_current_zero()
    except Exception as exc:
        print("[ADS1220] calibracion no realizada:", exc)


def reload_config():
    """Re-lee config.json en caliente (ver SensorBoard.reload_config)."""
    if _board is None:
        print("[main] aun no inicializado")
        return
    _board.reload_config()


def dump_config():
    """Imprime la configuracion de calibracion actualmente cargada."""
    if _board is None:
        print("[main] aun no inicializado")
        return
    print("[config]", _board._cfg)


def espnow_status():
    """Estado del enlace ESP-NOW con el T190 (llamar desde el REPL)."""
    if _en is None:
        print("[espnow] no inicializado")
        return
    print("[espnow] emparejado={} peer={} tx_count={}".format(
        _en.paired, mac_str(_en.peer),
        _board.state.espnow_tx_count if _board else 0))


def espnow_repair():
    """Olvida el peer ESP-NOW actual y vuelve a modo pairing (broadcast).
    Usar si cambiaste de T190 o la MAC dejo de responder."""
    if _en is None:
        print("[espnow] no inicializado")
        return
    _en.repair()


def power_status():
    """Estado de la vigilancia de B4 (GPIO11) + pulsos (GPIO10) y cuenta
    regresiva de sleep. Un pulso de velocidad cancela la cuenta igual que
    B4 presente (ver SensorBoard.power_task)."""
    if _board is None:
        print("[main] aun no inicializado")
        return
    timeout_s = _board._cfg["sleep"]["b4_loss_timeout_s"]
    pulsos = _board._pulses.pulse_count()
    suffix = " pulsos={}".format(pulsos)
    if _board.b4_present():
        print("[power] B4 presente (GPIO{}=1), timeout={:.0f}s{}".format(
            HW.B4_PRESENCE_PIN, timeout_s, suffix))
    elif timeout_s <= 0:
        print("[power] B4 ausente (GPIO{}=0), sleep automatico desactivado (timeout=0){}".format(
            HW.B4_PRESENCE_PIN, suffix))
    elif _board._b4_lost_since_ms is None:
        print("[power] B4 ausente (GPIO{}=0), cuenta regresiva por iniciar{}".format(
            HW.B4_PRESENCE_PIN, suffix))
    else:
        elapsed_s = time.ticks_diff(time.ticks_ms(), _board._b4_lost_since_ms) / 1000.0
        remaining_s = max(0.0, timeout_s - elapsed_s)
        print("[power] B4 ausente (GPIO{}=0) hace {:.0f}s -- sleep en {:.0f}s{}".format(
            HW.B4_PRESENCE_PIN, elapsed_s, remaining_s, suffix))


def force_sleep():
    """Fuerza el deep sleep ahora (pruebas de banco) -- persiste los
    acumulados igual que el disparo automatico por perdida de B4.
    Despierta con GPIO11 en alto (puentear a 3.3V para simular B4)."""
    if _board is None:
        print("[main] aun no inicializado")
        return
    _board._enter_deep_sleep()


if AUTO_START:
    start()
