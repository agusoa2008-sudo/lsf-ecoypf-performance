# ESP32 IdeaSpark — Display secundario "on wheel"

**Rol:** segundo display del vehículo (más grande/legible para el piloto que
el display integrado del T190). Recibe por **ESP-NOW** la telemetría ya
calculada por la unidad de abordo (`New T190/`) — no duplica ningún cálculo,
solo pairing + recepción + render.

**Alcance de esta primera versión:** SOLO receptor ESP-NOW + pairing inicial
+ pantalla de estado con la línea cruda recibida. Todavía NO parsea los
campos individuales (I, B1..B4, P, velocidad, etc.) en una UI tipo "un valor
grande a la vez" — eso es el próximo paso natural, ver §4.

---

## 0. Fix de hardware real — MemoryError + SPI clock (primer boot)

Primer intento en hardware real (log del usuario): `Generic ESP32 module with
ESP32` -- **no es un ESP32-S3**, es un ESP32 clásico **sin PSRAM** (a
diferencia del T190, que es un ESP32-S3R8 con 8MB de PSRAM). Dos fallas:

1. `E spi_hal: The clock_speed_hz should less than 26666666` /
   `spi_bus_add_device(500): assigned clock speed not supported` — en pines
   que no son el matriz nativo de VSPI/HSPI, el SPI por GPIO matrix del
   ESP32 clásico tiene un techo de 80MHz/3 ≈ 26.67MHz. `HW.TFT_BAUDRATE`
   estaba en 40MHz (copiado del T190, que sí soporta esa velocidad). Fix:
   bajado a **20MHz** (`HW.py`).
2. `MemoryError: memory allocation failed, allocating 108800 bytes` —
   `drivers/tft170.py` (portado 1:1 del T190) guardaba la pantalla completa
   como `framebuf.FrameBuffer` en RAM (170×320×2 bytes). En el T190 eso vive
   en PSRAM sin problema; en este ESP32 sin PSRAM, un solo bloque contiguo
   de ~106KB no entra en el heap disponible (ya reducido por el stack de
   WiFi/MicroPython). **Fix: se reescribió el driver completo** para que
   nunca guarde la pantalla en RAM — `fill()`/`hline()`/`text()` escriben
   directo al panel por SPI en bloques chicos (≤1KB), igual patrón que
   `New T190/st7789py.py` (Russ Hughes), que tampoco mantiene framebuffer
   propio. La API pública (`TFT170(...)`, `.fill()`, `.text()`, `.hline()`,
   `.show()`, `rgb565()`) quedó idéntica, así que `main.py`/`espnow_link.py`
   no necesitaron cambios.

**Costo de este driver "sin framebuffer":** no tiene `blit()` de sprites
(requeriría una pantalla destino en RAM para componer). Si en el futuro se
porta la UI de campos grandes del T190 (`seven_seg.py`, que usa
`tft.blit()` con fuentes `font_to_py`), hay que adaptar ese renderizador
para que cada glifo se mande directo por SPI en vez de componer sobre un
framebuffer — no alcanza con copiar `seven_seg.py` tal cual (ver nota en el
docstring de `drivers/tft170.py`).

---

## 1. Hardware — pinout

No existe un datasheet oficial de Ideaspark (es una marca que vende por
AliExpress sin documentación propia consolidada). El pinout de abajo es
ingeniería inversa de la comunidad, confirmada en dos fuentes independientes:

| Señal | GPIO |
|---|---|
| MOSI | 23 |
| SCLK | 18 |
| CS | 15 |
| DC | 2 |
| RST | 4 |
| Backlight | 32 |

