"""Minimal HTTP dashboard served by the paddock access point."""

import ujson
import network
import socket
import uasyncio as asyncio

import HW


DNS_PORT = 53


class _CaptiveDNSServer:
    """Responde toda consulta DNS con la IP del AP (portal cautivo).

    Asi los chequeos de conectividad de iOS/Android/Windows resuelven al
    Paddock y el SO abre el navegador cautivo solo, sin que el usuario
    tenga que tipear la IP a mano.
    """

    def __init__(self, ip):
        self._answer_ip = bytes(int(part) for part in ip.split("."))
        self._sock = None
        self._running = False

    def start(self):
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.setblocking(False)
        self._sock.bind(("0.0.0.0", DNS_PORT))
        self._running = True

    def stop(self):
        self._running = False
        sock = self._sock
        self._sock = None
        if sock is not None:
            sock.close()

    def _build_reply(self, query):
        question_end = query.index(b"\x00", 12) + 5
        question = query[12:question_end]
        header = (
            query[:2] +            # transaction ID (eco)
            b"\x81\x80" +          # flags: respuesta estandar, sin error
            query[4:6] +           # QDCOUNT (eco)
            b"\x00\x01" +          # ANCOUNT = 1
            b"\x00\x00" +          # NSCOUNT
            b"\x00\x00"            # ARCOUNT
        )
        answer = (
            b"\xc0\x0c" +          # nombre: puntero al QNAME (offset 12)
            b"\x00\x01" +          # TYPE A
            b"\x00\x01" +          # CLASS IN
            b"\x00\x00\x00\x3c" +  # TTL 60s
            b"\x00\x04" +          # RDLENGTH 4
            self._answer_ip
        )
        return header + question + answer

    async def run(self):
        while self._running:
            try:
                query, addr = self._sock.recvfrom(512)
            except OSError:
                await asyncio.sleep_ms(50)
                continue
            try:
                self._sock.sendto(self._build_reply(query), addr)
            except Exception as exc:
                print("[dns] error respondiendo consulta:", exc)


_PAGE = """<!doctype html>
<html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="refresh" content="60">
<title>Telemetría EcoYPF</title>
<style>
*{box-sizing:border-box}body{margin:0;background:#101820;color:#f4f7fa;
font:16px system-ui,sans-serif}main{max-width:760px;margin:auto;padding:20px}
h1{font-size:1.5rem;margin:0 0 6px}.sub{color:#aab8c4;margin:0 0 20px}
#status{padding:10px 12px;border-radius:8px;background:#263541;margin-bottom:14px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(145px,1fr));gap:10px}
.card{background:#1d2a34;border:1px solid #344550;border-radius:10px;padding:13px}
.label{display:block;color:#aab8c4;font-size:.85rem}.value{font-size:1.45rem;
font-weight:650;margin-top:5px}.unit{font-size:.85rem;color:#aab8c4}
footer{color:#91a0ab;font-size:.8rem;margin-top:18px}
</style></head><body><main>
<h1>Telemetría EcoYPF</h1><p class="sub">Receptor LoRa · XIAO ESP32-S3</p>
<div id="status">Conectando…</div><section id="cards" class="grid"></section>
<footer id="meta"></footer></main>
<script>
const cards=[
 ['speed_kmh','Velocidad','km/h'],['whkm_avg','Consumo medio','Wh/km'],
 ['current_a','Corriente','A'],['battery_pack_v','VBATS total','V'],
 ['battery_1_v','Batería 1','V'],
 ['battery_2_v','Batería 2','V'],['battery_3_v','Batería 3','V'],
 ['battery_4_v','Batería 4','V'],['power_w','Potencia','W'],
 ['power_avg_w','Potencia media','W'],['distance_m','Distancia','m'],
 ['whkm_inst','Consumo instantáneo','Wh/km'],['wh_total','Energía','Wh']];
const fmt=(n)=>Number(n).toLocaleString('es-AR',{maximumFractionDigits:2});
let last=null,lastWallMs=Date.now();
function render(d){
 last=d;lastWallMs=Date.now();
 document.getElementById('cards').innerHTML=cards.map(([k,l,u])=>
  '<article class="card"><span class="label">'+l+'</span><div class="value">'+
  (d.values[k]===undefined?'—':fmt(d.values[k]))+
  ' <span class="unit">'+u+'</span></div></article>').join('');
 renderStatus();
 document.getElementById('meta').textContent='Paquetes recibidos: '+d.rx_count+
  (d.last_error?' · Último paquete inválido: '+d.last_error:'');
}
function renderStatus(){
 if(!last)return;
 const d=last,elapsed=Math.floor((Date.now()-lastWallMs)/1000);
 let packetAge=d.packet_age_ms===null?null:Math.floor(d.packet_age_ms/1000)+elapsed;
 let sourceAge=d.source_age_ms===null?null:Math.floor(d.source_age_ms/1000)+elapsed;
 let text=d.rx_count?'LoRa: '+(packetAge<8?'recibiendo':'sin paquetes recientes')+
  ' · paquete hace '+packetAge+' s':'Esperando el primer paquete LoRa…';
 if(d.rx_count && sourceAge!==null){
  text+=' · origen '+(sourceAge<=5?'actualizado':'vencido')+' hace '+sourceAge+' s';
 }
 if(d.rx_count && (!d.adc_valid || !d.current_valid)){
  text+=' · sensores: '+(!d.adc_valid?'tensión inválida ':'')+
   (!d.current_valid?'corriente inválida':'');
 }
 if(!d.radio_ok)text='Radio LoRa no disponible'+(d.radio_error?': '+d.radio_error:'');
 document.getElementById('status').textContent=text;
}
async function fetchOnce(){
 try{
  const r=await fetch('/api',{cache:'no-store'});render(await r.json());
 }catch(e){if(!last)document.getElementById('status').textContent='Error consultando telemetría';}
}
const es=new EventSource('/events');
es.onmessage=(ev)=>render(JSON.parse(ev.data));
es.onerror=()=>{if(!last)document.getElementById('status').textContent='Conectando…';};
fetchOnce();
setInterval(renderStatus,1000);
</script></body></html>"""

