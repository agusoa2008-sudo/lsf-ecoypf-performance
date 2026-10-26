# ST7789 LCD Driver — `st7789py.py`

Driver MicroPython para displays TFT con controlador **ST7789**.  
Fuente: [russhughes/st7789py_mpy](https://github.com/russhughes/st7789py_mpy) — Licencia MIT.

---

## Pinout — Heltec Vision Master T190

| Señal LCD | GPIO ESP32-S3 | Descripción |
|-----------|--------------|-------------|
| VTFT_CTRL | **7**  | Alimentación VCC panel — **LOW = encender** |
| SCK       | **38** | SPI Clock |
| MOSI      | **48** | SPI Data |
| CS        | **39** | Chip Select (activo LOW) |
| DC        | **47** | Data / Command |
| RST       | **40** | Reset (activo LOW) |
| BL        | **17** | Backlight (HIGH = encendido) |

> **Importante:** GPIO 7 (`VTFT_CTRL`) debe estar en LOW antes de inicializar el SPI.  
> Sin esto el panel no recibe alimentación y el display no enciende.

---

## Display T190: resolución y rotaciones custom

El T190 usa un panel **170 × 320 px** ST7789 — no es uno de los tamaños predefinidos del driver (240×320, 240×240, 135×240, 128×128), por lo que hay que pasar `custom_rotations`.

```python
ROTATIONS_170x320 = (
    (0x00, 170, 320, 35,  0, False),  # 0 – Portrait
    (0x60, 320, 170,  0, 35, False),  # 1 – Landscape
    (0xC0, 170, 320, 35,  0, False),  # 2 – Portrait invertido
    (0xA0, 320, 170,  0, 35, False),  # 3 – Landscape invertido
)
```

Los offsets (35, 0) son necesarios porque el chip ST7789 tiene un buffer interno de 240×320 pero el panel físico usa sólo 170 columnas a partir de la columna 35.

---

## Constructor

```python
import st7789py as st7789
from machine import SPI, Pin

tft = st7789.ST7789(
    spi,              # objeto SPI (requerido)
    width,            # ancho físico del panel (requerido)
    height,           # alto  físico del panel (requerido)
    reset=None,       # Pin de reset (opcional)
    dc=None,          # Pin DC — REQUERIDO
    cs=None,          # Pin CS  (opcional)
    backlight=None,   # Pin backlight — el driver lo pone HIGH al final de __init__
    rotation=0,       # 0=Portrait 1=Landscape 2=Inv.Portrait 3=Inv.Landscape
    color_order=st7789.BGR,  # BGR (default) o RGB
    custom_init=None,        # secuencia de init personalizada
    custom_rotations=None,   # tabla de rotaciones personalizada (ver arriba)
)
```

### Parámetros de color_order

| Valor | Descripción |
|-------|-------------|
| `st7789.BGR` | Azul-Verde-Rojo (default, la mayoría de los paneles ST7789) |
| `st7789.RGB` | Rojo-Verde-Azul (usar si los colores salen invertidos) |

---

## Colores predefinidos

```python
st7789.BLACK    # 0x0000
st7789.BLUE     # 0x001F
st7789.RED      # 0xF800
st7789.GREEN    # 0x07E0
st7789.CYAN     # 0x07FF
st7789.MAGENTA  # 0xF81F
st7789.YELLOW   # 0xFFE0
st7789.WHITE    # 0xFFFF
```

### Color personalizado (RGB565)

```python
color = st7789.color565(r, g, b)   # r, g, b en rango 0–255
# Ejemplos:
naranja = st7789.color565(255, 128, 0)
teal    = st7789.color565(0, 128, 128)
gris    = st7789.color565(80, 80, 80)
```

---

## Métodos de la clase ST7789

### Control general

| Método | Descripción |
|--------|-------------|
| `tft.fill(color)` | Rellena toda la pantalla con un color |
| `tft.rotation(n)` | Cambia la rotación (0–3) en tiempo de ejecución |
| `tft.hard_reset()` | Reset por hardware (cicla el pin RST) |
| `tft.soft_reset()` | Reset por comando SPI |
| `tft.sleep_mode(True/False)` | Activa / desactiva modo sleep del panel |
| `tft.inversion_mode(True/False)` | Activa / desactiva inversión de colores |

### Primitivas de dibujo

| Método | Descripción |
|--------|-------------|
| `tft.pixel(x, y, color)` | Dibuja un píxel |
| `tft.hline(x, y, length, color)` | Línea horizontal |
| `tft.vline(x, y, length, color)` | Línea vertical |
| `tft.line(x0, y0, x1, y1, color)` | Línea entre dos puntos (Bresenham) |
| `tft.rect(x, y, w, h, color)` | Rectángulo sin relleno |
| `tft.fill_rect(x, y, w, h, color)` | Rectángulo con relleno |
| `tft.polygon(points, x, y, color, angle, cx, cy)` | Polígono (≥3 vértices), con rotación opcional |

### Imágenes / buffers

| Método | Descripción |
|--------|-------------|
| `tft.blit_buffer(buf, x, y, w, h)` | Vuelca un buffer RGB565 en la pantalla |
| `tft.bitmap(bmp_module, x, y, index)` | Dibuja un bitmap convertido (herramienta externa) |
| `tft.pbitmap(bmp_module, x, y, index)` | Igual que bitmap pero fila a fila (menor RAM) |

### Texto (requiere módulo de fuente)

| Método | Descripción |
|--------|-------------|
| `tft.text(font, text, x, y, color, bg)` | Texto con fuente bitmap BIOS (8 o 16 px ancho) |
| `tft.write(font, string, x, y, fg, bg)` | Texto con fuente TrueType convertida (proporcional) |
| `tft.write_width(font, string)` | Devuelve el ancho en px de un string con esa fuente |

### Scroll hardware

| Método | Descripción |
|--------|-------------|
| `tft.vscrdef(tfa, vsa, bfa)` | Define área de scroll vertical |
| `tft.vscsad(vssa)` | Establece línea de inicio del scroll |

---

## Ejemplos

### Ejemplo 1 — Inicialización T190 (mínimo)

```python
import st7789py as st7789
from machine import SPI, Pin
import time

# 1. Encender VCC del panel (OBLIGATORIO en T190)
Pin(7, Pin.OUT).value(0)
time.sleep_ms(120)

# 2. SPI bus 1
spi = SPI(1, baudrate=40_000_000, sck=Pin(38), mosi=Pin(48))

# 3. Rotaciones necesarias para 170×320
ROTATIONS = (
    (0x00, 170, 320, 35,  0, False),
    (0x60, 320, 170,  0, 35, False),
    (0xC0, 170, 320, 35,  0, False),
    (0xA0, 320, 170,  0, 35, False),
)

# 4. Crear instancia
tft = st7789.ST7789(
    spi, 170, 320,
    cs=Pin(39, Pin.OUT),
    dc=Pin(47, Pin.OUT),
    reset=Pin(40, Pin.OUT),
    backlight=Pin(17, Pin.OUT),
    custom_rotations=ROTATIONS,
    rotation=0,
    color_order=st7789.BGR,
)

# 5. Listo — pantalla negra y backlight encendido
```

---

### Ejemplo 2 — Hello World

```python
# Requiere tft inicializado (ver Ejemplo 1)
import framebuf

def print_text(tft, x, y, text, fg, bg=st7789.BLACK):
    """Imprime texto usando la fuente 8x8 built-in de MicroPython."""
    n = len(text)
    w, h = n * 8, 8
    stride = (w + 7) // 8
    mono = bytearray(stride * h)
    framebuf.FrameBuffer(mono, w, h, framebuf.MONO_HLSB).text(text, 0, 0, 1)
    fh, fl = fg >> 8, fg & 0xFF
    bh, bl = bg >> 8, bg & 0xFF
    buf = bytearray(w * h * 2)
    for r in range(h):
        rb = r * stride
        for c in range(w):
            i = (r * w + c) * 2
            if (mono[rb + c // 8] >> (c % 8)) & 1:
                buf[i], buf[i+1] = fh, fl
            else:
                buf[i], buf[i+1] = bh, bl
    tft.blit_buffer(buf, x, y, w, h)

tft.fill(st7789.BLACK)
print_text(tft, 10, 10, "Hello T190!", st7789.GREEN)
print_text(tft, 10, 24, "ST7789 OK", st7789.CYAN, st7789.color565(0,0,80))
```

> **Nota:** El driver `st7789py` no incluye ninguna fuente embebida. Usa `framebuf` de MicroPython como se muestra arriba, o descarga una fuente bitmap del repositorio.

---

### Ejemplo 3 — Formas geométricas

```python
tft.fill(st7789.BLACK)

# Líneas
tft.hline(0,  10, 170, st7789.WHITE)
tft.vline(85,  0, 320, st7789.GRAY if hasattr(st7789, 'GRAY') else st7789.color565(80,80,80))
tft.line(0, 0, 169, 319, st7789.CYAN)

# Rectángulos
tft.rect(10, 30, 80, 50, st7789.YELLOW)          # sin relleno
tft.fill_rect(10, 90, 80, 50, st7789.RED)         # con relleno

# Polígono — triángulo
tft.polygon([(0,0),(60,0),(30,50)], x=55, y=150, color=st7789.GREEN)

# Polígono con rotación (radianes)
import math
tft.polygon([(0,0),(60,0),(30,50)], x=55, y=220,
            color=st7789.MAGENTA, angle=math.pi/4)
```

---

### Ejemplo 4 — Rotación dinámica

```python
import time

for rot in range(4):
    tft.rotation(rot)
    tft.fill(st7789.BLACK)
    # tft.width y tft.height se actualizan automáticamente
    label = ["Portrait", "Landscape", "Inv.Portrait", "Inv.Landscape"][rot]
    print_text(tft, 4, 4, label, st7789.WHITE)
    time.sleep(2)
```

---

### Ejemplo 5 — Scroll vertical

```python
# Definir área de scroll: sin zonas fijas, scroll de toda la pantalla
tft.fill(st7789.BLACK)
tft.vscrdef(0, 320, 0)   # tfa=0, área scroll=320, bfa=0

# Dibujar contenido desplazable
for i in range(0, 320, 8):
    print_text(tft, 0, i, "Linea {}          ".format(i // 8), st7789.CYAN)

# Animar scroll
import time
for pos in range(0, 320):
    tft.vscsad(pos)
    time.sleep_ms(10)
```

---

### Ejemplo 6 — Buffer RGB565 directo (imagen cruda)

```python
# Mostrar una imagen de 170x10 px desde un buffer bytearray (datos RGB565)
# Cada píxel = 2 bytes big-endian: RRRRRGGGGGGBBBBB
import struct

W, H = 170, 10
buf = bytearray(W * H * 2)

# Degradado horizontal rojo→azul
for x in range(W):
    r = int(255 * x / W)
    b = 255 - r
    color = st7789.color565(r, 0, b)
    high, low = color >> 8, color & 0xFF
    for y in range(H):
        i = (y * W + x) * 2
        buf[i]   = high
        buf[i+1] = low

tft.blit_buffer(buf, 0, 0, W, H)
```

---

## Notas de uso en el T190

| Situación | Solución |
|-----------|----------|
| Pantalla completamente apagada (negra) | Verificar que GPIO 7 (`VTFT_CTRL`) esté en LOW |
| Colores invertidos (rojo=azul, etc.) | Cambiar `color_order=st7789.BGR` → `st7789.RGB` |
| Display sin tamaño estándar (T190 = 170×320) | Usar `custom_rotations` con offset `xstart=35` |
| `ValueError: Unsupported NxM display` | El display no está en la tabla interna — pasar `custom_rotations` |
| Imagen desplazada horizontalmente | Los offsets en `custom_rotations` son incorrectos |
| `SPI` lento / artefactos | Reducir `baudrate` de 40 MHz a 20 MHz |

---

## Archivos a subir al ESP32 (raíz `/`)

```
st7789py.py          ← driver principal (este archivo)
loralcd_test.py      ← aplicación principal
_sx126x.py           ← constantes LoRa
sx126x.py            ← clase base SX126X
sx1262.py            ← clase SX1262
```

`ST7735.py` ya **no** es necesario en el T190.
