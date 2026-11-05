"""Start the Paddock access point as a standalone Wi-Fi recovery/test mode."""

import network
import HW


ap = network.WLAN(network.AP_IF)
ap.active(True)
ap.config(essid=HW.AP_SSID, password=HW.AP_PASSWORD, authmode=3)
ap.ifconfig((HW.AP_IP, HW.AP_NETMASK, HW.AP_IP, HW.AP_IP))
print("[wifi] recovery AP {} ready at {}".format(HW.AP_SSID, HW.AP_IP))
