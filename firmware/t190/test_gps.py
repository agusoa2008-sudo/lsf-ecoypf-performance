# test_gps.py -- prueba de GPS NMEA en el conector QuickLink
#
# Cableado (conector SH1.0-4P, pines GND / 3V3 / GPIO2 / GPIO1):
#   GPIO1 (ESP32) <-- TX GPS   (ESP32 RECIBE  -> UART1 RX)
#   GPIO2 (ESP32) --> RX GPS   (ESP32 TRANSMITE -> UART1 TX)
#   GND           <-> GND GPS
#   3V3           --> VIN GPS
#
# GPS: Adafruit Ultimate GPS Breakout, chipset MTK3339
#      https://www.adafruit.com/product/746
# Salida de fabrica: NMEA 0183 a 9600 baud, 1 Hz ($GPGGA/$GPRMC/$GPGSA/$GPGSV/$GPVTG).
# Primer fix en frio: ~30-60s, requiere antena con vista al cielo.
#
# Uso: mpremote run test_gps.py   (o copiar al ESP32 y ejecutar desde el REPL)
# Ctrl-C para detener.

import time
from machine import UART

import HW

UART_ID  = HW.GPS_UART_ID
GPS_RX   = HW.GPS_RX_PIN
GPS_TX   = HW.GPS_TX_PIN
GPS_BAUD = HW.GPS_BAUDRATE

NO_DATA_WARNING_S = 5   # avisar si no llega nada en N segundos

try:
    HW.vext_enable()
    print("[test_gps] VEXT habilitado (si el GPS cuelga del 3V3 directo, esto no hace falta)")
except Exception as e:
    print("[test_gps] HW.vext_enable() no disponible ({}), asumiendo GPS en 3V3 directo".format(e))

uart = UART(UART_ID, baudrate=GPS_BAUD, tx=GPS_TX, rx=GPS_RX, timeout=1000)


def nmea_checksum_ok(sentence):
    if "*" not in sentence:
        return False
    body, _, chk = sentence.partition("*")
    body = body.lstrip("$")
    calc = 0
    for ch in body:
        calc ^= ord(ch)
    try:
        return calc == int(chk.strip(), 16)
    except ValueError:
        return False


def to_decimal(value, direction):
    if not value or not direction:
        return None
    try:
        raw = float(value)
    except ValueError:
        return None
    degrees = int(raw / 100)
    minutes = raw - degrees * 100
    dec = degrees + minutes / 60.0
    if direction in ("S", "W"):
        dec = -dec
    return dec


def parse_gga(fields):
    # $GPGGA,hhmmss.ss,lat,N/S,lon,E/W,fix,numsat,hdop,alt,M,geoid,M,age,stationID
    try:
        return {
            "fix": int(fields[6]) if fields[6] else 0,
            "sats": int(fields[7]) if fields[7] else 0,
            "lat": to_decimal(fields[2], fields[3]),
            "lon": to_decimal(fields[4], fields[5]),
            "alt_m": float(fields[9]) if fields[9] else None,
            "time": fields[1],
        }
    except (IndexError, ValueError):
        return None


def parse_rmc(fields):
    # $GPRMC,hhmmss.ss,status,lat,N/S,lon,E/W,speed_kn,course,ddmmyy,...
    try:
        return {
            "valid": fields[2] == "A",
            "lat": to_decimal(fields[3], fields[4]),
            "lon": to_decimal(fields[5], fields[6]),
            "speed_kmh": float(fields[7]) * 1.852 if fields[7] else 0.0,
            "course": float(fields[8]) if fields[8] else None,
            "date": fields[9],
        }
    except (IndexError, ValueError):
        return None


print("[test_gps] UART{} rx=GPIO{} tx=GPIO{} @ {} baud -- esperando NMEA...".format(
    UART_ID, GPS_RX, GPS_TX, GPS_BAUD))

last_rx = time.ticks_ms()

try:
    while True:
        line = uart.readline()
        if not line:
            if time.ticks_diff(time.ticks_ms(), last_rx) > NO_DATA_WARNING_S * 1000:
                print("[test_gps] sin datos hace {}s -- revisar TX/RX cruzado (GPIO1<-TX GPS, "
                      "GPIO2->RX GPS), alimentacion del GPS y baudrate".format(NO_DATA_WARNING_S))
                last_rx = time.ticks_ms()
            continue

        last_rx = time.ticks_ms()
        try:
            sentence = line.decode("ascii", "ignore").strip()
        except Exception:
            continue

        if not sentence.startswith("$"):
            continue

        print(sentence)

        if not nmea_checksum_ok(sentence):
            continue

        fields = sentence.split(",")
        kind = fields[0]

        if kind in ("$GPGGA", "$GNGGA"):
            gga = parse_gga(fields)
            if gga:
                if gga["fix"] == 0:
                    print("  -> sin fix ({} satelites)".format(gga["sats"]))
                else:
                    print("  -> fix={} sats={} lat={} lon={} alt={}m".format(
                        gga["fix"], gga["sats"], gga["lat"], gga["lon"], gga["alt_m"]))

        elif kind in ("$GPRMC", "$GNRMC"):
            rmc = parse_rmc(fields)
            if rmc:
                estado = "valido" if rmc["valid"] else "sin fix"
                print("  -> RMC {} lat={} lon={} vel={:.1f}km/h rumbo={} fecha={}".format(
                    estado, rmc["lat"], rmc["lon"], rmc["speed_kmh"], rmc["course"], rmc["date"]))

except KeyboardInterrupt:
    pass
finally:
    print("[test_gps] detenido.")
