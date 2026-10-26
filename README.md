# EcoYPF 2026 — Telemetría e Instrumentación

Firmware MicroPython y documentación del sistema de telemetría para el
Desafío Eco YPF (Campeonato Argentino, reglamento CDA/ACA–FIA). El sistema
mide tensión, corriente, velocidad y distancia del vehículo y transmite esas
métricas por radio hasta el paddock.

## Arquitectura: tres nodos

1. **Super Mini S3** (ESP32-S3 Super Mini) — sensado y cálculo. Lee las 4
   tensiones de batería (ADS1115), corriente (ADS1220 + toroide Hall) y
   pulsos de velocidad; calcula potencia, energía, velocidad, distancia y
   Wh/km; envía el snapshot por **ESP-NOW**. Es la única fuente de verdad de
   las métricas — ningún otro nodo recalcula.
2. **T190** (Heltec Vision Master T190) — display y gateway. Recibe el
   frame ESP-NOW del Super Mini, lo muestra en el TFT/LCD integrado y lo
   retransmite por **LoRa** (SX1262 onboard) hacia el paddock. GPS probado
   standalone, aún no integrado al flujo principal.
3. **Paddock S3** (Seeed XIAO ESP32-S3 + Wio-SX1262) — receptor LoRa en el
   box. Expone un access point Wi-Fi propio con una mini web de telemetría
   en tiempo real.

El enlace T190→Paddock es unidireccional (auto → box) y 100% inalámbrico por
LoRa, conforme al reglamento (sin conexión eléctrica entre el vehículo y el
box).

Para el detalle completo del protocolo, el marco reglamentario y el historial
de decisiones de diseño, ver [`docs/ARQUITECTURA_TELEMETRIA_ECOYPF.md`](docs/ARQUITECTURA_TELEMETRIA_ECOYPF.md).
Para el estado funcional actual de cada nodo (qué está implementado, qué
falta validar, qué está pendiente), ver [`docs/FUNCIONALIDADES.md`](docs/FUNCIONALIDADES.md).

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

Cada carpeta de firmware tiene su propio `README.md` con el pinout, los
archivos principales y cómo desplegarlo. El T190 además tiene notas de
desarrollo (`CONTINUACION_DESARROLLO.md`) y guías de los drivers de pantalla
y radio (`ST7789_LCD.md`, `SX1262_LoRa.md`).

## Nota sobre credenciales

Los archivos `wifi_config.py` e `ipaddress.cfg` de cada nodo traen
placeholders (`YOUR_SSID_HERE` / `YOUR_PASSWORD_HERE`) en lugar de las
credenciales reales de despliegue. Completar con la red Wi-Fi local antes de
flashear. Las contraseñas de los access points propios de cada dispositivo
(paddock / portal de configuración) sí quedan en el código: son redes locales
sin salida a internet, documentadas intencionalmente en los README de cada
nodo.
