#!/usr/bin/env python3

import time, socket, sys
import json
import os
import logging
# Import modules used by the PID controller
from pid_controller import PID
from network_injector import inject_delay_and_check_loss 

# --- CONFIGURATION FILE PATHS (Centralized) ---
CONFIG_DIR = "/opt/project/common/"
NETWORK_CONFIG_FILE = os.path.join(CONFIG_DIR, "network_config.json")
SETPOINT_CONFIG_FILE = os.path.join(CONFIG_DIR, "setpoint_config.json")
# --- END CONFIGURATION ---

# Set up logging for console output
logging.basicConfig(level=logging.INFO, format='[Sensor] %(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

# Global variables (initialized by load_network_config)
FAN_IP = None
FAN_PORT = None
MASTER_IP = None # Target IP for sending telemetry
MASTER_PORT = None # Target Port for sending telemetry
SAMPLE_TIME = 0.05

# --- HARDWARE & MOCKUP SETUP ---
try:
    # Attempt to import RPi.GPIO (for actual hardware)
    import RPi.GPIO as GPIO
    GPIO.setwarnings(False)
    GPIO.setmode(GPIO.BCM)
    
    # Set sensor pins
    TRIG_PIN = 23
    ECHO_PIN = 24
    
    GPIO.setup(TRIG_PIN, GPIO.OUT)
    GPIO.setup(ECHO_PIN, GPIO.IN)
    time.sleep(2) # Initial sensor warmup
    
    logger.info("Using actual RPi.GPIO distance sensor.")

    def get_distance_cm():
        """Reads distance using RPi.GPIO logic."""
        GPIO.output(TRIG_PIN, GPIO.LOW)
        time.sleep(0.000002)
        GPIO.output(TRIG_PIN, GPIO.HIGH)
        time.sleep(0.00001)
        GPIO.output(TRIG_PIN, GPIO.LOW)

        pulse_start = time.time()
        while GPIO.input(ECHO_PIN) == 0:
            pulse_start = time.time()
            if time.time() - pulse_start > 0.1: # Timeout protection
                return 0.0 

        pulse_end = time.time()
        while GPIO.input(ECHO_PIN) == 1:
            pulse_end = time.time()
            if time.time() - pulse_start > 0.1: # Timeout protection
                return 0.0 

        pulse_len = pulse_end - pulse_start
        # Return distance in cm
        return pulse_len * 17150.0 

except ImportError:
    # Fallback/Mock for testing environments (like the sandbox)
    logger.warning("RPi.GPIO not found. Using MockSensor for distance simulation.")
    import math
    class MockSensor:
        """Mocks the distance sensor for development on non-Pi or error environments."""
        def __init__(self):
            self.time = time.time()
            self.distance = 20.0 # Start at setpoint

        def get_distance_cm(self):
            # Simulate a slight, controlled oscillation around a default point (20cm)
            self.distance = 20.0 + 1.5 * math.sin(time.time() * 0.5) 
            return self.distance

    sensor_mock = MockSensor()
    get_distance_cm = sensor_mock.get_distance_cm # Assign mock method to function name


# --- CONFIGURATION LOADING ---

def load_network_config():
    """Loads network parameters (IP/Port) from the network configuration file."""
    global FAN_IP, FAN_PORT, SAMPLE_TIME, MASTER_IP, MASTER_PORT

    if not os.path.exists(NETWORK_CONFIG_FILE):
        logger.error(f"Network config file not found: {NETWORK_CONFIG_FILE}. Cannot run.")
        return False

    try:
        with open(NETWORK_CONFIG_FILE, 'r') as f:
            config = json.load(f)

            # Fan command target
            FAN_IP = config.get("FAN_NODE_IP")
            FAN_PORT = config.get("FAN_COMMAND_PORT")
            
            # Telemetry target (Master Controller is assumed to listen on the Sensor Node's IP)
            MASTER_IP = config.get("SENSOR_NODE_IP") 
            MASTER_PORT = config.get("TELEMETRY_PORT", 5006)

            # PID Sample Time from the config file
            SAMPLE_TIME = config.get("SAMPLE_TIME_S", 0.05) 

            if not FAN_IP or not FAN_PORT or not MASTER_IP or not MASTER_PORT:
                logger.error("Network IP or Port configuration is incomplete.")
                return False

            return True

    except Exception as e:
        logger.error(f"Failed to load network config: {e}")
        return False

def load_setpoint_config():
    """Loads the PID setpoint dynamically from the configuration file."""
    try:
        if os.path.exists(SETPOINT_CONFIG_FILE):
            with open(SETPOINT_CONFIG_FILE, 'r') as f:
                config = json.load(f)
                setpoint_val = config.get("PID_SETPOINT", 20.0)
                return setpoint_val
    except Exception as e:
        logger.error(f"Failed to load setpoint config: {e}. Defaulting to 20.0 cm.")
    return 20.0


# --- TELEMETRY FUNCTION ---

def send_telemetry(current_height_cm, fan_duty, fan_rpm, congestion_status):
    """Sends current system status (telemetry) to the Master Controller via UDP."""
    global telemetry_sock, MASTER_IP, MASTER_PORT

    if not MASTER_IP or not MASTER_PORT:
        return
        
    telemetry_data = {
        "current_height": current_height_cm,
        # FIX: Convert raw duty (0-255) to percentage (0-100)
        "fan_output": fan_duty * (100.0 / 255.0), 
        "fan_rpm": fan_rpm,
        # Convert delay back to MS for the dashboard display
        "delay": congestion_status.get("delay_s", 0.0) * 1000.0, 
        "loss_rate": congestion_status.get("loss_rate_perc", 0.0),
        "pid_setpoint": pid.setpoint # Send back the setpoint being used
    }

    try:
        message = json.dumps(telemetry_data).encode('utf-8')
        telemetry_sock.sendto(message, (MASTER_IP, MASTER_PORT))
    except Exception as e:
        # Suppress logging for frequent telemetry failures
        logger.error(f"Failed to send telemetry data: {e}.")
        pass 


# --- MAIN EXECUTION ---

# 1. Load Network Configuration
if not load_network_config():
    sys.exit(1)

# 2. PID Setup
SETPOINT = load_setpoint_config() # Initial load
pid = PID(
    Kp=300,
    Ki=0,
    Kd=0.6,
    setpoint=SETPOINT,
    sample_time=SAMPLE_TIME, # Uses value from network_config.json (default 0.05)
    output_limits=(0, 255),        # RAW DUTY 0–255 to fan
    controller_direction='REVERSE' # ball-on-air needs REVERSE gain direction
)

# Ensure PID uses the loaded sample time for its calculations
pid.set_sample_time(SAMPLE_TIME)

# 3. Initialize Sockets
# Socket for sending fan commands
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM) 
# Socket for sending telemetry data to Master Controller
telemetry_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