**Fuentes:**
- [TuxDoingStuff/dev-ideaspark-esp32](https://github.com/TuxDoingStuff/dev-ideaspark-esp32)
- [Pixelssquad/NerdMiner_v2_IdeaSpark1.9in-ST7789-Display-LCD-TFT-170x320](https://github.com/Pixelssquad/NerdMiner_v2_IdeaSpark1.9in-ST7789-Display-LCD-TFT-170x320)
- [ideaspark ESP32 1.9" TFT LCD — manual](https://manuals.plus/asin/B0D6QXC813)
- [arendst/Tasmota discussion #22669](https://github.com/arendst/Tasmota/discussions/22669) (hilo original que motivó esta placa)

⚠️ **Ideaspark tiene varias revisiones** de esta placa. GPIO4 (RST del TFT)
en algunas revisiones también está atado a un microswitch físico de reset
del panel — no es un GPIO de usuario. **Verificar contra las fotos del
listado real de AliExpress antes de cablear nada.**

Controlador: **ST7789 real**, 170x320, igual que el T190 — por eso
`drivers/tft170.py` se portó 1:1, pero sus offsets (`x_offset=35,
y_offset=0`) están **sin verificar en este panel concreto** (ver docstring
del driver). Si la imagen sale con bandas/corrida/espejada, portar
`New T190/madctl_test.py` para recalibrar.

---

## 2. Arquitectura de archivos (misma convención que `New T190/`)

| Archivo | Rol |
|---|---|
| `HW.py` | Pin map del display (sin ADC/I2C/motor — este board no los necesita) |
| `drivers/tft170.py` | Driver ST7789 170x320, portado de `New T190/drivers/tft170.py` |
| `espnow_link.py` | `EspNowLink` — lado receptor del protocolo de pairing, espejo de `New T190/espnow_link.py` (ver §3) |
| `main.py` | App "REPL libre": display + receptor ESP-NOW + pantalla de estado — ver §4 |
| `boot.py` | Hostname `WheelDisp-XXXX`, igual patrón que `New T190/boot.py` |
| `d.py` / `p.py` | Toggles de testing (deshabilitar/restaurar `main.py`), copiados sin cambios de `New T190/` |

No se portaron `r.py`, `w.py`, `startup_cleanup.py` ni `startup_fallback.py`
del T190: en `New T190/` ya están desconectados de `boot.py` (no se llaman
desde ningún lado) o dependen de módulos que no existen en esa carpeta
(`reset`, `wifiConnect`) — son restos sin alambrar, no vale la pena
replicar código ya huérfano en el origen.

---

## 3. Protocolo de pairing (espejo del lado del T190)

Roles fijos: **el T190 inicia, este display acepta** (igual que documenta
`New T190/PROYECTO_T190.md` §4.b).

1. Si hay una MAC guardada en `espnow_peer.bin`, se recuerda al bootear — ya
   acepta telemetría `TLM:...` de esa MAC sin pedir nada.
2. Si llega un paquete `T190_PAIR_REQ` (el T190 lo broadcastea cada ~1s
   mientras no tenga peer guardado), este display contesta `T190_PAIR_ACK`
   por broadcast y guarda la MAC de origen como peer (persiste en
   `espnow_peer.bin`).
3. Paquetes con prefijo `TLM:` del peer emparejado se entregan a `main.py`
   vía `EspNowLink.rx_task()` — se muestran crudos en pantalla.

No hace falta `add_peer()` para la MAC del T190 antes de contestar: ESP-NOW
entrega la MAC real del emisor en `recv()` sin importar si la respuesta se
manda broadcast o unicast — por eso la respuesta va siempre por broadcast,
evitando ese paso.

Desde el REPL: `main.status()` (estado + última línea recibida) y
`main.repair()` (olvida el peer actual, vuelve a aceptar cualquier
`T190_PAIR_REQ` — usar si se cambia de T190 o la MAC dejó de responder).

---

## 4. Próximos pasos

1. Probar pairing end-to-end con el T190 real (confirmar que el firmware de
   **ambas** placas trae compilado el módulo `espnow` — ver riesgo en §5).
2. Si la imagen del display sale mal, portar `New T190/madctl_test.py` para
   calibrar offset/MADCTL de este panel.
3. Parsear los campos de la línea `TLM:I=..;B1=..;...` (mismo formato que
   `New T190/telemetry.py: _build_payload`) y portar la tabla `FIELDS` +
   `_draw_field()` de `New T190/main.py` a este display, para mostrar "un
   valor a la vez" en vez de la línea cruda.
4. Si este board tiene algún botón de usuario utilizable (a confirmar según
   la revisión física — el front-button en GPIO0 mencionado en el hilo de
   Tasmota), reusar `New T190/buttons.py: PageButton` para navegar entre
   campos, igual que el T190 usa su botón S3.

---

## 5. Revisión del lado emisor (`New T190/espnow_link.py` + `telemetry.py` + `main.py`)

Repasado para escribir el receptor espejado. No hay nada bloqueante; notas
para tener en cuenta:

- **Riesgo ya documentado por ustedes mismos** (`PROYECTO_T190.md` §4.b): el
  módulo `espnow` depende de `MICROPY_PY_ESPNOW` en el build de MicroPython.
  Aplica a **ambas** placas — confirmar que el firmware de la Ideaspark
  también lo trae compilado, no asumir que sí porque el del T190 lo trae.
- **`send_telemetry()` (`espnow_link.py:120-131`) solo contempla `OSError`
  como falla de envío.** Según el build/puerto exacto de `micropython-espnow`
  que uses, `ESPNow.send()` puede devolver `False` en vez de lanzar una
  excepción cuando el peer no confirma el ACK de radio (p. ej. receptor
  apagado o fuera de rango). Si tu build hace eso, `send_telemetry()` nunca
  detecta la falla por esa vía y `state.espnow_ok` podría quedar en `True`
  con paquetes perdidos. Fácil de confirmar en el REPL del T190 apagando el
  receptor y mirando qué devuelve `self._e.send(...)` — si devuelve `False`,
  agregar ese chequeo junto al `try/except`.
- **Fuga menor de peers en la tabla ESP-NOW.** Cuando `send_telemetry` falla
  con `OSError`, pone `paired=False` y vuelve a modo pairing, pero nunca
  hace `del_peer()` del MAC viejo ni borra `espnow_peer.bin` — solo
  `repair()` hace esa limpieza explícita. Para una sola pareja T190↔display
  esto no importa, pero si vas a re-parear muchas veces en banco de pruebas,
  tené en cuenta que la tabla de peers del ESP32 tiene un límite (típicamente
  20) y los viejos nunca se liberan solos.
- El guard `if msg is None or self.paired: return` en `_handle_incoming()`
  (lado T190) está bien pensado: evita que ruido de broadcast reemplace el
  peer ya fijado una vez emparejado. El receptor que escribí en este folder
  es deliberadamente más permisivo (siempre re-ACKea y actualiza el peer en
  `_handle_pair_req`), porque en este protocolo el T190 es la única fuente
  de verdad sobre cuándo re-parear — solo entra en modo pairing cuando él
  mismo no tiene peer guardado o tras un `espnow_repair()` explícito, así que
  no hay riesgo real de que un emisor no deseado dispare un re-pairing en
  operación normal.
