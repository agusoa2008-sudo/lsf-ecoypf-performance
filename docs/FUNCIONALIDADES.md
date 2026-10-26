# EcoYPF 2026 — Funcionalidades actuales por nodo

> Estado al 2026-10-24. Marca ✅ = implementado y activo; ⚠️ = implementado
> pero sin validación física completa; ⏳ = diseñado, pendiente de código.

---

## Nodo 1 — Super Mini S3

**Hardware:** ESP32-S3 Super Mini  
**Carpeta:** `SUPER MINI S3/`  
**Rol:** único responsable de la adquisición de sensores y del cálculo de
todas las métricas de tracción. El T190 no recalcula nada de lo que el
Super Mini ya calculó.

### Sensores

| Sensor | Interfaz | GPIO | Qué mide |
|---|---|---|---|
| ADS1115 | I2C (SCL=12, SDA=13) | GPIO12/13 | 4 taps acumulativos del pack → B1..B4 individuales y VBATS total |
| ADS1220 + toroidal Hall "LSF" | SPI1 (SCK=4, MOSI=1, MISO=2, CS=3) | — | Corriente de batería (no invasivo) |
| Sensor de pulsos de velocidad | IRQ GPIO10, pull-up | GPIO10 | Pulsos de rueda → velocidad instantánea y distancia acumulada |
| Presencia de B4 (divisor del auto, 48V) | GPIO digital, pull-down | GPIO11 | Alto = auto encendido/B4 presente, bajo = B4 ausente → dispara deep sleep |

**Modo de medición ADS1115 — acumulativo (único modo actual):**
Los 4 canales del ADS1115 miden taps respecto a masa:
`A0=B1` (tap0), `A1=B1+B2` (tap1), `A2=B1+B2+B3` (tap2), `A3=B1+B2+B3+B4` (tap3).
El firmware resta taps consecutivos para obtener las tensiones individuales:
`B1=tap0`, `B2=tap1−tap0`, `B3=tap2−tap1`, `B4=tap3−tap2`.
Cada tap tiene su propio divisor resistivo; los ratios viven en
`config.json → battery.tap_divider_ratio`.

### Cálculos (fuente de verdad)

| Magnitud | Cómo | Estado |
|---|---|---|
| Tensiones B1–B4 y VBATS | ADS1115, ratio de divisor + factor grueso por banco | ✅ |
| Corriente I | ADS1220, sensibilidad Hall `current_sens_v_per_a` | ✅ |
| Potencia instantánea `P` | `VBATS × I` | ✅ |
| Potencia promedio 5 s `PA` | EMA con τ=5 s | ✅ |
| Velocidad `V` | Período entre pulsos; cero si último pulso > 2 s | ✅ |
| Distancia `D` | Suma de `delta_pulsos × metros_por_pulso` | ✅ |
| Energía `WT` | Integral de `P × dt` en Wh | ✅ |
| Eficiencia instantánea `WI` | `P / V` (solo si `V > 0.5 km/h`) | ✅ |
| Eficiencia promedio `WA` | `WT / (D/1000)` | ✅ |

### Validez de sensores y recuperación

- `AV=1` solo si ADS1115 respondió y ningún canal está cerca de saturación
  (`ADS1115_SAT_WARN_V = 3.1 V`; VDD = 3.3 V). ✅
- `IV=1` solo si ADS1220 inicializado y lectura actual válida. Si falla,
  potencia e integración de Wh se detienen; el Super Mini reintenta la
  inicialización cada 5 s. ✅
- Pulsos rechazados: flancos que impliquen superar `max_speed_kmh` se
  cuentan en `rechazados` y no suman distancia. ✅
- `main.calibrate_current_zero()` calibra el offset del ADS1220 con
  corriente nula (llamar una vez por sesión con la bicicleta en reposo). ✅

### Salida — ESP-NOW al T190

Frame V3, ~1 Hz, unicast al T190 emparejado:

```
VER=3;BOOT=<id>;Q=<seq>;AV=<0|1>;IV=<0|1>;PC=<pulsos>;
I=<A>;B1=<V>;B2=<V>;B3=<V>;B4=<V>;VBATS=<V>;
P=<W>;PA=<W>;V=<km/h>;D=<m>;WI=<Wh/km>;WA=<Wh/km>;WT=<Wh>
```

