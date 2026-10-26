# Driver SX1262 — LoRa para MicroPython

Driver para el módulo LoRa Semtech SX1262. Portado desde [RadioLib](https://github.com/jgromes/RadioLib) por [ehong-tl](https://github.com/ehong-tl/micropySX126X).

## Archivos necesarios

Copiar los 3 archivos al ESP32 (raíz del sistema de archivos):

```
_sx126x.py   ← constantes y códigos de error
sx126x.py    ← clase base
sx1262.py    ← clase SX1262 (este es el que se importa)
```

---

## Pinout — Heltec Wireless Tracker T190

| SX1262 | GPIO ESP32-S3 |
|---|---|
| SCK  | 9  |
| MOSI | 10 |
| MISO | 11 |
| CS   | 8  |
| RST  | 12 |
| DIO1 (IRQ) | 14 |
| BUSY (GPIO) | 13 |

---

## Constructor

```python
SX1262(spi_bus, clk, mosi, miso, cs, irq, rst, gpio)
```

| Parámetro | Descripción |
|---|---|
| `spi_bus` | ID del bus SPI (1 o 2) |
| `clk` | Pin SCK |
| `mosi` | Pin MOSI |
| `miso` | Pin MISO |
| `cs` | Pin NSS/CS |
| `irq` | Pin DIO1 |
| `rst` | Pin RESET |
| `gpio` | Pin BUSY |

---

## Método `begin()` — Modo LoRa

```python
lora.begin(freq, bw, sf, cr, syncWord, power, currentLimit,
           preambleLength, implicit, implicitLen, crcOn,
           txIq, rxIq, tcxoVoltage, useRegulatorLDO, blocking)
```

| Parámetro | Default | Descripción |
|---|---|---|
| `freq` | 434.0 | Frecuencia en MHz (150–960) |
| `bw` | 125.0 | Ancho de banda en kHz |
| `sf` | 9 | Spreading factor (5–12) |
| `cr` | 7 | Coding rate (5–8) → 4/5 a 4/8 |
| `syncWord` | 0x12 | 0x12=privado, 0x34=público (TTN) |
| `power` | 14 | Potencia TX en dBm (−9 a +22) |
| `currentLimit` | 60.0 | Límite de corriente en mA |
| `preambleLength` | 8 | Longitud del preámbulo |
| `crcOn` | True | Habilitar CRC |
| `tcxoVoltage` | 1.6 | Voltaje TCXO en V |
| `blocking` | True | Modo bloqueante |

---

## Métodos principales

```python
lora.send(data)          # Enviar bytes/bytearray → retorna (len, estado)
lora.recv(len, timeout_en, timeout_ms)  # Recibir → retorna (bytes, estado)
lora.setFrequency(freq)  # Cambiar frecuencia en MHz
lora.setOutputPower(power)  # Cambiar potencia TX (−9 a +22 dBm)
lora.getRSSI()           # RSSI del último paquete recibido (dBm)
lora.getSNR()            # SNR del último paquete LoRa recibido (dB)
lora.getTimeOnAir(len)   # Tiempo en el aire en µs para paquete de 'len' bytes
lora.setBlockingCallback(blocking, callback)  # Cambiar modo bloqueante/callback
```

---

## Ejemplos de uso

### Ejemplo 1 — Transmisión simple (bloqueante)

```python
from machine import Pin, SPI
from sx1262 import SX1262

# Heltec Wireless Tracker T190 — pines LoRa
lora = SX1262(spi_bus=1, clk=9, mosi=10, miso=11,
              cs=8, irq=14, rst=12, gpio=13)

# 915 MHz para América del Sur (usar 868 para Europa)
lora.begin(freq=915.0, bw=125.0, sf=7, cr=5,
           syncWord=0x12, power=14, tcxoVoltage=1.6)

msg = b"Hola desde Heltec T190!"
length, err = lora.send(msg)
print(f"Enviado: {length} bytes, estado: {err}")
```

---

### Ejemplo 2 — Recepción simple (bloqueante)

```python
from sx1262 import SX1262

lora = SX1262(spi_bus=1, clk=9, mosi=10, miso=11,
              cs=8, irq=14, rst=12, gpio=13)

lora.begin(freq=915.0, bw=125.0, sf=7, cr=5, syncWord=0x12, power=14)

print("Esperando mensajes...")
while True:
    data, err = lora.recv(timeout_en=True, timeout_ms=5000)
    if err == 0 and data:
        print(f"Recibido: {data.decode()} | RSSI: {lora.getRSSI()} dBm | SNR: {lora.getSNR()} dB")
    elif err == -6:
        print("Timeout, reintentando...")
```

---

### Ejemplo 3 — Ping-Pong (TX y RX alternados)

```python
from sx1262 import SX1262
import time

lora = SX1262(spi_bus=1, clk=9, mosi=10, miso=11,
              cs=8, irq=14, rst=12, gpio=13)

lora.begin(freq=915.0, bw=125.0, sf=7, cr=5, syncWord=0x12, power=14)

NODO = "A"   # Cambiar a "B" en el otro dispositivo
contador = 0

while True:
    if NODO == "A":
        msg = f"PING {contador}".encode()
        lora.send(msg)
        print(f"TX: {msg}")
        data, err = lora.recv(timeout_en=True, timeout_ms=3000)
        if err == 0 and data:
            print(f"RX: {data.decode()} | RSSI: {lora.getRSSI()} dBm")
        contador += 1
        time.sleep(1)
    else:
        data, err = lora.recv(timeout_en=True, timeout_ms=5000)
        if err == 0 and data:
            print(f"RX: {data.decode()}")
            lora.send(b"PONG")
```

---

### Ejemplo 4 — Modo no bloqueante con callback

```python
from sx1262 import SX1262

lora = SX1262(spi_bus=1, clk=9, mosi=10, miso=11,
              cs=8, irq=14, rst=12, gpio=13)

# Modo no bloqueante
lora.begin(freq=915.0, bw=125.0, sf=7, cr=5,
           syncWord=0x12, power=14, blocking=False)

def on_receive(events):
    if events & SX1262.RX_DONE:
        data, err = lora.recv()
        if err == 0:
            print(f"RX Callback: {data.decode()}")
    if events & SX1262.TX_DONE:
        print("TX completado")

lora.setBlockingCallback(False, callback=on_receive)

# El programa puede hacer otras cosas mientras espera
import time
while True:
    print("Haciendo otras tareas...")
    time.sleep(1)
```

---

## Códigos de error comunes

| Código | Constante | Descripción |
|---|---|---|
| 0 | `ERR_NONE` | Sin error |
| -5 | `ERR_TX_TIMEOUT` | Timeout en transmisión |
| -6 | `ERR_RX_TIMEOUT` | Timeout en recepción |
| -7 | `ERR_CRC_MISMATCH` | Error de CRC |
| -12 | `ERR_INVALID_FREQUENCY` | Frecuencia fuera de rango |
| -13 | `ERR_INVALID_OUTPUT_POWER` | Potencia fuera de −9 a +22 dBm |
| -2 | `ERR_CHIP_NOT_FOUND` | No se detecta el chip (revisar pines SPI) |

```python
# Ver diccionario completo de errores
from _sx126x import ERROR
print(ERROR)
```

---

## Frecuencias LoRa por región

| Región | Frecuencia |
|---|---|
| América del Sur | 915 MHz |
| Europa | 868 MHz |
| Asia (China) | 470 MHz |
| Asia (Japón) | 920 MHz |
