#!/usr/bin/env python3
import RPi.GPIO as GPIO
import time
import socket
import threading
import json
import logging
import random # Needed for packet loss simulation

# Assuming pid_controller.py is available in the environment
from pid_controller import PID

# --- LOGGING SETUP ---
logging.basicConfig(level=logging.INFO, format='[Sensor] %(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

# --- CONFIGURATION FILE PATHS (Static) ---
NETWORK_CONFIG_FILE = "/opt/project/common/network_config.json"
CONGESTION_CONFIG_FILE = "/opt/project/common/congestion_config.json"
SETPOINT_CONFIG_FILE = "/opt/project/common/setpoint_config.json"

# --- HARDWARE SETUP ---
TRIG_PIN = 23
ECHO_PIN = 24

try:
    GPIO.setwarnings(False)
    GPIO.setmode(GPIO.BCM)
    GPIO.setup(TRIG_PIN, GPIO.OUT)
    GPIO.setup(ECHO_PIN, GPIO.IN)
    GPIO.output(TRIG_PIN, GPIO.LOW) # Ensure trigger is low on startup
    time.sleep(0.5)
except Exception as e:
    logger.error(f"GPIO Initialization Failed: {e}. Check if running on RPi.")

# --- SHARED STATE & THREAD CONTROL ---
# Global variables for runtime configuration and status
# Protect access to these with a lock
state_lock = threading.Lock() 

# FIX: Changed 'height' to 'distance' throughout the code
current_state = {
    "current_distance": 0.0,
    "current_duty": 0,
    "pid_setpoint": 20.0,
    "delay": 0.0,         # MS
    "loss_rate": 0.0,     # %
    "sample_time": 0.05,
    "fan_ip": "192.168.22.1",
    "fan_port": 5005,
    "master_ip": "127.0.0.1",
    "master_telemetry_port": 5006
}

stop_event = threading.Event()
telemetry_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
fan_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

# --- PID INSTANCE ---
# Initialize with defaults; settings will be updated by config loader
pid = PID(
    Kp=180, Ki=2.0, Kd=0.8,
    setpoint=current_state["pid_setpoint"],
    sample_time=current_state["sample_time"],
    output_limits=(0, 255),
    controller_direction='REVERSE'
)

# ---- CONFIGURATION LOADING ----

def load_network_config():
    """Loads network settings from JSON config file."""
    global current_state
    try:
        with open(NETWORK_CONFIG_FILE, 'r') as f:
            config = json.load(f)

            with state_lock:
                current_state["fan_ip"] = config.get("FAN_NODE_IP", current_state["fan_ip"])
                current_state["fan_port"] = config.get("FAN_COMMAND_PORT", current_state["fan_port"])
                current_state["master_ip"] = config.get("WEB_APP_IP", current_state["master_ip"])
                current_state["master_telemetry_port"] = config.get("SENSOR_DATA_LISTEN_PORT", current_state["master_telemetry_port"])
                
        logger.info("Network configuration loaded.")
        return True
    except FileNotFoundError:
        logger.warning(f"Network config file not found: {NETWORK_CONFIG_FILE}. Using defaults.")
        return False
    except Exception as e:
        logger.warning(f"Could not load config file {NETWORK_CONFIG_FILE}. Using defaults. Error: {e}")
        return False

def update_runtime_configs(pid_controller):
    """
    Periodically loads SETPOINT and CONGESTION from files.
    Uses try/except FileNotFoundError to check for file presence without os.path.exists.
    """
    global current_state
    
    # 1. Load Setpoint
    try:
        with open(SETPOINT_CONFIG_FILE, 'r') as f:
            config = json.load(f)
            new_setpoint = config.get("PID_SETPOINT", current_state["pid_setpoint"])
            
            with state_lock:
                current_state["pid_setpoint"] = new_setpoint
                # Update the PID controller instance immediately
                pid_controller.setpoint = new_setpoint
            
    except FileNotFoundError:
        logger.debug(f"Setpoint config file not found: {SETPOINT_CONFIG_FILE}")
    except Exception as e:
        logger.debug(f"Failed to load setpoint config: {e}")

    # 2. Load Congestion
    try:
        with open(CONGESTION_CONFIG_FILE, 'r') as f:
            config = json.load(f)
            # Master Controller sends delay in MS
            new_delay_ms = config.get("CONGESTION_DELAY", current_state["delay"])
            new_loss_rate = config.get("PACKET_LOSS_RATE", current_state["loss_rate"])
            
            with state_lock:
                current_state["delay"] = new_delay_ms
                current_state["loss_rate"] = new_loss_rate
            
    except FileNotFoundError:
        logger.debug(f"Congestion config file not found: {CONGESTION_CONFIG_FILE}")
    except Exception as e:
        logger.debug(f"Failed to load congestion config: {e}")

# ---- ULTRASONIC SENSOR FUNCTION ----

def get_distance_cm():
    """Reads distance from the ultrasonic sensor."""
    # Ensure trigger is low before sending pulse
    GPIO.output(TRIG_PIN, GPIO.LOW)
    time.sleep(0.000002)
    
    # Send pulse
    GPIO.output(TRIG_PIN, GPIO.HIGH)
    time.sleep(0.00001)
    GPIO.output(TRIG_PIN, GPIO.LOW)

    pulse_start = time.time()
    # Wait for echo start (timeout safety check added)
    while GPIO.input(ECHO_PIN) == 0 and not stop_event.is_set():
        if time.time() - pulse_start > 0.1: 
            return 0.0
        pulse_start = time.time() 

    pulse_end = time.time()
    # Wait for echo end (timeout safety check added)
    while GPIO.input(ECHO_PIN) == 1 and not stop_event.is_set():
        if time.time() - pulse_end > 0.1: 
            return 0.0
        pulse_end = time.time()
        
    pulse_len = pulse_end - pulse_start
    # Distance = time * speed_of_sound / 2 (17150 cm/s)
    distance = pulse_len * 17150.0   
    return distance if distance > 0.0 else 0.0


# ---- THREAD 1: PID CONTROL LOOP (The critical timing loop) ----
def pid_control_thread_func(pid_controller):
    """
    Core thread: Reads sensor, computes PID output, sends fan command, applies congestion.
    """
    global current_state
    
    logger.info("PID Control loop starting...")

    while not stop_event.is_set():
        current_time = time.time()
        
        # 1. Update PID/Congestion Configuration from files (every loop cycle)
        update_runtime_configs(pid_controller)

        # 2. Sensor Read
        distance = get_distance_cm()
        
        # 3. PID Compute
        output = pid_controller.compute(distance)

        # 4. Command Preparation and Send
        duty = int(max(0, min(255, output)))
        
        # --- Inject Congestion Delay/Loss ---
        delay_s = current_state["delay"] / 1000.0 # Convert MS to Seconds
        loss_rate = current_state["loss_rate"]
        
        # Simulate delay
        if delay_s > 0:
            time.sleep(delay_s)
            
        packet_sent = True
        # Apply loss only to PID/Fan traffic based on loss_rate percentage
        if loss_rate > 0.0 and random.random() * 100.0 < loss_rate:
            packet_sent = False
        
        # 5. Update Shared State
        with state_lock:
            current_state["current_distance"] = distance
            current_state["current_duty"] = duty
            
        # 6. Send Command
        if packet_sent:
            try:
                fan_sock.sendto(str(duty).encode('utf-8'), (current_state["fan_ip"], current_state["fan_port"]))
                logger.debug(f"FAN duty SENT: {duty:3d} | H: {distance:6.2f}cm")
            except Exception as e:
                logger.error(f"Failed to send fan command: {e}")
        else:
            logger.warning(f"FAN command DROPPED (Loss Rate: {loss_rate:.1f}%)")


        # 7. Sleep for remaining sample time (to maintain the target frequency)
        sleep_time = pid_controller.sample_time - (time.time() - current_time) - delay_s
        if sleep_time > 0:
            time.sleep(sleep_time)

    logger.info("PID Control loop stopped.")


# ---- THREAD 2: TELEMETRY SENDER (Sends status to Master Controller) ----
def telemetry_sender_thread_func():
    """Periodically sends the current system state to the Master Controller via UDP."""
    global current_state
    REPORT_INTERVAL = 0.25 # Report 4 times per second

    logger.info(f"Telemetry Sender reporting to {current_state['master_ip']}:{current_state['master_telemetry_port']}...")

    while not stop_event.is_set():
        try:
            with state_lock:
                # Prepare the payload Master Controller's sensor listener expects
                payload_data = {
                    "current_distance": current_state["current_distance"],
                    "pid_setpoint": current_state["pid_setpoint"],
                    "delay": current_state["delay"],             # MS
                    "loss_rate": current_state["loss_rate"],     # %
                    "fan_output_duty": current_state["current_duty"]
                }
            
            # The key for distance must match what master_controller.py expects: current_distance
            payload = json.dumps(payload_data).encode('utf-8')
            telemetry_sock.sendto(payload, (current_state["master_ip"], current_state["master_telemetry_port"]))
            logger.debug(f"Telemetry sent: H={current_state['current_distance']:.2f}")

        except Exception as e:
            logger.error(f"Error in telemetry sender: {e}")
            
        # Wait for the next interval or until stop event is set
        time.sleep(REPORT_INTERVAL)

    logger.info("Telemetry Sender thread stopping.")


# ---- MAIN EXECUTION ----
def main():
    """Initializes system, starts threads, and handles cleanup."""
    if not load_network_config():
        return

    # Load initial PID and Congestion Status
    update_runtime_configs(pid)
    logger.info(f"PID Setpoint initialized to: {current_state['pid_setpoint']} cm")
    logger.info(f"Congestion initialized (Delay: {current_state['delay']}ms, Loss: {current_state['loss_rate']}%)")


    # Thread Setup
    pid_thread = threading.Thread(target=pid_control_thread_func, args=(pid,), name="PIDControl")
    telemetry_sender = threading.Thread(target=telemetry_sender_thread_func, name="TelemetrySender")

    try:
        pid_thread.start()
        telemetry_sender.start()
        logger.info("Sensor/PID Controller threads started. Press Ctrl+C to stop.")

        # Keep the main thread alive until a signal is received
        while pid_thread.is_alive() or telemetry_sender.is_alive():
            time.sleep(0.5)

    except KeyboardInterrupt:
        logger.info("\nStopping gracefully...")
    except Exception as e:
        logger.error(f"Main thread error: {e}")
    finally:
        # Cleanup
        stop_event.set()
        
        # Attempt to join threads cleanly
        pid_thread.join(timeout=1.0)
        telemetry_sender.join(timeout=1.0)
        
        # Attempt to stop fan on exit
        try:
            fan_sock.sendto(b"0", (current_state["fan_ip"], current_state["fan_port"]))
            logger.info("Sent 0 duty cycle to fan.")
        except Exception:
            pass 

        fan_sock.close()
        telemetry_sock.close()
        GPIO.cleanup()
        logger.info("Sensor/PID controller stopped and resources cleaned up.")

if __name__ == "__main__":
    main()
