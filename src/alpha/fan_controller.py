#!/usr/bin/env python3
# --- HARDWARE WIRING INSTRUCTIONS (ALPHA NODE ONLY) ---
# This script controls a 4-pin PWM fan using GPIO 18.
# 
# 1. FAN GROUND (Black/Blue) to Pi GROUND (GND).
# 2. FAN VCC (Red) to Pi 5V PIN.
# 3. FAN TACHOMETER (Yellow) is unused by this script.
# 4. FAN PWM CONTROL (White/Green/Blue) to GPIO PIN 18 (BCM numbering).
# 
# Raspberry Pi Header Reference:
# BCM 18 (PWM Signal) is Physical Pin 12
# 5V is Physical Pin 2 or 4
# GND is Physical Pin 6 or 9 or 14
# --------------------------------------------------------
import RPi.GPIO as GPIO
import time
import socket
import select
import sys

# --- Configuration ---
PWM_PIN = 18          # GPIO Pin 18 (Pin 12 on the RPi Header)
FAN_PWM_FREQ = 25000  # 25kHz is common for 4-pin PWM fans
UDP_IP = "0.0.0.0"    # Listen on all interfaces
UDP_PORT = 5005       # Control signal port
RECV_BUFFER_SIZE = 1024
TIMEOUT_SECONDS = 0.01 # Short timeout for non-blocking check

def setup_pwm():
    """Initializes GPIO and PWM."""
    try:
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(PWM_PIN, GPIO.OUT)
        
        # Initialize PWM object
        pwm = GPIO.PWM(PWM_PIN, FAN_PWM_FREQ)
        pwm.start(0) # Start with 0% duty cycle (Fan off)
        print(f"PWM initialized on GPIO {PWM_PIN} at {FAN_PWM_FREQ} Hz.")
        return pwm
    except Exception as e:
        print(f"FATAL ERROR: Failed to set up PWM on GPIO {PWM_PIN}. {e}")
        GPIO.cleanup()
        raise

def setup_socket():
    """Binds a UDP socket to receive control commands."""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind((UDP_IP, UDP_PORT))
        sock.setblocking(0)  # Set socket to non-blocking
        print(f"UDP listener set up on {UDP_IP}:{UDP_PORT}.")
        return sock
    except Exception as e:
        print(f"FATAL ERROR: Could not bind socket on port {UDP_PORT}. {e}")
        raise

def parse_data(data):
    """Attempts to parse the received data into a valid duty cycle (0-100)."""
    try:
        # Assuming the data is sent as a clean ASCII string (e.g., "45.0" or "0")
        duty_cycle = float(data.decode().strip())
        
        # Clamp value between 0 and 100
        return max(0, min(100, duty_cycle))
        
    except ValueError:
        print(f"WARNING: Received non-numeric data: {data.decode().strip()}. Ignoring.")
        return None
    except Exception as e:
        print(f"ERROR parsing data: {e}")
        return None

def main(pwm, sock):
    current_duty = -1 # Initialize with impossible value to force first update
    
    while True:
        # Use select to check if data is available without blocking indefinitely
        # This keeps the main loop responsive for clean shutdown and initial setup
        ready = select.select([sock], [], [], TIMEOUT_SECONDS)

        if ready[0]:
            try:
                data, addr = sock.recvfrom(RECV_BUFFER_SIZE)
                desired_duty = parse_data(data)
                
                if desired_duty is not None:
                    if desired_duty != current_duty:
                        # Only update PWM if the duty cycle has changed
                        pwm.ChangeDutyCycle(desired_duty)
                        current_duty = desired_duty
                        if desired_duty > 0:
                            print(f"Fan speed set to {desired_duty}% duty cycle (Received from {addr[0]}).")
                        elif desired_duty == 0:
                            print("Fan turned OFF (0% duty cycle).")
                            
            except BlockingIOError:
                # Should not happen with select, but included for robustness
                pass
            except Exception as e:
                print(f"ERROR during socket receive: {e}")
                
        else:
            # If no new data, the loop continues to check and enforce the last known duty cycle
            # but we don't need to call ChangeDutyCycle unless we lose data and need a safety measure.
            # For now, just allow the loop to repeat.
            pass

# --- Script Execution ---
pwm_controller = None
udp_socket = None
try:
    pwm_controller = setup_pwm()
    udp_socket = setup_socket()
    main(pwm_controller, udp_socket)
except KeyboardInterrupt:
    print("Fan controller script manually terminated.")
except Exception as e:
    print(f"FATAL ERROR: An unexpected error occurred: {e}")
finally:
    if udp_socket:
        udp_socket.close()
    if pwm_controller:
        pwm_controller.stop()
    GPIO.cleanup()
    print("Resources cleaned up. Fan stopped.")