Protocolo de pairing: el Super Mini broadcastea `SM_PAIR_REQ`; el T190
responde `T190_PAIR_ACK`; la MAC queda guardada en `espnow_peer.bin`. ✅

### Configuración remota desde el T190

Frame `CFG:` por ESP-NOW (unicast T190 → Super Mini):

```
CFG:V=1;ID=<revision>;MP=<metros/pulso>;DB=<us>;MAX=<km/h>;F1=<milli>;F2=<milli>;F3=<milli>;F4=<milli>
```

El Super Mini valida, persiste en `config.json`, recarga en caliente y
responde `CFGA:<revision>` (confirmado) o `CFGN:<revision>` (rechazado). ✅

### Deep sleep por pérdida de B4 (GPIO11)

El Super Mini puede alimentarse de B4 (banco de 48V del auto) o de su
Li-ion propia. GPIO11 lee, vía un divisor resistivo externo, si B4 está
presente (alto) o ausente (bajo) — sigue vivo con la Li-ion mientras
decide si dormir.

- Si B4 se mantiene ausente durante `sleep.b4_loss_timeout_s` (60 s por
  defecto, 0 = desactivado), guarda `wh_total` y `dist_m` en `trip.json`
  (escritura atómica, `trip_store.py`), apaga el LED y entra en deep sleep.
- Vuelta de B4 o un pulso de velocidad (GPIO10, rueda girando = auto en
  movimiento) cancela la cuenta regresiva antes del timeout.
- Wake: GPIO11 de bajo a alto (`esp32.wake_on_ext1`). Al despertar la
  placa reinicia (como todo deep sleep en ESP32-S3) y restaura
  Wh/distancia desde `trip.json`.
- El NeoPixel se apaga a mano antes de dormir (`StatusLed.off()`): un
  WS2812 retiene el último color escrito aunque el CPU se duerma. ✅
  código; ⚠️ sin prueba física con el auto todavía.

### Indicador de estado — LED NeoPixel (GPIO48)

| Color | Significado |
|---|---|
| Azul | Arrancando |
| Verde parpadeante | Todos los sensores OK |
| Amarillo parpadeante | Algún sensor falta |
| Rojo parpadeante | Ningún sensor responde |

### REPL del Super Mini

| Función | Descripción |
|---|---|
| `start()` / `stop()` | Arrancar/detener hilo de fondo |
| `status()` | Línea compacta con todos los valores actuales |
| `values(N)` | Dashboard legible; con argumento repite N segundos |
| `diag()` | Scan I2C + resumen de estado de cada sensor |
| `debug(on)` | Stream continuo de lecturas (útil para depurar) |
| `calibrate_current_zero()` | Calibrar offset ADS1220 con corriente nula |
| `reload_config()` | Recargar `config.json` sin detener el hilo |
| `dump_config()` | Imprimir configuración activa |
| `espnow_status()` | Estado del enlace con T190 |
| `espnow_repair()` | Olvidar peer y volver a modo pairing |
| `power_status()` | Presencia de B4 (GPIO11) y cuenta regresiva de sleep |
| `force_sleep()` | Forzar deep sleep ahora (pruebas de banco) |

### Configuración — `config.json`

```json
{
  "speed": { "meters_per_pulse": 0.1, "debounce_us": 2000, "max_speed_kmh": 80.0 },
  "battery": {
    "tap_divider_ratio": [5.3, 9.7, 15.3, 19.7],
    "current_sens_v_per_a": 0.007813,
    "voltage_factor_milli": [1000, 1000, 1000, 1000]
  },
  "sleep": { "b4_loss_timeout_s": 60 },
  "remote_config_id": 0
}
```

`meters_per_pulse` es provisional (0.1 m/pulso = 10 cm/pulso). Calibrar
midiendo una distancia conocida y dividiendo metros recorridos por pulsos
contados. Se puede editar y recargar con `reload_config()` sin reflashear.

---

## Nodo 2 — T190 (display + gateway)

