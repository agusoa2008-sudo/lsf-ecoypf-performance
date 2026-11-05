# EcoYPF 2026 — T190 Gateway — Continuación de desarrollo

> Documento de contexto para sesiones de IA offline. El código fuente es la
> fuente de verdad; este MD recoge decisiones de diseño, cambios pendientes
> y restricciones que no son obvias leyendo el código solo.
> Para el historial detallado ver `PROYECTO_T190.md`.

---

## Arquitectura en una línea

**T190** (Heltec Vision Master, ESP32-S3 con LCD 170×320, LoRa SX1262, GPS)
recibe telemetría de tracción desde el **Super Mini** por ESP-NOW, la muestra
en el LCD con fuente 7-segmentos, la retransmite por LoRa y la graba en microSD.
El Super Mini mide las 4 baterías 12 V en serie con ADS1115, la corriente del
pack con ADS1220 y la velocidad por pulsos de rueda.

---

> Para la lista completa de funcionalidades implementadas (T190, Super Mini,
> Paddock) ver `../FUNCIONALIDADES.md`. Este documento cubre solo las
> decisiones de diseño y los cambios pendientes de implementar.

## Módulos del firmware T190

| Archivo | Rol |
|---|---|
| `main.py` | App principal en `_thread`; REPL libre. `start()`, `stop()`, `status()` |
| `HW.py` | Pinout, ADC batería interna, control TFT/VEXT |
| `battery.py` | Tensión → porcentaje SOC estimado (1S Li-ion) |
| `gps.py` | Parser NMEA no bloqueante; sincroniza RTC a ART (UTC−3) |
| `espnow_link.py` | Pairing y recepción ESP-NOW desde Super Mini; protocolo V3 |
| `telemetry.py` | Valida frames ESP-NOW; envía por LoRa cada 2 s |
| `sd_logger.py` | Logger CSV append-only en `/sd`; flush/close periódico; CRC por fila |
| `sdcard.py` | Driver SPI microSD (micropython-lib) |
| `buttons.py` | `InterruptPageButton`: corto/doble/largo/extra por IRQ + asyncio |
| `seven_seg.py` | Render de texto grande con fuentes `font_to_py` en `TFT170` |
| `settings.py` | Ajustes persistentes en `t190_settings.json` |
| `config_server.py` | AP Wi-Fi bajo demanda + página móvil de configuración |
| `drivers/tft170.py` | Driver ST7789 corregido (MADCTL 0xA0 landscape, offsets 0,35) |
| `sx1262.py` / `sx126x.py` | Driver LoRa SX1262 onboard |

---

## Restricciones de hardware inamovibles

| Señal | GPIO | Nota |
|---|---|---|
| GPS RX (T190 ← GPS TX) | 1 | UART1 |
| GPS TX (T190 → GPS RX) | 2 | UART1 |
| Ve_Ctrl (VEXT / GPS power) | 5 | Activo alto |
| VBAT_Read ADC | 6 | Divisor R9/R11 |
| ADC_Ctrl (enable divisor) | 46 | Activo alto |
| LoRa SX1262 CS | 8 | SPI2 compartido |
| SPI2 SCK / MOSI / MISO | 9 / 10 / 11 | Compartido con microSD |
| microSD CS | 4 | SPI2 compartido |
| OLED I2C SCL / SDA | 15 / 16 | Solo si no hay cristal 32 kHz |
| TFT SPI1 | 38/47/48/39/40 | SCK/MOSI/DC/CS/RST |
| Backlight enable | 17 | Activo alto |
| BTN0 / LED naranja | 0 | Activo bajo, compartidos |
| S3 / USER_KEY | 21 | Activo bajo |
| REPL UART0 | 43 / 44 | No reutilizar |

**SPI2 es una sola instancia** compartida entre SX1262 y microSD; no crear
un segundo objeto SPI sobre los mismos GPIO.

---

## Protocolo ESP-NOW V3 (resumen)

### Super Mini → T190 (telemetría)

Frame con campos: `B1..B4` (V, tensiones individuales), `VBATS` (V, total pack),
`I` (A), `W` (W), `Wh` (Wh acumulados), `speed` (km/h), `dist` (km),
`pulses` (contador), `ads_valid` (bool ADS1115), `cur_valid` (bool ADS1220).

### T190 → Super Mini (configuración, tipo `CFG`)

Campos: `cm_per_pulse`, `debounce_ms`, `max_speed_kmh`,
`b1_factor`..`b4_factor` (factores gruesos de tensión),
`ads_mode` (nuevo — ver §Calibración abajo).

### Super Mini → T190 (confirmación, tipo `CFGA`)

Eco del CFG recibido con flag `ok`. El T190 reintenta hasta recibir CFGA.

---

## Cambios de diseño pendientes (aprobados, aún no implementados)

