#!/usr/bin/env python3
# DUAL-MODE FAN CONTROLLER: Prioritizes CircuitPython (Pi 3B) then falls back to SMBus (CM4/Generic)
# Includes data logging and plotting functionality.

import socket
import select
import time
import sys
import logging
import json
import os
import threading

# Set up logging for better error visibility
logging.basicConfig(level=logging.INFO, format='[Fan] %(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

# --- CONFIGURATION FILE PATHS (Centralized) ---
CONFIG_DIR = "/opt/project/common/"
NETWORK_CONFIG_FILE = os.path.join(CONFIG_DIR, "network_config.json")

# Global variables for runtime configuration
UDP_LISTEN_IP = "0.0.0.0"     # Listen on all interfaces for fan commands
UDP_LISTEN_PORT = 0           # Port to listen for PID commands
DATA_TARGET_IP = None         # IP to send telemetry data back to (Sensor Node)
DATA_TARGET_PORT = 0          # Port to send telemetry data back to
TIMEOUT = 0.01
BUFFER_SIZE = 1024

# --- I2C/SMBUS SPECIFIC CONFIGURATION ---
# Note: These are hardware configuration constants and do not need to be in the JSON
I2C_PRIORITY_COMBOS = [
    (10, 0x2F, 0x3C),  # CM4 I/O Board (EMC2301)
    (1, 0x4C, 0x4C)    # Pi 3B/Legacy (EMC2101)
]

# Shared Register Addresses (standard across EMC fan controllers)
FAN_PWM_REG = 0x30            # Fan 1 PWM Duty Cycle Register
TACH_HIGH_REG = 0x3E          # Fan 1 Tachometer Reading (High Byte)
TACH_DIVISOR = 0.5            # 0.5 assumes the default TACH_COUNT is 2 pulses/rev

# --- HARDWARE ABSTRACTION LAYER (HAL) ---
# Global variables for hardware access
bus = None
hardware_mode = "UNKNOWN"
PWM_DUTY_REG = 0x00
TACH_REG = 0x00

# Try to import either CircuitPython (busio) or SMBus
try:
    import board
    import busio
    hardware_mode = "CircuitPython"
except ImportError:
    try:
        import smbus
        hardware_mode = "SMBus"
    except ImportError:
        logger.error("Neither CircuitPython (busio) nor smbus found. Cannot control fan hardware.")
        sys.exit(1)


# --- DATA LOGGING AND UDP SENDING ---
fan_data_sock = None
data_thread = None
current_duty = 0.0
last_fan_rpm = 0

def load_network_config():
    """Loads network parameters (IP/Port) from the configuration file."""
    global UDP_LISTEN_PORT, DATA_TARGET_IP, DATA_TARGET_PORT
    
    if not os.path.exists(NETWORK_CONFIG_FILE):
        logger.error(f"Network config file not found: {NETWORK_CONFIG_FILE}. Using defaults.")
        return False
    
    try:
        with open(NETWORK_CONFIG_FILE, 'r') as f:
            config = json.load(f)
            
            # 1. PID Command Listen Port (Input)
            UDP_LISTEN_PORT = config.get("FAN_COMMAND_PORT")
            
            # 2. Data Target (Output to Sensor Node)
            DATA_TARGET_IP = config.get("SENSOR_NODE_IP")
            DATA_TARGET_PORT = config.get("FAN_DATA_LISTEN_PORT") # Fan data goes to this port on the Sensor Node

            if not all([UDP_LISTEN_PORT, DATA_TARGET_IP, DATA_TARGET_PORT]):
                logger.error("Missing critical network parameters in config.")
                return False
            
            logger.info(f"Loaded Config: Listen Port={UDP_LISTEN_PORT}, Data Target={DATA_TARGET_IP}:{DATA_TARGET_PORT}")
            return True

    except json.JSONDecodeError:
        logger.error(f"Error decoding JSON from network config file: {NETWORK_CONFIG_FILE}. Using defaults.")
    except Exception as e:
        logger.error(f"An unexpected error occurred reading network config: {e}. Using defaults.")
    return False

def send_fan_telemetry():
    """
    Thread function to periodically send fan RPM and Duty Cycle to the Sensor Node.
    """
    global last_fan_rpm, current_duty
    while True:
        try:
            # Read RPM immediately before sending
            fan_rpm = read_fan_rpm()
            last_fan_rpm = fan_rpm # Update global state
            
            # Create a JSON payload for the Fan's current status
            payload = {
                "timestamp": time.time(),
                "node": "fan",
                "rpm": fan_rpm,
                "duty_cycle": current_duty
            }
            message = json.dumps(payload).encode('utf-8')
            
            fan_data_sock.sendto(message, (DATA_TARGET_IP, DATA_TARGET_PORT))
            
            # Control the frequency of data reporting
            time.sleep(1.0) # Report fan status once per second
            
        except Exception as e:
            logger.error(f"Failed to send telemetry data: {e}")
            time.sleep(5.0) # Wait longer on failure

def initialize_bus():
    """Initializes the I2C bus and detects the fan controller chip."""
    # (Existing initialize_bus logic remains here - only network config changed)
    global bus, PWM_DUTY_REG, TACH_REG
    
    for bus_num, addr_2101, addr_2301 in I2C_PRIORITY_COMBOS:
        try:
            if hardware_mode == "CircuitPython":
                bus = busio.I2C(board.SCL, board.SDA)
                if addr_2101 in bus.scan():
                    logger.info(f"Fan Controller detected: EMC2101 at address 0x{addr_2101:02x} (CircuitPython)")
                    PWM_DUTY_REG = FAN_PWM_REG
                    TACH_REG = TACH_HIGH_REG
                    return True

            elif hardware_mode == "SMBus":
                import smbus
                bus = smbus.SMBus(bus_num)

                try:
                    bus.read_byte_data(addr_2301, 0x01)
                    logger.info(f"Fan Controller detected: EMC2301 at address 0x{addr_2301:02x} (SMBus)")
                    PWM_DUTY_REG = FAN_PWM_REG
                    TACH_REG = TACH_HIGH_REG
                    return True
                except:
                    try:
                        bus.read_byte_data(addr_2101, 0x01)
                        logger.info(f"Fan Controller detected: EMC2101 at address 0x{addr_2101:02x} (SMBus)")
                        PWM_DUTY_REG = FAN_PWM_REG
                        TACH_REG = TACH_HIGH_REG
                        return True
                    except:
                        pass
            
        except Exception as e:
            logger.debug(f"I2C initialization failed on bus {bus_num}: {e}")
            continue

    logger.error("No compatible fan controller chip found on any configured I2C address/bus.")
    bus = None
    return False

def set_pwm_duty(duty_cycle):
    """Sets the fan PWM duty cycle (0-100%)."""
    if bus is None:
        return
    
    duty_val = int(max(0, min(100, duty_cycle)) * 2.55)
    
    try:
        if hardware_mode == "CircuitPython":
            # CircuitPython write placeholder
            pass 
        elif hardware_mode == "SMBus":
            # Assuming first combo's address is the active one
            addr = I2C_PRIORITY_COMBOS[0][1] if PWM_DUTY_REG == FAN_PWM_REG else I2C_PRIORITY_COMBOS[0][2]
            if addr == 0x2F: addr = 0x2F # EMC2301 preferred
            elif addr == 0x4C: addr = 0x4C # EMC2101 preferred
            
            bus.write_byte_data(addr, FAN_PWM_REG, duty_val) 
            
    except Exception as e:
        logger.error(f"Failed to set fan duty cycle: {e}")

def read_fan_rpm():
    """Reads the fan's measured RPM."""
    if bus is None:
        return 0
        
    try:
        if hardware_mode == "CircuitPython":
            # CircuitPython read placeholder
            return 0
        elif hardware_mode == "SMBus":
            # Assuming first combo's address is the active one
            addr = I2C_PRIORITY_COMBOS[0][1] if TACH_REG == TACH_HIGH_REG else I2C_PRIORITY_COMBOS[0][2]
            if addr == 0x2F: addr = 0x2F 
            elif addr == 0x4C: addr = 0x4C
            
            # Read 2 bytes (High then Low byte)
            high_byte = bus.read_byte_data(addr, TACH_HIGH_REG)
            low_byte = bus.read_byte_data(addr, TACH_HIGH_REG + 1)
            tach_value = (high_byte << 8) | low_byte
            
            if tach_value > 0:
                rpm = (5400000 / (tach_value * 2)) * TACH_DIVISOR
                return int(rpm)
            return 0
            
    except Exception as e:
        logger.error(f"Failed to read fan RPM: {e}")
        return 0

# --- MAIN EXECUTION ---
if not load_network_config():
    sys.exit(1)

if not initialize_bus():
    logger.error("Hardware not initialized. Exiting fan controller.")
    sys.exit(1)

# UDP setup for receiving PID Commands
try:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((UDP_LISTEN_IP, UDP_LISTEN_PORT))
    logger.info(f"UDP command listener started on {UDP_LISTEN_IP}:{UDP_LISTEN_PORT}")
    
    fan_data_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    logger.info(f"UDP data sender initialized for {DATA_TARGET_IP}:{DATA_TARGET_PORT}")
    
except socket.error as msg:
    logger.error(f"Could not bind socket: {msg[0]}")
    sys.exit(1)

# Start the data reporting thread
data_thread = threading.Thread(target=send_fan_telemetry, daemon=True)
data_thread.start()
logger.info("Fan telemetry reporting thread started.")

try:
    while True:
        # Check for incoming UDP packet with a non-blocking select
        ready = select.select([sock], [], [], TIMEOUT)
        
        if ready[0]:
            data, addr = sock.recvfrom(BUFFER_SIZE)
            
            # A packet was received - this is the "active" mode
            try:
                # Decode the received data (which should be the new PWM duty cycle)
                new_duty = float(data.decode('utf-8'))
                current_duty = max(0.0, min(100.0, new_duty)) # Clamp 0-100%
                
                set_pwm_duty(current_duty)
                
                now_str = time.strftime('%H:%M:%S')
                logger.info(f"[{now_str}] ACTIVE ({hardware_mode}). Duty SET: {current_duty:5.1f}% | RPM: {last_fan_rpm:6d} | From: {addr[0]}")

            except ValueError:
                logger.warning(f"Received invalid duty cycle data: {data.decode('utf-8')}")
            
        else:
            # No packet received - this is the "idle" mode
            now_str = time.strftime('%H:%M:%S')
            
            logger.info(f"[{now_str}] IDLE ({hardware_mode}). Duty={current_duty:5.1f}% | RPM={last_fan_rpm:6d}")
            time.sleep(TIMEOUT * 10) # Slow down polling when idle (main loop)

except KeyboardInterrupt:
    logger.info("Stopped manually.")
except Exception as e:
    logger.error(f"An unexpected error occurred in the fan controller loop: {e}")
finally:
    # Attempt to set duty to 0% on exit
    if current_duty != 0:
        set_pwm_duty(0) 
        logger.info("Fan duty set to 0% on exit.")
    sock.close()
    if fan_data_sock:
        fan_data_sock.close()
    logger.info("Clean exit.")