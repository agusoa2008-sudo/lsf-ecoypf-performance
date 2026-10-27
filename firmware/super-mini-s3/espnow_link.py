# espnow_link.py
# Envio de telemetria por ESP-NOW al T190 (que es el receptor/display
# remoto) -- el Super Mini es el INICIADOR de este protocolo.
#
# Protocolo de pairing (simetrico a New T190/espnow_link.py, mismos magic
# bytes, rol invertido -- aca el Super Mini es quien habla):
#   1) Si hay una MAC de T190 guardada en PEER_FILE, se usa directo
#      (unicast) sin entrar en modo pairing.
#   2) Si no hay peer guardado, el Super Mini broadcastea PAIR_REQ_MAGIC
#      cada ~1s (a FF:FF:FF:FF:FF:FF) y escucha.
#   3) El T190, al ver PAIR_REQ_MAGIC, contesta PAIR_ACK_MAGIC -- el Super
#      Mini toma la MAC de origen de esa respuesta como el peer (no hace
#      falta que el T190 mande su propia MAC en el payload).
#   4) El Super Mini guarda esa MAC en PEER_FILE (persiste entre reboots)
#      y pasa a mandar telemetria unicast (prefijo TELEMETRY_PREFIX). Ya
#      emparejado, también acepta ajustes CFG del T190 y confirma guardado
#      mediante CFGA/CFGN.
#
# Para reparar (ej: cambiaste de T190), llamar a EspNowLink.repair()
# (expuesto en main.py como main.espnow_repair()).

import network
import espnow
import uos
import uasyncio as asyncio

PEER_FILE = "espnow_peer.bin"
BROADCAST = b"\xff\xff\xff\xff\xff\xff"
PAIR_REQ_MAGIC = b"SM_PAIR_REQ"      # lo manda el Super Mini
PAIR_ACK_MAGIC = b"T190_PAIR_ACK"    # lo contesta el T190
TELEMETRY_PREFIX = b"TLM:"
CONFIG_PREFIX = b"CFG:"
CONFIG_ACK_PREFIX = b"CFGA:"
CONFIG_NACK_PREFIX = b"CFGN:"
RESET_PREFIX = b"RST:"
RESET_ACK_PREFIX = b"RSTA:"
RESET_NACK_PREFIX = b"RSTN:"


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
    def __init__(self, on_configuration=None, on_reset=None):
        self._on_configuration = on_configuration
        self._on_reset = on_reset
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
        if self.peer is not None:
            try:
                self._e.add_peer(self.peer)
                self.paired = True
                print("[espnow] peer recordado:", mac_str(self.peer))
            except OSError as exc:
                print("[espnow] error al re-agregar peer guardado:", exc)
                self.peer = None

    def repair(self):
        """Olvida el peer actual y vuelve a modo pairing (broadcast)."""
        self.peer = None
        self.paired = False
        try:
            uos.remove(PEER_FILE)
        except OSError:
            pass
        print("[espnow] pairing reseteado -- esperando T190")

    def _handle_incoming(self, mac, msg):
        if msg is None:
            return
        if msg.startswith(PAIR_ACK_MAGIC) and not self.paired:
            self.peer = mac
            self.paired = True
            try:
                self._e.add_peer(mac)
            except OSError:
                pass
            _save_peer(mac)
            print("[espnow] pairing OK con", mac_str(mac))
            return

        if (msg.startswith(CONFIG_PREFIX) and self.paired and
                mac == self.peer and self._on_configuration is not None):
            revision = "0"
            try:
                payload = msg[len(CONFIG_PREFIX):].decode()
                for part in payload.split(";"):
                    key, separator, value = part.partition("=")
                    if separator and key == "ID":
                        revision = value
                        break
                accepted = self._on_configuration(payload)
            except (UnicodeError, ValueError, TypeError, KeyError,
                    RuntimeError, OSError) as exc:
                accepted = False
                print("[espnow] configuración remota rechazada:", exc)
            response = CONFIG_ACK_PREFIX if accepted else CONFIG_NACK_PREFIX
            try:
                self._e.send(mac, response + revision.encode())
            except OSError as exc:
                print("[espnow] no se pudo confirmar configuración:", exc)
            return

        if (msg.startswith(RESET_PREFIX) and self.paired and
                mac == self.peer and self._on_reset is not None):
            request_id = "0"
            try:
                payload = msg[len(RESET_PREFIX):].decode()
                fields = {}
                for part in payload.split(";"):
                    key, separator, value = part.partition("=")
                    if separator and key:
                        fields[key] = value
                if fields.get("V") != "1" or "ID" not in fields:
                    raise ValueError("version o ID de reset invalidos")
                request_id = fields["ID"]
                accepted = self._on_reset(int(request_id))
            except (UnicodeError, ValueError, TypeError, KeyError,
                    RuntimeError, OSError) as exc:
                accepted = False
                print("[espnow] reset remoto rechazado:", exc)
            response = RESET_ACK_PREFIX if accepted else RESET_NACK_PREFIX
            try:
                self._e.send(mac, response + request_id.encode())
            except OSError as exc:
                print("[espnow] no se pudo confirmar reset:", exc)

    async def pairing_task(self, interval_ms=1000):
        """Mientras no haya peer, broadcastea PAIR_REQ y escucha ACKs. Ya
        emparejado, solo escucha (liviano) por si se pide repair()."""
        while True:
            if not self.paired:
                try:
                    self._e.send(BROADCAST, PAIR_REQ_MAGIC)
                except OSError as exc:
                    print("[espnow] broadcast pairing error:", exc)
            mac, msg = self._e.recv(0)
            if mac is not None:
                self._handle_incoming(mac, msg)
            await asyncio.sleep_ms(interval_ms if not self.paired else 100)

    def send_telemetry(self, payload_str):
        """Envia telemetria unicast al T190 emparejado. No hace nada si
        todavia no se empareo."""
        if not self.paired:
            return False
        try:
            sent = self._e.send(self.peer, TELEMETRY_PREFIX + payload_str.encode())
            return bool(sent)
        except OSError as exc:
            print("[espnow] send error:", exc)
            self.paired = False   # el peer puede haberse ido; reintentar pairing
            return False