### 1. Simplificación de calibración de baterías

**Problema**: el esquema actual tiene tres capas independientes (factor fino
T190 en milésimas, campo mV opcional, factor grueso Super Mini), lo que es
demasiado complejo para calibrar en campo.

**Diseño nuevo**:

Cada banco B1–B4 tiene **un único campo de referencia**: la tensión real
medida con multímetro en ese momento. El sistema calcula el factor de
corrección automáticamente:

```
factor_b_n = tension_multimetro_v / tension_recibida_v
```

El factor resultante reemplaza tanto el ajuste fino del T190 como el grueso
del Super Mini; se envía al Super Mini en el frame CFG y se aplica allí (más
cerca de la medición). El T190 solo aplica la corrección si no hay confirmación
CFGA pendiente.

**Toggle de modo ADS1115** (nuevo campo en CFG/`t190_settings.json`):

| Modo | Descripción | Ejemplo de lecturas raw |
|---|---|---|
| `cumulative` | Taps respecto a masa; el Super Mini resta para obtener individuales | 0 V, 12.1 V, 24.3 V, 35.0 V, 49.0 V |
| `individual` | Cada canal ADS mide directamente su batería con divisor propio | 12.1 V, 12.2 V, 10.7 V, 14.0 V |

En modo `cumulative` el Super Mini calcula: B1=tap1, B2=tap2−tap1,
B3=tap3−tap2, B4=tap4−tap3 antes de aplicar factores. En modo `individual`
no hay resta. El default existente es `cumulative`.

**Archivos a modificar**:

- `config_server.py`: reemplazar los tres controles por banco (factor fino,
  mV, factor grueso) con un único input "Tensión real (V)" por banco y un
  radio/toggle global `ads_mode` (cumulative / individual).
- `settings.py`: nueva estructura `t190_settings.json`:
  ```json
  {
    "pack_wh": 816,
    "sleep_timeout_s": 300,
    "ads_mode": "cumulative",
    "b1_ref_v": 0, "b2_ref_v": 0, "b3_ref_v": 0, "b4_ref_v": 0
  }
  ```
  `ref_v = 0` significa sin corrección (factor 1.0). Migrar automáticamente
  desde el formato anterior al primer arranque con archivo viejo.
- `telemetry.py`: calcular `factor_bn = ref_v / recv_v` (si `ref_v > 0`);
  aplicar a B1..B4 y recalcular VBATS, W, Wh en espera de CFGA.
- Protocolo CFG: añadir campo `ads_mode` ("C"=cumulative/"I"=individual) y
  reemplazar `b1_factor`..`b4_factor` por los factores calculados.
- Super Mini firmware: implementar toggle `ads_mode` en la función de lectura
  ADS1115; guardar en `config.json`.

**Nota de migración**: el campo actual `b_fine_*` (milésimas) puede
convertirse a `ref_v` como `ref_v = 0` (sin corrección) en la primera
carga del archivo viejo para no romper instalaciones existentes.

---

### 2. Rediseño de la UI — pantallas agrupadas

**Estado actual del código:** `FIELDS` en `main.py` es una lista de 13
campos individuales (un valor por pantalla), sin agrupación. Ver
`../FUNCIONALIDADES.md` para la tabla completa.

**Diseño nuevo:** pantallas con múltiples valores, agrupadas por relevancia.
Pantalla 1 = la más útil en marcha; `CONFIGURACION` queda última para que
S3 corto desde pantalla 1 siga siendo el acceso rápido.

| # | Nombre pantalla | Contenido |
|---|---|---|
| 1 | `RUTA` | Velocidad grande (km/h) + Wh/km promedio debajo |
| 2 | `CONSUMO` | Potencia inst. grande (W) + Corriente A debajo |
| 3 | `EFICIENCIA` | Wh/km promedio grande + Wh/km inst. debajo |
| 4 | `BATERIAS` | B1 / B2 / B3 / B4 (V) en 4 líneas + VBATS total |
| 5 | `ENERGIA` | Wh acumulados + % pack restante (si capacidad configurada) |
| 6 | `VIAJE` | Distancia (m) + Pot. promedio 5 s (W) |
| 7 | `GPS` | Fix, satélites, coords, waypoint capturado |
| 8 | `DIAGNOSTICO` | Validez ADS, SD, GPS raw, hora ART, batería interna T190 |
| 9 | `AYUDA BOTONES` | Resumen gestos BTN0 / S3 |
| 10 | `CONFIGURACION` | (última; acceso rápido: S3 corto desde pantalla 1) |

**Notas de implementación:**

- Reemplazar la lista plana `FIELDS` por una estructura de pantallas, cada
  una con sus campos y layout. Índice 0 = `RUTA` para que el doble-click
  de BTN0 (volver a inicio) funcione sin cambios en la lógica de botones.
