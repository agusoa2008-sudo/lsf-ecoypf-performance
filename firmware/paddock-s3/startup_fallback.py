"""Start the Wi-Fi recovery AP when the main application is absent."""

try:
    import uos
except ImportError:
    uos = None


def run():
    """Run wifiConnect as a simple AP-only recovery mode without main.py."""
    if uos is not None:
        try:
            uos.stat("main.py")
            return
        except OSError:
            pass
    try:
        import wifiConnect
    except ImportError:
        print("[startup] main.py absent; wifiConnect fallback unavailable")
