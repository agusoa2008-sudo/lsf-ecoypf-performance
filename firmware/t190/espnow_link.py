# espnow_link.py
# Recepcion de telemetria por ESP-NOW desde el Super Mini (que lee los
# sensores + hace los calculos) -- el T190 es ahora PURO RECEPTOR/display,
# ya no manda telemetria a nadie por ESP-NOW.
#
# Protocolo de pairing (roles fijos: Super Mini = iniciador, T190 = quien
# acepta -- INVERTIDO respecto a la version anterior de este archivo, que
# mandaba telemetria desde el T190 a un segundo display tipo Ideaspark; ese
# caso de uso queda descartado por ahora, ver nota en la conversacion):
#   1) Si hay una MAC guardada en PEER_FILE, el T190 solo acepta pairing/
#      telemetria de esa MAC (no se re-empareja solo con cualquiera).
#   2) Si no hay peer guardado, el T190 escucha broadcasts de
#      PAIR_REQ_MAGIC del Super Mini y contesta PAIR_ACK_MAGIC unicast a
#      esa MAC.
#   3) El Super Mini, al ver PAIR_ACK_MAGIC, guarda la MAC del T190 y pasa
#      a mandar telemetria unicast (prefijo TELEMETRY_PREFIX). El T190
#      también envía ajustes CFG y recibe confirmaciones CFGA/CFGN.
#   4) El T190 guarda la MAC del Super Mini en PEER_FILE al emparejar (ya
#      sea por el ACK o, si se perdio, por el primer paquete de telemetria
#      que llegue de una MAC nueva).
#
# Para reparar (ej: cambiaste de Super Mini o de T190), llamar a
# EspNowLink.repair() (expuesto en main.py como main.espnow_repair()).

import network
import espnow
import uos
import time
import uasyncio as asyncio

PEER_FILE = "espnow_peer.bin"
BROADCAST = b"\xff\xff\xff\xff\xff\xff"
PAIR_REQ_MAGIC = b"SM_PAIR_REQ"      # lo manda el Super Mini
PAIR_ACK_MAGIC = b"T190_PAIR_ACK"    # lo contesta el T190
TELEMETRY_PREFIX = b"TLM:"
CONFIG_ACK_PREFIX = b"CFGA:"
CONFIG_NACK_PREFIX = b"CFGN:"
RESET_ACK_PREFIX = b"RSTA:"
RESET_NACK_PREFIX = b"RSTN:"

STALE_MS = 5000   # sin telemetria nueva en este tiempo -> se considera caida


def mac_str(mac):
    if mac is None:
        return "none"
    return ":".join("{:02X}".format(b) for b in mac)


def _load_peer():
    try:
        with open(PEER_FILE, "rb") as f:
            mac = f.read(6)
        if len(mac) == 6:
            return mac
    except OSError:
        pass
    return None


def _save_peer(mac):
    try:
        with open(PEER_FILE, "wb") as f:
            f.write(mac)
    except OSError as exc:
        print("[espnow] no se pudo guardar el peer:", exc)


