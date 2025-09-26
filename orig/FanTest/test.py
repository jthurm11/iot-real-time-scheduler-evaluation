import RPi.GPIO as GPIO
import time
import os

# Define GPIO pin for PWM output (e.g., 18)
pwm_pin = 18

# Set up GPIO
GPIO.setmode(GPIO.BCM)
GPIO.setup(pwm_pin, GPIO.OUT)

# Create PWM object
pwm = GPIO.PWM(pwm_pin, 1000)  # 1000 Hz frequency

# Function to set fan speed (0-100)
def set_fan_speed(duty_cycle):
    pwm.start(duty_cycle)

try:
    # Example usage:
    set_fan_speed(25)  # 25% speed
    time.sleep(2)
    set_fan_speed(75)  # 75% speed
    time.sleep(2)
    set_fan_speed(100) # Full speed
    time.sleep(2)
    set_fan_speed(0)   # Fan off

except KeyboardInterrupt:
    pass

finally:
    pwm.stop()
    GPIO.cleanup()
