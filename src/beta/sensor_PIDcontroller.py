#!/usr/bin/env python3
import RPi.GPIO as GPIO
import time
import socket
import threading
import json
import logging
import random
import csv
import os
from datetime import datetime

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
    GPIO.output(TRIG_PIN, GPIO.LOW)  # Ensure trigger is low on startup
    time.sleep(0.5)
except Exception as e:
    logger.error(f"GPIO Initialization Failed: {e}. Check if running on RPi.")

# --- SHARED STATE & THREAD CONTROL ---
state_lock = threading.Lock()

# NOTE: using 'current_distance' consistently (matches master_controller + dashboard)
current_state = {
    "current_distance": 0.0,
    "current_duty": 0,
    "pid_setpoint": 20.0,
    "delay": 0.0,        # ms
    "loss_rate": 0.0,    # %
    "sample_time": 0.05,
    "fan_ip": "192.168.22.1",
    "fan_port": 5005,
    "master_ip": "127.0.0.1",
    "master_telemetry_port": 5006,

    # Oscillation-related fields (for visualization + control)
    "oscillation_enabled": False,
    "oscillation_a": 20.0,
    "oscillation_b": 30.0,
    "oscillation_period": 20.0,  # seconds
    "pid_next_setpoint": 30.0,
    "pid_switch_in": 0.0,
    "pid_status": "RUNNING"
}

stop_event = threading.Event()
telemetry_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
fan_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

# --- PID INSTANCE ---
pid = PID(
    Kp=150, Ki=0.8, Kd=1.2,
    setpoint=current_state["pid_setpoint"],
    sample_time=current_state["sample_time"],
    output_limits=(0, 255),
    controller_direction='REVERSE'
)
# --- MINIMUM FAN DUTY (prevents free-fall on downward motion) ---
MIN_DUTY = 80

# --- LOG FILE SETUP ---
LOG_DIR = "/opt/project/logs"
os.makedirs(LOG_DIR, exist_ok=True)

LOG_FILENAME = f"{LOG_DIR}/sensor_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
log_file_lock = threading.Lock()

def write_log_row(data: dict):
    """Thread-safe CSV logging."""
    with log_file_lock:
        file_exists = os.path.exists(LOG_FILENAME)
        with open(LOG_FILENAME, "a", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=data.keys())
            if not file_exists:
                writer.writeheader()
            writer.writerow(data)


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


