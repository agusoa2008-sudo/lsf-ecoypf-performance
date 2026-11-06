# Diagnóstico ESP-NOW — Super Mini ↔ T190 (2026-11-05)

## Resumen

El ESP-NOW en sí (protocolo, pairing, PM_NONE) está bien implementado en ambas
placas y **no es la causa** de las pérdidas intermitentes. La causa encontrada
y observada en vivo es que **el T190 crashea y se reinicia solo**, gatillado
por el driver de LoRa, y cada reinicio produce un apagón total de ESP-NOW de
varios segundos hasta que vuelve a emparejar.

Pasó 2 veces en menos de 2 minutos de monitoreo en banco.

## Cómo se diagnosticó

Se leyó el código REALMENTE cargado en ambas placas (vía `mpremote`, sin
flashear nada) y se comparó contra los repos locales — ver más abajo, hay una
discrepancia de repos que conviene resolver. Las carpetas `super-mini-device/`
y `t190-device/` en este directorio son una copia fiel (snapshot) de lo que
hay en la flash de cada placa ahora mismo.

Luego se midió en vivo, por separado, los contadores de telemetría de cada
lado (`espnow_tx_count`/`espnow_tx_fail_count` en el Super Mini,
`espnow_rx_count`/`lora_tx_count` en el T190) mientras ambas placas corrían
normalmente.

## Evidencia directa

### 1) Primera corrida (`t190_rx_log.txt` / `supermini_tx_log.txt`)

El Super Mini mandaba telemetría unicast ~1/s sin problema (2 fallos
aislados de 1 muestra, normales, se recuperan solos). A los ~20s, el T190
hizo un **reset de hardware tipo POWERON** (`rst:0x1 (POWERON)`,
`reset_cause=1`) en medio de la prueba, sin que yo lo causara. Mientras se
reiniciaba (display, LoRa, SD, GPS, ESP-NOW re-pairing), el Super Mini
acumuló **4 fallos de envío consecutivos** (`fail=44,45,46,47`, `link_ok=False`)
— ese es exactamente el "ESP-NOW se pierde" que reporta el usuario.

### 2) Segunda corrida (`evidencia_crash_lora_20261105.txt`) — la más importante

Esta vez se capturó el **crash completo**:

```
[LoRa] send error: SX1262 send status -5        <- ERR_TX_TIMEOUT
Task exception wasn't retrieved
future: <Task> coro= <generator object 'lora_task'>
...
ValueError: generator already executing
...
Guru Meditation Error: Core 1 panic'ed (LoadProhibited)
...
Rebooting...
rst:0xc (RTC_SW_CPU_RST)
```

## Causa raíz

En `t190/sx1262.py` / `_sx126x.py` (driver SX1262, el mismo en ambos repos
locales y en la placa real):

1. `transmit()` es **bloqueante**: espera el TX_DONE sondeando
   `self.irq.value()` en un loop con `time.sleep_ms(1)` (función `yield_()`,
   línea 14-15 de `_sx126x_full.py`) — **no es un yield de asyncio**, congela
   todo el loop cooperativo (display, botones, y el `listen_task` de
   ESP-NOW) durante el tiempo de aire de LoRa (SF9/BW125 ≈ 300-500ms),
   cada 2 segundos (`lora_task` en `telemetry.py`).

2. **Al mismo tiempo**, el mismo pin DIO1 tiene registrada una **interrupción
   de hardware real** (`sx1262.py:165` → `super().setDio1Action(self._onIRQ)`
   → `self.irq.irq(trigger=Pin.IRQ_RISING, handler=...)` en
   `_sx126x_full.py:423`).

   Es decir: el pin que dispara TX_DONE se está mirando **dos veces en
   paralelo** — por polling directo desde el loop bloqueante de `transmit()`
   y por una ISR de hardware que puede dispararse en cualquier punto de la
   ejecución, incluso en medio de una transacción SPI del polling. Eso es
   justo el patrón que produce corrupción de memoria/reentrancia:
   `LoadProhibited` (puntero inválido) + `generator already executing`
   (el scheduler de asyncio intenta re-entrar la misma corrutina
   `lora_task` mientras ya está "corriendo" dentro del busy-wait).

3. Cuando eso pasa, el ESP32-S3 panikea y se reinicia solo
   (`Guru Meditation Error`). El Super Mini no hace nada mal — simplemente
   no tiene con quién hablar durante los ~3-5s que tarda el T190 en volver a
   bootear y re-emparejar (el pairing se recupera solo gracias al diseño ya
   resiliente de `espnow_link.py`, que no resetea el peer guardado ante un
   fallo puntual).

## Por qué el ESP-NOW en sí no es el problema

- Ambas placas ya tienen `PM_NONE` (radio WiFi sin power-save) — el fix
  correcto ya está aplicado en el código que corre en la placa real.
- `send_telemetry()` en el Super Mini ya NO rompe el pairing ante un fallo
  puntual (eso evita que cada bache dispare un re-pairing completo).
