# Calibración del modelo Peukert de energía restante (T190)

## 0. Qué problema resuelve

La **potencia objetivo** (`docs/ARQUITECTURA_TELEMETRIA_ECOYPF.md §0`) se calcula como:

```
potencia_objetivo_w = energia_restante_wh / (tiempo_restante_s / 3600)
```

`energia_restante_wh` se puede estimar de dos formas, ambas implementadas en `firmware/t190/settings.py`:

- **Lineal** (`T190Settings.battery_remaining_wh`): `capacidad − Wh_consumidos`. Simple, pero no refleja
  que una batería de plomo-ácido entrega **menos** Wh útiles cuanto más fuerte se la descarga (efecto
  Peukert) — ver `Instrumentacion_Telemetria_EcoYPF2026.pdf §4`, citado en `ARQUITECTURA_TELEMETRIA_
  ECOYPF.md §0`.
- **Peukert** (`T190Settings.energy_remaining_peukert_wh`): pondera cada muestra de consumo por la
  corriente instantánea respecto a una corriente de referencia (`T190Settings.note_effective_energy`).

La potencia objetivo que ve el piloto usa el modelo **Peukert** (`_power_target_w()` en
`firmware/t190/main.py`). Con los valores por defecto (`peukert_n = 1.0`, `peukert_i_ref` automático)
el factor de corrección es siempre 1 — **el modelo Peukert se comporta exactamente igual que el
lineal** hasta que se calibre con datos reales. No hay riesgo de "inventar" una corrección sin
validar: arranca neutro a propósito.

## 1. La fórmula implementada

Para cada muestra de telemetría aceptada (ver `note_effective_energy`, llamada desde el callback
`on_telemetry` en `main.py`):

```
factor      = (|I| / I_ref) ** (n − 1)      # factor = 1 si n = 1, o si |I| = I_ref
Wh_efectivo += P_inst · dt_horas · factor
```

`energia_restante_wh = capacidad_wh − Wh_efectivo` (clamped a ≥0).

- **`n`** (`peukert_n`, default `1.0`, rango válido `1.0–1.5`): exponente de Peukert. A mayor `n`, más
  penaliza una corriente alta por encima de `I_ref`.
- **`I_ref`** (`peukert_i_ref`, default `0.0` = automático): corriente de referencia, en A. Si se deja
  en `0`, se deriva de la capacidad configurada asumiendo pack de 48V nominal (4×12V serie) a régimen
  de 20h: `I_ref = (capacidad_wh / 48.0) / 20.0` — con los 816Wh de fábrica da ≈0.85A.

Esta es la forma estándar de la ecuación de Peukert (`C_efectiva = C_nominal · (I_ref/I)^(n−1)`)
reformulada como un acumulador por muestra en vez de una corrección estática de la capacidad nominal,
para que el peso de cada tramo de la carrera dependa de la corriente real de ese tramo.

Ambos parámetros son configurables desde la página de configuración del T190 (AP `Main-T190`,
sección "Pack de baterías"), junto con la capacidad del pack.

## 2. Cómo recolectar datos para calibrar

Se necesitan **al menos 2 pruebas de descarga a corriente distinta y sostenida**, idealmente bien
separadas (ej. una a corriente baja/crucero, otra a corriente alta/sprint), usando el log a microSD
que ya existe (`sd_logger.py`, se activa solo o manual con `main.log_start()`).

1. Con el pack recién cargado, marcar el inicio desde la página de configuración (`mark_charged`) o
   con el reset local (`BTN0 extra-largo`).
2. Mantener una corriente lo más constante posible durante un tramo conocido (ideal: en banco con
   carga resistiva controlada; alternativa: tramos de ruta a potencia objetivo fija).
3. Repetir a una corriente bien distinta de la anterior.
4. Descargar los CSV desde `http://192.168.4.1/logs` (página de configuración del T190) y quedarse con
   las columnas de corriente (`I`), tensión (`VBATS`) y energía acumulada (`WT`/Wh) de cada prueba.
5. Para cada prueba, calcular la energía realmente entregada hasta que el pack llegó al límite útil
   (o hasta un punto de comparación común, ej. mismo voltaje de corte) y la corriente promedio de ese
   tramo.

## 3. Cómo resolver `n` e `I_ref`

Con dos pruebas a corrientes `I₁` e `I₂` que entregaron energías útiles `Wh₁` y `Wh₂` respectivamente
(antes de llegar al mismo criterio de "batería agotada"):

```
Wh(I) = capacidad_wh · (I_ref / I) ** (n − 1)
```

Tomando logaritmos de la razón `Wh₁/Wh₂`:

```
n = 1 + ln(Wh₁ / Wh₂) / ln(I₂ / I₁)
```

y despejando `I_ref` de cualquiera de las dos ecuaciones originales. Con más de 2 pruebas, conviene un
ajuste por mínimos cuadrados sobre `ln(Wh)` vs. `ln(I)` (es una recta: `ln(Wh) = ln(capacidad·I_ref^(n−1)) − (n−1)·ln(I)`).

Si no se dispone de tiempo/pruebas para esto antes de una carrera, **dejar `peukert_n = 1.0`** — el
modelo lineal ya es una estimación razonable y conservadora, y es preferible a una corrección mal
calibrada que podría dar una potencia objetivo optimista.

## 4. Cómo cargar los valores calibrados

Desde la página de configuración del T190 (`http://192.168.4.1/`, sección "Pack de baterías"):
completar "Exponente Peukert (n)" e "Corriente de referencia Peukert I_ref" y guardar. Verificar con
`main.status()` por REPL (muestra `REM_lin=` y `REM_peuk=` por separado) que ambos modelos coinciden
cuando `n=1.0`, y que se separan de forma razonable al cambiar `n`.

## 5. Checklist de validación end-to-end antes de la carrera

- [ ] Enlace ESP-NOW Super Mini ↔ T190 emparejado y fresco (`main.espnow_status()`).
- [ ] Las 12 pantallas (BTN0 doble para recorrerlas) muestran valores razonables, en particular
      CARRERA (potencia objetivo vs. actual) y ENERGIA (restante lineal vs. Peukert).
- [ ] Reset local (BTN0 extra-largo): Wh, distancia, reloj de carrera y acumulador Peukert vuelven a 0.
- [ ] Reset remoto del Super Mini (combo BTN0 sostenido + S3 corto, repetido dentro de 5s para
      confirmar): `trip.json` del Super Mini queda en 0 tras un power-cycle (no debe "resucitar" el
      acumulado viejo).
- [ ] Reloj de carrera: iniciar, forzar deep sleep manual y despertar — el tiempo transcurrido debe
      seguir siendo coherente; repetir con un reboot completo para confirmar que persiste en
      `t190_settings.json`.
- [ ] Con el reloj de carrera corriendo y velocidad 0, el T190 NO debe entrar en auto-sleep por
      inactividad (sí debe seguir pudiendo dormir manualmente, o si pierde al Super Mini).
- [ ] Combos: sostener un botón mientras se tapea el otro dispara el combo, y el botón sostenido NO
      dispara además su propio gesto largo/extra al soltarlo.
- [ ] Vueltas por GPS: capturar waypoint (S3 corto) con fix real, alejarse y volver a cruzar — el
      contador de vueltas y el último tiempo de vuelta deben actualizarse en la página GPS.
