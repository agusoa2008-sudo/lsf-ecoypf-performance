"""Connect the T190 to a configured Wi-Fi network with a fixed test address."""

import network
import time

import wifi_config


CONNECT_TIMEOUT_MS = 15000
POLL_INTERVAL_MS = 100
NETMASK = "255.255.255.0"
GATEWAY = "192.168.0.1"
DNS = "8.8.8.8"


def connect():
    access_point = network.WLAN(network.AP_IF)
    if access_point.active():
        access_point.active(False)

    station = network.WLAN(network.STA_IF)
    station.active(True)
    if station.isconnected():
        print("[wifi] ya conectado; IP={}".format(station.ifconfig()[0]))
        return station

    last_error = None
    for candidate in wifi_config.NETWORKS:
        ssid = candidate.get("ssid")
        password = candidate.get("password")
        if not ssid or password is None:
            continue

        if station.isconnected():
            station.disconnect()
        ip = candidate.get("ip")
        if ip:
            station.ifconfig((
                ip,
                candidate.get("netmask", NETMASK),
                candidate.get("gateway", GATEWAY),
                candidate.get("dns", DNS),
            ))

        print("[wifi] conectando a {}".format(ssid))
        try:
            station.connect(ssid, password)
            started = time.ticks_ms()
            while not station.isconnected():
                if time.ticks_diff(time.ticks_ms(), started) >= CONNECT_TIMEOUT_MS:
                    raise OSError("timeout conectando a {}".format(ssid))
                time.sleep_ms(POLL_INTERVAL_MS)
            print("[wifi] conectado; IP={}".format(station.ifconfig()[0]))
            return station
        except OSError as exc:
            last_error = exc
            print("[wifi] fallo en {}: {}".format(ssid, exc))

    if last_error is not None:
        raise OSError("no se pudo conectar a ninguna red: {}".format(last_error))
    raise OSError("wifi_config.NETWORKS no contiene redes configuradas")


sta = connect()
