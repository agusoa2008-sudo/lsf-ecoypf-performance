# Sistema de Telemetría e Instrumentación — Desafío Eco YPF 2026

**Proyecto:** uPy Proto 1 — Super Mini S3 (sensado y métricas) + Heltec Vision Master T190 (display/gateway/piloto) + Paddock S3 (receptor LoRa)
**Categoría:** Desafío Eco YPF — Campeonato Argentino (Noviembre 2026), reglamento CDA/ACA–FIA
**Fecha del documento:** 2026-10-20
**Propósito:** Documento base (uso interno) de la arquitectura y del protocolo implementado.

**Historial:**
- v0.9 (2026-10-12): primera arquitectura de tres nodos (unidad de abordo T190 + display secundario +
  paddock), con el T190 haciendo la medición y el cálculo.
- **v1.1 (2026-10-19): implementación y protocolo alineados.** El Super Mini conserva las métricas
  calculadas junto a sus sensores; el T190 muestra y retransmite el último frame válido, marcando
  secuencia, validez y edad de origen; el Paddock diferencia edad del paquete LoRa de edad de la muestra.
- **v1.2 (2026-10-19):** B1–B4 ahora son tensiones individuales de cada batería; `VBATS` es la suma
  del pack y se usa para calcular potencia. El protocolo cambia a versión 3 en Super Mini, T190 y Paddock.
- **v1.3 (2026-10-20):** configuración desde el AP del T190: calibración fina individual B1–B4,
  capacidad útil del pack, timeout de deep sleep y envío confirmado por ESP-NOW de ajustes gruesos
  B1–B4 y parámetros de velocidad al Super Mini.
- v1.0 (2026-10-18) propuso trasladar todo el cálculo al T190. Esa migración **no se implementó** y se
  deja como alternativa futura, no como descripción del firmware activo.
- El GPS permanece en el T190 (no en el Super Mini, como proponía el diseño conceptual de La Salle
  Florida — `Instrumentacion_Telemetria_EcoYPF2026.pdf`, v0.1); se validó standalone en banco, pero
  todavía no se integra al flujo de telemetría ni calcula tiempos de vuelta.
- Requisitos aún pendientes del T190: alimentación independiente (batería propia) y modos deep
  sleep/wake por botón.

---

## 1. Resumen ejecutivo

El vehículo del Desafío Eco YPF es un monoplaza eléctrico de bajo consumo, con motor, variador y
baterías homologados y precintados por la CDA (ver §10 del reglamento técnico). Dentro de ese marco
cerrado, el reglamento permite explícitamente instrumentación digital de abordo con alimentación
propia (voltímetro, amperímetro y velocímetro — art. 11.5), siempre que no exceda la energía de 6
pilas AA y no tenga conexión al circuito eléctrico del vehículo.

La telemetría se implementa como un sistema de **dos nodos a bordo + un nodo de paddock**:

1. **Super Mini (sensores y métricas)** — ESP32-S3 Super Mini: lee las cuatro tensiones (ADS1115),
   corriente (ADS1220 + toroide) y pulsos; calcula potencia, energía, velocidad, distancia y Wh/km; y
   envía el snapshot por **ESP-NOW** con secuencia y flags de validez.
2. **T190 (display y gateway)** — Heltec Vision Master T190: recibe y valida el protocolo ESP-NOW,
   muestra las métricas y retransmite el frame con edad de origen por **LoRa** (SX1262 onboard).
   El GPS está probado standalone, pero aún no se integra en el flujo principal ni en el payload.
3. **Paddock** — Seeed XIAO ESP32-S3 con Wio-SX1262: receptor LoRa, AP WPA2 y mini web de telemetría
   (`Paddock S3/`, implementado; pendiente de validación física con el radio).

El enlace T190→paddock es **unidireccional** (auto → paddock) y por radiofrecuencia LoRa; no reemplaza
ni se confunde con los sistemas de comunicación piloto-box por voz regulados en el art. 13 del
reglamento (esos requieren manos libres integrado al casco y autorización específica de los
comisarios).

---

## 2. Marco reglamentario relevante