- Pantallas de 2 líneas: valor principal en fuente 80 px; valor secundario
  en fuente 40 px.
- Pantalla `BATERIAS`: cuatro valores en fuente 40 px más la suma total.
- Si un valor no está disponible (sin telemetría, distancia = 0, etc.),
  mostrar `--` en ese campo.

### 3. Pantalla OLED 0.96" adicional (I2C) ⏸️ EN PAUSA — problema físico sin resolver

**Resumen 2026-10-22: se deja de lado por ahora.** GPS vuelve a su
configuración original (GPIO1/2, QuickLink). Ver "Diagnóstico" más abajo
antes de retomar, para no repetir pruebas ya descartadas.

**Concepto:** un módulo OLED SSD1306 128x64 de 0.96" conectado a GPIO15
(SCL) / GPIO16 (SDA) como pantalla extendida fija — muestra un dato siempre
visible (ej.: velocidad o Wh/km) independientemente de la pantalla activa
en el TFT. Puede orientarse hacia el piloto mientras el TFT apunta al
exterior.

**Restricciones:**
- GPIO15/16 solo disponibles si no se instala cristal de 32 kHz (no hay
  uno en la placa; el ESP32-S3 usa su RC interno).
- Pull-ups I2C a 3.3 V requeridos; no duplicar si el módulo ya los incluye.
- La dirección I2C del SSD1306 (0x3C ó 0x3D) no debe colisionar con otros
  dispositivos en el mismo bus.
- **Alimentación:** el módulo OLED está cableado al `Ve_3V3` del
  QuickLink (`HW.VEXT_CTRL_PIN=5`), el mismo rail conmutado que hoy usa
  el GPS — no un 3V3 constante. Hay que llamar `HW.vext_enable()` antes
  de hablarle por I2C (`oled_test.py`/`oled_seven_seg_test.py` ya lo
  hacen). Al integrar a `main.py`: cuidado si algo deshabilita VEXT
  (deep sleep, o un futuro apagado del GPS) mientras el OLED todavía
  necesita mostrar algo — van a tener que coordinar el mismo rail.

**Hecho:**
- `drivers/ssd1306.py`: driver I2C SSD1306 estándar de micropython-lib,
  copiado al proyecto. Incluye `blit()` (passthrough a
  `framebuf.FrameBuffer.blit`) para poder pegar glyphs de fuentes
  `font_to_py` directo, sin pasar por `text()`.
- `HW.py`: `OLED_I2C_ID/SCL_PIN/SDA_PIN/FREQ` (ya existían) + helper nuevo
  `HW.make_oled_i2c()`.
- `oled_test.py`: script de banco aislado (patrón `test_gps.py`) — hace
  scan I2C, inicializa el panel y muestra un contador con `text()`
  (fuente chica 8x8). Correr con `mpremote run oled_test.py` para validar
  cableado/dirección I2C antes de integrar.
- `seven_seg.py`: se agregaron `draw_text_mono()` /
  `draw_text_mono_centered()`. El glyph de `fonts/seven_segment_24/40/80`
  ya viene en formato `MONO_HLSB` (mismo que usa `framebuf` para mono) —
  se blitea directo sobre el OLED sin convertir a RGB565 como hace falta
  para el TFT. Permite mostrar un valor grande (ej. velocidad) legible a
  distancia, reusando las mismas fuentes que ya están probadas en el TFT
  (no se adoptó una librería de fuente gigante aparte que se había
  dejado en la raíz — se perdió del disco antes de poder validarla y de
  todas formas esta opción reusa código ya probado).
- `oled_seven_seg_test.py`: script de banco — línea superior con
  `seven_segment_40` (valor principal), línea inferior con
  `seven_segment_24` (unidad). Correr con
  `mpremote run oled_seven_seg_test.py`.

**Diagnóstico (banco de pruebas 2026-10-22) -- leer antes de retomar:**
- El scan I2C encuentra el OLED (`0x3C`) de forma consistente, pero
  cualquier escritura más allá de un `write_cmd` de 2 bytes puede tirar
  `OSError [Errno 116] ETIMEDOUT` -- a veces en el primer comando de
  `show()`, a veces en medio del framebuffer completo. Sin patrón fijo.
- El bus llegó a quedar trabado del todo (scan devolviendo decenas de
  direcciones a la vez -- síntoma clásico de SDA pegado en bajo tras una
  transacción abortada). Se recupera cortando `Ve_3V3`
  (`Pin(5).value(0)`), 9 pulsos manuales de SCL, y volviendo a energizar.
