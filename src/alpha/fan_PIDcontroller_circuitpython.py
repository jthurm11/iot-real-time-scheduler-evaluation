#!/usr/bin/env python3

import socket
import select
import time
import math
import sys
import logging
import numpy as np
import matplotlib.pyplot as plt
import smbus2 
import board
import busio
from adafruit_emc2101.emc2101_lut import EMC2101_LUT as EMC2101 

# Set up logging
logging.basicConfig(level=logging.INFO, format='[Fan] %(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

# --- CONFIGURATION ---
UDP_IP = "0.0.0.0"
UDP_PORT = 5005
TIMEOUT = 0.01
BUFFER_SIZE = 1024

# --- I2C/SMBUS SPECIFIC CONFIGURATION ---
I2C_PRIORITY_COMBOS = [
    (10, 0x2F, 0x3C),  # CM4 I/O Board setup
    (1, 0x4C, 0x4C)    # Pi 3B/Legacy setup
]

FAN_PWM_REG = 0x30
TACH_HIGH_REG = 0x3E
TACH_DIVISOR = 0.5

# --- GLOBAL HARDWARE STATE ---
hardware_mode = 'UNKNOWN'
active_bus_obj = None
i2c_address = None
SMBUS_AVAILABLE = True
CIRCUITPYTHON_AVAILABLE = True

# --- DYNAMICALLY ASSIGNED FUNCTIONS ---
def set_pwm_duty(duty_percent):
    logger.error("Hardware not initialized. Cannot set PWM duty.")
    return -1

def read_fan_rpm():
    logger.error("Hardware not initialized. Cannot read fan RPM.")
    return -1

# --- SMBUS IMPLEMENTATION ---
try:
    import smbus2 
except ImportError:
    SMBUS_AVAILABLE = False
    logger.warning("smbus2 not found. SMBus functionality disabled.")

def smbus_set_pwm_duty(bus, i2c_addr, duty_percent):
    duty_byte = int(round(duty_percent * 2.55))
    duty_byte = max(0x00, min(0xFF, duty_byte))

    try:
        bus.write_byte_data(i2c_addr, FAN_PWM_REG, duty_byte)
        return 0
    except IOError as e:
        logger.error(f"SMBUS Write Error (Duty): {e}")
        return -1

def smbus_read_fan_rpm(bus, i2c_addr):
    try:
        tach_value = bus.read_word_data(i2c_addr, TACH_HIGH_REG)
        tach_value = ((tach_value & 0xFF) << 8) | ((tach_value >> 8) & 0xFF)

        if tach_value == 0xFFFF or tach_value == 0x0000:
            return 0

        # RPM = (f_tach * 60) / (tach_count)
        rpm = (1843200 / tach_value) * TACH_DIVISOR 

        return int(round(rpm))

    except IOError as e:
        logger.error(f"SMBUS Read Error (RPM): {e}")
        return -2

# --- CIRCUITPYTHON IMPLEMENTATION ---
try:
    import board
    import busio
    from adafruit_emc2101.emc2101_lut import EMC2101_LUT as EMC2101 
except ImportError as e:
    CIRCUITPYTHON_AVAILABLE = False
    logger.warning(f"CircuitPython libraries not found: {e}")

def circuitpython_initialize():
    """Initializes EMC2101 using CircuitPython libraries and disables the LUT."""
    if not CIRCUITPYTHON_AVAILABLE:
        return None
        
    try:
        i2c = busio.I2C(board.SCL, board.SDA) 
        emc = EMC2101(i2c)
        
        # Apply custom PWM configuration for fan stability
        emc.set_pwm_clock(use_preset=False) 
        emc.pwm_frequency = 31            # Datasheet recommends using the maximum value of 31 (0x1F)
        emc.pwm_frequency_divisor = 127   # Larger divisor = lower frequency
        emc.lut_enabled = False           # Disable Lookup Table (LUT)
        
        logger.info("CircuitPython initialization SUCCESS. LUT Disabled.")
        return emc
        
    except Exception as e:
        logger.error(f"CircuitPython Initialization failed: {e}")
        return None

# --- MAIN INITIALIZATION LOGIC (PRIORITIZED) ---
def initialize_fan_controller():
    global hardware_mode, active_bus_obj, i2c_address, set_pwm_duty, read_fan_rpm

    # 1. Attempt CircuitPython (Priority)
    if CIRCUITPYTHON_AVAILABLE:
        logger.info("Starting CircuitPython initialization...")
        emc_obj = circuitpython_initialize() 
        
        if emc_obj:
            active_bus_obj = emc_obj
            hardware_mode = 'CIRCUITPYTHON'
            set_pwm_duty = lambda duty: setattr(active_bus_obj, 'manual_fan_speed', duty)
            read_fan_rpm = lambda: int(active_bus_obj.fan_speed) 
            logger.info("CircuitPython mode successfully initialized.")
            return True

    # 2. Attempt SMBus Fallback
    if SMBUS_AVAILABLE:
        logger.info("Starting SMBus fallback attempts...")

        for current_bus_id, current_i2c_addr, current_config_reg in I2C_PRIORITY_COMBOS:
            try:
                bus = smbus2.SMBus(current_bus_id)
                bus.read_byte_data(current_i2c_addr, 0xFD)

                # Configure the fan to Manual PWM Mode (0x00)
                bus.write_byte_data(current_i2c_addr, current_config_reg, 0x00)

                active_bus_obj = bus
                i2c_address = current_i2c_addr
                hardware_mode = 'SMBUS'
                set_pwm_duty = lambda duty: smbus_set_pwm_duty(bus, i2c_address, duty)
                read_fan_rpm = lambda: smbus_read_fan_rpm(bus, i2c_address)
                logger.info(f"SMBus SUCCESS on Bus {current_bus_id} at 0x{i2c_address:X}.")
                return True

            except Exception as e:
                logger.debug(f"SMBus check failed on Bus {current_bus_id} at 0x{current_i2c_addr:X}: {e}")
                pass

    # 3. Initialization Failed
    logger.critical("FATAL ERROR: Could not initialize fan controller in any mode.")
    return False

# --- UDP SOCKET SETUP ---
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.bind((UDP_IP, UDP_PORT))
sock.setblocking(0)

# --- LOGGING SETUP for PLOTTING ---
t_log, rpm_log, duty_log = [], [], []
start_time = time.time()

# --- MAIN EXECUTION ---
if not initialize_fan_controller():
    logger.critical("Exiting script due to initialization failure.")
    sys.exit(1)

logger.info(f"Fan Controller running in mode: {hardware_mode}")
logger.info(f"Listening for UDP control on port {UDP_PORT}")

current_duty = -1
try:
    while True:
        ready = select.select([sock], [], [], TIMEOUT)
        now = time.time() - start_time
        
        if ready[0]:
            # Drain and keep the latest packet
            latest_data = None
            while ready[0]:
                data, addr = sock.recvfrom(BUFFER_SIZE)
                latest_data = data
                ready = select.select([sock], [], [], 0) 

            if latest_data:
                try:
                    duty = float(latest_data.decode().strip())
                    duty = max(0, min(100, duty))  # clamp

                    if duty != current_duty:
                        result = set_pwm_duty(duty)
                        if result == 0 or hardware_mode == 'CIRCUITPYTHON': 
                            current_duty = duty
                            
                    fan_rpm = read_fan_rpm()
                    
                    # Log successful update
                    t_log.append(now)
                    duty_log.append(current_duty)
                    rpm_log.append(fan_rpm)
                    
                    logger.info(f"Duty={current_duty:5.1f}% | RPM={fan_rpm:6d} | from {addr[0]}")

                except ValueError:
                    logger.warning("Invalid data received (could not convert to float).")
                except Exception as e:
                    logger.error(f"Error during packet processing: {e}")
        else:
            # Idle: read RPM to monitor fan health
            fan_rpm = read_fan_rpm()
            
            # Log idle polling data
            t_log.append(now)
            duty_log.append(current_duty)
            rpm_log.append(fan_rpm)
            
            logger.info(f"IDLE ({hardware_mode}). Duty={current_duty:5.1f}% | RPM={fan_rpm:6d}")
            time.sleep(TIMEOUT * 10)

except KeyboardInterrupt:
    logger.info("Stopped manually.")
finally:
    if current_duty != 0 and set_pwm_duty is not None:
        set_pwm_duty(0) 
        logger.info("Fan duty set to 0% on exit.")
    sock.close()
    logger.info("Clean exit.")

    # --- PLOTTING ---
    if t_log:
        plt.figure(figsize=(10, 8))
        plt.suptitle("Fan Node Performance: Duty Cycle vs. Measured RPM", fontsize=14)

        # 1. Fan Duty Cycle
        plt.subplot(2, 1, 1)
        plt.plot(t_log, duty_log, label="Commanded Duty Cycle (%)", color='orange')
        plt.ylabel("Duty Cycle (%)")
        plt.legend(loc='upper right')
        plt.grid(True)
        plt.title("Commanded Control Effort")

        # 2. Measured Fan RPM
        plt.subplot(2, 1, 2)
        plt.plot(t_log, rpm_log, label="Measured RPM", color='blue')
        plt.ylabel("RPM")
        plt.xlabel("Time (s)")
        plt.legend(loc='upper right')
        plt.grid(True)
        plt.title("Actual Fan Response (Tachometer)")
        
        plt.tight_layout(rect=[0, 0.03, 1, 0.97])
        plt.show()
    else:
        logger.warning("No data logged, skipping plot generation.")