class EspNowLink:
    def __init__(self, on_telemetry=None, on_config_ack=None,
                 on_reset_ack=None):
        """on_telemetry: callback(payload_str) -- se llama con cada linea
        de telemetria recibida del Super Mini ya emparejado. on_reset_ack:
        callback(request_id, accepted) -- confirmacion/rechazo del canal
        RST (reset remoto de los acumulados de vida entera del Super
        Mini, ver _apply_remote_reset en su main.py)."""
        self._on_telemetry = on_telemetry
        self._on_config_ack = on_config_ack
        self._on_reset_ack = on_reset_ack
        self._sta = network.WLAN(network.STA_IF)
        self._sta.active(True)
        self._e = espnow.ESPNow()
        self._e.active(True)
        try:
            self._e.add_peer(BROADCAST)
        except OSError:
            pass  # ya estaba agregado (ej: tras un main.stop()/start())

        self.peer = _load_peer()
        self.paired = False
        self.last_rx_ms = 0
        if self.peer is not None:
            try:
                self._e.add_peer(self.peer)
                self.paired = True
                print("[espnow] peer recordado:", mac_str(self.peer))
            except OSError as exc:
                print("[espnow] error al re-agregar peer guardado:", exc)
                self.peer = None

    def repair(self):
        """Olvida el peer actual y vuelve a modo pairing (escucha broadcast)."""
        self.peer = None
        self.paired = False
        self.last_rx_ms = 0
        try:
            uos.remove(PEER_FILE)
        except OSError:
            pass
        print("[espnow] pairing reseteado -- esperando Super Mini")

    @property
    def fresh(self):
        """True si llego telemetria hace menos de STALE_MS."""
        if self.last_rx_ms == 0:
            return False
        return time.ticks_diff(time.ticks_ms(), self.last_rx_ms) < STALE_MS

    def _handle_incoming(self, mac, msg):
        if msg is None:
            return

        if (self.paired and mac == self.peer and
                (msg.startswith(CONFIG_ACK_PREFIX) or
                 msg.startswith(CONFIG_NACK_PREFIX))):
            accepted = msg.startswith(CONFIG_ACK_PREFIX)
            prefix = CONFIG_ACK_PREFIX if accepted else CONFIG_NACK_PREFIX
            try:
                revision = int(msg[len(prefix):].decode())
            except (UnicodeError, ValueError):
                print("[espnow] confirmación de configuración inválida")
                return
            if self._on_config_ack is not None:
                self._on_config_ack(revision, accepted)
            return

        if (self.paired and mac == self.peer and
                (msg.startswith(RESET_ACK_PREFIX) or
                 msg.startswith(RESET_NACK_PREFIX))):
            accepted = msg.startswith(RESET_ACK_PREFIX)
            prefix = RESET_ACK_PREFIX if accepted else RESET_NACK_PREFIX
            try:
                request_id = int(msg[len(prefix):].decode())
            except (UnicodeError, ValueError):
                print("[espnow] confirmación de reset inválida")
                return
            if self._on_reset_ack is not None:
                self._on_reset_ack(request_id, accepted)
            return

        if msg.startswith(PAIR_REQ_MAGIC):
            if self.paired and mac != self.peer:
                return   # ya emparejado con otro -- hace falta repair() explicito
            try:
                self._e.add_peer(mac)   # ESP-NOW exige el peer registrado antes de send()
            except OSError:
                pass   # ya estaba agregado
            try:
                self._e.send(mac, PAIR_ACK_MAGIC)
            except OSError as exc:
                print("[espnow] error al responder ACK:", exc)
            return

        if msg.startswith(TELEMETRY_PREFIX):
            if not self.paired:
                # El ACK se pudo haber perdido -- el primer paquete de
                # telemetria de una MAC nueva tambien confirma el pairing.
                self.peer = mac
                self.paired = True
                try:
                    self._e.add_peer(mac)
                except OSError:
                    pass
                _save_peer(mac)
                print("[espnow] pairing OK con", mac_str(mac))
            if mac != self.peer:
                return   # ignora telemetria de una MAC que no es el peer
            if self._on_telemetry is not None:
                try:
                    accepted = self._on_telemetry(
                        msg[len(TELEMETRY_PREFIX):].decode())
                except (UnicodeError, ValueError) as exc:
                    print("[espnow] telemetria invalida:", exc)
                    return
                if accepted is False:
                    return
            self.last_rx_ms = time.ticks_ms()

    def send_configuration(self, revision, meters_per_pulse, debounce_us,
                           max_speed_kmh, voltage_factors_milli, ads_mode):
        if not self.paired or self.peer is None:
            return False
        factors = list(voltage_factors_milli)
        if len(factors) != 4:
            raise ValueError("se requieren cuatro factores")
        am = "C" if ads_mode == "cumulative" else "I"
        payload = (
            "CFG:V=1;ID={};MP={:.4f};DB={};MAX={:.1f};"
            "F1={};F2={};F3={};F4={};AM={}"
        ).format(
            revision, meters_per_pulse, debounce_us, max_speed_kmh,
            factors[0], factors[1], factors[2], factors[3], am).encode()
        try:
            return bool(self._e.send(self.peer, payload))
        except OSError as exc:
            print("[espnow] error enviando configuración al Super Mini:", exc)
            return False

    def send_reset_command(self, request_id):
        """Pide al Super Mini que resetee sus acumulados de vida entera
        (ver _apply_remote_reset en su main.py). Analogo a
        send_configuration/CFG, con su propio canal RST/RSTA/RSTN."""
        if not self.paired or self.peer is None:
            return False
        payload = "RST:V=1;ID={}".format(request_id).encode()
        try:
            return bool(self._e.send(self.peer, payload))
        except OSError as exc:
            print("[espnow] error enviando reset al Super Mini:", exc)
            return False

    async def listen_task(self, poll_ms=50):
        """Escucha continua -- responde pairing y despacha telemetria al
        callback. El T190 nunca manda telemetria, solo escucha."""
        while True:
            mac, msg = self._e.recv(0)
            if mac is not None:
                self._handle_incoming(mac, msg)
            await asyncio.sleep_ms(poll_ms)
