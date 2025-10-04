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
import sys

# --- Configuration ---
PWM_PIN = 18          # GPIO Pin 18 (Pin 12 on the RPi Header)
FAN_PWM_FREQ = 2500   # Working frequency confirmed by user (2.5 kHz)
TEST_DUTIES = [5, 20, 50, 80, 100] # Key duty cycles to test (0 is always tested)
MIN_FAN_DUTY = 20     # Assumed minimum duty cycle needed for fan movement
MAX_FAN_DUTY = 100    # Maximum duty cycle
STEP_TIME = 0.05      # Time in seconds between duty cycle steps

def setup_pwm():
    """Initializes GPIO and PWM."""
    try:
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(PWM_PIN, GPIO.OUT)
        
        # Initialize PWM object
        pwm = GPIO.PWM(PWM_PIN, FAN_PWM_FREQ)
        pwm.start(0) # Start at 0% duty cycle
        print(f"PWM initialized on GPIO {PWM_PIN} at {FAN_PWM_FREQ} Hz.")
        return pwm
    except Exception as e:
        print(f"FATAL ERROR: Failed to set up PWM on GPIO {PWM_PIN}. {e}")
        GPIO.cleanup()
        sys.exit(1)

def ramp_fan(pwm, start_duty, end_duty, duration):
    """Smoothly ramps the fan speed over a given duration."""
    start_time = time.time()
    steps = int(duration / STEP_TIME)
    
    print(f"\nRamping from {start_duty}% to {end_duty}% over {duration} seconds...")
    
    for i in range(1, steps + 1):
        # Calculate duty cycle for this step
        ratio = i / steps
        current_duty = start_duty + (end_duty - start_duty) * ratio
        
        # Clamp value between 0 and 100
        duty_cycle = max(0, min(100, current_duty))
        
        pwm.ChangeDutyCycle(duty_cycle)
        
        # Print update every few steps, not every single one
        if i % 10 == 0 or i == steps:
            print(f"  > Duty Cycle: {duty_cycle:.1f}%")
        
        time.sleep(STEP_TIME)
    
    # Ensure final state is exactly what was requested
    pwm.ChangeDutyCycle(end_duty)
    time.sleep(0.5) # Allow fan to stabilize at end speed

def test_fixed_speeds(pwm):
    """Tests key duty cycles needed for PID control."""
    print("\n--- Testing Fixed Duty Cycles for PID Control Range ---")
    
    # 1. Minimum Effective Speed (Adjust MIN_FAN_DUTY if necessary)
    duty_min = MIN_FAN_DUTY
    print(f"Testing MIN DUTY (Likely Starting Point): {duty_min}% for 3 seconds.")
    pwm.ChangeDutyCycle(duty_min)
    time.sleep(3)

    # 2. Average/Cruising Speed (Middle of the range)
    duty_avg = (MIN_FAN_DUTY + MAX_FAN_DUTY) / 2
    print(f"Testing AVERAGE DUTY: {duty_avg}% for 3 seconds.")
    pwm.ChangeDutyCycle(duty_avg)
    time.sleep(3)

    # 3. Maximum Speed
    duty_max = MAX_FAN_DUTY
    print(f"Testing MAX DUTY: {duty_max}% for 3 seconds.")
    pwm.ChangeDutyCycle(duty_max)
    time.sleep(3)
    
    # 4. Shut down fan
    print("Shutting fan off (0%).")
    pwm.ChangeDutyCycle(0)
    time.sleep(1)


def main():
    print("--- Fan Cycle Test Script Starting ---")
    pwm_controller = setup_pwm()

    try:
        # Phase 1: Full Ramp Test (5 second duration)
        ramp_fan(pwm_controller, 0, 100, 5)
        print("\nMax speed achieved. Pausing for 2 seconds.")
        time.sleep(2)
        ramp_fan(pwm_controller, 100, 0, 5)

        # Phase 2: Targeted Speed Test
        test_fixed_speeds(pwm_controller)

        print("\n--- Test Complete: Fan Cycle Passed ---")
        
    except Exception as e:
        print(f"\nFATAL ERROR during test: {e}")
    finally:
        # Ensure resources are cleaned up safely
        if pwm_controller:
            pwm_controller.stop()
        GPIO.cleanup()
        print("GPIO cleanup complete. Fan stopped.")

if __name__ == "__main__":
    main()