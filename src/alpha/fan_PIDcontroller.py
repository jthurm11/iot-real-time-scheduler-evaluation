#!/usr/bin/env python3
import RPi.GPIO as GPIO
import socket
import select
import time

# CONFIGURATION
PWM_PIN = 18           # GPIO18 (Physical Pin 12)

# JT: Changed to 10k, as nothing above seemed to work.
PWM_FREQ = 10000       # 25 kHz for 4-pin PWM fans

UDP_IP = "0.0.0.0"     # Listen on all interfaces
UDP_PORT = 5005
TIMEOUT = 0.01         # select() timeout
BUFFER_SIZE = 1024

# SETUP GPIO + PWM
GPIO.setmode(GPIO.BCM)
GPIO.setup(PWM_PIN, GPIO.OUT)
pwm = GPIO.PWM(PWM_PIN, PWM_FREQ)
pwm.start(0)

print(f"[Fan] PWM ready on GPIO{PWM_PIN} ({PWM_FREQ} Hz)")
print(f"[Fan] Listening for UDP control on port {UDP_PORT}")


# UDP SOCKET SETUP
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.bind((UDP_IP, UDP_PORT))
sock.setblocking(0)


# MAIN LOOP
current_duty = -1
try:
    while True:
        ready = select.select([sock], [], [], TIMEOUT)
        if ready[0]:
            try:
                data, addr = sock.recvfrom(BUFFER_SIZE)
                duty = float(data.decode().strip())
                duty = max(0, min(100, duty))  # clamp

                if duty != current_duty:
                    pwm.ChangeDutyCycle(duty)
                    current_duty = duty
                    print(f"[Fan] Duty = {duty:5.1f}% from {addr[0]}")

            except ValueError:
                print("[Fan] Invalid data received.")
            except Exception as e:
                print(f"[Fan] Error: {e}")
        else:
            pass  # no packet; maintain last duty
except KeyboardInterrupt:
    print("\n[Fan] Stopped manually.")
finally:
    pwm.stop()
    GPIO.cleanup()
    sock.close()
    print("[Fan] Clean exit.")