def update_runtime_configs(pid_controller: PID):
    """
    Periodically loads SETPOINT, OSCILLATION, and CONGESTION from files.

    - Setpoint / Oscillation: from SETPOINT_CONFIG_FILE
      Keys:
        PID_SETPOINT
        OSCILLATION_ENABLED
        OSCILLATION_A
        OSCILLATION_B
        OSCILLATION_PERIOD_SEC

    - Congestion: from CONGESTION_CONFIG_FILE
      Prefers new keys:
        delay (ms)
        loss  (%)
      Falls back to old:
        CONGESTION_DELAY, PACKET_LOSS_RATE
    """
    global current_state

    # 1. Load Setpoint + Oscillation config
    try:
        with open(SETPOINT_CONFIG_FILE, 'r') as f:
            config = json.load(f)

        base_setpoint = config.get("PID_SETPOINT", current_state["pid_setpoint"])
        
        # Read the PID status flag (e.g., "RUNNING" or "STOPPED")
        pid_status_cfg = config.get("PID_STATUS", current_state.get("pid_status", "RUNNING"))

        osc_enabled = config.get("OSCILLATION_ENABLED", current_state["oscillation_enabled"])
        osc_a = config.get("OSCILLATION_A", current_state["oscillation_a"])
        osc_b = config.get("OSCILLATION_B", current_state["oscillation_b"])
        period = config.get("OSCILLATION_PERIOD_SEC", current_state["oscillation_period"])

        with state_lock:
            # Update the PID status flag first
            current_state["pid_status"] = pid_status_cfg.upper()
            
            # Update oscillation settings
            current_state["oscillation_enabled"] = bool(osc_enabled)
            current_state["oscillation_a"] = float(osc_a)
            current_state["oscillation_b"] = float(osc_b)
            current_state["oscillation_period"] = float(period)

            # If oscillation is OFF: just use the base PID_SETPOINT from config
            if not current_state["oscillation_enabled"]:
                current_state["pid_setpoint"] = float(base_setpoint)
                pid_controller.setpoint = float(base_setpoint)

    except FileNotFoundError:
        logger.debug(f"Setpoint config file not found: {SETPOINT_CONFIG_FILE}")
    except Exception as e:
        logger.debug(f"Failed to load setpoint/oscillation config: {e}")

    # 2. Load Congestion config
    try:
        with open(CONGESTION_CONFIG_FILE, 'r') as f:
            config = json.load(f)

        # Prefer new keys 'delay' and 'loss', fall back to legacy ones if present
        new_delay_ms = config.get("delay", config.get("CONGESTION_DELAY", current_state["delay"]))
        new_loss_rate = config.get("loss", config.get("PACKET_LOSS_RATE", current_state["loss_rate"]))

        with state_lock:
            current_state["delay"] = float(new_delay_ms)
            current_state["loss_rate"] = float(new_loss_rate)

    except FileNotFoundError:
        logger.debug(f"Congestion config file not found: {CONGESTION_CONFIG_FILE}")
    except Exception as e:
        logger.debug(f"Failed to load congestion config: {e}")


# ---- ULTRASONIC SENSOR FUNCTION ----

def get_distance_cm():
    """Reads distance from the ultrasonic sensor. Now includes global try/except."""
    try:
        GPIO.output(TRIG_PIN, GPIO.LOW)
        time.sleep(0.000002)

        # Send pulse
        GPIO.output(TRIG_PIN, GPIO.HIGH)
        time.sleep(0.00001)
        GPIO.output(TRIG_PIN, GPIO.LOW)

        pulse_start = time.time()
        # Use stop_event check to prevent blocking when system is shutting down
        while GPIO.input(ECHO_PIN) == 0 and not stop_event.is_set():
            if time.time() - pulse_start > 0.1:
                return 0.0 # Software timeout
            pulse_start = time.time()

        pulse_end = time.time()
        while GPIO.input(ECHO_PIN) == 1 and not stop_event.is_set():
            if time.time() - pulse_end > 0.1:
                return 0.0 # Software timeout
            pulse_end = time.time()

        pulse_len = pulse_end - pulse_start
        distance = pulse_len * 17150.0  # (cm)
        return distance if distance > 0.0 else 0.0
    
    except Exception as e:
        # Catch unexpected I/O errors from GPIO during the pulse measurement
        logger.error(f"Hardware/GPIO Error during distance read: {e}. Returning 0.0.")
        return 0.0

# ---- THREAD 1: PID CONTROL LOOP (The critical timing loop) ----

