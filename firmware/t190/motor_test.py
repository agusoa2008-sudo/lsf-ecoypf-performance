# DEPRECATED: prueba de banco del prototipo de acelerador/freno/velocidad.
# No ejecutar con el mapa actual del T190: sus pines y helpers fueron retirados.
# Sin display: imprime por REPL. Util para validar cableado ADC/DAC/pulso
# antes de montar el controlador chino en el vehiculo.
#
# Uso: mpremote run motor_test.py   (o copiar y ejecutar desde el REPL)
# Ctrl-C para detener (corta los DAC a 0V antes de salir).

import time

from motor_control import MotorController, SpeedSensor

mc = MotorController()
speed = SpeedSensor()

print("[motor_test] acelerador/freno -> DAC, Ctrl-C para salir")

try:
    while True:
        thr, brk = mc.update()
        print("thr={:.2f}  brk={:.2f}  speed={:.1f} km/h  pulses={}".format(
            thr, brk, speed.speed_kmh(), speed.pulse_count()))
        time.sleep_ms(200)
except KeyboardInterrupt:
    pass
finally:
    mc.stop()
    print("[motor_test] DAC a 0V, detenido.")
