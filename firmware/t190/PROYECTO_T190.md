# eBike2026 — Heltec Vision Master T190 — v2 (sin Phaserunner)

## Estado actual del firmware T190

`main.py` corre en un hilo para mantener el REPL libre. Al iniciar habilita
`Ve_3V3` por GPIO5, arranca el GPS por UART1 en GPIO1/GPIO2, lee la bateria
interna y retransmite por LoRa los datos recibidos del Super Mini por ESP-NOW.
La bateria mostrada es la del T190, no la del banco de traccion. El porcentaje
es una estimacion por tension de una celda Li-ion 1S; hay que calibrarlo
contra un multimetro y no es preciso bajo carga. `HW.read_system_battery_v()`
activa el divisor por GPIO46, espera su estabilizacion, descarta muestras
iniciales y usa la mediana de nueve lecturas ADC. Con la bateria conectada,
la prueba serial del firmware actualizado dio 3.856–3.866 V (rango de 9.8 mV);
esto confirma estabilidad, no calibracion absoluta.

### Pinout verificado contra el esquema HT-VMT190

| GPIO | Funcion de la placa |
|---|---|
| 0 | Boton BOOT/BTN0 y LED2 naranja activo-bajo, compartidos |
| 1, 2 | QuickLink QL_SCL/QL_SDA; UART GPS RX/TX en este firmware (no I2C simultaneo) |
| 3 | Header J3; sin asignacion en el firmware |
| 4 | Header J3; CS independiente de microSD |
| 5 | `Ve_Ctrl`: habilita la salida `Ve_3V3` del QuickLink |
| 6 | `VBAT_Read`: entrada ADC del divisor de bateria interno |
| 7 | `VTFT_Ctrl`: alimentacion del TFT, activa en bajo |
| 8–14 | LoRa SX1262 onboard; GPIO8 NSS/CS, 9–11 SPI, 12 reset, 13 busy, 14 DIO1 |
| 15, 16 | Header J2; SCL/SDA del OLED I2C; funciones alternativas XTAL_32K_P/N |
| 17 | `LEDK_EN`: habilitacion del backlight TFT |
| 18 | `TP_INT`, interfaz/test pad no usada por la UI actual |
| 19, 20 | USB nativo D-/D+ |
| 21 | Boton S3 / `USER_KEY` |
| 38, 39, 40, 47, 48 | TFT: SCK, CS, RST, DC, MOSI |
| 41, 42, 45 | `TP_RST`, `TP_SCL`, `TP_SDA`, nets de test pad |
| 43, 44 | UART0 TX/RX, consola REPL |
| 46 | `ADC_Ctrl`: conmuta el divisor de `VBAT_Read` por Q3 |

