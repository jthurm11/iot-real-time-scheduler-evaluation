import RPi.GPIO as GPIO
import time

GPIO.setwarnings(False)
GPIO.setmode(GPIO.BCM)
TRIG_PIN = 23
ECHO_PIN = 24

GPIO.setup(TRIG_PIN, GPIO.OUT)
GPIO.setup(ECHO_PIN, GPIO.IN)

time.sleep(2)

def distance():
	GPIO.output(TRIG_PIN, GPIO.LOW)
	time.sleep(0.000002)
	GPIO.output(TRIG_PIN, GPIO.HIGH)
	time.sleep(0.00001)
	GPIO.output(TRIG_PIN, GPIO.LOW)

	pulse_start = time.time()
	pulse_end = time.time()

	while GPIO.input(ECHO_PIN) == 0:
		pulse_start = time.time()
	while GPIO.input(ECHO_PIN) == 1:
		pulse_end = time.time()

	pulse_len = pulse_end - pulse_start
	dist = (pulse_len * 17150)

	return dist

while True:
	d = distance()
	print(f"distance: {d} cm")
	time.sleep(1)
