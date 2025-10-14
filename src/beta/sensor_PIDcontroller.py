import socket
import time
import random
import RPi.GPIO as GPIO


# Configuration
HOST = ''       # Listen on all available interfaces
PORT = 5000     # Must match controller port
SAMPLE_TIME = 0.1  # seconds (100 ms)

# GPIO Setup
GPIO.setwarnings(False)
GPIO.setmode(GPIO.BCM)
TRIG_PIN = 23
ECHO_PIN = 24

GPIO.setup(TRIG_PIN, GPIO.OUT)
GPIO.setup(ECHO_PIN, GPIO.IN)

time.sleep(2)

def read_distance():
    GPIO.output(TRIG_PIN, GPIO.LOW)
    time.sleep(0.000002)
    GPIO.output(TRIG_PIN, GPIO.HIGH)
    time.sleep(0.00001)
    GPIO.output(TRIG_PIN, GPIO.LOW)

    pulse_start = time.time()
    pulse_end = time.time()

    timeout = time.time() + 0.04  # 40 ms max waiting for echo to start
    while GPIO.input(ECHO_PIN) == 0 and time.time() < timeout:
        pulse_start = time.time()

    timeout = time.time() + 0.04  # 40 ms max waiting for echo to end
    while GPIO.input(ECHO_PIN) == 1 and time.time() < timeout:
        pulse_end = time.time()

    pulse_len = pulse_end - pulse_start
    dist = pulse_len * 17150  # distance in cm

    # Filter out invalid ranges
    if dist < 2 or dist > 400:
        return None
    return round(dist, 2)


# Start Server
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.bind((HOST, PORT))
s.listen(1)
print(f"[Sensor] Waiting for fan controller to connect on port {PORT}...")

conn, addr = s.accept()
print(f"[Sensor] Connected to fan controller at {addr}")


# Main loop
try:
    while True:
        distance = read_distance()

        # If the sensor failed, skip this iteration
        if distance is None:
            continue

        print(f"[Sensor] Sent {distance:.2f} cm")
        time.sleep(SAMPLE_TIME)

except KeyboardInterrupt:
    print("\n[Sensor] Stopped by user")

finally:
    conn.close()
    s.close()
    GPIO.cleanup()