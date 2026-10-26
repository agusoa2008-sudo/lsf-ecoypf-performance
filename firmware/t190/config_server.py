"""On-demand phone configuration AP and small HTTP form for the T190."""

import os

import network
import socket
import uasyncio as asyncio


AP_SSID = "Main-T190"
AP_PASSWORD = "lasalle2026"
AP_IP = "192.168.4.1"
AP_NETMASK = "255.255.255.0"
DNS_PORT = 53


class _CaptiveDNSServer:
    """Responde toda consulta DNS con la IP del AP (portal cautivo).

    Asi los chequeos de conectividad de iOS/Android/Windows resuelven al
    T190 y el SO abre el navegador cautivo solo, sin que el usuario tenga
    que tipear la IP a mano.
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
<meta name="color-scheme" content="dark">
<title>Configuracion T190</title>
<style>
*{box-sizing:border-box}body{margin:0;background:#101820;color:#f4f7fa;font:16px system-ui,sans-serif}
main{max-width:560px;margin:auto;padding:20px}h1{font-size:1.5rem}
form{background:#1d2a34;border:1px solid #40515c;border-radius:12px;padding:16px;margin:14px 0}
label{display:block;font-weight:600;margin:14px 0 6px}
input[type=number],input[type=text]{width:100%;padding:12px;border-radius:8px;
border:1px solid #667783;background:#101820;color:#fff;font-size:1rem}
small{color:#c6d0d8;line-height:1.5}.value{color:#fff;font-weight:700}
button{width:100%;padding:13px;border:0;border-radius:8px;background:#1687d9;color:white;
font-weight:700;font-size:1rem;margin-top:16px}button.secondary{background:#436273}
h2{font-size:1.15rem;margin:8px 0}.bat{border-top:1px solid #40515c;padding-top:8px;margin-top:10px}
.tag{color:#7fb3d3;font-size:.9rem}
.radio-row{display:flex;flex-wrap:wrap;gap:16px;margin:8px 0}
.radio-row label{font-weight:400;display:flex;align-items:center;gap:6px;margin:0}
</style></head><body><main>
<h1>Configuracion T190</h1>
<p><a href="/logs" style="color:#7fb3d3">Descargar registros de viaje (CSV)</a></p>
<p>Los factores de tension se aplican en el Super Mini (mas cerca del sensor).
Ingresa la tension real medida con multimetro para recalcular el factor de cada banco.</p>
<form method="POST" action="/apply">

<h2>Modo de medicion ADS1115</h2>
<div class="radio-row">
<label><input type="radio" name="ads_mode" value="cumulative" @CHECKED_CUM@>
Acumulativo — taps respecto a masa (default)</label>
<label><input type="radio" name="ads_mode" value="individual" @CHECKED_IND@>
Individual — divisor por celda</label>
</div>
<small>Acumulativo: A0=B1, A1=B1+B2, A2=B1+B2+B3, A3=total. El Super Mini resta taps para obtener individuales.
Individual: cada canal mide su bateria directamente con divisor propio.</small>

<h2>Factores de tension B1-B4</h2>
<small>Si dejas el campo vacio, el factor existente no cambia. Factor actual en milesimas (1000 = sin correccion, rango 800-1200).</small>
<div class="bat">
<span>B1 — <span class="tag">lectura: @RAW1@ V</span> | <span class="tag">factor actual: @FACTOR1@ mils</span></span>
<label>Tension real B1 (V, opcional — ej: 12.34)</label>
<input name="real_1_v" type="number" min="0.5" max="30" step="0.01" placeholder="dejar vacio = no cambiar"></div>
<div class="bat">
<span>B2 — <span class="tag">lectura: @RAW2@ V</span> | <span class="tag">factor actual: @FACTOR2@ mils</span></span>
<label>Tension real B2 (V, opcional)</label>
<input name="real_2_v" type="number" min="0.5" max="30" step="0.01" placeholder="dejar vacio = no cambiar"></div>
<div class="bat">
<span>B3 — <span class="tag">lectura: @RAW3@ V</span> | <span class="tag">factor actual: @FACTOR3@ mils</span></span>
<label>Tension real B3 (V, opcional)</label>
<input name="real_3_v" type="number" min="0.5" max="30" step="0.01" placeholder="dejar vacio = no cambiar"></div>
<div class="bat">
<span>B4 — <span class="tag">lectura: @RAW4@ V</span> | <span class="tag">factor actual: @FACTOR4@ mils</span></span>
<label>Tension real B4 (V, opcional)</label>
<input name="real_4_v" type="number" min="0.5" max="30" step="0.01" placeholder="dejar vacio = no cambiar"></div>

<h2>Pack de baterias</h2>
<label>Capacidad util del pack (Wh)</label>
<input name="capacity_wh" type="number" min="0" max="200000" step="1" value="@CAPACITY@" required>
<small>816 Wh nominales (4x12V 17Ah serie). Ajustar segun estado real. 0 desactiva el calculo de autonomia.</small>
<label><input name="mark_charged" type="checkbox" value="1" style="width:auto">
Pack cargado ahora (reiniciar consumo desde carga completa)</label>
<label>Minutos sin movimiento antes de deep sleep (0 = desactivado)</label>
<input name="sleep_timeout_min" type="number" min="0" max="240" step="1" value="@SLEEP@" required>

<h2>Super Mini — velocidad</h2>
<label>Recorrido por pulso (cm/pulso)</label>
<input name="centimeters_per_pulse" type="number" min="1" max="10000" step="0.1" value="@CM_PER_PULSE@" required>
<small>10 cm/pulso = provisional. Calibrar midiendo distancia conocida: cm/pulso = cm recorridos / pulsos contados.</small>
<label>Anti-rebote (us)</label>
<input name="debounce_us" type="number" min="0" max="1000000" step="1" value="@DEBOUNCE@" required>
<label>Velocidad maxima valida (km/h)</label>
<input name="max_speed_kmh" type="number" min="1" max="200" step="0.1" value="@MAX_SPEED@" required>

<h2>Pantalla de carga</h2>
<label>Energia de precarga — offset inicial del contador Wh+ (Wh)</label>
<input name="precharge_wh" type="number" min="0" max="5000" step="1" value="@PRECHARGE@">
<small>0 = contador arranca desde cero. Ingresa la energia ya cargada para continuar desde ese nivel (ej: 120).</small>

<p>Estado Super Mini: <span class="value">@SM_STATUS@</span></p>
<button type="submit">Guardar y salir del AP</button>
</form>
<form method="POST" action="/cancel">
<button class="secondary" type="submit">Salir sin guardar</button>
</form>
</main></body></html>"""


