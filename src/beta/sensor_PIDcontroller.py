#!/usr/bin/env python3
from gpiozero.pins.pigpio import PiGPIOFactory
from gpiozero import DistanceSensor
from pid_controller import PID
import socket, time, matplotlib.pyplot as plt


# CONFIGURATION
FAN_IP = "192.168.50.139"   # IP of the fan Pi
FAN_PORT = 5005
SETPOINT = 20.0              # Desired height (cm)
SAMPLE_TIME = 0.1            # Control interval (s)

# PID tuning parameters — adjust as needed
# JT: Set controller_direction='REVERSE' for the ball-on-top setup ***
pid = PID(
    Kp=0.05, 
    Ki=0.05, 
    Kd=0.002, 
    setpoint=SETPOINT, 
    sample_time=SAMPLE_TIME, 
    output_limits=(0, 100),
    controller_direction='REVERSE'
)

# SENSOR SETUP (pigpio)
DistanceSensor.pin_factory = PiGPIOFactory()
sensor = DistanceSensor(echo=24, trigger=23, max_distance=5)


# UDP SETUP
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
print(f"[Sensor] PID control started. Sending to {FAN_IP}:{FAN_PORT}")


# LOGGING SETUP
t_log, h_log, sp_log, out_log, err_log = [], [], [], [], []
start = time.time()


# MAIN CONTROL LOOP
try:
    while True:
        # Measure current distance (m → cm)
        distance_cm = sensor.distance * 100.0

        # Compute new control output from PID
        output = pid.compute(distance_cm)

        # Send duty cycle command to fan Pi
        sock.sendto(f"{output:.2f}".encode(), (FAN_IP, FAN_PORT))

        # Log data
        now = time.time() - start
        error = pid.setpoint - distance_cm
        t_log.append(now)
        h_log.append(distance_cm)
        sp_log.append(pid.setpoint)
        out_log.append(output)
        err_log.append(error)

        # Print live status
        print(f"[Sensor] t={now:5.2f}s | h={distance_cm:5.2f} cm | out={output:6.2f}% | err={error:6.2f}")

        # Wait for next sample
        time.sleep(SAMPLE_TIME)

except KeyboardInterrupt:
    print("\n[Sensor] Experiment ended manually.")
finally:
    sock.close()
    print("[Sensor] Cleaning up and plotting results...")


    # PLOTTING
    plt.figure(figsize=(10, 8))

    # Height vs Setpoint
    plt.subplot(3, 1, 1)
    plt.plot(t_log, h_log, label="Measured Height h(t)", color='blue')
    plt.plot(t_log, sp_log, '--', label="Setpoint hSP(t)", color='red')
    plt.ylabel("Height (cm)")
    plt.legend(loc='upper right')

    # PID Output (Fan %)
    plt.subplot(3, 1, 2)
    plt.plot(t_log, out_log, label="Fan Output (PID %)", color='green')
    plt.ylabel("PWM Output (%)")
    plt.legend(loc='upper right')

    # Error vs Time
    plt.subplot(3, 1, 3)
    plt.plot(t_log, err_log, label="Error e(t) = hSP - h", color='purple')
    plt.xlabel("Time (s)")
    plt.ylabel("Error (cm)")
    plt.legend(loc='upper right')

    plt.suptitle("Distributed Ping-Pong Ball PID Response (Sensor → Fan over UDP)", fontsize=14)
    plt.tight_layout()
    plt.show()