**Hardware:** Heltec Vision Master T190 (ESP32-S3)  
**Carpeta:** `New T190/`  
**Rol:** display de cabina para el piloto, gateway LoRa y registrador SD.
No mide sensores de tracción; consume lo calculado por el Super Mini.

### Display TFT (ST7789, 170×320 px landscape)

Pantalla con fuente 7 segmentos grande, blanco sobre negro.
Actualmente: un campo por vez, navegado con BTN0/S3.

**Campos disponibles (14 en total, orden actual en `FIELDS`):**

| # | Grupo | Campo | Código | Unidad |
|---|---|---|---|---|
| 0 | RUTA | VELOCIDAD | SPD | km/h |
| 1 | EFICIENCIA | Wh/km PROM | WA | Wh/km |
| 2 | CONSUMO | POT PROM 5s | PA | W |
| 3 | CONSUMO | POT INSTANT | PI | W |
| 4 | CONSUMO | CORRIENTE | I | A |
| 5 | EFICIENCIA | Wh/km INSTANT | WI | Wh/km |
| 6 | VIAJE | DISTANCIA | DST | m |
| 7 | VIAJE | ENERGIA | WT | Wh |
| 8 | BATERIA | BATERIA 1 | B1 | V |
| 9 | BATERIA | BATERIA 2 | B2 | V |
| 10 | BATERIA | BATERIA 3 | B3 | V |
| 11 | BATERIA | BATERIA 4 | B4 | V |
| 12 | BATERIA | VBATS TOTAL | TOT | V |
| 13 | CALIBRACION | PULSOS | PLS | — |

`PULSOS` muestra `pulse_count` tal como llega del Super Mini (campo `PC`
del protocolo V3, ver `telemetry.py`) — el contador crudo de pulsos de
rueda, sin convertir a distancia. Sirve para calibrar
`meters_per_pulse` (config.json del Super Mini, grupo `speed`): rodar una
distancia conocida, anotar el delta de pulsos entre el inicio y el final,
y `metros_por_pulso = distancia_m / delta_pulsos`.

Más pantallas especiales: `DIAGNOSTICO`, `AYUDA BOTONES`, `CONFIGURACION`,
`CARGA`.

> **Pendiente de rediseño:** ver `CONTINUACION_DESARROLLO.md §2` para el
> nuevo orden de pantallas agrupado por relevancia en marcha.

### Pantalla OLED 0.96" adicional (I2C) ⏸️ en pausa — ver `CONTINUACION_DESARROLLO.md §3`

Se intentó un OLED SSD1306 128x64 como pantalla extendida fija, primero en
GPIO15/16 y después en GPIO1/2 (QL_SCL/QL_SDA, único par I2C real de la
placa según el pin map oficial de Heltec). Quedó **pausado sin resolver**:
el bus respondía al scan pero las escrituras tiraban `OSError ETIMEDOUT`
de forma inconsistente (a veces en comandos de 2 bytes, a veces en el
framebuffer completo), y el bus llegó a trabarse por completo más de una
vez (necesitando recuperación manual). Se descartó pines, frecuencia
(400/100/50kHz), I2C por hardware vs. `SoftI2C`, y tamaño de transacción
como causa — todo apunta a algo físico (pull-ups, cable, o la fuente
`Ve_3V3` cayendo bajo carga) que no se pudo terminar de diagnosticar de
forma remota. El driver (`drivers/ssd1306.py`, con `blit()` para glyphs)
y los scripts de banco (`oled_test.py`, `oled_seven_seg_test.py`,
`seven_seg.draw_text_mono*`) quedan en el repo por si se retoma, pero el
GPS ya volvió a ocupar GPIO1/2 en el QuickLink (configuración original) y
esto no está integrado a `main.py`.

### Botones

| Botón / GPIO | Gesto | Acción |
|---|---|---|
| BTN0 / GPIO0 | Corto (< 420 ms) | Pantalla siguiente |
| BTN0 | Doble (2° click < 320 ms) | Volver a VELOCIDAD; cancela AP sin guardar |
| BTN0 | Largo (1,2 s – < 2,2 s) | Alternar log SD; en `CONFIGURACION`, iniciar/detener AP |
| BTN0 | Extra (≥ 2,2 s) | Sin acción |
| S3 / GPIO21 | Corto (< 420 ms) | Pantalla anterior; cancela AP y vuelve a VELOCIDAD |
| S3 | Doble | Sin acción efectiva (reset Super Mini pendiente) |
| S3 | Largo (1,2 s – < 2,2 s) | Capturar waypoint GPS en RAM |
| S3 | Extra largo (≥ 2,2 s) | Solicitar deep sleep al soltar |

