#!/usr/bin/env python3

# --- HARDWARE WIRING INSTRUCTIONS ---
# This script monitors Wi-Fi connection status using an LED.
# 
# LED ANODE (+) to a CURRENT-LIMITING RESISTOR (e.g., 330 ohm).
# RESISTOR to GPIO PIN 23 (BCM numbering).
# LED CATHODE (-) to GROUND PIN (GND).
# 
# Raspberry Pi Header Reference:
# BCM 23 (LED Signal) is Physical Pin 16
# GND is Physical Pin 14 or 20 or 25
# -----------------------------------

import RPi.GPIO as GPIO
import time
import subprocess

# --- Configuration ---
LED_PIN = 23  # GPIO Pin 23 (Pin 16 on the RPi Header)
BLINK_INTERVAL = 0.5
CONNECTED_STATUS = "100 (connected)" # The exact string output by 'nmcli -g general.state ...'

def setup_gpio():
    """Initializes GPIO and sets LED pin as output."""
    try:
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(LED_PIN, GPIO.OUT)
        GPIO.output(LED_PIN, GPIO.LOW)
        print("Network status monitor started. LED on GPIO 23.")
    except Exception as e:
        print(f"Error setting up GPIO: {e}")
        # Reraise to ensure Systemd knows the setup failed
        raise

def check_wifi_connection():
    """Checks for an active 'connected' NetworkManager state on wlan0."""
    try:
        # Check if the wlan0 device state is "connected"
        result = subprocess.run(['nmcli', '-g', 'general.state', 'device', 'show', 'wlan0'], 
                                capture_output=True, text=True, check=True, timeout=5)
        
        # The output should be exactly "100 (connected)" if connected, or something else if not.
        current_state = result.stdout.strip()
        
        # Compare the stripped output directly to the expected connected status
        if current_state == CONNECTED_STATUS:
            return True
        else:
            return False

    except subprocess.CalledProcessError as e:
        # Device might not exist or nmcli failed
        return False
    except FileNotFoundError:
        print("nmcli command not found. Cannot check network status.")
        return False

def main():
    setup_gpio()
    last_status = False

    while True:
        current_status = check_wifi_connection()

        if current_status and not last_status:
            # Transitioned to connected (Green)
            GPIO.output(LED_PIN, GPIO.HIGH)
            print("Status: Network connected. LED ON.")
            last_status = True

        elif not current_status and last_status:
            # Transitioned to disconnected (Red)
            GPIO.output(LED_PIN, GPIO.LOW)
            print("Status: Network lost. LED OFF, starting blink.")
            last_status = False

        elif not current_status:
            # Still disconnected: Blink for visual feedback
            GPIO.output(LED_PIN, GPIO.HIGH)
            time.sleep(BLINK_INTERVAL)
            GPIO.output(LED_PIN, GPIO.LOW)
            time.sleep(BLINK_INTERVAL)

        else:
            # Still connected: Keep LED ON
            time.sleep(2) # Reduce checks when stable

# Ensure GPIO cleanup happens gracefully on exit
try:
    main()
except KeyboardInterrupt:
    print("Script manually terminated.")
except Exception as e:
    print(f"FATAL ERROR: An unexpected error occurred: {e}")
finally:
    GPIO.cleanup()
    print("GPIO cleanup complete.")