# debug_ap.py
# AP de debug/status del Super Mini -- herramienta de banco, no de a bordo.
# Activado desde main.py (debug_ap_button_task) manteniendo HW.BTN0_PIN
# (GPIO0, boton BOOT de fabrica) ~2s con B4 ausente (auto apagado). Mismo
# patron que Paddock S3/web_server.py (AP + servidor HTTP asyncio) pero mas
# simple: sin DNS cautivo ni Server-Sent Events, la pagina solo hace polling
# a /api cada 1s -- alcanza para una herramienta de diagnostico, no justifica
# la complejidad extra en la placa que mas importa que el loop de sensores
# no pierda tiempo de CPU.
#
# Ademas levanta WebREPL (puerto 8266) para poder entrar a la consola de
# MicroPython por WiFi sin cable -- util para calibrar/depurar sin acceso
# fisico al puerto serie.

import network
import os
import ujson
import uasyncio as asyncio

import HW

_PAGE = """<!doctype html>
<html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Super Mini -- debug/status</title>
<style>
*{box-sizing:border-box}body{margin:0;background:#101820;color:#f4f7fa;
font:16px system-ui,sans-serif}main{max-width:760px;margin:auto;padding:20px}
h1{font-size:1.4rem;margin:0 0 4px}.sub{color:#aab8c4;margin:0 0 18px}
#status{padding:10px 12px;border-radius:8px;background:#263541;margin-bottom:14px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(145px,1fr));gap:10px}
.card{background:#1d2a34;border:1px solid #344550;border-radius:10px;padding:13px}
.label{display:block;color:#aab8c4;font-size:.85rem}.value{font-size:1.4rem;
font-weight:650;margin-top:5px}.unit{font-size:.85rem;color:#aab8c4}
footer{color:#91a0ab;font-size:.8rem;margin-top:18px;line-height:1.5}
code{background:#263541;padding:1px 5px;border-radius:4px}
</style></head><body><main>
<h1>Super Mini -- debug/status</h1>
<p class="sub">Herramienta de banco -- este AP se apaga solo si el auto arranca</p>
<div id="status">Conectando&hellip;</div>
<section id="cards" class="grid"></section>
<footer id="webrepl-note">WebREPL: consultando&hellip;</footer>
</main>
<script>
const cards=[
 ['v_bats','VBATS total','V'],['i_bat','Corriente','A'],
 ['p_inst','Potencia inst.','W'],['p_avg5s','Potencia media','W'],
 ['v_b1','Bateria 1','V'],['v_b2','Bateria 2','V'],
 ['v_b3','Bateria 3','V'],['v_b4','Bateria 4','V'],
 ['speed_kmh','Velocidad','km/h'],['dist_m','Distancia','m'],
 ['whkm_inst','Wh/km inst.','Wh/km'],['whkm_avg','Wh/km medio','Wh/km'],
 ['wh_total','Energia','Wh'],['pulse_count','Pulsos','']];
const fmt=(n)=>Number(n).toLocaleString('es-AR',{maximumFractionDigits:2});
function render(d){
 document.getElementById('cards').innerHTML=cards.map(([k,l,u])=>
  '<article class="card"><span class="label">'+l+'</span><div class="value">'+
  (d[k]===undefined?'—':fmt(d[k]))+
  ' <span class="unit">'+u+'</span></div></article>').join('');
 let text='ADC '+(d.adc_ok?'OK':'ERROR')+' · corriente '+
  (d.current_ok?'OK':'ERROR')+(d.current_error?' ('+d.current_error+')':'')+
  ' · pulsos rechazados '+d.pulse_rejected;
 text+=' · B4 '+(d.b4_present?'presente':'ausente');
 text+=' · ESP-NOW '+(d.espnow_paired?'emparejado #'+d.espnow_tx_count:'buscando T190...');
 document.getElementById('status').textContent=text;
 document.getElementById('webrepl-note').innerHTML=d.webrepl_started?
  'WebREPL: <a href="/webrepl/webrepl.html" style="color:#8ec9ff">consola embebida</a> '+
  '(sin internet, servida por esta placa) con la contrasena configurada.':
  'WebREPL: no se pudo iniciar (revisar consola serie) -- la pagina de '+
  'status sigue andando igual.';
}
async function poll(){
 try{const r=await fetch('/api',{cache:'no-store'});render(await r.json());}
 catch(e){document.getElementById('status').textContent='Error consultando status';}
}
poll();setInterval(poll,1000);
</script></body></html>"""