Todos los gestos se disparan al soltar (IRQ en flanco activo-bajo + asyncio
debounce 25 ms). Un hold de 420 ms – 1,2 s no hace nada. ✅

### GPS

Módulo NMEA por UART1, GPIO1 (RX del T190 ← TX del GPS) y GPIO2 (TX →
RX del GPS), 9600 baud. VEXT habilitado por GPIO5 al arrancar.
El parser descarta frases con bytes no imprimibles (las cuenta en
`gps_status()`). Con RMC válido sincroniza el RTC del T190 a ART (UTC−3),
máximo una vez por minuto. Fix y satélites visibles en pantalla
`DIAGNOSTICO`. Captura de waypoint GPS con S3 largo (guardado en RAM). ✅  
Cálculo de tiempo de vuelta y cruce de waypoint: ⏳ por implementar.

### LoRa — TX al Paddock ⚠️

SX1262 onboard (HT-RA62), GPIO8-14. Perfil `tradeoff`:
915 MHz, BW 125 kHz, SF9, CR 4/6, 17 dBm, sync 0x12, preámbulo 12.
Retransmite el frame V3 cada ~2 s con `AGE` (edad de origen en ms).
Si `AGE > 5000 ms`, marca `AV=0;IV=0` pero sigue transmitiendo.
TX local confirmado; sin ACK del Paddock. ✅ código; ⚠️ sin prueba física.

### microSD — Logger CSV ⚠️

Comparte SPI2 con el SX1262 (CS independientes: LoRa GPIO8, SD GPIO4).
Se monta en `/sd` al arrancar. Escribe una fila por segundo con:
tiempo monotónico relativo, secuencia/boot, timestamp ART (cuando hay GPS),
validez de sensores, B1–B4 (V), VBATS, I, P, V, D, Wh/km, Wh acumulados,
pulsos, GPS (cuando hay fix). Cada fila incluye CRC16.
Nombres de archivo: `RIDE_YYYYMMDD_HHMMSS.CSV` (con GPS) o `RIDE####.CSV`.
Flush por fila; cierre/reapertura cada 5 s para persistir metadata FAT.
Al detener o entrar en deep sleep: escribe `END`, cierra y desmonta. ✅ código; ⚠️ sin prueba con LoRa simultáneo.

**Inicio del log:**
- Automático: cuando `speed >= 0.5 km/h`
- Manual: BTN0 largo fuera de `CONFIGURACION`
- REPL: `main.log_start()`, `main.log_stop()`, `main.log_auto()`

### Calibración de tensiones y configuración del pack

**T190 aplica factores finos** (`fine_voltage_factors_milli`, 800–1200
milésimas) a B1–B4 recibidos del Super Mini; recalcula VBATS y ajusta P/Wh
por la relación de tensión total. La corriente, velocidad y distancia no
se escalan.

**Pack de 4 × 12 V serie = 48 V, 17 Ah, 816 Wh nominales.** La capacidad
útil se puede reducir según la química y el estado de la batería.
Marcar el pack como "cargado" desde la página del AP inicia la estimación
de energía restante y porcentaje de carga.

> **Pendiente de rediseño:** ver `CONTINUACION_DESARROLLO.md §1` para la
> simplificación de calibración (un único campo de tensión real por banco,
> sin separación entre ajuste fino T190 y ajuste grueso Super Mini).

### AP de configuración

AP Wi-Fi `Main-T190` bajo demanda (SSID/contraseña en `config_server.py`).
Para activarlo: ir a pantalla `CONFIGURACION` (S3 corto desde VELOCIDAD),
BTN0 largo (1,2 s – < 2,2 s). Página en `http://192.168.4.1/`.
Permite ajustar:
- B1–B4: factor fino del T190 (milésimas) o tensión real en mV para
  calcular el factor automáticamente