print("[Sensor] PID control running and connected to dashboard telemetry...")
start_time = time.time()
mock_rpm = 0 # Placeholder RPM value

try:
    while True:
        # A. Read Input and Setpoint
        height = get_distance_cm()
        new_setpoint = load_setpoint_config()
        pid.setpoint = new_setpoint
        
        # B. Compute Output (PID library handles the internal SAMPLE_TIME check)
        output = pid.compute(height)

        # C. Network Congestion Injection
        packet_sent, congestion_status = inject_delay_and_check_loss()
        
        # D. Process Command based on Packet Status
        duty = int(max(0, min(255, output)))
        now_str = time.strftime('%H:%M:%S')

        if packet_sent:
            try:
                sock.sendto(str(duty).encode(), (FAN_IP, FAN_PORT))
                # Update mock RPM (for display) based on current duty
                mock_rpm = int(duty * (5000/255)) # Assuming max RPM is 5000 at 255 duty
                logger.info(f"[{now_str}] H: {height:6.2f}cm | SP: {pid.setpoint:5.1f}cm | DUTY: {duty:3d} | DELAY: {congestion_status['delay_s']*1000.0:.1f}ms | SENT")

            except Exception as e:
                logger.error(f"[{now_str}] Failed to send UDP command: {e}")
        else:
            logger.warning(f"[{now_str}] H: {height:6.2f}cm | SP: {pid.setpoint:5.1f}cm | Packet DROPPED (Loss: {congestion_status['loss_rate_perc']}%)")
            
        # E. Send Telemetry (Always send, even if packet was dropped)
        send_telemetry(
            current_height_cm=height, 
            fan_duty=duty, 
            fan_rpm=mock_rpm, 
            congestion_status=congestion_status
        )
        
        # F. Non-blocking sleep
        # We rely on pid.compute's internal timer for control rate, 
        # so we just yield CPU time briefly.
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
            message = "0".encode('utf-8')
            sock.sendto(message, (FAN_IP, FAN_PORT))
    except Exception as e:
        logger.error(f"Failed to send 0 duty cycle command on exit: {e}")
    
    # Cleanup GPIO only if it was successfully imported
    if 'GPIO' in sys.modules:
        GPIO.cleanup()
        
    logger.info("PID Controller Exit Complete.")