- Variables ya probadas y descartadas como causa única:
  - Pines: GPIO15/16 y GPIO1/2 (`QL_SCL`/`QL_SDA`, el único par que
    Heltec etiqueta oficialmente como I2C según el pin map -- GPIO15/16
    son genéricos, solo `32K_P`/`32K_N` + ADC, sin diseño de I2C detrás).
  - Frecuencia: 400kHz, 100kHz, 50kHz.
  - `machine.I2C` (hardware) vs. `machine.SoftI2C` (bit-banging) --
    mismo resultado con ambos, lo que descarta un bug del periférico I2C
    del ESP32-S3 específicamente.
  - Tamaño de transacción: un solo `writeto()` de ~1KB, `writevto()`, y
    en bloques de 128 bytes -- todas fallan en algún momento. Escrituras
    sueltas de hasta 256 bytes (fuera de la secuencia de init) sí
    funcionan, lo que sugiere que el problema aparece específicamente
    cerca del power-on de la charge pump/panel, no por tamaño en sí.
  - Delay de settle de 100ms después de `SET_DISP|0x01` antes del primer
    `fill()+show()`: no fue suficiente de forma consistente.
- **Sospecha principal, sin confirmar:** pull-ups ausentes/débiles en
  SCL/SDA, o caída de `Ve_3V3` bajo la corriente que pide el panel al
  encenderse de verdad (no solo la lógica I2C). Requiere multímetro:
  medir resistencia SDA/SCL a 3.3V con el módulo apagado (debería dar
  2-10kΩ si tiene pull-ups), y la tensión de `Ve_3V3` en vivo durante un
  intento de `show()`.
- No se descartó un módulo OLED defectuoso (no se probó con una segunda
  unidad).

**Pendiente (si se retoma):**
- Resolver el punto físico de arriba antes de volver a tocar el driver.
- Validar `oled_test.py` / `oled_seven_seg_test.py` en la placa real.
- `main.py`: inicializar el OLED al arrancar en `_bg()`; tarea asyncio
  que actualiza el campo de pantalla 1 (velocidad o Wh/km) con
  `seven_seg.draw_text_mono_centered()` a la misma cadencia que el TFT.
  Coordinar con `vext_enable()/vext_disable()` para no perder
  alimentación si el GPS o el deep sleep tocan el mismo rail (GPS ya
  volvió a usar GPIO1/2, así que un OLED futuro necesitaría otro par de
  pines o compartir el bus con el GPS de otra forma).

---

## Tareas de validación en hardware (pendientes, en orden de prioridad)

1. **Batería interna ADC**: comparar `main.battery_status()` contra
   multímetro con y sin USB. Ajustar el divisor en `HW.py` si hay offset.
2. **Deep sleep automático**: confirmar que el timeout solo corre con
   telemetría fresca y `speed <= 0.1 km/h`; que movimiento o pérdida de
   enlace lo reinician; que S3/GPIO21 despierta el T190.
3. **GPS al aire libre**: confirmar fix, satélites, sincronización RTC con
   `main.gps_status()` y captura de waypoint con S3 largo.
4. **Ve_3V3**: confirmar que cae al hacer `stop()` y vuelve al reiniciar.
5. **ESP-NOW + LoRa**: probar con ambas placas encendidas; confirmar que
   `espnow_status()` muestra recepciones y el receptor LoRa en Paddock
   recibe el frame V3.
6. **microSD con firmware completo**: confirmar montaje, CSV válido,
   LoRa activo durante escrituras, BTN0 largo alterna log, CSV se cierra
   en deep sleep.
7. **AP de configuración**: conectar teléfono real, guardar y cancelar,
   confirmar que AP se apaga. Calibrar VBATS con la nueva UI simplificada.
8. **Gestos S3**: confirmar que extra (≥2,2 s) duerme al soltar y que largo
   (1,2–<2,2 s) captura waypoint sin dormir.

---

## Notas de build MicroPython

- Verificar que el firmware incluya `MICROPY_PY_ESPNOW`; sin él aparece
  `ImportError: no module named 'espnow'` y el gateway no funciona.
- microSD: formatear como **FAT32** desde PC. `VfsFat` de MicroPython no
  monta exFAT (falla silenciosamente o con `OSError`).
- Driver display: ST7789 real. MADCTL landscape = 0xA0, offsets (col=0,
  row=35). No mandar registros de gamma/VCOM extra (solo SWRESET, SLPOUT,
  COLMOD, MADCTL, INVON, NORON, DISPON).

---

## Comandos REPL útiles durante desarrollo

```python
import main
main.status()          # estado general
main.battery_status()  # voltaje, ADC crudo, GPIO6
main.gps_status()      # fix, satélites, bytes inválidos, hora ART
main.espnow_status()   # enlace, contador recepciones
main.log_status()      # SD, archivo actual, modo
main.log_start()       # iniciar log manual
main.log_stop()        # detener log
main.log_auto()        # volver a modo automático
main.config_status()   # estado configuración/AP
main.deep_sleep()      # solicitar deep sleep inmediato
main.stop()            # detener hilo de app
main.start()           # reiniciar hilo de app
```