def pid_control_thread_func(pid_controller: PID):
    """
    Core thread: Reads sensor, handles oscillation, computes PID output,
    sends fan command, applies congestion. Now includes robustness for sensor reads.
    """
    global current_state

    logger.info("PID Control loop starting...")

    while not stop_event.is_set():
        loop_start = time.time()

        # 1. Load runtime configs (setpoint, oscillation, congestion, and PID_STATUS)
        update_runtime_configs(pid_controller)

        with state_lock:
            status = current_state["pid_status"]

        # Default duty to the last successful duty cycle
        duty = current_state["current_duty"]
        distance = current_state["current_distance"] # Default to last known distance

        if status == "STOPPED":
            # PID is disabled. Set duty to 0 and reset PID state to prevent windup.
            distance = get_distance_cm()
            duty = 0
            pid_controller.initialize() # Reset I-term and last_output
            logger.debug("PID STOPPED. Setting duty to 0.")
    
        else: # status == "RUNNING"
            # 2. Oscillation logic (if enabled)
            with state_lock:
                if current_state["oscillation_enabled"]:
                    a = current_state["oscillation_a"]
                    b = current_state["oscillation_b"]
                    period = current_state["oscillation_period"]

                    now = time.time()
                    cycle_index = int(now / period) % 2
                    target = a if cycle_index == 0 else b
                    next_target = b if cycle_index == 0 else a

                    # time within current cycle
                    time_in_cycle = now % period
                    switch_in = period - time_in_cycle

                    current_state["pid_setpoint"] = target
                    pid_controller.setpoint = target

                    current_state["pid_next_setpoint"] = next_target
                    current_state["pid_switch_in"] = switch_in

            # --- CRITICAL ROBUSTNESS BLOCK ---
            try:
                # 3. Read distance
                new_distance = get_distance_cm()

                # If the sensor returns 0.0, it indicates an internal timeout/error/bad read.
                if new_distance <= 0.0:
                    logger.warning("Invalid sensor reading (0.0 cm). Retaining last duty cycle.")
                    # Update distance state to 0.0 for telemetry visualization
                    distance = 0.0
                    
                    # Log the bad reading, but SKIP PID update and fan command for this cycle
                    # to prevent a massive spike in output (as 0.0 cm is far from setpoint).
                    
                    # Update shared state with the bad distance
                    with state_lock:
                        current_state["current_distance"] = distance
                        
                    # Skip the rest of the control logic and proceed to timing/logging
                    # We continue to the next iteration, sending the last valid 'duty'
                    # if the loop had continued without this continue statement.
                    # Since we updated distance, we use 'break' to jump to the logging/sending section.
                    pass # Continue to congestion/send logic using the last known duty
                
                else:
                    # Good read: proceed with control
                    distance = new_distance
                    
                    # 4. PID compute
                    output = pid_controller.compute(distance)

                    # 5. Apply minimum fan duty
                    if output < MIN_DUTY:
                        duty = MIN_DUTY
                    else:
                        duty = int(min(255, output))

                    # Update shared state with successful read
                    with state_lock:
                        current_state["current_distance"] = distance
                        
            except Exception as e:
                # Catch any unexpected, fatal thread-killing exception from the sensor read
                logger.error(f"FATAL I/O EXCEPTION: {e}. Retaining last known duty ({duty}).")
                # Do not update distance or duty in shared state, just let the loop continue.
                # The old values are used for logging/sending below.
            # --- END CRITICAL ROBUSTNESS BLOCK ---

        # 6. Update shared duty state (whether calculated, retained, or stopped)
        with state_lock:
            current_state["current_duty"] = duty
            
        # 7. Congestion simulation
        with state_lock:
            delay_s = current_state["delay"] / 1000.0
            loss_rate = current_state["loss_rate"]

        if delay_s > 0:
            time.sleep(delay_s)

        packet_sent = True
        if loss_rate > 0.0 and random.random() * 100.0 < loss_rate:
            packet_sent = False

        # 8. Send fan command if not dropped
        if packet_sent:
            try:
                # Ensure we use the (potentially retained) 'duty' value
                fan_sock.sendto(str(duty).encode('utf-8'),
                                (current_state["fan_ip"], current_state["fan_port"]))
                logger.debug(f"FAN duty SENT: {duty:3d} | H: {distance:6.2f}cm")
            except Exception as e:
                logger.error(f"Failed to send fan command: {e}")
        else:
            logger.warning(f"FAN command DROPPED (Loss Rate: {loss_rate:.1f}%)")

        # --- LOG THIS LOOP ---
        log_data = {
            "timestamp": time.time(),
            "distance": current_state["current_distance"], # Use shared state for most accurate telemetry
            "setpoint": current_state["pid_setpoint"],
            "duty": current_state["current_duty"],         # Use shared state
            "delay_ms": current_state["delay"],
            "loss_rate": current_state["loss_rate"],
            "osc_a": current_state["oscillation_a"],
            "osc_b": current_state["oscillation_b"],
            "osc_period": current_state["oscillation_period"],
            "next_setpoint": current_state["pid_next_setpoint"],
            "switch_in": current_state["pid_switch_in"],
            "pid_status": current_state["pid_status"]
        }
        write_log_row(log_data)

        # 9. Maintain loop timing (respect sample_time)
        elapsed = time.time() - loop_start
        sleep_time = pid_controller.sample_time - elapsed
        if sleep_time > 0:
            time.sleep(sleep_time)

    logger.info("PID Control loop stopped.")


