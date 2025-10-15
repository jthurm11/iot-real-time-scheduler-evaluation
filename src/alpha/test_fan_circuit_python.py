# Make sure you have installed the necessary library:
# sudo pip3 install adafruit-circuitpython-emc2101
# You may also need to install the blinka dependencies first.

import time
import board
import busio
try:
    # We must import from emc2101_lut to access advanced PWM configuration methods.
    from adafruit_emc2101.emc2101_lut import EMC2101_LUT as EMC2101 
except ImportError:
    print("Error: The 'adafruit-circuitpython-emc2101' library is not installed.")
    print("Please run: sudo pip3 install adafruit-circuitpython-emc2101")
    exit()

# --- Configuration ---
# The default I2C address for EMC2101 is 0x4C, which is handled by the library.
FAN_SPEEDS = [0, 25, 50, 75, 100] # Duty cycle percentages to test
CYCLE_DELAY = 1.5 # Time (seconds) to hold each speed

def main():
    """
    Initializes the EMC2101, sets the PWM frequency for stable fan control, 
    and cycles the fan through various speeds.
    """
    
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
                
            except Exception as e:
                # This ensures the script continues even if one read fails.
                print(f"   Warning: Could not read sensor data. Error: {e}")
            
            # We skip emc.external_temperature to avoid the reported crash.
            
            print("-" * 30)
            time.sleep(0.5)

if __name__ == "__main__":
    main()