| Artículo | Contenido | Impacto en el diseño |
|---|---|---|
| 9.1 | Única fuente de energía: 4 baterías selladas y precintadas por la CDA | El Super Mini **mide** estas 4 baterías pero no puede alimentarse de ellas ni intervenirlas |
| 9.4 | Prohibida toda conexión eléctrica o cable hacia el auto en boxes | El enlace T190↔paddock debe ser 100% inalámbrico (LoRa) |
| 11.1–11.2 | Cableado eléctrico libre; prohibido usar el chasis como conductor | Toda la instrumentación debe tener su propio retorno, no usar masa de chasis |
| 11.4 | Prohibido agregar capacitores al circuito eléctrico del vehículo | No intervenir el circuito de potencia del auto para medir |
| **11.5** | **Permitido el uso de voltímetro, amperímetro y medidor de velocidad digital, con alimentación propia, cuya batería no exceda la energía de 6 pilas AA** | **Habilita el proyecto.** GPS, IMU y telemetría LoRa **no figuran explícitamente** en el artículo — consultar a `concursodesafioeco@ypf.com` (y/o `tecnica@aca.org.ar` por el canal del art. 17.1) si aplican la misma excepción |
| 13.1–13.2 | Comunicaciones piloto-box solo por manos libres integrado al casco, sin conexión al circuito del auto; cualquier sistema de comunicación debe declararse en la verificación técnica | El telemetry LoRa (T190→paddock, solo datos, sin voz) debe declararse y autorizarse por los comisarios, igual que cualquier sistema de comunicación a bordo. Un receptor GPS solo recibe (no transmite) y no debería caer bajo esta restricción |
| 10.1 / 15.1 | Motor, variador, acelerador y baterías sellados: prohibido abrirlos o modificarlos | La medición de corriente (sensor toroidal) y de pulsos de velocidad es **no invasiva**, sin abrir ni modificar los elementos sellados |

**Consecuencia de diseño:** tanto el Super Mini como el T190 deben alimentarse con batería(s) auxiliar(es)
propia(s), aisladas galvánicamente del banco de tracción, dimensionadas dentro del límite equivalente a
6 pilas AA por nodo (a confirmar con el organizador si el límite es por nodo o por el sistema completo).

---

## 3. Arquitectura general

```
 SUPER MINI S3 (sensores + métricas)       T190 (display + gateway)             PADDOCK S3
┌───────────────────────┐    ESP-NOW     ┌───────────────────────────────┐    LoRa    ┌──────────────────────┐
│ ADS1115 -> B1..B4 + VBATS│ ~1 Hz        │ Valida seq y flags de sensor   │   ~0.5 Hz  │ Valida origen y      │
│ ADS1220 -> I_bat       │ ─────────────▶ │ Display TFT + relé de datos   │ ─────────▶ │ edad LoRa separado   │
│ IRQ -> pulse_count     │ ver.=3; Q      │ No recalcula las métricas     │ ver.=3; AGE│ AP WPA2 + dashboard  │
│ Calcula P/Wh/V/D/Whkm  │ AV/IV + valores│ LoRa TX local (sin ACK RX)    │ + flags    │ HTTP 192.168.4.1     │
│ NeoPixel estado        │                │ GPS: prueba standalone        │            └──────────────────────┘
└───────────────────────┘                 │ aún no integrado               │
                                           │ GPS propio (UART GPIO1 RX /    │
                                           │ GPIO2 TX, MTK3339): prueba      │
                                           │ standalone; aún no integrado   │
                                           │                                 │
                                           │ Boton S3 (GPIO21):              │
                                           │  - short press = siguiente dato│
                                           │  - wake desde deep sleep       │
                                           │                                 │
                                           │ Bateria propia independiente   │
                                           │ (aislada del banco de traccion)│
                                           └───────────────┬─────────────────┘
                                                            │ ESP-NOW broadcast (existente, opcional)
                                                            ▼
                                           ESP32 IdeaSpark — display de volante
                                           (código ya en el repo; fuera del
                                            alcance de esta actualización)
```

Enlaces: Super Mini → T190 por ESP-NOW (unicast, pairing persistente); T190 → paddock por LoRa
(SX1262, parámetros idénticos en ambos extremos). El LoRa actual es unidireccional: el éxito indica
que terminó el TX local, no que Paddock recibió el paquete.

El canal de mediciones es Super Mini → T190. Para calibración, ESP-NOW también transporta
comandos versionados T190 → Super Mini y confirmaciones `CFGA`/`CFGN` en sentido inverso.

---

## 4. Nodo 1 — Super Mini (adquisición de datos)

