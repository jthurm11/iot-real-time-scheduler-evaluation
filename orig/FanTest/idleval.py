from gpiozero import PWMOutputDevice
import time

fan_pwm = PWMOutputDevice(pin=18)

fan_pwm.value = 0.0

while True:
	temp = float(input("select fan output percent [0.0, 1.0]: "))
	fan_pwm.value = temp
	time.sleep(1)
