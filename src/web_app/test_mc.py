#!/usr/bin/env python3
import os
import json
import time
import math
import logging
import socket
import threading
import subprocess # New for running shell commands cleanly

# Third-party libraries
from flask import Flask, render_template, request, jsonify
from flask_socketio import SocketIO, emit

# --- CONFIGURATION PATHS ---
# The primary network config
NETWORK_CONFIG_FILE = '/opt/project/common/network_config.json'
# Config for PID Setpoint (read by sensor_PIDcontroller.py)
SETPOINT_CONFIG_FILE = '/opt/project/common/setpoint_config.json'
# Config for Network Congestion (read by network_injector.py/sensor_PIDcontroller.py)
CONGESTION_CONFIG_FILE = '/opt/project/common/congestion_config.json'
# New: Path for the experiment status file (will be written by experiment_manager.sh)
EXPERIMENT_STATUS_FILE = '/tmp/current_experiment.txt'

# --- NETWORK CONFIGURATION (Defaults) ---
# We've migrated to common json configuration files that get loaded by load_network_config. 
# These are all safe default values to use until load_network_config replaces them. 
SENSOR_TELEMETRY_PORT = 5006 # This will be the SENSOR_DATA_LISTEN_PORT
FAN_TELEMETRY_PORT = 5007 # This will be the FAN_DATA_LISTEN_PORT

# Global status for experiment tracking (now entirely controlled by this process)
CURRENT_EXPERIMENT = "none" # Tracks current load type
PID_STATUS = "STOPPED" # Tracks PID loop status (derived from experiment status)

