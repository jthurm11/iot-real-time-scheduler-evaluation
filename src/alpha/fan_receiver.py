#!/usr/bin/env python3
import pigpio
import time
import socket
import threading
import json
import logging

# --- LOGGING SETUP ---
logging.basicConfig(level=logging.INFO, format='[Fan] %(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

# --- CONFIGURATION PATHS ---
# The primary network config
NETWORK_CONFIG_FILE = '/opt/project/common/network_config.json'

# --- FAN HARDWARE CONFIGURATION ---
PWM_PIN = 18            # blue wire from fan (PWM input)
TACHO_PIN = 23          # yellow wire from fan (Tachometer output)
FREQ = 25000            # 25 kHz typical for 4-wire fans
FAN_POLE_PAIRS = 2      # Typical for a 4-pole fan (2 pulses per revolution)

# --- NETWORK CONFIGURATION (Defaults) ---
# We've migrated to common json configuration files that get loaded by load_network_config. 
# These are all safe default values to use until load_network_config replaces them. 
FAN_COMMAND_IP = "0.0.0.0"
FAN_COMMAND_PORT = 5005
SENSOR_NODE_IP = "127.0.0.1" 
FAN_DATA_LISTEN_PORT = 5007
RPM_REPORT_INTERVAL = 0.5 # Send RPM data every half second

# --- SHARED STATE & LOCKS ---
global_rpm = 0
rpm_lock = threading.Lock()
stop_event = threading.Event()

# --- UTILITY SETUP ---
pi = pigpio.pi()


# --- TACHOMETER CLASS (pigpio callback for RPM measurement) ---
class Tachometer:
    """Manages the fan's RPM calculation using pigpio's callback mechanism."""
    def __init__(self, pi, tacho_pin, fan_pole_pairs):
        self.pi = pi
        self.fan_pole_pairs = fan_pole_pairs
        self.last_tick = None
        self.cbf = self.pi.callback(tacho_pin, pigpio.FALLING_EDGE, self._cbf)
        logger.info(f"Tachometer initialized on GPIO {tacho_pin}.")

    def _cbf(self, gpio, level, tick):
        """Callback function for each falling edge pulse."""
        global global_rpm
        if self.last_tick is not None:
            # Calculate time difference in seconds
            t_diff = pigpio.tickDiff(self.last_tick, tick) / 1000000.0

            if t_diff > 0:
                # Calculate RPM: 60 / (time_per_pulse * pulses_per_rev)
                # pulses_per_rev is FAN_POLE_PAIRS
                rpm = 60.0 / (t_diff * self.fan_pole_pairs)

                with rpm_lock:
                    global_rpm = int(rpm)

        self.last_tick = tick

    def cancel(self):
        """Clean up the pigpio callback."""
        if self.cbf:
            self.cbf.cancel()


# --- THREAD 1: FAN COMMAND RECEIVER (Based on original main loop) ---
def fan_receiver_thread_func():
    """Listens on UDP for PWM duty cycle commands and controls the fan."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.bind((FAN_COMMAND_IP, FAN_COMMAND_PORT))
        sock.settimeout(1.0) # Set a small timeout for clean shutdown
        logger.info(f"Listening for dutycycle commands on UDP port {FAN_COMMAND_PORT}...")

        while not stop_event.is_set():
            try:
                data, addr = sock.recvfrom(1024)
                # EXPECT sensor to send 0–255
                duty = int(data.decode().strip())
                # clamp to safe range
                duty = max(0, min(255, duty))

                pi.set_PWM_dutycycle(PWM_PIN, duty)
                logger.info(f"Duty SET: {duty:3d} | From: {addr[0]}")

            except socket.timeout:
                # Expected when waiting for stop_event
                continue
            except ValueError:
                logger.warning(f"Received non-integer duty cycle data.")
            except Exception as e:
                logger.error(f"Error in command receiver: {e}")

    finally:
        sock.close()


# --- THREAD 2: RPM TELEMETRY SENDER ---
def rpm_sender_thread_func():
    """Periodically reads the global RPM value and sends it via UDP."""
    telemetry_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    logger.info(f"Sending RPM telemetry to {SENSOR_NODE_IP}:{FAN_DATA_LISTEN_PORT} every {RPM_REPORT_INTERVAL}s...")

    while not stop_event.is_set():
        try:
            current_rpm = 0
            with rpm_lock:
                current_rpm = global_rpm

            # Send a simple JSON payload with the RPM value
            payload = json.dumps({"fan_rpm": current_rpm})
            telemetry_sock.sendto(payload.encode('utf-8'), (SENSOR_NODE_IP, FAN_DATA_LISTEN_PORT))
            logger.debug(f"RPM sent: {current_rpm}")

            # Sleep for the report interval
            time.sleep(RPM_REPORT_INTERVAL)

        except Exception as e:
            logger.error(f"Error in RPM sender thread: {e}")
            time.sleep(1) # Wait longer on error

    telemetry_sock.close()


# --- MAIN EXECUTION ---
def load_network_config():
    """Loads network settings from JSON config file."""
    global FAN_COMMAND_PORT, SENSOR_NODE_IP, FAN_DATA_LISTEN_PORT
    try:
        with open(NETWORK_CONFIG_FILE, 'r') as f:
            config = json.load(f)
            # Use configuration values from network_config.json
            FAN_COMMAND_PORT = config.get("FAN_COMMAND_PORT", FAN_COMMAND_PORT)
            SENSOR_NODE_IP = config.get("SENSOR_NODE_IP", SENSOR_NODE_IP)
            FAN_DATA_LISTEN_PORT = config.get("FAN_DATA_LISTEN_PORT", FAN_DATA_LISTEN_PORT)
        logger.info("Network configuration loaded.")
    except Exception as e:
        logger.warning(f"Could not load config file {NETWORK_CONFIG_FILE}. Using defaults. Error: {e}")


def main():
    load_network_config()

    # Hardware Setup
    pi.set_mode(PWM_PIN, pigpio.OUTPUT)
    pi.set_PWM_frequency(PWM_PIN, FREQ)
    pi.set_PWM_dutycycle(PWM_PIN, 0) # Start fan at 0%
    
    # Tachometer Setup
    tachometer = Tachometer(pi, TACHO_PIN, FAN_POLE_PAIRS)

    # Thread Setup
    command_thread = threading.Thread(target=fan_receiver_thread_func, name="CommandReceiver")
    telemetry_thread = threading.Thread(target=rpm_sender_thread_func, name="RPMSender")

    try:
        command_thread.start()
        telemetry_thread.start()
        logger.info("Fan controller threads started. Press Ctrl+C to stop.")

        # Keep the main thread alive until a signal is received
        while command_thread.is_alive() or telemetry_thread.is_alive():
            time.sleep(0.1)

    except KeyboardInterrupt:
        logger.info("\nStopping gracefully...")
    except Exception as e:
        logger.error(f"Main thread error: {e}")
    finally:
        # Cleanup
        stop_event.set()
        if command_thread.is_alive(): command_thread.join()
        if telemetry_thread.is_alive(): telemetry_thread.join()

        tachometer.cancel()
        pi.set_PWM_dutycycle(PWM_PIN, 0)
        pi.stop()
        logger.info("Fan controller stopped and resources cleaned up.")

if __name__ == "__main__":
    main()