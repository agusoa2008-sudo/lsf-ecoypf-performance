# status_led.py
# Indicador de estado por color + parpadeo sobre el NeoPixel onboard
# (GPIO48) del Super Mini -- unica señal visual del equipo sin display
# propio.
#
# No sabe nada de ADS1220/ADS1115/ESP-NOW en particular: solo recibe flags
# de salud (bool) y un flag de conexion, y decide color + patron. Brillo
# bajo a proposito (valores ~0-40) para no encandilar ni consumir de mas.
#
# Separa "cual es el estado" (update_health / set_espnow_connected, los
# llama sensor_task cada vez que lee) de "como se ve en el tiempo" (tick,
# lo llama una tarea aparte a ritmo fijo -- ver main.py: led_task). Asi el
# parpadeo no depende de cada cuanto se leen los sensores.
#
# Patron:
#   - rojo parpadeando  = algun sensor en falla (update_health con 0 OK)
#   - amarillo parpadeando = falla parcial (update_health con OK mixto)
#   - verde parpadeando = todo OK
#   - verde/azul alternando = todo OK + ESP-NOW conectado

_COLOR_BOOT    = (0, 0, 40)    # azul tenue -- arrancando / calibrando
_COLOR_OK      = (0, 40, 0)    # verde -- todos los subsistemas OK
_COLOR_PARTIAL = (40, 30, 0)   # amarillo -- falta alguno
_COLOR_FAIL    = (40, 0, 0)    # rojo -- ninguno OK / error critico
_COLOR_ESPNOW  = (0, 0, 40)    # azul -- se alterna con verde si hay link
_COLOR_OFF     = (0, 0, 0)


class StatusLed:
    def __init__(self, neopixel):
        self._np = neopixel
        self._ok = None            # None=booteando, True, False, "partial"
        self._espnow_connected = False
        self._on = False
        self.set_boot()

    def _set(self, color):
        self._np[0] = color
        self._np.write()

    def set_boot(self):
        self._ok = None
        self._set(_COLOR_BOOT)

    def off(self):
        """Apaga el LED -- llamar antes de machine.deepsleep() (ver
        main.py: _enter_deep_sleep). El NeoPixel retiene el ultimo color
        escrito aunque el CPU se duerma, asi que si no se apaga a mano
        queda prendido (drenando corriente) durante todo el sleep."""
        self._ok = None
        self._on = False
        self._set(_COLOR_OFF)

    def update_health(self, *health_flags):
        """health_flags: un bool por subsistema (ej. adc_ok, current_ok).
        Solo actualiza el estado interno -- tick() es el que pinta."""
        if not health_flags:
            self._ok = None
            return
        n_ok = sum(1 for f in health_flags if f)
        if n_ok == len(health_flags):
            self._ok = True
        elif n_ok == 0:
            self._ok = False
        else:
            self._ok = "partial"

    def set_espnow_connected(self, connected):
        """Llamar desde la tarea de ESP-NOW cuando cambie el estado del
        link (todavia no implementada -- queda listo para cuando este)."""
        self._espnow_connected = connected

    def tick(self):
        """Llamar periodicamente (ver main.py: led_task, cada ~300ms) --
        alterna el LED segun el ultimo estado cargado por update_health()/
        set_espnow_connected()."""
        self._on = not self._on
        if self._ok is None:
            self._set(_COLOR_BOOT if self._on else _COLOR_OFF)
        elif self._ok is False:
            self._set(_COLOR_FAIL if self._on else _COLOR_OFF)
        elif self._ok == "partial":
            self._set(_COLOR_PARTIAL if self._on else _COLOR_OFF)
        elif self._espnow_connected:
            self._set(_COLOR_OK if self._on else _COLOR_ESPNOW)
        else:
            self._set(_COLOR_OK if self._on else _COLOR_OFF)
