#!/usr/bin/env python3
from gpiozero.pins.pigpio import PiGPIOFactory
from gpiozero import DistanceSensor
from pid_controller import PID
import socket, time, matplotlib.pyplot as plt
import numpy as np # Added for plotting utility

# Import necessary components from the network_injector module
from network_injector import CONGESTION_DELAY, PACKET_LOSS_RATE, inject_delay_and_check_loss, get_current_status

# CONFIGURATION
FAN_IP = "192.168.22.1"      # IP of the fan Pi
FAN_PORT = 5005              # Must match opened port on neighbor node!
SETPOINT = 20.0              # Desired height (cm)
SAMPLE_TIME = 0.1            # Control interval (s)

# PID tuning parameters — **ADJUSTED FOR FASTER RAMP UP**
# Kp increased 5x (0.05 -> 0.25) and Ki increased 3x (0.05 -> 0.15) to force a faster response.
pid = PID(
    Kp=0.25,
    Ki=0.15,
    Kd=0.005, # Kd slightly increased to help dampen overshoot
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

# Capture static status variables for continuous logging
status = get_current_status()
delay_s = status['delay_s']
loss_perc = status['loss_rate_perc']
print(f"[Sensor] Congestion Settings: Delay={delay_s}s | Loss={loss_perc}%")

# LOGGING SETUP
t_log, h_log, sp_log, out_log, err_log, delay_log = [], [], [], [], [], []
# Logs for the exact time/value when a packet was dropped
dropped_points_t, dropped_points_y = [], []

start = time.time()


# MAIN CONTROL LOOP
try:
    while True:
        # Measure current distance (m → cm)
        distance_cm = sensor.distance * 100.0

        # Compute new control output from PID
        output = pid.compute(distance_cm)

        # --- CONGESTION INJECTION ---
        # CORRECTED: Call the function from the provided network_injector.py
        should_send = inject_delay_and_check_loss() 

        if should_send:
            # Send duty cycle command to fan Pi
            sock.sendto(f"{output:.2f}".encode(), (FAN_IP, FAN_PORT))
            send_status = "SENT"
        else:
            # Packet was dropped due to simulated congestion
            send_status = "DROPPED"
            # Log the dropped packet for plotting
            dropped_points_t.append(time.time() - start)
            dropped_points_y.append(output)

        # Log data
        now = time.time() - start
        error = pid.setpoint - distance_cm
        t_log.append(now)
        h_log.append(distance_cm)
        sp_log.append(pid.setpoint)
        out_log.append(output)
        err_log.append(error)
        delay_log.append(delay_s) # Log the currently active delay (from status check)

        # Print live status
        print(f"[Sensor] t={now:5.2f}s | h={distance_cm:5.2f} cm | out={output:6.2f}% | err={error:6.2f} | Status: {send_status}")

        # The time.sleep() call below accounts for the total SAMPLE_TIME, but since 
        # `inject_delay_and_check_loss()` already blocks for `CONGESTION_DELAY`, 
        # the time spent inside that function is automatically handled.
        time_elapsed_in_loop = time.time() - start - now
        time.sleep(max(0, SAMPLE_TIME - (time.time() - start + now)))


except KeyboardInterrupt:
    print("\n[Sensor] Experiment ended manually.")
finally:
    sock.close()
    print("[Sensor] Cleaning up and plotting results...")


    # PLOTTING
    plt.figure(figsize=(12, 10))
    plt.suptitle("Distributed Ping-Pong Ball PID Response", fontsize=14)


    # Height vs Setpoint
    plt.subplot(4, 1, 1)
    plt.plot(t_log, h_log, label="Measured Height h(t)", color='blue')
    plt.plot(t_log, sp_log, '--', label="Setpoint hSP(t)", color='red')
    plt.ylabel("Height (cm)")
    plt.legend(loc='upper right')
    plt.grid(True)
    plt.title("Ball Height (cm)")

    # PID Output (Fan %)
    plt.subplot(4, 1, 2)
    plt.plot(t_log, out_log, label="Fan Output (PID %)", color='green')
    # Plot dropped points directly on the output graph
    if dropped_points_t:
        plt.scatter(dropped_points_t, dropped_points_y, marker='x', color='red', s=50, label="Packet Dropped", zorder=5)
    plt.ylabel("PWM Output (%)")
    plt.legend(loc='upper right')
    plt.grid(True)
    plt.title("Control Effort / Fan Output (%)")

    # Congestion Delay
    plt.subplot(4, 1, 3)
    # Using 'step' to show the instantaneous change in delay
    plt.step(t_log, delay_log, label="Congestion Delay (s)", color='#FFA500') # Orange
    plt.ylabel("Delay (s)")
    plt.legend(loc='upper right')
    plt.grid(True)
    plt.title("Injected Network Latency (Delay)")

    # Error vs Time
    plt.subplot(4, 1, 4)
    plt.plot(t_log, err_log, label="Error e(t) = hSP - h", color='purple')
    plt.xlabel("Time (s)")
    plt.ylabel("Error (cm)")
    plt.legend(loc='upper right')
    plt.grid(True)
    plt.title("Control Error (Setpoint - Measured)")

    plt.tight_layout(rect=[0, 0.03, 1, 0.97]) # Adjust for suptitle
    plt.show()
