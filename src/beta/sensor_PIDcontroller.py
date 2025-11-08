#!/usr/bin/env python3
import RPi.GPIO as GPIO
import time, socket
from pid_controller import PID
import csv, os
from datetime import datetime
#import matplotlib.pyplot as plt
#from collections import deque

# ---- FAN NETWORK ----
FAN_IP = "192.168.22.1"
FAN_PORT = 5005
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

# ---- SENSOR SETUP ----
GPIO.setwarnings(False)
GPIO.setmode(GPIO.BCM)
TRIG_PIN = 23
ECHO_PIN = 24
GPIO.setup(TRIG_PIN, GPIO.OUT)
GPIO.setup(ECHO_PIN, GPIO.IN)
time.sleep(2)

def get_distance_cm():
    GPIO.output(TRIG_PIN, GPIO.LOW)
    time.sleep(0.000002)
    GPIO.output(TRIG_PIN, GPIO.HIGH)
    time.sleep(0.00001)
    GPIO.output(TRIG_PIN, GPIO.LOW)

    while GPIO.input(ECHO_PIN) == 0:
        pulse_start = time.time()
    while GPIO.input(ECHO_PIN) == 1:
        pulse_end = time.time()

    pulse_len = pulse_end - pulse_start
    return pulse_len * 17150.0   # cm

# ---- PID CONFIG ----
SETPOINT = 20.0   # cm target height
pid = PID(
    Kp=300,
    Ki=0,
    Kd=0.6,
    setpoint=SETPOINT,
    sample_time=0.05,
    output_limits=(0, 255),        # RAW DUTY 0–255 to fan
    controller_direction='REVERSE' # ball-on-air needs REVERSE gain direction
)

print("[Sensor] PID control running...")

# ---- LOGGING SETUP ----
os.makedirs("logs", exist_ok=True)
timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
log_filename = f"logs/control_log_{timestamp}.csv"

log_file = open(log_filename, "w", newline="")
log_writer = csv.writer(log_file)
log_writer.writerow(["time_s", "height_cm", "setpoint_cm", "duty", "error_cm"])

start_time = time.time()

try:
    while True:
        height = get_distance_cm()
        output = pid.compute(height)

        duty = int(max(0, min(255, output)))
        sock.sendto(str(duty).encode(), (FAN_IP, FAN_PORT))

        current_time = time.time() - start_time
        error = pid.setpoint - height

        # LOG DATA
        log_writer.writerow([current_time, height, pid.setpoint, duty, error])

        print(f"h={height:6.2f} cm | duty={duty:3d} | err={error:6.2f}")
        time.sleep(0.05)

except KeyboardInterrupt:
    print("\n[Sensor] Stopping...")
    log_file.close()       # <---- important
    sock.close()
    GPIO.cleanup()
