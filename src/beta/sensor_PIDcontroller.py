#!/usr/bin/env python3
from gpiozero.pins.pigpio import PiGPIOFactory
from gpiozero import DistanceSensor
from pid_controller import PID
import socket, time
import json
import os
import logging
import sys

# Import necessary components from the network_injector module
from network_injector import load_config, get_current_status, inject_delay_and_check_loss

# --- CONFIGURATION FILE PATHS (Centralized) ---
CONFIG_DIR = "/opt/project/common/"
NETWORK_CONFIG_FILE = os.path.join(CONFIG_DIR, "network_config.json")
CONGESTION_CONFIG_FILE = os.path.join(CONFIG_DIR, "congestion_config.json")
SETPOINT_CONFIG_FILE = os.path.join(CONFIG_DIR, "setpoint_config.json")

# Set up logging
logging.basicConfig(level=logging.INFO, format='[Sensor] %(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

# Global variables for runtime configuration
FAN_IP = None
FAN_PORT = None
SETPOINT = 20.0
SAMPLE_TIME = 0.1
# Sensor listens for fan data on this port (new)
SENSOR_DATA_LISTEN_PORT = 0 

def load_network_config():
    """Loads network and timing parameters from the configuration file."""
    global FAN_IP, FAN_PORT, SAMPLE_TIME, SENSOR_DATA_LISTEN_PORT
    
    if not os.path.exists(NETWORK_CONFIG_FILE):
        logger.error(f"Network config file not found: {NETWORK_CONFIG_FILE}. Cannot run.")
        return False
    
    try:
        with open(NETWORK_CONFIG_FILE, 'r') as f:
            config = json.load(f)
            # Read fan connection parameters (output)
            FAN_IP = config.get("FAN_NODE_IP")
            FAN_PORT = config.get("FAN_COMMAND_PORT") # Updated key
            SAMPLE_TIME = config.get("SAMPLE_TIME_S", 0.1)
            
            # Read Sensor's Data Listen Port (input)
            SENSOR_DATA_LISTEN_PORT = config.get("FAN_DATA_LISTEN_PORT") # Port where sensor listens for fan telemetry
            
            if not all([FAN_IP, FAN_PORT, SAMPLE_TIME, SENSOR_DATA_LISTEN_PORT]):
                logger.error("Missing critical network/time parameters in config.")
                return False
            
            logger.info(f"Loaded Network Config: Fan IP={FAN_IP}, Command Port={FAN_PORT}, SampleTime={SAMPLE_TIME}s, Data Listen Port={SENSOR_DATA_LISTEN_PORT}")
            return True
    
    except json.JSONDecodeError:
        logger.error(f"Error decoding JSON from network config file: {NETWORK_CONFIG_FILE}.")
    except Exception as e:
        logger.error(f"An unexpected error occurred reading network config: {e}.")
    return False

def load_setpoint_config():
    """Loads the desired setpoint from the configuration file."""
    global SETPOINT
    if not os.path.exists(SETPOINT_CONFIG_FILE):
        logger.warning(f"Setpoint config file not found at: {SETPOINT_CONFIG_FILE}. Using default SETPOINT={SETPOINT}cm.")
        return

    try:
        with open(SETPOINT_CONFIG_FILE, 'r') as f:
            config = json.load(f)
            loaded_setpoint = config.get("SETPOINT_CM")
            if loaded_setpoint is not None and isinstance(loaded_setpoint, (int, float)):
                SETPOINT = float(loaded_setpoint)
                logger.info(f"Loaded SETPOINT: {SETPOINT}cm.")
            else:
                logger.warning(f"SETPOINT_CM key missing or invalid in config. Using default SETPOINT={SETPOINT}cm.")

    except json.JSONDecodeError:
        logger.error(f"Error decoding JSON from setpoint config file: {SETPOINT_CONFIG_FILE}. Using default SETPOINT={SETPOINT}cm.")
    except Exception as e:
        logger.error(f"An unexpected error occurred reading setpoint config: {e}. Using default SETPOINT={SETPOINT}cm.")

# --- INITIALIZATION ---
if not load_network_config():
    # If network config failed to load, exit early
    sys.exit(1)

load_setpoint_config()
# Load congestion values into network_injector module
load_config(CONGESTION_CONFIG_FILE) 


# PID initialization depends on loaded SETPOINT and SAMPLE_TIME
pid = PID(
    Kp=0.25,
    Ki=0.15,
    Kd=0.005,
    setpoint=SETPOINT, 
    sample_time=SAMPLE_TIME,
    output_limits=(0, 100),
    controller_direction='REVERSE'
)

# SENSOR SETUP (pigpio)
DistanceSensor.pin_factory = PiGPIOFactory()
# Placeholder: assuming echo=24, trigger=23 are the correct pins for the distance sensor
sensor = DistanceSensor(echo=24, trigger=23, max_distance=5) 


# UDP SETUP (for sending commands to Fan)
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM) # UDP
sock.settimeout(0.1) 


# PID Loop State Variables
last_time = time.time()
# Initialize a simulated height for the first loop
simulated_height = SETPOINT

logger.info("Starting PID Control Loop...")

try:
    while True:
        now = time.time()
        time_elapsed = now - last_time

        if time_elapsed >= SAMPLE_TIME:
            # --- 1. Read Sensor Input (using a mock for simulation purposes) ---
            
            # Simplified first-order response simulation for testing logic:
            pid_output = pid.output if pid.output is not None else 0.0
            
            target_value = (pid_output / 100.0) * 40.0 # Max height simulated at 40cm
            time_constant = 0.5 
            delta_h = (target_value - simulated_height) * (time_elapsed / time_constant)
            input_val = simulated_height + delta_h

            # Ensure input is bounded (e.g., 0cm to 40cm)
            input_val = max(0.0, min(40.0, input_val))
            simulated_height = input_val # Update simulated state

            # --- 2. Compute PID Output ---
            pid.compute(input_val)
            output_val = pid.output

            # --- 3. Apply Congestion and Send Command ---
            congestion_status = get_current_status()
            packet_sent = inject_delay_and_check_loss()
            now_str = time.strftime('%H:%M:%S')

            if packet_sent:
                command_str = f"{output_val:.1f}"
                try:
                    sock.sendto(command_str.encode('utf-8'), (FAN_IP, FAN_PORT))
                    logger.info(f"[{now_str}] FAN: {output_val:5.1f}% | H: {input_val:5.1f}cm | SP: {SETPOINT:5.1f}cm | DELAY: {congestion_status['delay_s']:.3f}s | SENT")
                except Exception as e:
                    logger.error(f"[{now_str}] Failed to send UDP command: {e}")
            else:
                logger.warning(f"[{now_str}] FAN: Packet DROPPED (Loss Rate: {congestion_status['loss_rate_perc']}%)")

            # Reset timer
            last_time = now

        time.sleep(0.001)

except KeyboardInterrupt:
    logger.info("PID controller stopped manually.")
except Exception as e:
    logger.error(f"An unexpected error occurred in the main loop: {e}")

finally:
    # Attempt to set fan speed to 0% on exit
    try:
        if FAN_IP and FAN_PORT:
            logger.info("Attempting to set fan to 0% on clean exit...")
            message = "0.0".encode('utf-8')
            sock.sendto(message, (FAN_IP, FAN_PORT))
            logger.info("Fan set to 0%.")
    except Exception as e:
        logger.error(f"Error setting fan to 0% on exit: {e}")
    
    sock.close()
    logger.info("Clean exit.")