_MAX_SSE_CLIENTS = 4


class DashboardServer:
    def __init__(self, state):
        self._state = state
        self._ap = network.WLAN(network.AP_IF)
        self._server = None
        self._sse_writers = []
        self._stop_event = asyncio.Event()
        self._dns = None
        self._dns_task = None

    async def start(self):
        self._ap.active(True)
        self._ap.config(essid=HW.AP_SSID, password=HW.AP_PASSWORD, authmode=3)
        self._ap.ifconfig((
            HW.AP_IP, HW.AP_NETMASK, HW.AP_IP, HW.AP_IP,
        ))
        self._server = await asyncio.start_server(
            self._handle_client, "0.0.0.0", 80)
        self._dns = _CaptiveDNSServer(HW.AP_IP)
        self._dns.start()
        self._dns_task = asyncio.create_task(self._dns.run())
        print("[wifi] AP protegido {} listo en http://{}/ DNS={}".format(
            HW.AP_SSID, HW.AP_IP, DNS_PORT))

    async def stop(self):
        self._stop_event.set()
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
        if self._dns_task is not None:
            self._dns_task.cancel()
            self._dns_task = None
        if self._dns is not None:
            self._dns.stop()
            self._dns = None
        for writer in list(self._sse_writers):
            try:
                writer.close()
            except OSError:
                pass
        self._sse_writers.clear()
        self._ap.active(False)
        print("[wifi] AP detenido")

    async def _send_event(self, writer, payload):
        if payload is None:
            chunk = b": hb\n\n"
        else:
            chunk = b"data: " + ujson.dumps(payload).encode("utf-8") + b"\n\n"
        writer.write(chunk)
        await writer.drain()

    async def broadcast(self):
        """Push the current telemetry snapshot to every connected SSE client."""
        if not self._sse_writers:
            return
        payload = self._state.as_dict()
        dead = []
        for writer in list(self._sse_writers):
            try:
                await self._send_event(writer, payload)
            except OSError:
                dead.append(writer)
        for writer in dead:
            if writer in self._sse_writers:
                self._sse_writers.remove(writer)
            try:
                writer.close()
            except OSError:
                pass

    async def _serve_sse(self, writer):
        if len(self._sse_writers) >= _MAX_SSE_CLIENTS:
            try:
                writer.write(b"HTTP/1.1 503 Service Unavailable\r\nConnection: close\r\n\r\n")
                await writer.drain()
            except OSError:
                pass
            writer.close()
            return
        try:
            writer.write(
                b"HTTP/1.1 200 OK\r\n"
                b"Content-Type: text/event-stream; charset=utf-8\r\n"
                b"Cache-Control: no-store\r\n"
                b"Connection: keep-alive\r\n\r\n"
            )
            await writer.drain()
            self._sse_writers.append(writer)
            await self._send_event(writer, self._state.as_dict())
            while not self._stop_event.is_set():
                try:
                    await asyncio.wait_for(self._stop_event.wait(), 15)
                except asyncio.TimeoutError:
                    await self._send_event(writer, None)
        except (OSError, UnicodeError):
            pass
        finally:
            if writer in self._sse_writers:
                self._sse_writers.remove(writer)
            try:
                writer.close()
            except OSError:
                pass

    async def _handle_client(self, reader, writer):
        try:
            request = await reader.readline()
            while True:
                header = await reader.readline()
                if header in (b"", b"\r\n", b"\n"):
                    break
        except (OSError, UnicodeError) as exc:
            print("[http] cliente desconectado:", exc)
            writer.close()
            return
        parts = request.decode("ascii").strip().split()
        path = parts[1] if len(parts) > 1 else "/"
        if path == "/events":
            await self._serve_sse(writer)
            return
        try:
            if path == "/api":
                body = ujson.dumps(self._state.as_dict()).encode("utf-8")
                content_type = "application/json; charset=utf-8"
            else:
                # "/" y cualquier ruta desconocida (sondeos de conectividad
                # de iOS/Android/Windows, portal cautivo) reciben el
                # dashboard en vez de 404, para que el SO abra el
                # navegador cautivo solo.
                body = _PAGE.encode("utf-8")
                content_type = "text/html; charset=utf-8"
            status = "200 OK"
            response = (
                "HTTP/1.1 {}\r\n"
                "Content-Type: {}\r\n"
                "Content-Length: {}\r\n"
                "Connection: close\r\n"
                "Cache-Control: no-store\r\n\r\n"
            ).format(status, content_type, len(body))
            writer.write(response.encode("ascii"))
            writer.write(body)
            await writer.drain()
        except (OSError, UnicodeError) as exc:
            print("[http] cliente desconectado:", exc)
        finally:
            writer.close()
