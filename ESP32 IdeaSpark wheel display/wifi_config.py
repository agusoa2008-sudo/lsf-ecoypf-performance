"""Wi-Fi credential configuration for the power meter project.

This module lists the candidate Wi-Fi networks that the device should cycle
through when attempting to connect. Update the ``NETWORKS`` list to match the
SSIDs and passwords available in the deployment environment.
"""

NETWORKS = [
    {
        "ssid": "Telecentro-FJS",
        "password": "frayjusto1960",
        "ip": "192.168.0.26",
        "hostname": "ESP-S3XIAO"
   },
    # Example of an additional fallback network entry:
    # {
    #     "ssid": "backup_ssid",
    #     "password": "backup_password",
    # },
]
