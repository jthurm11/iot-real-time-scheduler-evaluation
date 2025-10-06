from gpiozero.pins.pigpio import PiGPIOFactory
from gpiozero import PWMOutputDevice
from time import sleep

factory = PiGPIOFactory()

# Wiring: 
# 1. FAN GROUND (Black/Blue) to Pi GROUND (i.e., GPIO6).
# 2. FAN VCC (Red) to Pi 5V PIN (i.e., GPIO2).
# 3. FAN TACHOMETER (Yellow) is unused by this script.
# 4. FAN PWM CONTROL (White/Green/Blue) to GPIO18.
fan = PWMOutputDevice(pin=18, frequency=2500, pin_factory=factory)

print ('Pulsing fan for 15 seconds...')
fan.pulse(fade_in_time=3, fade_out_time=3, n=2)
sleep(15)

print ('Toggle fan...')
fan.toggle() 
sleep(1)

print ('Fan off...')
fan.off()