GPIO15/16 aparecen en J2 y el esquema los identifica como señales 32K_XP/XN
hacia el ESP32-S3. Son funciones alternativas para un cristal externo
opcional de 32.768 kHz; no son el cristal principal de 40 MHz. El ESP32-S3
tambien dispone de un oscilador RC lento interno, por lo que para esta
asignacion se usan GPIO15/16 como I2C y no se instala ni habilita el cristal
externo de 32 kHz. La captura del punto de largada se hace con una pulsacion
larga de S3: mantenerlo al menos 1,2 s, pero menos de 2,2 s, y soltarlo. Ver el
[esquema HT-VMT190 de Heltec](https://resource.heltec.cn/download/HT-VMT190/HT-VMT90%20Schematic%20Diagram.pdf).
El Adafruit Ultimate GPS v3 entrega fecha y hora UTC por RMC; con una muestra
válida, `main.py` ajusta el RTC del T190 a hora argentina ART (UTC−3).

## 0.b Fix del driver de display (display se veia corrupto)

El panel del T190 es un **ST7789 real**, NO un GC9107 como asumia la version
anterior de `drivers/tft170.py`. Se verifico contra el driver oficial de
Heltec para Arduino (Adafruit ST7789 renombrado "HT_ST7789"):
https://github.com/HelTecAutomation/Heltec_ESP32/blob/master/src/HT_st7789spi.cpp

Dos bugs confirmados que causaban el display corrupto (bandas horizontales +
texto espejado/invertido):

1. **Offset en el eje equivocado.** El driver viejo usaba `x_offset=0,
   y_offset=35` para portrait. El real (calculado por Heltec para
   `init(170,320)`) es `_colstart=35` (eje X), `_rowstart=0` (eje Y) — es
   decir **`x_offset=35, y_offset=0`**. El panel de 170px esta centrado en
   el GRAM nativo de 240px del controlador en el eje X, no en el Y (el
   alto 320 coincide exacto con el GRAM nativo).
2. **MADCTL y orden de color incorrectos.** El driver viejo usaba
   `MX|BGR` (0x48) para rotation 0. El valor real de Heltec es
   `MY|MX` **sin** el bit BGR = **0xC0**, con orden de color **RGB** (no
   BGR). Tabla completa (`setRotation()` de Heltec):

   | Rotation | MADCTL | offset X | offset Y |
   |---|---|---|---|
   | 0 — portrait | 0xC0 | 35 | 0 |
   | 1 — landscape | 0xA0 | 0 | 35 |
   | 2 — portrait invertido | 0x00 | 35 | 0 |
   | 3 — landscape invertido | 0x60 | 0 | 35 |

   Ademas, el driver viejo mandaba una tanda extra de registros de gamma/
   VCOM/power-control (`PORCTRL/GCTRL/VCOMS/LCMCTRL/VRHS/VDVS/PWCTRL1/
   gamma`) copiados de un datasheet generico de GC9107. El init real de
   Heltec **no manda ninguno de esos registros** — solo SWRESET, SLPOUT,
   COLMOD, MADCTL, INVON, NORON, DISPON. Esos registros extra, en un
   controlador real distinto, pueden dejarlo en un estado invalido
   (gamma/VCOM mal configurados) y producir corrupcion visual.

Se corrigieron `drivers/tft170.py` (usado por `main.py`) y las tablas
`ROTATIONS`/`color_order` de `font_demo.py`, `font_demo_40.py` y
`loralcd_test.py` (que usan el driver generico `st7789py.py`).
`madctl_test.py` ya tenia el offset correcto (35,0); si volves a correrlo
para confirmar en tu unidad fisica, la respuesta esperada es **OPT 3/3
"MY=1 MX=1" (0xC0)**.

## 0. Contexto del prototipo original

- **Se elimina el Phaserunner** (UART/Modbus RTU) como controlador de motor.
- El controlador BLDC y las rutas ADC/DAC de acelerador/freno son
  documentación del prototipo; no forman parte del `main.py` gateway actual.
- El firmware actual sí usa el LoRa HT-RA62/SX1262 en GPIO8-14 para
  retransmitir la telemetría recibida del Super Mini.

---

## 1. Pines disponibles y opción para microSD

El T190 ya no mide acelerador/freno ni controla el driver; el Super Mini es
responsable de las mediciones de tracción y velocidad. Se quitaron del mapa
activo de `HW.py` los pines ADC/DAC e interrupción de velocidad del prototipo.
GPIO3/4 están expuestos en J3; GPIO15/16 en J2. GPIO4 es CS de la microSD;
GPIO3 queda libre. GPIO15/16 se asignan a I2C para el OLED adicional. Los
GPIO1/2 están asignados al GPS mientras este está conectado.

La microSD en modo SPI comparte las líneas del SX1262:

| Señal microSD | Conexión |
|---|---|
| SCK | GPIO9, compartido con LoRa |
| MOSI / DI | GPIO10, compartido con LoRa |
| MISO / DO | GPIO11, compartido con LoRa |
| CS / SS | GPIO4 (GPIO3 queda libre) |
| Alimentación | 3V3 regulados y GND |

El firmware comparte una única instancia de `SPI(2)` entre SX1262 y
microSD; LoRa conserva CS GPIO8 y la SD usa CS GPIO4. Las operaciones de
ambos drivers son sincronas dentro del mismo loop asyncio, por lo que no se
intercalan a mitad de una transaccion. No usar GPIO43/44 (REPL/UART0),
GPIO1/2 (GPS), ni los test pads GPIO18/41/42/45 como si fueran pines de
expansion confirmados.
Alimentar la tarjeta a 3.3 V y verificar el consumo disponible de la línea
antes de conectarla; no aplicar 5 V a las señales del ESP32-S3.

Asignación de pines para los periféricos:

| Periférico | Señal | GPIO / conexión |
|---|---|---|
| GPS UART1 | RX del T190 | GPIO1, conectar a TX del GPS |
| GPS UART1 | TX del T190 | GPIO2, conectar a RX del GPS |
| microSD SPI | SCK | GPIO9, compartido con LoRa |
| microSD SPI | MOSI / DI | GPIO10, compartido con LoRa |
| microSD SPI | MISO / DO | GPIO11, compartido con LoRa |
| microSD SPI | CS / SS | GPIO4, junto al pin LoRa CS GPIO8 pero eléctricamente independiente |
| OLED I2C | SCL | GPIO15 (32K_P alternativo) |
| OLED I2C | SDA | GPIO16 (32K_N alternativo) |
| — | GPIO libre | GPIO3 |

GPIO15/16 se pueden usar como GPIO si no se conecta/habilita un cristal
externo de 32.768 kHz en esos pines. La placa conserva el reloj principal;
el ESP32-S3 puede usar su oscilador RC interno como reloj lento. Conectar
pull-ups I2C a 3.3 V (muchos modulos OLED ya los incluyen) y verificar que
no se dupliquen en exceso.

Durante la inicializacion SD usa el mismo objeto SPI y deja CS LoRa inactivo;
la tarjeta se configura a 2 MHz, igual que SX1262. No se crea un segundo
controlador SPI sobre GPIO9/10/11.

Para probar la tarjeta de forma independiente, detener primero la app desde
el REPL (`stop(wait_ms=5000)`), copiar el driver con
`mpremote fs cp sdcard.py :sdcard.py` y ejecutar `mpremote run test_sd.py`.
La prueba no formatea ni sobrescribe:
monta el volumen FAT existente, muestra capacidad y deja un archivo
`SDTESTxx.TXT` con 1024 bytes verificados. El driver usa `VfsFat`; si una
tarjeta de 32 GB está en exFAT, MicroPython no podrá montarla. En ese caso
respaldar los datos y formatearla como FAT32 desde un PC antes de repetir.

El prototipo de motor queda retirado del firmware operativo. Los archivos
`motor_control.py` y `motor_test.py` se conservan solo como referencia; son
legado y no deben ejecutarse con el mapa actual de `HW.py`.

---

## 2. Módulos nuevos

| Archivo | Rol |
|---|---|
| `HW.py` | Mapa de pines de placa, ADC de bateria local, display y VEXT |
| `battery.py` | Conversion de tension de la bateria 1S a porcentaje estimado |
| `gps.py` | Recepcion NMEA no bloqueante por UART; extrae hora/fecha UTC y calcula ART |
| `sdcard.py` | Driver SPI de microSD (micropython-lib), usa el bus compartido con LoRa |
| `sd_logger.py` | Montaje SD y logging CSV append-only con CRC por fila, timestamp ART y nombre fechado |
| `test_sd.py` | Prueba de deteccion, montaje FAT y escritura/lectura de microSD; no formatea |
| `drivers/ads1115.py` | Driver mínimo ADS1115 (single-shot, 4 canales single-ended) |
| `drivers/ads1220.py` | Driver ADS1220 (24 bit, SPI) — sensor de corriente Hall toroidal, porteado del C++ de [ECO-YPF-2025-LSF](https://github.com/Electronica-LSF/ECO-YPF-2025-LSF) |
| `buttons.py` | `InterruptPageButton` para S3/BTN0 y `PageButton` compatible — portado de `inDev/buttons.py` (Martin) |
| `seven_seg.py` | Renderizador de texto con fuentes `font_to_py` sobre `drivers/tft170.TFT170` |
| `telemetry.py` | `TelemetryRuntime` — valida ESP-NOW y reenvia los datos por LoRa |
| `espnow_link.py` | `EspNowLink` — pairing y recepcion ESP-NOW desde el Super Mini — ver §4.b |
| `settings.py` | Ajustes persistentes de calibración fina B1–B4, pack, sleep y configuración Super Mini |
| `config_server.py` | AP Wi-Fi bajo demanda y página móvil de configuración T190/Super Mini |
| `wifiConnect.py` | Conexion temporal como cliente Wi-Fi con IP estática para pruebas desde la LAN (`import w`) |
| `main.py` | App de telemetría: display 7-seg + botones + hilo de fondo (REPL libre) — ver §4 |

## 3. Módulos reutilizados sin cambios

| Archivo | Origen |
|---|---|
| `drivers/tft170.py` | `uPy reference Martin/T190/drivers/` (faltaba en `T190 original/`) — **init/MADCTL/offset corregidos, ver §0.b** |
| `st7789py.py` | `T190 original/` sin cambios |
| `madctl_test.py` | `T190 original/` — `color_order` corregido a RGB, ver §0.b |
| `sx1262.py`, `sx126x.py`, `_sx126x.py` | `T190 original/` (driver LoRa onboard) |
| `loralcd_test.py` | `T190 original/` — `ROTATIONS`/`color_order` corregidos, ver §0.b |
| `fonts/seven_segment_24.py`, `fonts/seven_segment_40.py` | `T190 original/` |
| `fonts/seven_segment_80.py` | `uPy reference Martin/.../eBike Old/1.69 LCD/micropython-font-to-py/` — usada por `main.py` en landscape |
| `font_demo.py`, `font_demo_40.py` | `T190 original/` — import actualizado a `from fonts import ...`, `ROTATIONS`/`color_order` corregidos (§0.b) |
| `boot.py`, `startup_cleanup.py`, `startup_fallback.py` | `T190 original/` — entorno de testing |
| `r.py`, `d.py`, `w.py`, `p.py` | `T190 original/` — toggles de testing (reset, disable-main, wifi, restore-main) |
| `wifi_config.py`, `ipaddress.cfg` | `T190 original/` |

## 4. Telemetría (`main.py` actual)

`main.py` ya NO es el demo de 5 pantallas de color — ahora es la app de
telemetría eBike2026. Arquitectura "REPL libre" portada de
`uPy reference Martin/FC Upy/eBike Old/inDev/t.py`: la app (display, GPS,
lectura de bateria, botones y LoRa) corre dentro de un `_thread` separado
lanzado por `start()`; `main.py` solo arranca ese hilo al bootear
(`AUTO_START = True`) y retorna de inmediato, dejando la consola REPL
disponible para `import main; main.status()` / `main.stop()` / `main.start()`.

### Qué es real y qué es demo/fake

| Dato | Fuente | Modulo |
|---|---|---|
| Telemetria de traccion (B1..B4 individuales, VBATS total, I, potencia, Wh, velocidad, distancia) | Recibida por ESP-NOW desde el Super Mini | `espnow_link.py` y `telemetry.py` |
| Bateria interna del T190 | ADC GPIO6, divisor R9/R11 y control GPIO46; actualizacion cada 10 s | `HW.read_system_battery_v()` / `battery.py` |
| Porcentaje de bateria | Estimacion de una celda Li-ion 1S por tension | `battery.py: percent_from_voltage` |
| GPS | NMEA por UART1 a 9600 baud; VEXT GPIO5 se activa al inicio | `gps.py` / `main.py` |

El parser GPS descarta la frase NMEA que contenga bytes UART no imprimibles
y cuenta esos bytes en `main.gps_status()`; una frase corrupta ya no debe
detener la tarea asincrona de lectura. Cuando recibe un RMC válido, toma la
fecha/hora UTC, la convierte a ART (UTC−3) y sincroniza el RTC del T190; la
resincronización se hace como máximo una vez por minuto.

### Registro de rendimiento en microSD

La SD se monta en `/sd` al arrancar y comparte la instancia SPI2 con SX1262.
Por defecto el registro automatico inicia cuando llega telemetria fresca con
velocidad >= 0.5 km/h; BTN0 mantenido >= 1.2 s fuerza inicio o detencion
manual. Se escribe una fila por segundo con tiempo monotono relativo,
secuencia/boot, timestamp ART, validez de ADC y corriente, tension de bancos, corriente,
potencia, velocidad, distancia, Wh/km, Wh acumulados, pulsos y GPS cuando
hay fix. Cada fila termina con CRC16; después de sincronizar el RTC, los
archivos quedan como `RIDE_YYYYMMDD_HHMMSS.CSV` y las filas incluyen
`timestamp_art`. Si aún no hay hora GPS, se conserva el nombre secuencial
`RIDE####.CSV` y el timestamp queda vacío hasta obtener sincronización.
`SD:REC`, `SD:ARM` o `SD:ERR` aparecen en el header.
Las columnas `v_b1_v`..`v_b4_v` son tensiones individuales; `vbats_v` es
la suma total del pack.

Cada fila se hace flush; cada cinco segundos el archivo se cierra y vuelve a
abrirse en append para persistir el tamano/metadata FAT con una ventana
pequena de datos vulnerables. Al detener la app o entrar en deep sleep se
escribe un marcador `END`, se cierra el archivo y se desmonta la SD. Esto
reduce el riesgo, pero no puede garantizar FAT intacto ante corte fisico
durante una actualizacion de metadata; si pasa, ignorar una ultima fila sin
CRC valido y reparar FAT desde un PC. Para pruebas se puede usar BTN0 largo;
desde REPL: `main.log_start()`, `main.log_stop()`, `main.log_auto()` y
`main.log_status()`.

### Hardware legado de motor y sensor de corriente

- `motor_control.py` y `motor_test.py` pertenecen al prototipo retirado y no
  se inicializan en el gateway actual.
- El T190 recibe las mediciones de traccion desde el Super Mini; no conectar
  un ADS1220 reutilizando los GPIO del LoRa.
- Los datos de velocidad que muestra el gateway llegan por ESP-NOW desde el
  Super Mini; el T190 no cuenta pulsos de velocidad localmente.
- El Super Mini descarta flancos que impliquen superar `speed.max_speed_kmh`
  (80 km/h por defecto en `SUPER MINI S3/config.json`) y no los cuenta para
  distancia. Si la lectura alta persiste, comprobar `main.diag()` en el
  Super Mini: el contador `rechazados` identifica pulsos rápidos rechazados;
  revisar también cableado/ruido del GPIO10 y calibrar centímetros por pulso
  desde la página de configuración. El valor inicial de 10 cm/pulso es
  provisional, no una medición.

### UI y botones

Las acciones manuales de ahorro de energia/deep sleep corresponden a
**S3/GPIO21**, no a BTN0. El gesto `extra` de S3 solicita el deep sleep
manual; ademas existe el timeout automatico por velocidad cero descrito
abajo. El detector registra el gesto al soltar el boton, primero cierra las
tareas/registro y perifericos, y luego entra en deep sleep. S3 tambien es la
fuente de wake configurada.

| Boton y gesto | Accion |
|---|---|
| BTN0/GPIO0 corto (hasta 420 ms) | Pantalla siguiente |
| BTN0 doble (dos cortos, segundo dentro de 320 ms) | Volver a `VELOCIDAD`; si el AP esta activo, cancelar sin guardar |
| BTN0 largo (desde 1,2 s y menos de 2,2 s) | Alternar log SD; en `CONFIGURACION`, iniciar/detener el AP |
| BTN0 extra (desde 2,2 s) | Sin accion asignada |
| S3/GPIO21 corto (hasta 420 ms) | Pantalla anterior; con AP activo, cancelar y volver a `VELOCIDAD` |
| S3 doble | Sin acción efectiva: el reset al Super Mini aún no está implementado |
| S3 largo (desde 1,2 s y menos de 2,2 s) | Capturar waypoint GPS en RAM |
| **S3 extra largo (desde 2,2 s)** | **Solicitar deep sleep manual al soltar el boton** |

- Display en **landscape** (`rotation=1`, 320x170) con fuente 7 segmentos
  grande, blanco sobre negro. El texto secundario usa un tono claro de alto
  contraste. El header muestra ESP-NOW, estado GPS y
  bateria local; la fila inferior muestra el estado de origen y TX LoRa.
- La pantalla `DIAGNOSTICO` muestra validez de los sensores ADS
  recibida del Super Mini, montaje/estado y capacidad de SD, fix/satélites GPS,
  bytes UART inválidos, hora ART y lectura/ADC crudo de la batería interna del
  T190. Después están `AYUDA BOTONES` y `CONFIGURACION`; la primera resume
  BTN0/GPIO0 y B21/S3, el modo AP y deep sleep. La configuración sigue siendo
  la última pantalla para conservar el acceso conocido con S3 corto desde
  `VELOCIDAD`.
- BTN0/GPIO0 corto avanza pantalla; doble click vuelve a `VELOCIDAD`.
  BTN0 largo inicia/detiene el log SD en modo manual (en automatico el
  registro empieza al detectar movimiento). En la pantalla
  `CONFIGURACION`, mantener BTN0 desde 1,2 segundos y soltarlo antes de
  llegar a 2,2 segundos inicia el AP `Main-T190`; repetir el gesto lo apaga.
  Para llegar allí desde la pantalla inicial `VELOCIDAD`, dar una pulsación
  corta a S3: la navegación retrocede y envuelve desde la primera pantalla
  hasta `CONFIGURACION`. El LCD muestra el SSID, la clave WPA2 y
  `http://192.168.4.1/`; conectar el teléfono a esa red y abrir esa dirección
  en el navegador. Guardar desde la página confirma los cambios y cierra el
  AP. S3 corto o BTN0 doble durante el AP lo cancela sin guardar y vuelve a
  `VELOCIDAD`.
- S3/GPIO21 corto retrocede (o cancela el AP como se indica arriba); doble
  click invoca el reset local, pero aun falta implementar el comando hacia
  el Super Mini. Pulsacion larga captura el waypoint GPS en RAM. Mantener S3
  **2,2 s o mas (extra largo)** y soltarlo solicita deep sleep manual. El
  timeout de deep sleep automático se ajusta desde la página (`0` lo desactiva).
  Antes de dormir se detienen las tareas, se cierra el CSV, se duerme LoRa y
  se apagan TFT/backlight y VEXT/GPS. S3/GPIO21 en nivel bajo es la
  fuente de wake. Ademas, si la telemetria ESP-NOW sigue fresca y reporta
  velocidad absoluta <= 0.1 km/h durante el tiempo configurado, el firmware
  solicita el mismo apagado; cualquier movimiento o perdida de telemetria
  reinicia el temporizador. El umbral permanece en `IDLE_SPEED_THRESHOLD_KMH`.
- Los gestos de `InterruptPageButton` se disparan al soltar: los flancos
  activos-bajo se capturan por IRQ y el debounce de 25 ms/gestos se procesa
  en `asyncio`, fuera de la interrupcion. Corto hasta 420 ms,
  doble click con el segundo click dentro de 320 ms, largo desde 1,2 s y
  extra desde 2,2 s. Una pulsacion sostenida entre 420 ms y 1,2 s no hace
  nada; así no se confunde un hold intermedio con navegación o una acción.
  En el gesto S3 extra, el firmware solicita el sleep tras soltar la tecla,
  para que el pin quede libre y pueda usarse para despertar.
- Desde el REPL: `main.status()`, `main.config_status()`,
  `main.battery_status()` y `main.gps_status()` muestran los estados actuales;
  `main.deep_sleep()`
  solicita deep sleep inmediatamente, sin esperar el timeout.

### Configuración desde el teléfono

Para iniciar el AP: en la pantalla inicial `VELOCIDAD`, pulsar y soltar S3
una vez para ir a `CONFIGURACION`; allí mantener BTN0 al menos 1,2 segundos,
pero soltarlo antes de 2,2 segundos. El AP se habilita solo bajo demanda; no
queda encendido durante el uso normal. Conectar el teléfono al SSID
`Main-T190` usando la clave que muestra el LCD (`lasalle2026`, definida por
`AP_PASSWORD` en `config_server.py`) y abrir `http://192.168.4.1/` en el
navegador (escribir también `http://`; no usar `https://`). Si el teléfono
avisa que la red no tiene Internet, elegir permanecer conectado a `Main-T190`;
el AP solo sirve la página local. Para verificar el enlace HTTP se puede
abrir `http://192.168.4.1/health`, que debe responder `T190 HTTP OK`.
Pulsar **Guardar** en la página es la confirmación y guarda los
cambios. Para salir sin guardar, pulsar S3 una vez o hacer doble click en
BTN0; ambos cierran el AP y regresan a `VELOCIDAD`. También se puede mantener
BTN0 entre 1,2 y menos de 2,2 segundos otra vez para apagar el AP sin guardar.
La página permite ajustar individualmente B1–B4: se puede editar el factor
fino del T190 (800–1200 milésimas) o ingresar la tensión real en mV, usando
una lectura ESP-NOW fresca para calcular la corrección de esa batería. La
corrección fina se aplica a la lectura recibida después del ajuste grueso del
Super Mini; si se cambian ambos en el mismo envío, el cálculo considera el
nuevo factor grueso para no aplicar dos veces la desviación. El T190 suma las
cuatro baterías corregidas y escala potencia/energía por la relación entre
VBATS corregido y recibido. Corriente, velocidad y distancia no se escalan.

El pack de cuatro baterías de 12 V y 17 Ah en serie tiene 48 V, 17 Ah y
**816 Wh nominales**. Ese es el valor inicial para una instalación nueva; el
campo de la página es la capacidad útil y se puede reducir según la química,
la edad y la descarga admisible. Una configuración antigua sin capacidad
definida o guardada como 0 se migra una sola vez a 816 Wh nominales. Marcar
el pack como cargado inicia el cálculo de energía restante.

La misma página configura el Super Mini: recorrido en cm por pulso, anti-rebote,
velocidad máxima válida y cuatro factores gruesos de tensión (B1–B4). El
Super Mini aplica esos factores después de restar los taps acumulativos del
ADS1115, y recalcula tensión total/potencia/Wh sin alterar la corriente. Los
ajustes se envían en tramas `CFG` por ESP-NOW, se guardan en `config.json`,
se aplican en caliente y vuelven con `CFGA` al T190. El T190 reintenta hasta
recibir confirmación. Desde el REPL, `main.config_status()` muestra el ID y
el estado confirmado/pendiente/rechazado. Los centímetros por pulso se
convierten internamente a metros por pulso; 10 cm/pulso es solo el valor
inicial provisional. Medirlo recorriendo una distancia conocida y dividiendo
los centímetros recorridos por los pulsos contados.

Para depurar la página desde una computadora de la misma LAN, primero iniciar
el AP desde `CONFIGURACION` para que `config_server` quede atendiendo en el
puerto 80. Desde el REPL USB ejecutar `import w`: `wifiConnect.py` apaga el AP
y asocia el T190 a la red configurada en `wifi_config.py`, conservando el
servidor HTTP en ejecución. La IP estática configurada es `192.168.0.25`;
desde una computadora de esa LAN abrir `http://192.168.0.25/` o
`http://192.168.0.25/health`. El modo STA es solo una prueba de diagnóstico:
puede cambiar el canal de la radio compartida con ESP-NOW y dejar de recibir
temporalmente al Super Mini. Reiniciar el T190 para volver al uso normal/AP.

Los ajustes quedan en `t190_settings.json`; se usa un archivo temporal y
respaldo durante la sustitución. La energía usada se deriva de incrementos
del contador `WT` del Super Mini, compensados por la corrección fina total;
el estado se guarda periódicamente y al detener el firmware. Una pérdida abrupta de
alimentación puede descartar el incremento desde el último checkpoint. La
estimación de porcentaje es orientativa, no sustituye una medición del pack.
La coexistencia del AP con ESP-NOW y LoRa debe validarse en la unidad física.

### Telemetría por LoRa

`telemetry.py: lora_task` reenvia por `SX1262.send()` cada 2 s el frame V3
recibido por ESP-NOW, agregando edad y flags de validez. B1..B4 son las
tensiones individuales y `VBATS` es la suma total del pack. SX1262 y
microSD comparten la misma instancia SPI2 con CS independientes; el display
usa SPI id=1 (ver `loralcd_test.py`).

## 4.b ESP-NOW de entrada desde el Super Mini

El T190 escucha el protocolo V3 enviado por el Super Mini. No transmite
telemetria ESP-NOW a un segundo display; su salida remota de telemetria es
LoRa hacia el Paddock.

### Funciones de REPL

- `main.espnow_status()` — estado del enlace y contador de recepciones.
- `main.espnow_repair()` — recuperacion del peer cuando corresponda al
  firmware ESP-NOW instalado.
- `main.log_status()` — estado SD, archivo actual, modo y error.
- `main.log_start()` / `main.log_stop()` — solicitan iniciar o detener el
  registro desde el REPL sin tocar el SPI en el hilo REPL.
- `main.log_auto()` — vuelve al inicio automatico al detectar movimiento.

### Riesgo conocido — sin verificar en hardware

El módulo `espnow` de MicroPython **no está garantizado en todos los
builds** (depende de `MICROPY_PY_ESPNOW` al compilar el firmware). Si al
arrancar aparece `ImportError: no module named 'espnow'`, significa que
el firmware actual del T190 no lo trae compilado — haría falta un build
custom o confirmar que el firmware oficial para ESP32-S3 lo incluye.

## 5. Validacion pendiente en hardware

1. Comparar la lectura local (`main.battery_status()`, que informa voltaje
   calculado, GPIO6, ADC crudo y método de conversión) con un multímetro tanto
   con USB como desconectado. La estabilidad de la muestra ya se verificó por
   serial; la exactitud y la caída percibida al desconectar USB siguen sin
   calibrar y no deben corregirse sin esos valores de referencia.
2. Probar deep sleep automatico con el firmware completo: confirmar que el
   timeout comienza solo con telemetria fresca y velocidad <= 0.1 km/h,
   que movimiento o perdida del enlace lo reinician, y que tras dormir
   despierta con S3/GPIO21. El wake temporizado ya se verifico en la placa;
   el wake fisico con S3 sigue pendiente.
3. Probar el GPS al aire libre, confirmar fix/satelites con
   `main.gps_status()` y capturar el waypoint con S3 largo (1,2 a <2,2 s).
4. Confirmar que `Ve_3V3` del QuickLink cae al detener `main.py` y vuelve a
   habilitarse al reiniciar el hilo.
5. Validar la recepcion ESP-NOW y el TX LoRa con las placas reales.
6. Probar la microSD con el firmware completo: comprobar el montaje FAT,
   que SX1262 siga transmitiendo durante escrituras CSV, que BTN0 largo
   alterne el registro manual y que el deep sleep cierre el archivo. Verificar
   el CSV en un PC y confirmar filas/CRC validos; la prueba SD previa fue
   independiente del LoRa.
7. Probar la pantalla CONFIGURACION desde BTN0, conectar un teléfono al AP,
   guardar/cancelar y confirmar que el AP se apaga. Calibrar VBATS contra un
   multímetro y verificar que la recepción ESP-NOW y la transmisión LoRa
   continúan durante el modo de configuración. Confirmar la capacidad útil
   real del pack antes de activar su estimación de energía restante.
8. Validar en el equipo que S3 mantenido >=2,2 s solicita deep sleep solo al
   soltarlo, y que una pulsación larga de S3 (1,2 a <2,2 s) captura waypoint
   sin dormir. Confirmar que S3 despierta el T190 desde deep sleep.

El porcentaje de bateria se estima desde tension instantanea; bajo carga o
mientras se carga puede diferir del estado de carga real. No se ha calibrado
la lectura del ADC ni el SOC en hardware.




creo la seccion de parametros quedo demasiada parametrizada para las tensiones, esta ajuste fino, valor en mv opcional, ajuste grueso. no seria mejor dejar B1 a b4 con la posibilidad de poner la tension real de cada una y ajustar los parametros del super mini en funcion y listo? deberia tener una togle si es una medion respecto a masa ie 12, 24.3, 35, 49v o medicione por celda, 12, 13, 12.5, 13.8v etc

crea un md con la documentacion q creas necesaria para contnuar el desarrollo en una IA local offline. tenemos el codigo local pero este md nuevo deberia ayudar a pulir lo que queda.


la ui deberia arrancar pantalla 1 con lo mas importante, velocidad o wh/km. luego el resto con una logica de agrupacion / uso