_LOGS_PAGE = """<!doctype html>
<html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="dark">
<title>Logs T190</title>
<style>
*{box-sizing:border-box}body{margin:0;background:#101820;color:#f4f7fa;font:16px system-ui,sans-serif}
main{max-width:560px;margin:auto;padding:20px}h1{font-size:1.5rem}
table{width:100%;border-collapse:collapse;margin:14px 0}
th,td{text-align:left;padding:8px;border-bottom:1px solid #344550}
a{color:#7fb3d3}.note{color:#c6d0d8;line-height:1.5}
form{display:inline;margin:0}
button.secondary{padding:6px 10px;border:0;border-radius:6px;background:#436273;color:#fff;font-size:.85rem}
</style></head><body><main>
<h1>Registros de viaje</h1>
@NOTE@
@TABLE@
<p><a href="/">Volver a configuracion</a></p>
</main></body></html>"""


_DAY_PAGE = """<!doctype html>
<html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="dark">
<title>Logs T190</title>
<style>
*{box-sizing:border-box}body{margin:0;background:#101820;color:#f4f7fa;font:16px system-ui,sans-serif}
main{max-width:560px;margin:auto;padding:20px}h1{font-size:1.3rem}
table{width:100%;border-collapse:collapse;margin:14px 0}
th,td{text-align:left;padding:8px;border-bottom:1px solid #344550}
a{color:#7fb3d3}.note{color:#c6d0d8;line-height:1.5}
form{display:inline;margin:0}
button.secondary{padding:6px 10px;border:0;border-radius:6px;background:#436273;color:#fff;font-size:.85rem}
</style></head><body><main>
<h1>Registros — @DAY@</h1>
@NOTE@
@TABLE@
<p><a href="/logs">Volver a dias</a></p>
</main></body></html>"""


