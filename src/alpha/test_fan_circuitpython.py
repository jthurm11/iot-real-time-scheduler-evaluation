# Make sure you have installed the necessary library:
# `sudo pip3 install adafruit-circuitpython-emc2101`
#
# I2C must be enabled (via raspi-config)
# `sudo raspi-config nonint do_i2c 0`
#
# You may also need to install the blinka dependencies first.
# Check here for instructions: 
# https://learn.adafruit.com/circuitpython-on-raspberrypi-linux/installing-circuitpython-on-raspberry-pi
#
# The instructions install blinka to a VENV, which must be re-activated on each boot/login: 
# `cd ~ && source ./env/bin/activate`

import time
import board
import busio
import sys # Added for system exit
import os  # Added for file operations
import socket
import json

try:
    # We must import from emc2101_lut to access advanced PWM configuration methods.
    from adafruit_emc2101.emc2101_lut import EMC2101_LUT as EMC2101 
except ImportError:
    print("Error: The 'adafruit-circuitpython-emc2101' library is not installed.")
    print("Please run: sudo pip3 install adafruit-circuitpython-emc2101")
    sys.exit(1) # Corrected to use sys.exit(1) for consistent error handling

# --- Configuration ---
# The default I2C address for EMC2101 is 0x4C, which is handled by the library.
FAN_SPEEDS = [0, 25, 50, 75, 100] # Duty cycle percentages to test
CYCLE_DELAY = 1.5 # Time (seconds) to hold each speed

# Revision prefixes for Raspberry Pi 4 / Compute Module 4 (BCM2711 based)
# If any of these are detected, the script will exit.
# We're only running this script on Jake's test lab, which has Pi 3 / Pi Zero HW. 
CM4_REVISION_PREFIXES = ["a031", "b031", "c031", "d031"] 


def get_pi_revision():
    """Reads the hardware revision from /proc/cpuinfo."""
    if not os.path.exists('/proc/cpuinfo'):
        return None 
    
    with open('/proc/cpuinfo', 'r') as f:
        for line in f:
            if line.startswith('Revision'):
                # Extracts the revision code (e.g., '0000a020d3')
                return line.split(':')[-1].strip()
    return None

def check_board_type():
    """Checks if the board is an excluded type (CM4) and exits if true."""
    revision = get_pi_revision()
    
    if revision is None:
        # If /proc/cpuinfo is missing (e.g., running on non-Linux or weird setup)
        print("Warning: Could not determine hardware revision. Proceeding with caution.")
        return
        
    # Check against CM4 prefixes (first 4 characters of the revision code)
    if revision[:4] in CM4_REVISION_PREFIXES:
        print("\n--- HARDWARE CHECK FAILED ---")
        print(f"Detected Pi 4/CM4 Architecture (Revision prefix: {revision[:4]}).")
        print("This script is configured to only run on Pi 3B or Pi Zero.")
        print("Exiting script to prevent hardware conflict.")
        print("-----------------------------\n")
        sys.exit(1)
    else:
        # Assumes any non-CM4 architecture is a Pi 3 or Pi Zero (e.g., 9000c1, a02082)
        print(f"Hardware Check OK: Revision {revision} detected. Compatible board found.")

def rpm_sender(fan_rpm):
    """Send RPM value via UDP."""
    telemetry_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    current_rpm = fan_rpm

    # Send a simple JSON payload with the RPM value
    payload = json.dumps({"rpm": current_rpm})
    telemetry_sock.sendto(payload.encode('utf-8'), ('192.168.22.2', '5007'))
    print(f"RPM sent: {current_rpm}")

def main():
    """
    Initializes the EMC2101, sets the PWM frequency for stable fan control, 
    and cycles the fan through various speeds.
    """
    
    # 0. Hardware Check (NEW STEP)
    check_board_type()
    
    # 1. Initialize I2C connection
    try:
        # Uses the default I2C bus (usually bus 1 on Raspberry Pi)
        i2c = busio.I2C(board.SCL, board.SDA) 
        emc = EMC2101(i2c)
        print("--- EMC2101 Fan Controller Initialized ---")
        
    except ValueError as e:
        print(f"I2C Initialization Error: {e}")
        print("Verify I2C is enabled and the sensor is connected correctly.")
        return

    # 2. Set PWM Frequency (Crucial for Fan Stability)
    print("\n--- Configuring Custom PWM Frequency ---")
    
    # Set the PWM clock source (not using a preset)
    emc.set_pwm_clock(use_preset=False) 
    
    # Set the PWM clock division rate (0-31), typically a low number like 14 or 15
    emc.pwm_frequency = 14 
    
    # Set the frequency divisor (1-127), larger number = lower frequency
    emc.pwm_frequency_divisor = 127 
    
    print(f"PWM Configured: Freq={emc.pwm_frequency}, Divisor={emc.pwm_frequency_divisor}")
    print("------------------------------------------")

    # 3. Cycle Fan Speeds
    print("Starting fan speed test cycle...")
    print("Note: The library automatically sets the chip to manual PWM mode.")
    print("-------------------------------------------------")
    
    while True:
        for speed_percent in FAN_SPEEDS:
            
            # SET FAN SPEED
            print(f"-> Setting fan speed to {speed_percent}%...")
            try:
                # manual_fan_speed expects a percentage (0-100)
                emc.manual_fan_speed = speed_percent
            except Exception as e:
                print(f"ERROR setting fan speed: {e}")
                
            time.sleep(CYCLE_DELAY)
            
            # READ FAN SPEED (RPM) AND INTERNAL TEMP
            try:
                # fan_speed reads the RPM value from the Tach register
                fan_rpm = emc.fan_speed
                # internal_temperature reads the chip's own temperature
                internal_temp = emc.internal_temperature
                
                print(f"   Fan Speed: {fan_rpm} RPM")
                print(f"   Internal Temp: {internal_temp:.2f} C")

                # Send RPM via UDP
                rpm_sender(fan_rpm)

            except Exception as e:
                # This ensures the script continues even if one read fails.
                print(f"   Warning: Could not read sensor data. Error: {e}")
            
            # We skip emc.external_temperature to avoid the reported crash.
            
            print("-" * 30)
            time.sleep(0.5)

if __name__ == "__main__":
    main()