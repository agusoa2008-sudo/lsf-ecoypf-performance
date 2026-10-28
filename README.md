# LSF EcoYPF — Performance

Instrumentación de a bordo del equipo **La Salle Florida (LSF)** para el Desafío Eco YPF 2026. No es
un proyecto de "telemetría" por sí misma: es el sistema que mide, calcula y muestra en tiempo real el
**performance** del auto, para que el piloto y el equipo técnico puedan maximizarlo durante la carrera.

## El objetivo: potencia objetivo vs. potencia actual

La prueba de Endurance del Desafío Eco YPF tiene dos restricciones fijas: **80 minutos** de carrera y
la **energía de las baterías provistas**, selladas y precintadas por la CDA — no se puede agregar ni
un Wh más. Gana el auto que recorre más distancia con esa energía fija en ese tiempo fijo; quedarse sin
batería y detenerse en pista es exclusión directa.

El dato central que resuelve ese problema en vivo es la **potencia**, no el Wh/km:

- **Potencia objetivo** = energía restante en la batería ÷ tiempo restante de carrera. Es la potencia
  constante que, sostenida el resto de la carrera, agota la batería justo en el minuto 80. Se recalcula
  en vivo a medida que avanza la carrera.
- **Potencia actual** (promedio reciente, `PA`) — lo que el piloto está gastando en este momento.

Comparar las dos le dice al piloto, sin ambigüedad, si tiene que acelerar (va a sobrar batería) o
aflojar (se va a quedar sin batería antes de tiempo). Para este auto conviene sostener la potencia
pareja en vez de alternar picos y valles: el arrastre aerodinámico crece más rápido que la velocidad, y
la batería de plomo-ácido entrega menos Wh útiles cuanto más fuerte se la descarga (efecto Peukert) —
el propio diseño conceptual del equipo ya lo señala: *"Conviene un ritmo parejo"*
(`docs/Instrumentacion_Telemetria_EcoYPF2026.pdf`, §4).

El Wh/km (`WI`/`WA`) se sigue calculando, pero como dato secundario de análisis después de cada tanda —
no es el número que el piloto mira en vivo para decidir.

El detalle completo de por qué se mide cada cosa está en
[`docs/ARQUITECTURA_TELEMETRIA_ECOYPF.md §0`](docs/ARQUITECTURA_TELEMETRIA_ECOYPF.md#0-objetivo-potencia-objetivo-vs-potencia-actual-el-dato-central-del-proyecto).
**Potencia objetivo ya está implementada** en el firmware del T190 (pantalla CARRERA: reloj de carrera
+ energía restante con modelo Peukert calibrable, ver [`docs/CALIBRACION_PEUKERT.md`](docs/CALIBRACION_PEUKERT.md)) —
falta validarla en banco y en pista.

## Arquitectura: tres nodos

1. **Super Mini S3** (ESP32-S3 Super Mini) — sensado y cálculo. Lee las 4 tensiones de batería
   (ADS1115), corriente (ADS1220 + toroide Hall) y pulsos de velocidad; calcula potencia, energía,
   velocidad, distancia y Wh/km; envía el snapshot por **ESP-NOW**. Es la única fuente de verdad de
   las métricas — ningún otro nodo recalcula.
2. **T190** (Heltec Vision Master T190) — display de cabina y gateway. Recibe el frame ESP-NOW del
   Super Mini, se lo muestra al piloto en el TFT integrado y lo retransmite por **LoRa** (SX1262
   onboard) hacia el paddock. GPS probado standalone, aún no integrado al flujo principal.
3. **Paddock S3** (Seeed XIAO ESP32-S3 + Wio-SX1262) — receptor LoRa en el box. Expone un access
   point Wi-Fi propio con una mini web de performance en tiempo real para el equipo técnico.

El enlace T190→Paddock es unidireccional (auto → box) y 100% inalámbrico por LoRa, conforme al
reglamento (sin conexión eléctrica entre el vehículo y el box).

Para el protocolo completo, el marco reglamentario y el historial de decisiones de diseño, ver
[`docs/ARQUITECTURA_TELEMETRIA_ECOYPF.md`](docs/ARQUITECTURA_TELEMETRIA_ECOYPF.md). Para el estado
funcional de cada nodo — qué está implementado, qué falta validar, qué está pendiente — ver
[`docs/FUNCIONALIDADES.md`](docs/FUNCIONALIDADES.md).

## Estructura del repositorio

```
docs/                          Documentación de arquitectura, funcionalidades y referencia
  ARQUITECTURA_TELEMETRIA_ECOYPF.md
  FUNCIONALIDADES.md
  Instrumentacion_Telemetria_EcoYPF2026.pdf   Diseño conceptual original (La Salle Florida)
  Telemetria_EcoYPF_Arquitectura_v0.9.pdf     Arquitectura v0.9
  reglamento-tecnico.pdf                      Reglamento técnico CDA/ACA-FIA del Desafío Eco YPF

firmware/
  super-mini-s3/     Firmware del nodo de sensado y métricas (ESP32-S3 Super Mini)
  t190/              Firmware del nodo display/gateway (Heltec Vision Master T190)
  paddock-s3/        Firmware del receptor LoRa + dashboard web (Seeed XIAO ESP32-S3)
```

Cada carpeta de firmware tiene su propio `README.md` con el pinout, los archivos principales y cómo
desplegarlo. El T190 además tiene notas de desarrollo (`CONTINUACION_DESARROLLO.md`) y guías de los
drivers de pantalla y radio (`ST7789_LCD.md`, `SX1262_LoRa.md`).

## Historia del desarrollo

<p align="center">
  <img src="docs/Fotos/WhatsApp%20Image%202026-10-17%20at%207.27.15%20PM.jpeg" width="420" alt="Equipo armando la carrocería del auto en el taller">
  <img src="docs/Fotos/WhatsApp%20Image%202026-10-18%20at%201.13.11%20PM.jpeg" width="420" alt="Componentes de electrónica de a bordo sobre la mesa de trabajo">
</p>

Instantáneas del taller de La Salle Florida: armado de la carrocería y electrónica de a bordo antes de
integrarla al auto. Más fotos, videos del proceso y el esquemático de cableado del Super Mini (KiCad)
en [`docs/Fotos/`](docs/Fotos/) y [`docs/KiCad/`](docs/KiCad/).

## Nota sobre credenciales

Los archivos `wifi_config.py` e `ipaddress.cfg` de cada nodo traen placeholders
(`YOUR_SSID_HERE` / `YOUR_PASSWORD_HERE`) en lugar de las credenciales reales de despliegue. Completar
con la red Wi-Fi local antes de flashear. Las contraseñas de los access points propios de cada
dispositivo (paddock / portal de configuración) sí quedan en el código: son redes locales sin salida a
internet, documentadas intencionalmente en los README de cada nodo.
