
# boot.py — ESP32 IdeaSpark wheel display
# Arranca la placa: REPL disponible.
import network

if hasattr(network, 'hostname'):
    import machine
    try:
        uid = machine.unique_id()
        suffix = '{:02X}{:02X}'.format(uid[-2], uid[-1])
    except Exception:
        suffix = '0000'
    network.hostname('WheelDisp-{}'.format(suffix))
