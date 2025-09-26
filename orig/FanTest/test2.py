from gpiozero import PWMOutputDevice
from gpiozero import OutputDevice
import time

fan_pwm = PWMOutputDevice(pin=18)
#fan = OutputDevice(pin=1)

#fan.off()
fan_pwm.value = 0

time.sleep(3)

#fan.on()
#fan_pwm.value = 1.0

#time.sleep(3)

#fan.off()
#fan_pwm.value = 0

#time.sleep(3)

speed = 1
while speed < 1:
	fan_pwm.value = speed
	speed += 0.1
	time.sleep(1)

#speed = 0.743
#fan_pwm.value = speed

#time.sleep(3)

#speed = 0.928
#fan_pwm.value = speed

time.sleep(3)

fan_pwm.value = 1

time.sleep(10)