class DebugAP:
    """AP + servidor HTTP de status, mas WebREPL. Vida corta: se crea al
    activar el modo (ver main.py: _toggle_debug_ap) y se descarta al
    desactivarlo -- no hay instancia persistente escuchando de fondo
    cuando el modo esta apagado."""

    def __init__(self, board, espnow_link):
        self._board = board
        self._en = espnow_link
        self._ap = network.WLAN(network.AP_IF)
        self._server = None
        self._webrepl_started = False

    async def start(self):
        self._ap.active(True)
        self._ap.config(essid=HW.AP_SSID, password=HW.AP_PASSWORD, authmode=3)
        self._ap.ifconfig((HW.AP_IP, HW.AP_NETMASK, HW.AP_IP, HW.AP_IP))
        self._server = await asyncio.start_server(
            self._handle_client, "0.0.0.0", 80)
        try:
            import webrepl
            webrepl.start(password=HW.AP_PASSWORD)
            self._webrepl_started = True
        except Exception as exc:
            print("[debug_ap] WebREPL no se pudo iniciar:", exc)
        print("[debug_ap] AP {} listo en http://{}/ (WebREPL puerto 8266)".format(
            HW.AP_SSID, HW.AP_IP))

    async def stop(self):
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
        if self._webrepl_started:
            try:
                import webrepl
                webrepl.stop()
            except Exception as exc:
                print("[debug_ap] WebREPL no se pudo detener:", exc)
            self._webrepl_started = False
        self._ap.active(False)
        print("[debug_ap] AP detenido")

    def _status_dict(self):
        st = self._board.state
        en = self._en
        return {
            "v_b1": st.v_b1, "v_b2": st.v_b2, "v_b3": st.v_b3, "v_b4": st.v_b4,
            "v_bats": st.v_bats, "i_bat": st.i_bat,
            "p_inst": st.p_inst, "p_avg5s": st.p_avg5s,
            "speed_kmh": st.speed_kmh, "dist_m": st.dist_m,
            "whkm_inst": st.whkm_inst, "whkm_avg": st.whkm_avg,
            "wh_total": st.wh_total,
            "pulse_count": st.pulse_count, "pulse_rejected": st.pulse_rejected,
            "adc_ok": st.adc_ok, "current_ok": st.current_ok,
            "current_error": st.current_error,
            "b4_present": self._board.b4_present(),
            "espnow_paired": bool(en and en.paired),
            "espnow_tx_count": st.espnow_tx_count,
            "espnow_tx_fail_count": st.espnow_tx_fail_count,
            "webrepl_started": self._webrepl_started,
        }

    async def _handle_client(self, reader, writer):
        try:
            request_line = await reader.readline()
            while True:
                header = await reader.readline()
                if not header or header == b"\r\n":
                    break
            path = request_line.split(b" ")[1] if request_line else b"/"
            if path == b"/api":
                body = ujson.dumps(self._status_dict()).encode("utf-8")
                writer.write(b"HTTP/1.0 200 OK\r\nContent-Type: application/json\r\n"
                             b"Content-Length: " + str(len(body)).encode() +
                             b"\r\nConnection: close\r\n\r\n" + body)
                await writer.drain()
            elif path.startswith(b"/webrepl/"):
                await self._serve_static(writer, path[len(b"/webrepl/"):])
            else:
                body = _PAGE.encode("utf-8")
                writer.write(b"HTTP/1.0 200 OK\r\nContent-Type: text/html\r\n"
                             b"Content-Length: " + str(len(body)).encode() +
                             b"\r\nConnection: close\r\n\r\n" + body)
                await writer.drain()
        except Exception as exc:
            print("[debug_ap] error atendiendo cliente:", exc)
        finally:
            try:
                await writer.wait_closed()
            except Exception:
                pass

    async def _serve_static(self, writer, name):
        """Sirve un archivo del cliente WebREPL embebido (webrepl_client/,
        ver nota al principio del archivo) leyendo del filesystem en
        bloques -- term.js pesa ~157KB, cargarlo entero en RAM de una
        competiria con el resto de los tasks asyncio (sensores, ESP-NOW)
        que siguen corriendo en paralelo."""
        content_type = {
            b"webrepl.html": "text/html",
            b"webrepl.css": "text/css",
            b"webrepl.js": "application/javascript",
            b"term.js": "application/javascript",
            b"FileSaver.js": "application/javascript",
        }.get(name)
        if content_type is None:
            writer.write(b"HTTP/1.0 404 Not Found\r\nConnection: close\r\n\r\n")
            await writer.drain()
            return
        path = "webrepl_client/" + name.decode()
        try:
            size = os.stat(path)[6]
        except OSError:
            writer.write(b"HTTP/1.0 404 Not Found\r\nConnection: close\r\n\r\n")
            await writer.drain()
            return
        writer.write("HTTP/1.0 200 OK\r\nContent-Type: {}\r\nContent-Length: {}"
                      "\r\nConnection: close\r\n\r\n".format(content_type, size)
                      .encode("utf-8"))
        await writer.drain()
        with open(path, "rb") as f:
            while True:
                chunk = f.read(2048)
                if not chunk:
                    break
                writer.write(chunk)
                await writer.drain()
