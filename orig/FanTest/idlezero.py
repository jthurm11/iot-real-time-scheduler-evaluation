from gpiozero import PWMOutputDevice
import time

fan_pwm = PWMOutputDevice(pin=18)

fan_pwm.value = 0

while True:
	time.sleep(1)
