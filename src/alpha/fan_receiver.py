import pigpio
import time
import socket

PWM_PIN = 18            # blue wire from fan
FREQ = 25000            # 25 kHz typical for 4-wire fans

pi = pigpio.pi()
pi.set_mode(PWM_PIN, pigpio.OUTPUT)
pi.set_PWM_frequency(PWM_PIN, FREQ)


# ---- UDP Receiver Setup ----
UDP_IP = "0.0.0.0"
UDP_PORT = 5005

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.bind((UDP_IP, UDP_PORT))

print(f"[Fan] Listening for raw dutycycle on UDP port {UDP_PORT}...")

try:
    while True:
        data, addr = sock.recvfrom(1024)
        duty = int(data.decode().strip())   # EXPECT sensor to send 0–255
        duty = max(0, min(255, duty))       # clamp to safe range
        pi.set_PWM_dutycycle(PWM_PIN, duty)
        print(f"[Fan] duty={duty}")

except KeyboardInterrupt:
    print("\n[Fan] Stopping...")
    pi.set_PWM_dutycycle(PWM_PIN, 0)
    pi.stop()
    sock.close()





