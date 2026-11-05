import uos
import machine

print("Saving main.py -> mainBkp.py (Disabling Main)...")
try:
    uos.stat("main.py")
    try:
        uos.remove("mainBkp.py")
    except OSError:
        pass
    uos.rename("main.py", "mainBkp.py")
    print("Done. Rebooting...")
    machine.reset()
except OSError:
    print("Error: 'main.py' not found.")