# ---- THREAD 2: TELEMETRY SENDER (Sends status to Master Controller) ----

def telemetry_sender_thread_func():
    """Periodically sends the current system state to the Master Controller via UDP."""
    global current_state
    REPORT_INTERVAL = 0.25  # Report 4 times per second

    logger.info(
        f"Telemetry Sender reporting to {current_state['master_ip']}:{current_state['master_telemetry_port']}..."
    )

    while not stop_event.is_set():
        try:
            with state_lock:
                payload_data = {
                    "current_distance": current_state["current_distance"],
                    "pid_setpoint": current_state["pid_setpoint"],
                    "delay": current_state["delay"],         # ms
                    "loss_rate": current_state["loss_rate"], # %
                    "fan_output_duty": current_state["current_duty"],
                    "pid_status": current_state["pid_status"], # NEW: Include PID status

                    # Extra fields for oscillation visualization
                    "oscillation_enabled": current_state["oscillation_enabled"],
                    "oscillation_a": current_state["oscillation_a"],
                    "oscillation_b": current_state["oscillation_b"],
                    "pid_next_setpoint": current_state["pid_next_setpoint"],
                    "pid_switch_in": current_state["pid_switch_in"]
                }

            payload = json.dumps(payload_data).encode('utf-8')
            telemetry_sock.sendto(
                payload,
                (current_state["master_ip"], current_state["master_telemetry_port"])
            )
            logger.debug(f"Telemetry sent: H={current_state['current_distance']:.2f}")

        except Exception as e:
            logger.error(f"Error in telemetry sender: {e}")

        time.sleep(REPORT_INTERVAL)

    logger.info("Telemetry Sender thread stopping.")


# ---- MAIN EXECUTION ----

def main():
    """Initializes system, starts threads, and handles cleanup."""
    if not load_network_config():
        return

    # Load initial PID and Congestion Status
    update_runtime_configs(pid)
    logger.info(f"PID Status initialized to: {current_state['pid_status']}")
    logger.info(f"PID Setpoint initialized to: {current_state['pid_setpoint']} cm")
    logger.info(
        f"Congestion initialized (Delay: {current_state['delay']}ms, Loss: {current_state['loss_rate']}%)"
    )
    logger.info(f"Logging data to: {LOG_FILENAME}")

    pid_thread = threading.Thread(
        target=pid_control_thread_func, args=(pid,), name="PIDControl"
    )
    telemetry_sender = threading.Thread(
        target=telemetry_sender_thread_func, name="TelemetrySender"
    )

    try:
        pid_thread.start()
        telemetry_sender.start()
        logger.info("Sensor/PID Controller threads started. Press Ctrl+C to stop.")

        while pid_thread.is_alive() or telemetry_sender.is_alive():
            time.sleep(0.5)

    except KeyboardInterrupt:
        logger.info("\nStopping gracefully...")
    except Exception as e:
        logger.error(f"Main thread error: {e}")
    finally:
        stop_event.set()

        pid_thread.join(timeout=1.0)
        telemetry_sender.join(timeout=1.0)

        try:
            # Ensure fan is zeroed out on shutdown
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