Carpeta: `SUPER MINI S3/`. Mide, cuenta y actualmente calcula las métricas derivadas junto a los
sensores. Es la fuente de verdad de potencia/energía/velocidad/distancia/Wh-km.

### 4.1 Sensado

| Magnitud | Sensor / interfaz | Qué manda |
|---|---|---|
| Tensión de baterías B1–B4 y total `VBATS` | ADS1115 (I2C), taps acumulativos; diferencias consecutivas para cada batería, suma para el total | Valores instantáneos por ciclo de muestreo |
| Corriente de batería | ADS1220 (SPI) + sensor toroidal Hall (placa "LSF"), no invasivo | Valor instantáneo por ciclo de muestreo |
| Pulsos de velocidad | Contador por IRQ en `HW.SPEED_PULSE_PIN` | Contador acumulado `PC` y velocidad; distancia se suma por delta de pulsos |

### 4.2 Por qué contador acumulado y no velocidad ya calculada

- Un paquete ESP-NOW perdido no pierde la cuenta del sensor: `PC` permanece acumulado y `D` se
  incrementa en el Super Mini con `delta_pulsos × metros_por_pulso`.
- La velocidad se estima por el período entre pulsos; si no llegan pulsos recientes, se reporta cero.
- Para rechazar rebotes/ruido, el Super Mini ignora intervalos que impliquen superar el límite
  `speed.max_speed_kmh` de `config.json`; esos flancos no suman distancia. El primer flanco tras el
  arranque solo fija la referencia temporal y no se usa para calcular una velocidad.
- El perímetro de rueda vive en `config.json` del Super Mini y se puede ajustar desde REPL sin reflashear.

### 4.3 Salida (ESP-NOW hacia el T190)

Payload versión 3: `VER`, `Q` (secuencia 16-bit), `AV` (tensiones válidas/no clipeadas), `IV`
(corriente válida), `PC` (contador acumulado) y las lecturas/métricas
`I,B1..B4,VBATS,P,PA,V,D,WI,WA,WT`. B1–B4 son las tensiones individuales de los cuatro segmentos;
`VBATS` es la suma total del pack.
T190 rechaza paquetes incompletos, inválidos, repetidos o fuera de orden y marca la muestra como
vencida después de 5 s.

El Super Mini aplica cuatro factores gruesos independientes después de convertir los taps
acumulativos del ADS1115 a B1–B4. Los factores y los parámetros de velocidad se persisten en
`config.json`; la corriente no se escala con estos ajustes.

Status LED (NeoPixel) con color según salud de sensores (verde=OK, amarillo=falta algo, rojo=ninguno
responde, azul=arrancando) — esto no cambia.

### 4.4 Validez y recuperación de sensores

- Una lectura ADS1220 fallida invalida inmediatamente `IV` y pone la corriente reportada a cero; no se
  vuelve a calcular potencia/Wh/km instantáneo con la última corriente conocida.
- El Super Mini reintenta la inicialización del ADS1220 cada 5 s. Si el ADC arrancó tarde y nunca se
  calibró, queda inválido hasta ejecutar `main.calibrate_current_zero()` desde el REPL con corriente
  cero (vehículo/batería en reposo).
- `AV=0` ante error del ADS1115 o si algún canal está cerca de saturación. Los campos retenidos se
  identifican como inválidos y el T190/Paddock los muestran con su estado.
- Distancia acumulada por pulsos, no integrando una velocidad que cae a cero al superar 2 s entre
  pulsos; así no se pierden metros a baja velocidad.

### 4.5 Pendiente

- Alimentación propia (batería aislada del banco de tracción), igual que el T190.

---

## 5. Nodo 2 — T190 (unidad de cómputo / gateway principal / piloto)

Carpeta: `New T190/`. El T190 es el **display de cabina y gateway**. Consume las métricas ya calculadas
por el Super Mini, valida su secuencia/frescura/flags y reenvía el último estado al paddock.

### 5.1 Cómputo y estado del origen

El firmware activo **no recalcula** las métricas de tracción en el T190; los cálculos continúan en el
Super Mini. El T190 aplica la calibración fina individual B1–B4, suma las tensiones corregidas y
ajusta potencia/energía por la relación de tensión total. Esta decisión conserva una sola fuente
de verdad para los integradores.