- Capacidad útil del pack (Wh)
- Timeout de deep sleep (0 = desactivado)
- Parámetros del Super Mini: cm/pulso, anti-rebote, velocidad máxima,
  factores gruesos B1–B4

Guardar envía los cambios y cierra el AP. Cancelar: S3 corto o BTN0 doble.
La coexistencia del AP con ESP-NOW y LoRa debe validarse en hardware. ⚠️

### Deep sleep

- **Automático por velocidad:** si la telemetría ESP-NOW está fresca y
  reporta `speed ≤ 0.1 km/h` durante el tiempo configurado
  (`idle_sleep_timeout_min`), solicita deep sleep. Movimiento reinicia el
  temporizador.
- **Automático por pérdida del Super Mini:** si el Super Mini ya estaba
  emparejado y la telemetría se queda STALE (ver `SOURCE_STALE_MS` en
  `telemetry.py`) — porque se durmió (deep sleep por B4 ausente, ver
  `SUPER MINI S3/main.py: _enter_deep_sleep`) o quedó fuera de rango — y no
  vuelve en `SUPERMINI_LOST_SLEEP_TIMEOUT_MS` (30 s), el T190 lo acompaña a
  dormir en vez de quedarse despierto sin fuente de datos. Si todavía no
  emparejó nunca (arranque normal esperando al Super Mini), no cuenta para
  este timeout. Si la telemetría vuelve antes de agotarse, el temporizador
  se reinicia (sigue estacionario) o se desactiva (hay movimiento). Ambos
  automáticos se desactivan junto con `idle_sleep_timeout_min = 0`.
- **Aviso en pantalla:** mientras cualquiera de los dos temporizadores
  automáticos está corriendo, la pantalla principal muestra
  `DUERME EN Xs (detenido)` o `DUERME EN Xs (Super Mini ausente)` en rojo
  (`_sleep_warning_text()` / `idle_sleep_task` en `main.py`).
- **Cualquier botón reinicia el temporizador:** un gesto de BTN0 o S3
  (corto/doble/largo/extra) reinicia el temporizador automático que esté
  corriendo — ver `_note_button_activity()` / `_with_activity()` en
  `main.py`. El equipo sigue en uso, no se considera abandonado.
- **Manual:** S3 extra largo (≥ 2,2 s), se ejecuta al soltar el botón.
- Antes de dormir: detiene tareas, cierra CSV, duerme LoRa, apaga TFT/
  backlight y VEXT/GPS.
- Wake: S3/GPIO21 en nivel bajo. ✅ timeout wake verificado en placa;
  ⚠️ wake físico con S3 pendiente de validación.

### Valores no disponibles en pantalla

Si la telemetría del Super Mini no está fresca (`source_fresh()` falso —
recién arrancando sin emparejar aún, o perdida), el valor grande de la
pantalla activa (velocidad, tensiones B1–B4/VBATS, corriente, potencia,
Wh/km, distancia, pulsos) muestra `--` en gris en vez del último valor
numérico (que podía confundirse con una lectura real de cero). La fila de
estado ya mostraba `SRC:STALE`/`ESPNOW: SIN DATOS`; ahora el valor
principal también lo refleja.

### Batería interna del T190

ADC GPIO6, divisor R9/R11, control GPIO46. Mediana de 9 lecturas con
descarte inicial. Se muestra en `DIAGNOSTICO` y en el header. ✅

### Persistencia — `t190_settings.json`

Guarda: factores finos B1–B4, capacidad del pack, estado de energía usado,
parámetros del Super Mini, revisión de configuración, timeout de deep sleep.
Escritura atómica con archivo temporal y respaldo. ✅

### REPL del T190

| Función | Descripción |
|---|---|
| `start()` / `stop()` | Arrancar/detener hilo de app |
| `status()` | Estado general del gateway |
| `battery_status()` | Voltaje, ADC crudo, método de conversión |
| `gps_status()` | Fix, satélites, bytes inválidos, hora ART |
| `espnow_status()` | Enlace y contador de recepciones |
| `espnow_repair()` | Olvidar peer y volver a modo pairing |
| `log_status()` | Estado SD, archivo actual, modo |
| `log_start()` / `log_stop()` | Iniciar/detener log desde REPL |
| `log_auto()` | Volver a modo automático |
| `config_status()` | Estado de configuración y AP |
| `deep_sleep()` | Solicitar deep sleep inmediato |

