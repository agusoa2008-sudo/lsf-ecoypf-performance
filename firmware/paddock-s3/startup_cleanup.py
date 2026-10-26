"""Startup helper that removes main.py when button 0 is held low."""

try:
    import machine
except ImportError:
    machine = None

try:
    import uos
except ImportError:
    uos = None


def run():
    """Delete main.py if the XIAO boot selector button reads low."""
    if machine is None or uos is None or not hasattr(machine, "Pin"):
        return
    try:
        button = machine.Pin(0, machine.Pin.IN, machine.Pin.PULL_UP)
    except (TypeError, ValueError):
        button = machine.Pin(0, machine.Pin.IN)
    try:
        pressed = button.value() == 0
    except AttributeError:
        pressed = False
    if not pressed:
        return
    try:
        uos.remove("main.py")
        print("[startup] GPIO0 held: main.py removed; REPL recovery mode")
    except OSError as exc:
        print("[startup] main.py could not be removed:", exc)