El T190 valida cada frame completo `VER=3`, comprueba la secuencia `Q` con wrap de 16 bits, y solo
refresca el reloj de origen cuando acepta una muestra nueva. Paquetes duplicados, fuera de orden,
incompletos o no numéricos no refrescan el estado ni la indicación de enlace.

### 5.2 Display (✅ implementado, no cambia)

Display TFT 170×320 (ST7789) integrado: un valor a la vez, fuente de 7 segmentos, fila de estado de
enlace ESP-NOW arriba y estado de LoRa/índice abajo. Botón S3 (`HW.PAGE_BTN_PIN`, GPIO21) cicla al
siguiente campo. Muestra B1–B4 como tensiones individuales y `VBATS` como tension total del pack.

### 5.3 GPS — tiempo de vuelta y waypoint de largada (⏳ pendiente de integrar)

- Hardware: módulo GPS NMEA (Adafruit Ultimate GPS / MTK3339) por UART1, `GPIO1 = RX` (TX del GPS),
  `GPIO2 = TX` (RX del GPS), 9600 baud. Validado en banco con `New T190/test_gps.py` (lee y decodifica
  `$GPGGA`/`$GPRMC`).
- **Captura de waypoint de largada:** al presionar el botón de "Start" (o una acción dedicada), guardar
  lat/lon del fix GPS actual como referencia de la línea de largada/meta.
- **Cálculo de tiempo de vuelta:** detectar el cruce del vehículo por esa referencia (línea virtual
  entre el waypoint guardado y el rumbo/posición sucesiva, o un radio de tolerancia alrededor del
  punto) y medir el tiempo transcurrido entre cruces consecutivos.
- Nota de diseño del documento de La Salle Florida (`Instrumentacion_Telemetria_EcoYPF2026.pdf`, §6):
  *"El GPS no reemplaza a los pulsos como velocidad principal: es referencia y herramienta de
  análisis."* — en esta arquitectura el GPS se usa específicamente para vuelta/largada, no para
  velocidad instantánea (esa la sigue dando el conteo de pulsos del Super Mini, ya calculada en el T190).
- Antena con vista al cielo, no debajo de metal/fibra de carbono.

### 5.4 Gateway LoRa hacia el paddock (TX implementado)

- Módulo LoRa onboard HT-RA62 (SX1262), inicializado con el perfil
  `tradeoff` (915 MHz, BW 125 kHz, SF9, CR 4/6, 17 dBm).
- Intenta transmitir cada ~2000 ms el último frame versión 3, agregando `AGE` (edad de origen). Cuando
  el origen supera 5 s, marca `AV=0;IV=0`; conserva la secuencia y métricas para que el receptor pueda
  distinguir un valor congelado de uno actualizado.
- `lora_ok` significa **TX local completado** (código SX1262 cero), no recepción confirmada en Paddock.
  El protocolo no tiene ACK remoto.
- LoRa TX es bloqueante en el event loop asyncio; los tiempos de aire deben medirse en el hardware. Si
  se ve retraso de UI/ESP-NOW, migrar a TX no bloqueante.

### 5.5 Alimentación independiente (⏳ pendiente)

- El T190 necesita batería propia, aislada del banco de tracción, para cumplir el espíritu del art.
  11.5 (voltímetro/amperímetro/velocímetro con alimentación propia ≤ 6 pilas AA — a confirmar si aplica
  igual al conjunto T190+LoRa+GPS).
- Hoy no está dimensionada ni implementada; el T190 corre con la alimentación de banco/USB del
  prototipo.

### 5.6 Deep sleep / wake por botón (⏳ pendiente)

- `HW.py` ya reserva `MAIN_WAKE_PIN = 21` (mismo pin físico que el botón de usuario S3,
  `PAGE_BTN_PIN`) para esta función, pero **no hay código de deep sleep todavía** en `main.py`.
- A definir: qué dispara el sleep (timeout de inactividad, falta de telemetría del Super Mini, o una
  pulsación larga del mismo botón S3) y si la pulsación corta sigue sirviendo para ciclar pantallas una
  vez despierto, sin disparar sleep por accidente.
- Objetivo: estirar la autonomía de la batería propia del T190 entre sesiones (boxes, espera en grilla)
  sin depender de desconectar/reconectar manualmente.

---

## 6. Nodo 3 — Paddock S3 (firmware implementado, pendiente de prueba física)

