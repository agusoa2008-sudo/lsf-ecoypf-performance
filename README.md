# LSF EcoYPF — Performance

Instrumentación de a bordo del equipo **La Salle Florida (LSF)** para el Desafío Eco YPF 2026. No es
un proyecto de "telemetría" por sí misma: es el sistema que mide, calcula y muestra en tiempo real el
**performance** del auto, para que el piloto y el equipo técnico puedan maximizarlo durante la carrera.

## El objetivo: bajar el Wh/km

El Desafío Eco YPF es una categoría de **eficiencia energética**, no de velocidad pura. Performance acá
significa recorrer la mayor distancia posible con la menor energía posible, dentro del tiempo de
carrera. La métrica que lo resume es **`Wh/km`** (energía consumida por kilómetro recorrido) — cuanto
más bajo, mejor.

Todo lo que este sistema mide existe para producir ese número, en vivo, y dárselo al piloto para que
pueda corregir su manejo antes de que termine la tanda:

- **Tensión y corriente de batería** → potencia instantánea (`P = V × I`) → energía consumida (`Wh`).
- **Pulsos de velocidad** → velocidad y distancia recorrida (`D`), el denominador de Wh/km.
- **`P` y `V` combinados** → `Wh/km` instantáneo (lo que el piloto corrige en el momento) y promedio
  (el resultado final de la tanda).
- **GPS y tiempo de vuelta** (en desarrollo) → cruza el Wh/km con el ritmo real, porque la estrategia
  ideal no es gastar lo mínimo posible (eso sería no moverse) sino encontrar el manejo más eficiente
  sin caer del ritmo mínimo competitivo.
- **Dashboard en el paddock** → el reglamento prohíbe cualquier cable entre el auto y boxes; el enlace
  LoRa inalámbrico es la única forma de que el equipo técnico vea el performance en vivo y asesore al
  piloto por los canales de comunicación autorizados.

El detalle completo de por qué se mide cada cosa está en
[`docs/ARQUITECTURA_TELEMETRIA_ECOYPF.md §0`](docs/ARQUITECTURA_TELEMETRIA_ECOYPF.md#0-objetivo-performance-no-telemetría-por-sí-misma).

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

## Nota sobre credenciales

Los archivos `wifi_config.py` e `ipaddress.cfg` de cada nodo traen placeholders
(`YOUR_SSID_HERE` / `YOUR_PASSWORD_HERE`) en lugar de las credenciales reales de despliegue. Completar
con la red Wi-Fi local antes de flashear. Las contraseñas de los access points propios de cada
dispositivo (paddock / portal de configuración) sí quedan en el código: son redes locales sin salida a
internet, documentadas intencionalmente en los README de cada nodo.
