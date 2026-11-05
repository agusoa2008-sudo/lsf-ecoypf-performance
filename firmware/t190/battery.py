"""Estimacion de carga para una bateria Li-ion 1S a partir de su tension."""

_VOLTAGE_SOC = (
    (3.30, 0),
    (3.50, 5),
    (3.60, 10),
    (3.65, 15),
    (3.70, 20),
    (3.74, 30),
    (3.77, 40),
    (3.80, 50),
    (3.84, 60),
    (3.88, 70),
    (3.95, 80),
    (4.05, 90),
    (4.20, 100),
)


def percent_from_voltage(voltage):
    """Devuelve un SOC aproximado; la tension bajo carga no es un medidor exacto."""
    voltage = float(voltage)
    if voltage <= _VOLTAGE_SOC[0][0]:
        return 0
    if voltage >= _VOLTAGE_SOC[-1][0]:
        return 100
    for index in range(1, len(_VOLTAGE_SOC)):
        upper_voltage, upper_percent = _VOLTAGE_SOC[index]
        lower_voltage, lower_percent = _VOLTAGE_SOC[index - 1]
        if voltage <= upper_voltage:
            ratio = (voltage - lower_voltage) / (upper_voltage - lower_voltage)
            return int(lower_percent + ratio * (upper_percent - lower_percent) + 0.5)
    raise ValueError("tension de bateria fuera de rango")