- Hardware: Seeed XIAO ESP32-S3 con módulo Wio-SX1262, usando el pinout de
  `uPy reference Martin/FC Upy/XiaoS3Lora/HW.py`.
- Función: recibir el payload LoRa del T190 (ya con las métricas calculadas) y levantar un **AP Wi-Fi**
  propio con una **mini web** de telemetría en vivo (velocidad, tensiones, corriente, potencia, Wh/km,
  y — una vez integrado — vuelta actual y tiempo de vuelta), para que el equipo técnico la vea desde el
  celular o la notebook en boxes, sin ningún cable hacia el auto (cumple art. 9.4).
- El firmware está en `Paddock S3/`; ejecuta recepción LoRa y servidor HTTP con `uasyncio` en un hilo
  `_thread`, dejando libre el REPL. Levanta el AP `Paddock-LSF` en `192.168.4.1`; el dashboard se abre
  en `http://192.168.4.1/`, protegido por WPA2 (contraseña local configurada en `HW.py`).
- La página distingue antigüedad del paquete LoRa de `AGE` (edad de la muestra original) y reporta
  `AV`/`IV`, evitando presentar como vigente una telemetría congelada.
- T190 y Paddock usan el perfil LoRa `tradeoff` (915 MHz, BW 125 kHz, SF9,
  CR 4/6, 17 dBm, sync word 0x12, preámbulo 12) como punto de partida para
  el objetivo de 1 km en línea de vista. El alcance depende de antenas, altura,
  obstáculos e interferencias y debe validarse en campo. Se evita el perfil
  `long_distance` SF12/BW31.25 por su tiempo de aire para estos paquetes.

---

## 7. Protocolo de datos

### 7.1 ESP-NOW (Super Mini → T190)

Frame compacto versión 3, prefijado por `TLM:` en ESP-NOW:

```
VER=3;BOOT=<id>;Q=<1..65535>;AV=<0|1>;IV=<0|1>;PC=<pulsos>;
I=<A>;B1=<V>;B2=<V>;B3=<V>;B4=<V>;VBATS=<V>;
P=<W>;PA=<W>;V=<km/h>;D=<m>;WI=<Wh/km>;WA=<Wh/km>;WT=<Wh>
```

- `BOOT` identifica la sesión de arranque; `Q` incrementa por snapshot transmitido y vuelve a 1
  después de 65535. Un nuevo `BOOT` permite aceptar `Q` reiniciado tras reiniciar el Super Mini.
- `AV=1` solo si ADS1115 respondió y no hubo canal con riesgo de saturación; `IV=1` solo si ADS1220
  está inicializado y la lectura actual es válida.
- `PC` es el contador acumulado de pulsos. `D` se integra en el Super Mini mediante el delta de pulsos.
- Los consumidores aplican el paquete de forma atómica y no refrescan la frescura con secuencias
  repetidas o antiguas.

La configuración usa mensajes ESP-NOW unicast independientes del frame de telemetría:

```
CFG:V=1;ID=<revision>;MP=<metros/pulso>;DB=<us>;MAX=<km/h>;F1=<milli>;F2=<milli>;F3=<milli>;F4=<milli>
CFGA:<revision>   # el Super Mini persistió y recargó la configuración
CFGN:<revision>   # configuración inválida o no aplicada
```

El T190 reintenta la misma revisión hasta recibir `CFGA`. Los valores de tensión F1–F4 son
factores gruesos del Super Mini; los factores finos y capacidad útil se persisten localmente en el
T190. La página acepta recorrido en cm por pulso (10 cm/pulso inicial provisional), lo convierte
a metros por pulso y transmite el valor interno.

### 7.2 LoRa (T190 → paddock)

El T190 retransmite el mismo snapshot y agrega `AGE`, edad en milisegundos desde que recibió el último
frame ESP-NOW aceptado:

```
VER=3;BOOT=<id>;Q=<n>;AGE=<ms>;AV=<0|1>;IV=<0|1>;PC=<pulsos>;
I=<A>;B1=<V>;B2=<V>;B3=<V>;B4=<V>;VBATS=<V>;
P=<W>;PA=<W>;V=<km/h>;D=<m>;WI=<Wh/km>;WA=<Wh/km>;WT=<Wh>
```

