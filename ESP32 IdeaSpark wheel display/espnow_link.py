# espnow_link.py
# Lado "receptor" del protocolo de pairing ESP-NOW -- espejo de
# New T190/espnow_link.py. Roles fijos: el T190 inicia el pairing
# (broadcastea PAIR_REQ), este display solo acepta y contesta.
#
#   1) Si hay una MAC de T190 guardada en PEER_FILE, se recuerda al bootear
#      (solo para mostrar estado / filtrar ruido de otros emisores) -- no
#      hace falta volver a pairear, este display ya acepta telemetria de
#      esa MAC sin pedir nada.
#   2) Mientras escucha, si llega un paquete que empieza con PAIR_REQ_MAGIC,
#      contesta PAIR_ACK_MAGIC por broadcast -- no hace falta add_peer()
#      para la MAC del T190: ESP-NOW entrega la MAC real del emisor en
#      recv() independientemente de si la respuesta se manda broadcast o
#      unicast (mismo comentario del lado del T190). Guarda esa MAC como
#      peer y la persiste en PEER_FILE.
#   3) Cualquier paquete con prefijo TELEMETRY_PREFIX se entrega via
#      rx_task()/poll() -- SIN parsear los campos individuales todavia,
#      ver PROYECTO_IDEASPARK.md #Proximos pasos.
#
# Para re-parear a mano (ej: cambiaste de T190), llamar a
# EspNowLink.repair() (expuesto en main.py como main.repair()).

import network
import espnow
import uos
import time
import uasyncio as asyncio

PEER_FILE = "espnow_peer.bin"
BROADCAST = b"\xff\xff\xff\xff\xff\xff"
PAIR_REQ_MAGIC = b"T190_PAIR_REQ"
PAIR_ACK_MAGIC = b"T190_PAIR_ACK"
TELEMETRY_PREFIX = b"TLM:"


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
    def __init__(self):
        self._sta = network.WLAN(network.STA_IF)
        self._sta.active(True)
        self._e = espnow.ESPNow()
        self._e.active(True)
        try:
            self._e.add_peer(BROADCAST)
        except OSError:
            pass  # ya estaba agregado (ej: tras un main.stop()/start())

        self.peer = _load_peer()
        self.paired = self.peer is not None
        if self.paired:
            print("[espnow] peer recordado:", mac_str(self.peer))
        else:
            print("[espnow] sin peer -- esperando PAIR_REQ del T190")

        self.rx_count = 0
        self.last_rx_ms = None

    def repair(self):
        """Olvida el T190 emparejado -- vuelve a aceptar cualquier PAIR_REQ."""
        self.peer = None
        self.paired = False
        try:
            uos.remove(PEER_FILE)
        except OSError:
            pass
        print("[espnow] pairing reseteado -- esperando T190")

    def _handle_pair_req(self, mac):
        try:
            self._e.send(BROADCAST, PAIR_ACK_MAGIC)
        except OSError as exc:
            print("[espnow] ack error:", exc)
            return
        if self.peer != mac:
            self.peer = mac
            _save_peer(mac)
            print("[espnow] pairing OK con", mac_str(mac))
        self.paired = True

    def poll(self):
        """No bloqueante -- devuelve el payload de telemetria (str, sin el
        prefijo TLM:) si llego uno nuevo del peer emparejado, o None."""
        mac, msg = self._e.recv(0)
        if mac is None or msg is None:
            return None
        if msg.startswith(PAIR_REQ_MAGIC):
            self._handle_pair_req(mac)
            return None
        if msg.startswith(TELEMETRY_PREFIX):
            if self.peer is not None and mac != self.peer:
                return None  # ruido de otro emisor; ignorar
            self.rx_count += 1
            self.last_rx_ms = time.ticks_ms()
            try:
                return msg[len(TELEMETRY_PREFIX):].decode()
            except Exception:
                return None
        return None

    async def rx_task(self, on_payload, interval_ms=50):
        """Tarea asyncio: hace poll() seguido y llama on_payload(str) cada
        vez que llega telemetria nueva (tambien procesa pairing en cada
        poll, no hace falta una tarea separada para eso)."""
        while True:
            payload = self.poll()
            if payload is not None:
                on_payload(payload)
            await asyncio.sleep_ms(interval_ms)