# --- LOGGING SETUP ---
# Set up logging with the desired [Master] prefix
logging.basicConfig(level=logging.INFO, format='[Master] %(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

# --- FLASK & SOCKETIO SETUP ---
app = Flask(__name__)
# Suppress Werkzeug logs for cleaner output during SocketIO run
logging.getLogger('werkzeug').setLevel(logging.ERROR)

# Use simple threading for SocketIO
socketio = SocketIO(app, cors_allowed_origins="*")

# --- THREAD CONTROL EVENT (Used by Poller and Listener) ---
stop_event = threading.Event()

# --- DATA STORES (Placeholder for real-time data) ---
# Last known status of the system
system_status = {
    "last_update_sensor": 0.0, # Unix timestamp for sensor data
    "last_update_fan": 0.0,    # Unix timestamp for fan data
    "pid_setpoint": 20.0,
    "current_height": 0.0,
    "fan_output": 0.0,         # Commanded Fan Duty Cycle (0.0 - 100.0)
    "fan_rpm": 0,
    "delay": 0.0,
    "loss_rate": 0.0,
    "load_magnitude": 0.0, # New: 0.0 to 100.0 (indicates load activity)
    "experiment_name": "N/A", 
    "pid_running": False
}

# Add a lock for thread-safe access to system_status
status_lock = threading.Lock() 

# --- CONFIGURATION & INIT ---

def load_config():
    """Loads and returns network configuration from the JSON file."""
    try:
        if os.path.exists(NETWORK_CONFIG_FILE):
            with open(NETWORK_CONFIG_FILE, 'r') as f:
                return json.load(f)
        else:
            logger.warning(f"Network config file not found at: {NETWORK_CONFIG_FILE}. Using defaults.")
            return {}
    except Exception as e:
        logger.error(f"Could not load network config at {NETWORK_CONFIG_FILE}. Using defaults. Error: {e}")
        return {}


def load_initial_pid_status():
    """Loads initial PID setpoint and congestion values from their respective config files."""
    global system_status
    # 1. Load Setpoint
    try:
        if os.path.exists(SETPOINT_CONFIG_FILE):
            with open(SETPOINT_CONFIG_FILE, 'r') as f:
                config = json.load(f)
                with status_lock:
                    system_status['pid_setpoint'] = config.get("PID_SETPOINT", 20.0)
                logger.info(f"Loaded initial PID Setpoint: {system_status['pid_setpoint']} cm")
    except Exception as e:
        logger.warning(f"Failed to load initial setpoint config: {e}")

    # 2. Load Congestion
    try:
        if os.path.exists(CONGESTION_CONFIG_FILE):
            with open(CONGESTION_CONFIG_FILE, 'r') as f:
                config = json.load(f)
                with status_lock:
                    system_status['delay'] = config.get("CONGESTION_DELAY", 0.0)
                    system_status['loss_rate'] = config.get("PACKET_LOSS_RATE", 0.0)
                logger.info(f"Loaded initial Congestion: Delay={system_status['delay']}ms, Loss={system_status['loss_rate']}%")
    except Exception as e:
        logger.warning(f"Failed to load initial congestion config: {e}")


# --- UTILITY FUNCTION FOR CONFIG WRITING ---
def save_config(filepath, config_dict):
    """Saves a dictionary to a JSON file."""
    try:
        with open(filepath, 'w') as f:
            json.dump(config_dict, f, indent=4)
        logger.info(f"Configuration saved to {os.path.basename(filepath)}")
        return True
    except Exception as e:
        logger.error(f"Failed to save config to {os.path.basename(filepath)}: {e}")
        return False

def run_sudo_command(command, command_args=None):
    """Safely runs a command prefixed with sudo using subprocess."""
    full_command = ["sudo", command]
    if command_args:
        full_command.extend(command_args)
    
    logger.info(f"Executing: {' '.join(full_command)}")
    try:
        # Use subprocess.run for simple execution and wait
        result = subprocess.run(full_command, capture_output=True, text=True, check=True)
        # Check=True raises CalledProcessError for non-zero exit codes
        logger.debug(f"Command output: {result.stdout.strip()}")
        if result.stderr:
             logger.warning(f"Command Stderr: {result.stderr.strip()}")
        return True
    except subprocess.CalledProcessError as e:
        logger.error(f"Command failed (Code {e.returncode}): {e.stderr.strip()}")
        return False
    except FileNotFoundError:
        logger.error(f"Command not found: {command}")
        return False
    except Exception as e:
        logger.error(f"Error running command: {e}")
        return False


# --- FLASK ROUTES ---
@app.route('/')
def index():
    """Serves the main dashboard page using the external template."""
    return render_template('index.html')

# --- SOCKETIO EVENT HANDLERS ---
@socketio.on('connect')
def handle_connect():
    """Handles new client connections and sends initial status."""
    logger.info("Client connected.")
    # Immediately send the current status upon connection
    with status_lock:
        emit('status_update', system_status.copy())

@socketio.on('request_status')
def handle_status_request():
    """Responds to client requests for the current status."""
    with status_lock:
        emit('status_update', system_status.copy())

@socketio.on('set_setpoint')
def handle_setpoint_update(data):
    """
    Handles setpoint updates from the dashboard.
    1. Updates in-memory status.
    2. Saves value to setpoint_config.json.
    """
    setpoint = data.get('setpoint')
    if setpoint is not None:
        try:
            float_setpoint = float(setpoint)
            
            # 1. Update the in-memory status (for the next telemetry update)
            with status_lock:
                system_status['pid_setpoint'] = float_setpoint

            # 2. Save the value to the file (for sensor_PIDcontroller.py to read)
            config_dict = {"PID_SETPOINT": float_setpoint}
            save_config(SETPOINT_CONFIG_FILE, config_dict)
            
            logger.info(f"Setpoint updated to {float_setpoint:.1f} cm.")

            # Send a confirmation/acknowledgment back to the client
            emit('command_ack', {'message': f"Setpoint updated to {float_setpoint:.1f} cm.", 'success': True})
        except ValueError:
            emit('command_ack', {'message': "Invalid setpoint value.", 'success': False})


@socketio.on('set_congestion')
def handle_congestion_update(data):
    """
    Handles congestion (delay/loss) updates from the dashboard.
    1. Updates in-memory status.
    2. Saves values to congestion_config.json.
    """
    delay_ms = data.get('delay_ms')
    loss_perc = data.get('loss_perc')
    
    if delay_ms is not None or loss_perc is not None:
        try:
            float_delay_ms = float(delay_ms)
            float_loss_perc = float(loss_perc)
            
            # 1. Update the in-memory status
            with status_lock:
                system_status['delay'] = float_delay_ms
                system_status['loss_rate'] = float_loss_perc

            # 2. Save the value to the file (for network_injector.py to read)
            config_dict = {
                "CONGESTION_DELAY": float_delay_ms, # Save in MS
                "PACKET_LOSS_RATE": float_loss_perc
            }
            save_config(CONGESTION_CONFIG_FILE, config_dict)
            
            logger.info(f"Congestion values saved: Delay={float_delay_ms:.0f}ms, Loss={float_loss_perc:.1f}%.")

            # Acknowledge the client that the config was saved, not necessarily applied
            emit('command_ack', {'message': f"Congestion config saved. Click 'APPLY TC' to activate.", 'success': True})
        except ValueError:
            emit('command_ack', {'message': "Invalid delay/loss value.", 'success': False})


@socketio.on('apply_tc')
def handle_apply_tc():
    """Applies the current congestion values using the traffic_manager.sh script."""
    delay = system_status['delay']
    loss = system_status['loss_rate']

    logger.info(f"Applying TC rules: Delay={delay}ms, Loss={loss}%")
    
    # Executes: sudo /opt/project/beta/traffic_manager.sh apply <delay_ms> <loss_perc>
    success = run_sudo_command(TC_SCRIPT, ["apply", str(delay), str(loss)])

    if success:
        message = f"TC Applied: Delay={delay:.0f}ms, Loss={loss:.1f}%."
    else:
        message = "Failed to APPLY Traffic Control rules."
    
    emit('command_ack', {'message': message, 'success': success})
    
@socketio.on('remove_tc')
def handle_remove_tc():
    """Removes all traffic control rules using the traffic_manager.sh script."""
    logger.info("Removing all TC rules (Teardown).")
    
    # Executes: sudo /opt/project/beta/traffic_manager.sh teardown
    success = run_sudo_command(TC_SCRIPT, ["teardown"])
    
    if success:
        message = "Traffic Control rules REMOVED. Network is clean."
    else:
        message = "Failed to REMOVE Traffic Control rules."

    # Optionally reset in-memory status, though the next congestion update will also do this
    with status_lock:
        system_status['delay'] = 0.0
        system_status['loss_rate'] = 0.0
    
    emit('command_ack', {'message': message, 'success': success})


@socketio.on('start_experiment')
def handle_start_experiment(data):
    """
    Handles request to start an experiment/load.
    The master controller will now directly manage the load via subprocess.
    """
    load_type = data.get('load_type', 'none')
    if load_type not in ['iperf', 'stress', 'none']:
        load_type = 'none' 

    if load_type == 'none':
        # If 'none' is selected, simply push status update
        logger.info("Experiment START requested with 'none' load.")
    else:
        logger.info(f"Attempting to START experiment load: {load_type}")
        # Executes: sudo /opt/project/beta/load_manager.sh start <load_type>
        success = run_sudo_command(LOAD_MANAGER_SCRIPT, ["start", load_type])
        
        if not success:
            emit('command_ack', {'message': f"Failed to start load type: {load_type}", 'success': False})
            load_type = 'none'

    # Update in-memory status
    with status_lock:
        global CURRENT_EXPERIMENT
        CURRENT_EXPERIMENT = load_type
        # Assuming PID is always running when an experiment is running
        system_status["experiment_name"] = f"{CURRENT_EXPERIMENT} (PID RUNNING)"
        system_status["pid_running"] = True
        system_status["load_magnitude"] = 100.0 if load_type != 'none' else 0.0
        
    emit('command_ack', {'message': f"Experiment load '{load_type}' started.", 'success': True})
    with status_lock:
        socketio.emit('status_update', system_status.copy()) 

@socketio.on('stop_experiment')
def handle_stop_experiment():
    """Handles request to stop the current experiment/load."""
    
    logger.info("Attempting to STOP current experiment load.")
    
    # Executes: sudo /opt/project/beta/load_manager.sh stop
    success = run_sudo_command(LOAD_MANAGER_SCRIPT, ["stop"])
    
    # Update in-memory status regardless of success
    with status_lock:
        global CURRENT_EXPERIMENT
        CURRENT_EXPERIMENT = "none"
        system_status["experiment_name"] = "N/A (PID STOPPED)"
        system_status["pid_running"] = False
        system_status["load_magnitude"] = 0.0
        
    if success:
        message = "Experiment load stopped."
    else:
        message = "Attempted to stop load, but execution failed."
    
    emit('command_ack', {'message': message, 'success': success})
    with status_lock:
        socketio.emit('status_update', system_status.copy()) 


def status_poller():
    """Continuously emits the current system status to all connected clients."""
    logger.info("Starting status poller thread...")
    while not stop_event.is_set():
        try:
            # Update timestamp for when this status was last collected/reported
            with status_lock:
                system_status['last_update'] = time.strftime('%H:%M:%S')
                # 2. Emit status
                socketio.emit('status_update', system_status.copy())
            
            time.sleep(1.0) # Update rate: 1 second
        except Exception as e:
            logger.error(f"Status Poller error: {e}")
            time.sleep(1)


# --- TELEMETRY LISTENER THREADS (No changes to the logic here) ---

def sensor_data_listener(listen_ip, listen_port):
    """
    Listens for continuous sensor data (height, setpoint, duty, delay, loss) 
    from the sensor node.
    """
    global system_status
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind((listen_ip, listen_port))
        logger.info(f"Sensor Data Listener started on {listen_ip}:{listen_port}")
        while not stop_event.is_set():
            data, addr = sock.recvfrom(1024)
            data_dict = json.loads(data.decode('utf-8'))
            
            with status_lock:
                system_status["last_update_sensor"] = time.time() # Update timestamp
                # The commanded duty cycle calculated by the PID
                system_status["fan_output"] = data_dict.get("fan_output_duty", system_status["fan_output"]) 
                # Data from sensor node
                system_status["current_height"] = data_dict.get("current_height", system_status["current_height"])
                system_status["pid_setpoint"] = data_dict.get("pid_setpoint", system_status["pid_setpoint"])
                system_status["delay"] = data_dict.get("delay", system_status["delay"])
                system_status["loss_rate"] = data_dict.get("loss_rate", system_status["loss_rate"])
                
    except Exception as e:
        if not stop_event.is_set():
            logger.error(f"Sensor Data Listener failed: {e}")
    finally:
        if 'sock' in locals() and not stop_event.is_set(): # Only close if not in cleanup phase
             sock.close()


def fan_data_listener(listen_ip, listen_port):
    """Listens for continuous fan data (RPM) from the fan node."""
    global system_status
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind((listen_ip, listen_port))
        logger.info(f"Fan Data Listener started on {listen_ip}:{listen_port}")
        while not stop_event.is_set():
            data, addr = sock.recvfrom(1024)
            data_dict = json.loads(data.decode('utf-8'))
            
            with status_lock:
                system_status["last_update_fan"] = time.time() # Update timestamp
                # Update only the fan-node reported fields
                system_status["fan_rpm"] = data_dict.get("fan_rpm", system_status["fan_rpm"])
                
    except Exception as e:
        if not stop_event.is_set():
            logger.error(f"Fan Data Listener failed: {e}")
    finally:
        if 'sock' in locals() and not stop_event.is_set(): # Only close if not in cleanup phase
             sock.close()


# --- MAIN EXECUTION ---

def main():
    """Loads config, initializes state, resets congestion, and starts the Flask/SocketIO server."""
    config = load_config()
    load_initial_pid_status() # Load saved values at startup

    # =========================================================================
    # --- STARTUP RESET LOGIC (Ensures clean network state and config file) ---
    logger.info("Resetting network congestion config to zero (0ms, 0.0%) for startup.")
    
    # Update in-memory status
    with status_lock:
        system_status['delay'] = 0.0
        system_status['loss_rate'] = 0.0
        system_status['load_magnitude'] = 0.0
        system_status['experiment_name'] = "N/A (PID STOPPED)"
        system_status['pid_running'] = False


    # Save the zero-values to the configuration file
    initial_congestion_config = {
        "CONGESTION_DELAY": 0.0, # 0 milliseconds
        "PACKET_LOSS_RATE": 0.0  # 0.0 percent
    }
    save_config(CONGESTION_CONFIG_FILE, initial_congestion_config)
    
    # Also ensure any external load is stopped and TC is removed on startup (via shell)
    run_sudo_command(TC_SCRIPT, ["teardown"])
    run_sudo_command(LOAD_MANAGER_SCRIPT, ["stop"])
    
    # =========================================================================

    # Read network details from config
    web_app_ip = config.get('WEB_APP_IP', '0.0.0.0')
    web_app_port = config.get('WEB_APP_PORT', 8000)
    # The IP used for dashboard display (e.g., the sensor IP)
    sensor_ip = config.get('SENSOR_NODE_IP', '192.168.22.2') 
    
    # The IP on which the Web App is listening for telemetry
    web_app_listen_ip = config.get('WEB_APP_IP', '0.0.0.0') 
    sensor_telemetry_port = config.get('SENSOR_DATA_LISTEN_PORT', 5006)
    fan_telemetry_port = config.get('FAN_DATA_LISTEN_PORT', 5007)


    # --- LOGGING CONFIGURATION ---
    logger.info("Configuration loaded:")
    logger.info(f"  Status Listener: {web_app_ip}:{web_app_port}") 
    logger.info(f"  Telemetry Listener (Sensor): {web_app_listen_ip}:{sensor_telemetry_port}")
    logger.info(f"  Telemetry Listener (Fan): {web_app_listen_ip}:{fan_telemetry_port}")

    # Start the data poller thread (emits system_status to dashboard clients)
    poller_thread = threading.Thread(target=status_poller)
    poller_thread.start()

    # Start the continuous telemetry listener threads
    sensor_listener = threading.Thread(target=sensor_data_listener, args=(web_app_listen_ip, sensor_telemetry_port), daemon=True)
    fan_listener = threading.Thread(target=fan_data_listener, args=(web_app_listen_ip, fan_telemetry_port), daemon=True)
    sensor_listener.start()
    fan_listener.start()

    logger.info(f"Master Controller is running. Access the dashboard at: http://{sensor_ip}:{web_app_port}")

    try:
        # allow_unsafe_werkzeug=True is often required for running in some environments
        socketio.run(app, host=web_app_ip, port=web_app_port, allow_unsafe_werkzeug=True)
    except KeyboardInterrupt:
        logger.info("Controller stopped manually.") 
    except Exception as e:
        logger.error(f"Failed to start web server: {e}")
    finally:
        stop_event.set()
        poller_thread.join()
        logger.info("Sockets closed. Clean exit.")

if __name__ == '__main__':
    # This is the entry point when master_controller.py is executed
    main()