El T190 sigue transmitiendo el estado con `AV=0;IV=0` si `AGE` supera 5000 ms. Paddock presenta
separadamente la edad de paquete LoRa y la edad de muestra fuente. GPS/vueltas siguen siendo una
extensión futura con campos versionados adicionales.

---

## 8. Estado actual de la implementación vs. objetivo

| Dato / función | Dónde vive hoy (código) | Dónde debería vivir (definitivo) | Estado |
|---|---|---|---|
| Tensión de 4 baterías (ADS1115) | Super Mini | Super Mini | ✅ Real, sin cambios |
| Corriente de batería (ADS1220 + toroidal) | Super Mini | Super Mini | ✅ Real, sin cambios |
| Contador de pulsos (crudo) | Super Mini | Super Mini | ✅ Real, sin cambios |
| Potencia inst./promedio, Wh, Wh/km | Super Mini | Super Mini | ✅ Calculado en la fuente junto a los sensores |
| Velocidad y distancia (desde pulsos) | Super Mini | Super Mini | ✅ Distancia por delta de pulsos; velocidad por período |
| ESP-NOW Super Mini → T190 | Super Mini, versión 3 | T190 valida V3, secuencia y flags | ✅ Integrado; actualizar los tres firmwares juntos |
| Configuración T190 → Super Mini por ESP-NOW | T190 AP, guardado en `t190_settings.json` y `config.json` | Factores gruesos B1–B4 y parámetros de velocidad en Super Mini | ✅ Código integrado; falta confirmar el ciclo físico en ambas placas |
| Ajuste fino B1–B4 y capacidad útil | AP/persistencia local del T190 | T190 | ✅ Implementado; confirmar tensiones/capacidad real en banco |
| Display local T190 (7-segmentos) | T190 | T190 | ✅ Implementado |
| Reenvío LoRa T190 → paddock | T190, retransmite cada 2 s + edad de origen | Mismo snapshot más GPS cuando exista | ⚠️ TX local implementado, recepción sin ACK |
| GPS en T190 (lectura NMEA) | T190 (standalone) | T190 (integrado) | ✅ Validado en banco (`test_gps.py`), falta integrar a `main.py` |
| GPS — cálculo de tiempo de vuelta | — | T190 | ⏳ Por implementar |
| GPS — captura de waypoint de largada | — | T190 | ⏳ Por implementar |
| Payload LoRa con datos de vuelta/GPS | — | T190 → paddock | ⏳ Por implementar |
| Alimentación independiente (Super Mini y T190) | — | Ambos nodos | ⏳ Pendiente de dimensionar |
| Deep sleep / wake por botón (T190) | — | T190 | ⏳ Pin reservado (`HW.MAIN_WAKE_PIN=21`), falta lógica |
| Nodo paddock (recepción LoRa + AP WPA2 + web) | `Paddock S3/` | Paddock | ⚠️ Código implementado, falta prueba física |
| Declaración del sistema LoRa ante comisarios | — | — | ⏳ Pendiente, art. 13.2 |
| Consulta al organizador sobre GPS/IMU en art. 11.5 | — | — | ⏳ Pendiente, `concursodesafioeco@ypf.com` |

---

## 9. Próximos pasos

1. Actualizar Super Mini, T190 y Paddock como conjunto compatible con protocolo V3; validar flags,
   pérdida/duplicación de paquetes y antigüedad visible al cortar ESP-NOW.
2. Probar el cálculo de distancia por pulsos a muy baja velocidad y calibrar cm por pulso en pista.
3. Probar desconexión y reinicialización ADS1220; calibrar cero solo con corriente nula usando
   `main.calibrate_current_zero()` si el ADC arrancó tarde.
4. Probar en banco T190 ↔ Paddock: recepción LoRa, AP WPA2 y actualización del dashboard.
5. Integrar el GPS al `main.py` del T190 como tarea `asyncio` (hoy solo existe como test standalone).
6. Definir la lógica de waypoint de largada y detección de cruce para tiempo de vuelta; extender el
   protocolo versionado con los datos GPS/vuelta.
7. Medir cuánto bloquea el TX LoRa del T190 y cambiarlo a no bloqueante si retrasa display/ESP-NOW.
8. Dimensionar/cablear alimentación independiente y enviar consultas al organizador sobre GPS/IMU y
   límites de alimentación del art. 11.5.
9. Declarar el sistema LoRa ante los comisarios técnicos en la verificación previa
   (art. 13.2).