def _parse_form(body):
    fields = {}
    for part in body.decode("ascii").split("&"):
        if not part:
            continue
        key, separator, value = part.partition("=")
        if separator:
            fields[key.replace("+", " ")] = value.replace("+", " ")
    return fields


def _http_headers(status, content_type, body):
    return (
        "HTTP/1.1 {}\r\n"
        "Content-Type: {}\r\n"
        "Content-Length: {}\r\n"
        "Connection: close\r\n"
        "Cache-Control: no-store\r\n\r\n"
    ).format(status, content_type, len(body)).encode("ascii")


class ConfigServer:
    def __init__(self, settings, get_raw_batteries, get_source_cursor,
                 get_supermini_status, apply_settings, request_stop,
                 get_sd_logger):
        self.settings = settings
        self.get_raw_batteries = get_raw_batteries
        self.get_source_cursor = get_source_cursor
        self.get_supermini_status = get_supermini_status
        self.apply_settings = apply_settings
        self.request_stop = request_stop
        self.get_sd_logger = get_sd_logger
        self.ap = network.WLAN(network.AP_IF)
        self.server = None
        self.dns = None
        self._dns_task = None

    async def start(self):
        self.ap.active(True)
        self.ap.config(essid=AP_SSID, password=AP_PASSWORD, authmode=3)
        self.ap.ifconfig((AP_IP, AP_NETMASK, AP_IP, AP_IP))
        self.server = await asyncio.start_server(
            self._handle_client, "0.0.0.0", 80)
        self.dns = _CaptiveDNSServer(AP_IP)
        self.dns.start()
        self._dns_task = asyncio.create_task(self.dns.run())
        print("[config] AP {} listo; IP={} HTTP=80 DNS={}".format(
            AP_SSID, self.ap.ifconfig()[0], DNS_PORT))

    async def stop(self):
        server = self.server
        self.server = None
        dns_task = self._dns_task
        self._dns_task = None
        if dns_task is not None:
            dns_task.cancel()
        if self.dns is not None:
            self.dns.stop()
            self.dns = None
        try:
            if server is not None:
                server.close()
                await server.wait_closed()
        finally:
            self.ap.active(False)
        print("[config] AP detenido")

    @staticmethod
    def _validate_segment(value, label):
        if not value or "/" in value or ".." in value:
            raise ValueError("{} invalido".format(label))

    @staticmethod
    def _list_days(logger):
        days = []
        for name in os.listdir(logger.mount_point):
            path = "{}/{}".format(logger.mount_point, name)
            if os.stat(path)[0] & 0x4000:   # S_IFDIR
                days.append(name)
        return sorted(days, reverse=True)

    @staticmethod
    def _list_root_files(logger):
        """Archivos sueltos directamente en la raiz de la microSD (fuera de
        cualquier carpeta por dia) -- por ejemplo registros de antes del
        cambio a carpetas por dia, que quedan invisibles en el listado
        normal de /logs porque este solo muestra subcarpetas."""
        names = []
        for name in os.listdir(logger.mount_point):
            path = "{}/{}".format(logger.mount_point, name)
            if not (os.stat(path)[0] & 0x4000):   # no es carpeta
                names.append(name)
        return sorted(names, reverse=True)

    def _render_index_page(self):
        raw_batteries = self.get_raw_batteries()
        page = _PAGE
        factors = self.settings.b_supermini_factors_milli
        ads_mode = self.settings.ads_mode
        for index in range(1, 5):
            raw = None if raw_batteries is None else raw_batteries[index - 1]
            raw_text = "--" if raw is None else "{:.3f}".format(raw)
            page = page.replace("@RAW{}@".format(index), raw_text)
            page = page.replace("@FACTOR{}@".format(index),
                                str(factors[index - 1]))
        page = page.replace("@CHECKED_CUM@",
                            "checked" if ads_mode == "cumulative" else "")
        page = page.replace("@CHECKED_IND@",
                            "checked" if ads_mode == "individual" else "")
        page = page.replace("@CAPACITY@", str(
            int(self.settings.battery_capacity_wh)))
        page = page.replace("@SLEEP@", str(
            self.settings.idle_sleep_timeout_min))
        page = page.replace("@CM_PER_PULSE@", "{:.1f}".format(
            self.settings.supermini_meters_per_pulse * 100.0))
        page = page.replace("@DEBOUNCE@", str(
            self.settings.supermini_debounce_us))
        page = page.replace("@MAX_SPEED@", str(
            self.settings.supermini_max_speed_kmh))
        page = page.replace("@PRECHARGE@", str(
            int(self.settings.precharge_wh)))
        page = page.replace("@SM_STATUS@", self.get_supermini_status())
        return page

    def _render_logs_page(self):
        logger = self.get_sd_logger()
        note = ""
        table = ""
        if logger is None or not logger.ready:
            note = "<p class=\"note\">microSD no disponible.</p>"
        else:
            days = self._list_days(logger)
            root_files = self._list_root_files(logger)
            if not days and not root_files:
                note = "<p class=\"note\">No hay registros en la microSD.</p>"
            else:
                rows = ""
                if root_files:
                    total_kb = sum(
                        os.stat("{}/{}".format(logger.mount_point, n))[6]
                        for n in root_files) / 1024.0
                    rows += (
                        "<tr><td><a href=\"/logs/_root/\">(raiz - sueltos)"
                        "</a></td><td>{0}</td><td>{1:.1f} KB</td>"
                        "<td></td></tr>"
                    ).format(len(root_files), total_kb)
                for day in days:
                    day_path = "{}/{}".format(logger.mount_point, day)
                    files = [n for n in os.listdir(day_path)
                             if n.upper().endswith(".CSV")]
                    total_kb = sum(
                        os.stat("{}/{}".format(day_path, n))[6]
                        for n in files) / 1024.0
                    rows += (
                        "<tr><td><a href=\"/logs/{0}/\">{0}</a></td>"
                        "<td>{1}</td><td>{2:.1f} KB</td>"
                        "<td><form method=\"POST\" action=\"/logs/{0}/delete\" "
                        "onsubmit=\"return confirm('Borrar todo {0}?')\">"
                        "<button class=\"secondary\" type=\"submit\">Borrar dia"
                        "</button></form></td></tr>"
                    ).format(day, len(files), total_kb)
                table = (
                    "<table><thead><tr><th>Dia</th><th>Archivos</th>"
                    "<th>Tamano</th><th></th></tr></thead>"
                    "<tbody>{}</tbody></table>"
                ).format(rows)
            if logger.recording:
                note += ("<p class=\"note\">Grabando el viaje actual: deten el "
                         "log (boton largo) antes de borrar o descargar.</p>")
        return _LOGS_PAGE.replace("@NOTE@", note).replace("@TABLE@", table)

    def _resolve_day_path(self, logger, day):
        if day == "_root":
            return logger.mount_point
        self._validate_segment(day, "dia")
        if day not in os.listdir(logger.mount_point):
            raise ValueError("dia no encontrado")
        return "{}/{}".format(logger.mount_point, day)

    def _render_day_page(self, day):
        logger = self.get_sd_logger()
        note = ""
        table = ""
        if logger is None or not logger.ready:
            note = "<p class=\"note\">microSD no disponible.</p>"
        else:
            day_path = self._resolve_day_path(logger, day)
            if day == "_root":
                # Raiz: mostrar todo archivo suelto, no solo .CSV, para
                # poder ver exactamente que quedo ahi.
                names = sorted(
                    n for n in os.listdir(day_path)
                    if not (os.stat("{}/{}".format(day_path, n))[0] & 0x4000))
            else:
                names = sorted(
                    n for n in os.listdir(day_path) if n.upper().endswith(".CSV"))
            if logger.recording:
                note += ("<p class=\"note\">Grabando el viaje actual: deten el "
                         "log (boton largo) antes de borrar o descargar.</p>")
            if not names:
                note += "<p class=\"note\">Sin archivos en este dia.</p>"
            else:
                rows = ""
                for name in reversed(names):
                    size_kb = os.stat(
                        "{}/{}".format(day_path, name))[6] / 1024.0
                    rows += (
                        "<tr><td>{0}</td><td>{1:.1f} KB</td>"
                        "<td><a href=\"/logs/{2}/{0}\">Descargar</a></td>"
                        "<td><form method=\"POST\" action=\"/logs/{2}/{0}/delete\" "
                        "onsubmit=\"return confirm('Borrar {0}?')\">"
                        "<button class=\"secondary\" type=\"submit\">Borrar"
                        "</button></form></td></tr>"
                    ).format(name, size_kb, day)
                table = (
                    "<table><thead><tr><th>Archivo</th><th>Tamano</th>"
                    "<th></th><th></th></tr></thead><tbody>{}</tbody></table>"
                ).format(rows)
        day_label = "raiz (sueltos)" if day == "_root" else day
        return (_DAY_PAGE.replace("@DAY@", day_label)
                .replace("@NOTE@", note).replace("@TABLE@", table))

    def _resolve_log_download(self, day, name):
        logger = self.get_sd_logger()
        if logger is None or not logger.ready:
            raise ValueError("microSD no disponible")
        if logger.recording:
            raise ValueError("deten la grabacion antes de descargar logs")
        day_path = self._resolve_day_path(logger, day)
        self._validate_segment(name, "archivo")
        if name not in os.listdir(day_path):
            raise ValueError("archivo no encontrado")
        return logger, "{}/{}".format(day_path, name)

    def _delete_day(self, day):
        if day == "_root":
            raise ValueError("no se puede borrar la raiz entera")
        logger = self.get_sd_logger()
        if logger is None or not logger.ready:
            raise ValueError("microSD no disponible")
        if logger.recording:
            raise ValueError("deten la grabacion antes de borrar logs")
        day_path = self._resolve_day_path(logger, day)
        for name in os.listdir(day_path):
            os.remove("{}/{}".format(day_path, name))
        os.rmdir(day_path)
        print("[config] carpeta borrada:", day_path)

    def _delete_file(self, day, name):
        """Borra un archivo del dia; si era el ultimo, borra tambien la
        carpeta vacia. Devuelve True si la carpeta del dia desaparecio.
        Para "_root" (sueltos en la raiz) nunca hace rmdir: day_path ahi
        es el punto de montaje de la SD, no una carpeta propia."""
        logger = self.get_sd_logger()
        if logger is None or not logger.ready:
            raise ValueError("microSD no disponible")
        if logger.recording:
            raise ValueError("deten la grabacion antes de borrar logs")
        day_path = self._resolve_day_path(logger, day)
        self._validate_segment(name, "archivo")
        if name not in os.listdir(day_path):
            raise ValueError("archivo no encontrado")
        os.remove("{}/{}".format(day_path, name))
        print("[config] archivo borrado:", "{}/{}".format(day_path, name))
        if day == "_root" or os.listdir(day_path):
            return False
        os.rmdir(day_path)
        print("[config] carpeta vacia borrada:", day_path)
        return True

    async def _send_file(self, writer, logger, path):
        size = os.stat(path)[6]
        name = path.rsplit("/", 1)[-1]
        header = (
            "HTTP/1.1 200 OK\r\n"
            "Content-Type: text/csv\r\n"
            "Content-Length: {}\r\n"
            "Content-Disposition: attachment; filename=\"{}\"\r\n"
            "Connection: close\r\n"
            "Cache-Control: no-store\r\n\r\n"
        ).format(size, name).encode("ascii")
        writer.write(header)
        await writer.drain()
        with open(path, "rb") as file:
            while True:
                # Mismo guard que TripLogger._write_line: el SX1262 comparte
                # el bus SPI y puede dejar su CS bajo entre operaciones.
                logger.lora_cs.value(1)
                logger.sd_cs.value(1)
                chunk = file.read(1024)
                if not chunk:
                    break
                writer.write(chunk)
                await writer.drain()
        print("[config] descarga completa: {} ({} bytes)".format(name, size))

    async def _handle_client(self, reader, writer):
        status = "200 OK"
        content_type = "text/html; charset=utf-8"
        body = b""
        stop_after_response = False
        download_target = None
        try:
            request = await reader.readline()
            parts = request.decode("ascii").strip().split()
            method = parts[0] if len(parts) > 0 else ""
            path = parts[1] if len(parts) > 1 else "/"
            print("[config] HTTP {} {}".format(method, path))
            content_length = 0
            while True:
                header = await reader.readline()
                if header in (b"", b"\r\n", b"\n"):
                    break
                lower = header.lower()
                if lower.startswith(b"content-length:"):
                    content_length = int(header.split(b":", 1)[1].strip())

            if method == "GET" and path == "/health":
                content_type = "text/plain; charset=utf-8"
                body = b"T190 HTTP OK"
            elif method == "GET" and path in ("/", "/index.html"):
                body = self._render_index_page().encode("utf-8")
            elif method == "GET" and path in ("/logs", "/logs/"):
                body = self._render_logs_page().encode("utf-8")
            elif method == "GET" and path.startswith("/logs/"):
                day, sep, rest = path[len("/logs/"):].partition("/")
                if sep and rest:
                    download_target = self._resolve_log_download(day, rest)
                else:
                    body = self._render_day_page(day).encode("utf-8")
            elif (method == "POST" and path.startswith("/logs/")
                  and path.endswith("/delete")):
                target = path[len("/logs/"):-len("/delete")]
                day, sep, rest = target.partition("/")
                if sep and rest:
                    removed_day = self._delete_file(day, rest)
                    body = (self._render_logs_page() if removed_day
                             else self._render_day_page(day)).encode("utf-8")
                else:
                    self._delete_day(day)
                    body = self._render_logs_page().encode("utf-8")
            elif method == "POST" and path in ("/apply", "/cancel"):
                if content_length > 1024:
                    raise ValueError("formulario demasiado grande")
                data = bytearray()
                while len(data) < content_length:
                    chunk = await reader.read(content_length - len(data))
                    if not chunk:
                        raise ValueError("formulario incompleto")
                    data.extend(chunk)
                if path == "/cancel":
                    stop_after_response = True
                    body = ("<html><meta name='viewport' content='width=device-width'>"
                            "<body>AP cerrado. Puedes volver al tablero.</body></html>"
                            ).encode("utf-8")
                else:
                    fields = _parse_form(bytes(data))
                    # Start with existing factors; only update where real_V given
                    b_supermini_factors = list(
                        self.settings.b_supermini_factors_milli)
                    real_any = any(
                        fields.get("real_{}_v".format(i), "").strip()
                        for i in range(1, 5))
                    if real_any:
                        raw_batteries = self.get_raw_batteries()
                        if raw_batteries is None:
                            raise ValueError(
                                "no hay telemetria ADS fresca; espera una "
                                "lectura valida antes de calibrar")
                        for index in range(1, 5):
                            real_v_str = fields.get(
                                "real_{}_v".format(index), "").strip()
                            if not real_v_str:
                                continue
                            real_v = float(real_v_str)
                            if not 0.5 <= real_v <= 30.0:
                                raise ValueError(
                                    "tension real B{} fuera de rango".format(
                                        index))
                            recv_v = raw_batteries[index - 1]
                            if recv_v <= 0:
                                raise ValueError(
                                    "lectura B{} no valida para calibrar".format(
                                        index))
                            current_factor = b_supermini_factors[index - 1]
                            new_factor = int(
                                real_v / recv_v * current_factor + 0.5)
                            b_supermini_factors[index - 1] = max(
                                800, min(1200, new_factor))
                    ads_mode = fields.get("ads_mode", "cumulative")
                    if ads_mode not in ("cumulative", "individual"):
                        ads_mode = "cumulative"
                    capacity = float(fields.get(
                        "capacity_wh",
                        str(self.settings.battery_capacity_wh)))
                    centimeters_per_pulse = float(fields.get(
                        "centimeters_per_pulse", ""))
                    if not 1 <= centimeters_per_pulse <= 10000:
                        raise ValueError(
                            "centimetros por pulso fuera de rango")
                    meters_per_pulse = centimeters_per_pulse / 100.0
                    sleep_timeout_min = int(fields.get("sleep_timeout_min", ""))
                    debounce_us = int(fields.get("debounce_us", ""))
                    max_speed_kmh = float(fields.get("max_speed_kmh", ""))
                    charged = fields.get("mark_charged") == "1"
                    precharge_wh = float(
                        fields.get("precharge_wh", "0") or "0")
                    source_boot, source_wh = self.get_source_cursor()
                    self.apply_settings(
                        b_supermini_factors, ads_mode, capacity, charged,
                        source_boot, source_wh,
                        meters_per_pulse, debounce_us, max_speed_kmh,
                        sleep_timeout_min, precharge_wh)
                    stop_after_response = True
                    body = ("<html><meta name='viewport' content='width=device-width'>"
                            "<body>Configuracion guardada. Los ajustes se enviaran "
                            "al Super Mini por ESP-NOW. Verificar con "
                            "main.config_status(). AP cerrado.</body>"
                            "</html>").encode("utf-8")
            elif method == "GET":
                # Captive portal: cualquier ruta GET desconocida (sondeos de
                # conectividad de iOS/Android/Windows) recibe la pagina de
                # config en vez de 404, para que el SO abra el navegador
                # cautivo automaticamente.
                body = self._render_index_page().encode("utf-8")
            else:
                status = "404 Not Found"
                content_type = "text/plain; charset=utf-8"
                body = b"Not found"
        except (ValueError, UnicodeError) as exc:
            status = "400 Bad Request"
            content_type = "text/plain; charset=utf-8"
            body = str(exc).encode("utf-8")
        except OSError as exc:
            print("[config] error HTTP:", exc)
            status = "500 Internal Server Error"
            content_type = "text/plain; charset=utf-8"
            body = b"No se pudo procesar la solicitud"
        except Exception as exc:
            print("[config] error inesperado procesando HTTP:", exc)
            status = "500 Internal Server Error"
            content_type = "text/plain; charset=utf-8"
            body = b"Error interno del servidor T190"
        try:
            if download_target is not None:
                await self._send_file(writer, *download_target)
            else:
                writer.write(_http_headers(status, content_type, body))
                writer.write(body)
                print("[config] respuesta {} {} bytes".format(status, len(body)))
                await writer.drain()
            if stop_after_response:
                self.request_stop()
        except OSError as exc:
            print("[config] cliente desconectado:", exc)
        finally:
            writer.close()
