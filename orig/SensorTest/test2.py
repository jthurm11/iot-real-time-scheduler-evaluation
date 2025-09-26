import RPi.GPIO as GPIO
import time

try:
    #GPIO.setmode(GPIO.BOARD)
    GPIO.setmode(GPIO.BCM)
    GPIO.setwarnings(False)

    PIN_TRIGGER = 0
    PIN_ECHO = 2

    GPIO.setup(PIN_TRIGGER, GPIO.OUT)
    GPIO.setup(PIN_ECHO, GPIO.IN)

    GPIO.output(PIN_TRIGGER, GPIO.LOW)
    time.sleep(2)

    print("Distance")
    GPIO.output(PIN_TRIGGER, GPIO.HIGH)
    time.sleep(0.00001)
    GPIO.output(PIN_TRIGGER, GPIO.LOW)

    print("test1")

    while GPIO.input(PIN_ECHO)==0:
        pulse_start_time = time.time()

    print("test2")

    while GPIO.input(PIN_ECHO)==1:
        pulse_end_time = time.time()

    print("test3")

    pulse_duration = pulse_end_time - pulse_start_time
    distance = round(pulse_duration * 17150, 2)
    print("Distance:", distance, "cm")

finally:
    GPIO.cleanup()
