import socket, time, matplotlib.pyplot as plt
from pid_controller import PID
import RPi.GPIO as GPIO


# Setup
FAN_PIN = 18
GPIO.setmode(GPIO.BCM)
GPIO.setup(FAN_PIN, GPIO.OUT)
pwm = GPIO.PWM(FAN_PIN, 1000)
pwm.start(0)

# Connect with sensor pi
HOST = '192.168.50.234'   # Sensor Pi IP
PORT = 5000
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.connect((HOST, PORT))
s_file = s.makefile('r')

# initialize PID values
pid = PID(Kp=0.05, Ki=0.05, Kd=0.002, setpoint=20.0, sample_time=0.1, output_limits=(0, 100))

# Create data logs
time_log, height_log, setpoint_log, out_log, err_log = [], [], [], [], []
start = time.time()

print("Connected. Running control loop...")



# Main loop
for i in range(300):  # Run for about 30 seconds (300 * 0.1s)
    line = s_file.readline().strip()    # Receive data from sensor Pi
    if not line:
        continue

    try:
        height = float(line)            # Parse height value
        output = pid.compute(height)    # Run PID control
        pwm.ChangeDutyCycle(output)     # Send output to fan
    except ValueError:
        continue

    # Record values
    now = time.time() - start
    error = pid.setpoint - height
    time_log.append(now)
    height_log.append(height)
    setpoint_log.append(pid.setpoint)
    out_log.append(output)
    err_log.append(error)

    print(f"{now:5.2f}s | h={height:5.2f} | out={output:6.2f} | err={error:6.2f}")
    time.sleep(pid.sample_time)



# Cleanup & plotting
pwm.stop()
GPIO.cleanup()
s.close()

plt.figure(figsize=(10, 8))

# --- Figure 1: Height vs Time ---
plt.subplot(3, 1, 1)
plt.plot(time_log, height_log, label="Measured height h(t)", color='blue')
plt.plot(time_log, setpoint_log, '--', label="Setpoint hSP(t)", color='red')
plt.ylabel("Height (cm)")
plt.legend(loc='upper right')

# --- Figure 2: Output (fan voltage/PWM) ---
plt.subplot(3, 1, 2)
plt.plot(time_log, out_log, label="Fan Output V(t)", color='green')
plt.ylabel("Output (PWM %)")
plt.legend(loc='upper right')

# --- Figure 3: Error vs Time ---
plt.subplot(3, 1, 3)
plt.plot(time_log, err_log, label="Error e(t) = hSP - h", color='purple')
plt.xlabel("Time (s)")
plt.ylabel("Error (cm)")
plt.legend(loc='upper right')

plt.suptitle("PingPongPID Response Data (Python Implementation)", fontsize=14)
plt.tight_layout()
plt.show()