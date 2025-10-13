from gpiozero.pins.pigpio import PiGPIOFactory
from gpiozero import DistanceSensor
from time import sleep

# Force all DistanceSensors to use the pigpio library to interface to 
# the GPIO pins. This relies on the daemon to be running (sudo pigpiod).
# Optionally, specify a HOST and PORT to connect remotely to. 
#
# To set the factory per device, use the 'pin_factory=' keyword parameter:
#    factory = PiGPIOFactory(host='IP ADDR', port='NUMBER')
#    sensor = DistanceSensor(pin_factory=factory)
DistanceSensor.pin_factory = PiGPIOFactory()

# TRIG is connected to GPIO23
# ECHO is connected to GPIO24
# max_distance (meters) defaults to 1.
# threshold_distance (meters) defaults to 0.3.
sensor = DistanceSensor(echo=24, trigger=23, max_distance=5)

# Run a funcion when something gets near the sensor.
# This is triggered by the 'threshold_distance' parameter.
#sensor.when_in_range = do_something
#sensor.when_out_of_range = do_something_else

while True:
    print('Distance in centimeters: ', sensor.distance * 100)
    sleep(1)
