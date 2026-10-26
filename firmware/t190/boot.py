
# boot.py — Heltec Vision Master T190
# Arranca la placa: display ON, REPL disponible.
import network as network
import machine

try:
    import startup_cleanup
    startup_cleanup.run()
except ImportError:
    pass

try:
    import startup_fallback
    startup_fallback.run()
except ImportError:
    pass


if hasattr(network, 'hostname'):
    import machine
    try:
        uid = machine.unique_id()
        suffix = '{:02X}{:02X}'.format(uid[-2], uid[-1])
    except Exception:
        suffix = '0000'
    network.hostname('T190-{}'.format(suffix))