---

## Nodo 3 — Paddock S3

**Hardware:** Seeed XIAO ESP32-S3 + Wio-SX1262  
**Carpeta:** `Paddock S3/`  
**Rol:** recibir el frame LoRa del T190 y servir un dashboard web en vivo
al equipo técnico en cajas.

| Feature | Estado |
|---|---|
| Recepción LoRa V3 (mismo perfil que T190) | ✅ código |
| AP WPA2 `Paddock-LSF`, IP `192.168.4.1` | ✅ código |
| Dashboard HTTP en vivo (velocidad, tensiones, I, P, Wh/km) | ✅ código |
| Push al dashboard por SSE (`/events`), sin esperar sondeo de 1 s | ✅ código |
| Distinción entre edad del paquete LoRa y edad de muestra (`AGE`) | ✅ código |
| Reporte de validez `AV`/`IV` | ✅ código |
| Validación física con radio real | ⚠️ pendiente |

LoRa parámetros: 915 MHz, BW 125 kHz, SF9, CR 4/6, 17 dBm, sync 0x12,
preámbulo 12 — idéntico al T190. El alcance depende de antenas y entorno;
objetivo 1 km en línea de vista. El enlace es unidireccional (T190 → Paddock).

### Dashboard web — push por SSE (baja latencia) ✅ código

El teléfono abría `/api` por `fetch` cada 1 s con una conexión TCP nueva
por request — esa era la mayor fuente de latencia entre "llega el paquete
LoRa" y "se ve en el teléfono" (hasta 1 s de sondeo + overhead de conectar
cada vez), mayor que la latencia propia del T190 (~2 s en su propio loop
de pantalla, caso aparte).

Ahora la página abre un stream `EventSource` a `/events`; el Paddock
empuja un JSON apenas decodifica cada paquete LoRa (`broadcast()` en
`web_server.py`, llamado desde `_on_message` en `main.py`). `/api` sigue
disponible para el primer render y como respaldo si el navegador no
soporta SSE. Máximo 4 clientes SSE simultáneos; heartbeat cada 15 s que
también depura conexiones muertas (teléfono que salió de rango). Ver
`Paddock S3/README.md`.

⚠️ pendiente de validar en banco con radio real y varios teléfonos a la vez.

---

## Resumen de pinout Super Mini S3

| GPIO | Señal |
|---|---|
| 1 | ADS1220 MOSI |
| 2 | ADS1220 MISO |
| 3 | ADS1220 CS |
| 4 | ADS1220 SCK |
| 10 | Pulso de velocidad (IRQ, pull-up) |
| 12 | I2C SCL → ADS1115 |
| 13 | I2C SDA → ADS1115 |
| 48 | LED NeoPixel (status) |

## Resumen de pinout T190

| GPIO | Señal |
|---|---|
| 0 | BTN0 (activo bajo) + LED naranja |
| 1 | GPS UART1 RX (← TX del módulo GPS) |
| 2 | GPS UART1 TX (→ RX del módulo GPS) |
| 4 | microSD CS (SPI2 compartido) |
| 5 | Ve_Ctrl: habilita Ve_3V3 / VEXT / GPS |
| 6 | VBAT_Read: ADC batería interna |
| 7 | VTFT_Ctrl: alimentación TFT (activo bajo) |
| 8–14 | LoRa SX1262: CS/SPI/RST/BUSY/DIO1 |
| 15 | I2C SCL → OLED adicional (si se conecta) |
| 16 | I2C SDA → OLED adicional |
| 17 | LEDK_EN: backlight TFT |
| 21 | S3 / USER_KEY (activo bajo; también wake desde deep sleep) |
| 38/47/48/39/40 | TFT SPI1: SCK/MOSI/DC/CS/RST |
| 43/44 | UART0 TX/RX (REPL) |
| 46 | ADC_Ctrl: habilita divisor de batería |
