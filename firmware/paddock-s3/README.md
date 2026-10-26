# Paddock S3 — receptor LoRa y dashboard Wi-Fi

Firmware MicroPython para Seeed XIAO ESP32-S3 con el módulo Seeed Wio-SX1262
usado en las pruebas de `uPy reference Martin/FC Upy/XiaoS3Lora/`.

## Compatibilidad LoRa

El enlace T190→Paddock usa el perfil **`tradeoff`** de las referencias de
Martin: **915 MHz, BW 125 kHz, SF9, CR 4/6, 17 dBm, sync word 0x12 y
preámbulo 12**. Es un punto de partida con más margen que SF7 para el objetivo
de 1 km en línea de vista; el alcance real debe validarse con las antenas,
altura y entorno de uso. Ambos extremos deben tener los mismos parámetros.

Las referencias incluyen además estos perfiles probados:

| Perfil | Frecuencia | BW | SF | CR | Potencia |
|---|---:|---:|---:|---:|---:|
| `long_distance` | 915 MHz | 31.25 kHz | 12 | 4/8 | 22 dBm |
| `tradeoff` | 915 MHz | 125 kHz | 9 | 4/6 | 17 dBm |
| `fast` | 915 MHz | 500 kHz | 7 | 4/5 | 14 dBm |
| `tradeoff` (este firmware) | 915 MHz | 125 kHz | 9 | 4/6 | 17 dBm |

El perfil `long_distance` (SF12/BW31.25/CR 4/8) aumenta mucho el tiempo de
aire de estos paquetes periódicos largos, por eso no se elige como perfil
inicial. Confirmar que la frecuencia y potencia estén autorizadas para el
evento y el lugar de uso.

## Archivos que se copian a la raíz del filesystem MicroPython

Copiar los archivos `.py` de esta carpeta a la raíz del XIAO. No copiar
`README.md` ni `__pycache__/`; no se necesitan drivers ADS. `boot.py` importa
`main`; `main.py` arranca LoRa y el servidor web en un hilo `_thread` y
retorna para dejar el REPL disponible. Los módulos SX1262 incluidos sí son
necesarios para el radio. No se instala ninguna dependencia externa.

## Acceso al dashboard

- SSID del AP: `Paddock-LSF`; contraseña WPA2: `lasalle2026`.
- IP: `192.168.4.1`; abrir `http://192.168.4.1/`.
- La página se actualiza por push: abre un stream SSE (`/events`) y el
  servidor empuja un nuevo JSON apenas se decodifica cada paquete LoRa, en
  vez de que el teléfono tenga que ir a preguntar cada segundo (ese sondeo
  por `fetch` con una conexión nueva por request era la mayor fuente de
  latencia hacia el teléfono). `/api` sigue disponible para una consulta
  puntual (primer render y fallback si el navegador no soporta SSE). Hasta
  4 clientes SSE simultáneos; los que se desconectan (teléfono fuera de
  rango) se depuran solos en el próximo broadcast o heartbeat (cada 15 s).
  La página distingue la antigüedad del paquete LoRa de la antigüedad de la
  muestra original del Super Mini.
- El payload versión 3 incluye `VER`, `BOOT` (sesión de arranque), `Q`
  (secuencia), `AGE` (edad de la
  muestra), `AV`/`IV` (validez de tensión/corriente) y `PC` (contador de
  pulsos), además de las métricas existentes. `B1`..`B4` son las tensiones
  individuales y `VBATS` es la tensión total del pack. El prefijo opcional
  `TLM:` se admite antes del payload.

## Consola REPL

`main.status()` muestra el estado y los últimos valores;
`main.stop()` detiene la app y el AP; `main.start()` vuelve a iniciarla.

## Arranque y utilidades de recuperación

`boot.py` sigue la misma secuencia del Super Mini: `startup_cleanup.run()`,
`startup_fallback.run()` y después asigna el hostname `PaddockS3-<id>`.

- Mantener GPIO0 bajo durante el arranque elimina `main.py` y deja el REPL en
  modo de recuperación; al faltar `main.py`, el fallback inicia el AP
  `Paddock-LSF` sin arrancar LoRa ni el servidor.
- `r.py`: reinicio inmediato (`machine.reset()`).
- `d.py`: mueve `main.py` a `mainBkp.py` y reinicia, deshabilitando el autoarranque.
- `p.py`: restaura `mainBkp.py` como `main.py` y reinicia.
- `w.py`: importa `wifiConnect.py` para iniciar el AP de prueba/recuperación.

Copiar también estos archivos auxiliares al filesystem junto al firmware.
`mainBkp.py` se conserva cuando el cleanup por GPIO0 elimina el `main.py`
activo.

Este nodo solo recibe. No devuelve ACK LoRa. El alcance y la fiabilidad deben
validarse en el paddock con ambos radios, antenas y la banda permitida para
el evento.
