import uos
import machine

print("Restoring mainBkp.py -> main.py (Enabling Main)...")
try:
    uos.stat("mainBkp.py")
    try:
        uos.remove("main.py")
    except OSError:
        pass
    uos.rename("mainBkp.py", "main.py")
    print("Done. Rebooting...")
    machine.reset()
except OSError:
    print("Error: 'mainBkp.py' not found.")