- Los 2 fallos aislados de 1 muestra vistos en la corrida 1 son ruido RF
  normal, se recuperan en el siguiente ciclo (1s) y ni siquiera llegan a
  marcar "stale" en el T190 (ventana de gracia `STALE_MS=5000`).

## ⚠️ Aviso aparte: repos desincronizados

Lo que corre en la placa real **no coincide con `firmware/super-mini-s3` ni
con `firmware/t190`** del repo — esos árboles están desactualizados (les
falta el fix de PM_NONE y tienen la versión vieja, menos resiliente, de
`send_telemetry`). Lo que SÍ coincide exactamente con la placa real es:

- Super Mini → carpeta `SUPER MINI S3/`
- T190 → carpetas `New T190/` y `T190 Last/` (idénticas entre sí)

Conviene decidir cuál es la fuente de verdad antes de seguir editando,
para no perder los fixes ya aplicados ni editar el árbol que no se usa.

## Recomendación de arreglo

El arreglo de fondo es en el driver LoRa del T190: evitar que el polling
bloqueante y la ISR de hardware compitan por el mismo pin. Dos caminos,
de menor a mayor esfuerzo:

1. **Mitigación rápida**: deshabilitar la ISR de DIO1 (no llamar
   `setDio1Action`) y dejar solo el polling bloqueante tal como está — pierde
   nada de funcionalidad porque hoy el polling ya hace todo el trabajo; solo
   quita la interrupción redundante que compite por el pin/SPI.
2. **Arreglo robusto**: usar el modo no bloqueante del driver
   (`blocking=False` → `_startTransmit`) y que `lora_task()` political
   el estado con `await asyncio.sleep_ms(...)` en vez de un busy-wait — así
   un TX lento no congela el resto del sistema (display, botones, ESP-NOW)
   y tampoco hay doble consumidor del pin IRQ.

No se aplicó ningún cambio a los repos todavía — esto es solo el
diagnóstico. Avisar si se quiere que se implemente la mitigación rápida
(opción 1, bajo riesgo) sobre `New T190/` (o la carpeta que se confirme como
fuente de verdad).

## Nota aparte: GPS del T190

Al mismo tiempo se detectó que el GPS no emitía ningún byte por UART1
(0 satélites, 0 bytes inválidos, sin fix) a pesar de que VEXT (GPIO5) estaba
correctamente en HIGH. El usuario confirmó que había desconectado el GPS del
QuickLink manualmente — no es un bug. El sync automático de RTC desde GPS
**ya existe** en `gps_task()` (`main.py` del T190): sincroniza
`machine.RTC()` apenas llega el primer fix válido (sentencia RMC) y
re-sincroniza cada 60s mientras el GPS siga con fix.

Se verificó en vivo con la pila nueva puesta: fix en ~2s (warm start gracias
al almanaque retenido por la pila), hora coincidiendo exacta con la hora real
del sistema, y recuperación limpia tras desconectar/reconectar el cable
30s (`invalid_bytes=0`, fix de nuevo en segundos, hora correcta).

### Fix aplicado: sync de hora sin fix de posición

**Archivos**: `New T190/gps.py` y `T190 Last/gps.py` (idénticos, coinciden con
lo flasheado en la placa — ver nota de repos desincronizados más abajo).
Ya subido al dispositivo real (USB1) y probado.

**Antes**: `_parse_sentence()` solo leía el campo de hora de la sentencia RMC
cuando `status == "A"` (fix de posición completo). Si el GPS no tenía fix
pero su RTC interno (mantenido por la pila CR1220 del Adafruit Ultimate GPS)
ya tenía la hora correcta, el T190 la ignoraba por completo y no sincronizaba
`machine.RTC()` hasta lograr fix de posición.

**Ahora**: se acepta el campo de hora también con `status == "V"` (sin fix),
siempre que la fecha parseada sea `>= _MIN_PLAUSIBLE_DATE = (2026, 11, 5)`
(fecha ancla fija — como el calendario real solo avanza, cualquier hora real
futura siempre la va a superar, no hace falta tocarla salvo que se reflashee
mucho después). Esto filtra tanto el epoch default (1980/2000) que manda un
chip sin pila o que nunca logró fix, como una hora vieja de una pila que
perdió carga hace tiempo. No cambia nada de la lógica de posición/fix, solo
la de sincronización de hora. `gps_task()` (`main.py`) no necesitó ningún
cambio: ya reacciona a cualquier incremento de `time_update_count`, venga de
un fix completo o de este camino nuevo.

No se pudo confirmar en banco el camino `status == "V"` específicamente:
tapar la antena con la mano no alcanzó para perder el fix ya adquirido (el
receptor sigue trackeando con mucha menos señal de la que necesitó para
adquirir el lock por primera vez). El fix se implementó igual en base al
comportamiento estándar NMEA (el campo de hora se puebla desde el RTC interno
del chip independientemente del flag de validez de posición) y quedó
verificado que no rompe el camino normal (`status == "A"` sigue sincronizando
igual que antes, confirmado en vivo con fix real).
