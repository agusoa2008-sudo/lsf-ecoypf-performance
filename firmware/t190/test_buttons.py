# test_buttons.py -- prueba de banco de los dos botones del T190
#
# S3    = GPIO21 (HW.PAGE_BTN_PIN)
# BTN0  = GPIO0  (HW.BTN0_PIN, boton BOOT/PRG)
#
# Imprime por REPL cada gesto detectado (short/double/long/extra) para los
# dos botones a la vez. Sin display: util para calibrar los tiempos de
# PAGE_DEFAULTS (SHORT_MS/DOUBLE_MS/LONG_MS/EXTRA_MS en buttons.py) antes de
# confiar en los gestos desde main.py.
#
# Uso: mpremote run test_buttons.py   (o copiar y ejecutar desde el REPL)
# Ctrl-C para detener.

import uasyncio as asyncio
from machine import Pin

import HW
from buttons import InterruptPageButton

_counts = {"S3": {}, "BTN0": {}}


def _make_logger(label):
    def _log(kind):
        _counts[label][kind] = _counts[label].get(kind, 0) + 1
        print("[{}] {} (total {}={})".format(
            label, kind, kind, _counts[label][kind]))
    return _log


def _handlers(label):
    log = _make_logger(label)
    return {
        "short": lambda: log("short"),
        "double": lambda: log("double"),
        "long": lambda: log("long"),
        "extra": lambda: log("extra"),
    }


s3_h = _handlers("S3")
btn0_h = _handlers("BTN0")
s3_btn = InterruptPageButton(
    Pin(HW.PAGE_BTN_PIN, Pin.IN, Pin.PULL_UP),
    short=s3_h["short"], double=s3_h["double"],
    long=s3_h["long"], extra=s3_h["extra"], label="S3",
    irq_trigger=Pin.IRQ_FALLING | Pin.IRQ_RISING, debounce_ms=25,
)
btn0_btn = InterruptPageButton(
    Pin(HW.BTN0_PIN, Pin.IN, Pin.PULL_UP),
    short=btn0_h["short"], double=btn0_h["double"],
    long=btn0_h["long"], extra=btn0_h["extra"], label="BTN0",
    irq_trigger=Pin.IRQ_FALLING | Pin.IRQ_RISING, debounce_ms=25,
)

print("[test_buttons] S3=GPIO{} BTN0=GPIO{} IRQ debounce=25ms -- "
      "short<={}ms double window={}ms long>={}ms extra>={}ms".format(
    HW.PAGE_BTN_PIN, HW.BTN0_PIN,
    s3_btn.t["SHORT_MS"], s3_btn.t["DOUBLE_MS"],
    s3_btn.t["LONG_MS"], s3_btn.t["EXTRA_MS"]))
print("[test_buttons] probar: click corto, doble click rapido, mantener "
      "~0.5-1.1s (sin accion), ~1.5s (long), ~2.5s+ (extra), "
      "en cada boton. Ctrl-C para salir.")


async def _main():
    tasks = [
        asyncio.create_task(s3_btn.task()),
        asyncio.create_task(btn0_btn.task()),
    ]
    try:
        while True:
            await asyncio.sleep_ms(200)
    finally:
        for t in tasks:
            try:
                t.cancel()
            except Exception:
                pass
        s3_btn.close()
        btn0_btn.close()


try:
    asyncio.run(_main())
except KeyboardInterrupt:
    pass
finally:
    print("[test_buttons] detenido. Resumen:", _counts)
