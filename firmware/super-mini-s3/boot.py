
# boot.py — ESP32 
import network as network, machine

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
    network.hostname('S3SuperMini-{}'.format(suffix))
