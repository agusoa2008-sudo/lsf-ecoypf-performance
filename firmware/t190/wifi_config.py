"""Wi-Fi credential configuration for the power meter project.

This module lists the candidate Wi-Fi networks that the device should cycle
through when attempting to connect. Update the ``NETWORKS`` list to match the
SSIDs and passwords available in the deployment environment.
"""

NETWORKS = [
    {
        "ssid": "YOUR_SSID_HERE",
        "password": "YOUR_PASSWORD_HERE",
        "ip": "192.168.0.25",
        "hostname": "ESP-PowerMeter"
   },
    {
        "ssid": "wificonnect",
        "password": "lasalle2026",
    },
    # Example of an additional fallback network entry:
    # {
    #     "ssid": "backup_ssid",
    #     "password": "backup_password",
    # },
]
