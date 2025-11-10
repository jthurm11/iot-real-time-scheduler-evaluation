#!/usr/bin/env python3
import os
import json
import time
import math
import logging
import socket
import threading

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

# Global status for experiment tracking
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
    "last_update_sensor": 0.0, # Unix timestamp for sensor data (NEW)
    "last_update_fan": 0.0,    # Unix timestamp for fan data (NEW)
    "pid_setpoint": 20.0,
    "current_height": 0.0,
    "fan_output": 0.0,         # Changed from 0 to 0.0 for float comparison
    "fan_rpm": 0,
    "delay": 0.0,
    "loss_rate": 0.0,
    "experiment_name": "N/A",  # New field for experiment name
    "pid_running": False       # New field for explicit PID loop status
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
                system_status['pid_setpoint'] = config.get("PID_SETPOINT", 20.0)
                logger.info(f"Loaded initial PID Setpoint: {system_status['pid_setpoint']} cm")
    except Exception as e:
        logger.warning(f"Failed to load initial setpoint config: {e}")

    # 2. Load Congestion
    try:
        if os.path.exists(CONGESTION_CONFIG_FILE
):
            with open(CONGESTION_CONFIG_FILE
    , 'r') as f:
                config = json.load(f)
                # NOTE: The master controller now expects and stores delay in MS
                system_status['delay'] = config.get("CONGESTION_DELAY", 0.0)
                system_status['loss_rate'] = config.get("PACKET_LOSS_RATE", 0.0)
                logger.info(f"Loaded initial Congestion: Delay={system_status['delay']}ms, Loss={system_status['loss_rate']}%")
    except Exception as e:
        logger.warning(f"Failed to load initial congestion config: {e}")


def load_experiment_status():
    """Reads the current experiment and PID status from a file written by the experiment_manager."""
    global CURRENT_EXPERIMENT, PID_STATUS, system_status
    try:
        if os.path.exists(EXPERIMENT_STATUS_FILE):
            with open(EXPERIMENT_STATUS_FILE, 'r') as f:
                content = f.read().strip().split(',')
                if len(content) == 2:
                    CURRENT_EXPERIMENT = content[0]
                    PID_STATUS = content[1] # 'RUNNING' or 'STOPPED'
                    
                    with status_lock:
                         system_status["experiment_name"] = f"{CURRENT_EXPERIMENT} (PID {PID_STATUS})"
                         system_status["pid_running"] = (PID_STATUS == "RUNNING")
                    
        else:
            # File doesn't exist, assume stopped
            CURRENT_EXPERIMENT = "none"
            PID_STATUS = "STOPPED"
            with status_lock:
                 system_status["experiment_name"] = "N/A"
                 system_status["pid_running"] = False
            
    except Exception as e:
        logger.error(f"Error reading experiment status file: {e}")
        

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
    emit('status_update', system_status)

@socketio.on('request_status')
def handle_status_request():
    """Responds to client requests for the current status."""
    emit('status_update', system_status)

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
            # We are now handling delay in MS throughout the master controller
            float_delay_ms = float(delay_ms)
            float_loss_perc = float(loss_perc)
            
            # 1. Update the in-memory status
            system_status['delay'] = float_delay_ms
            system_status['loss_rate'] = float_loss_perc

            # 2. Save the value to the file (for network_injector.py to read)
            config_dict = {
                "CONGESTION_DELAY": float_delay_ms, # Save in MS
                "PACKET_LOSS_RATE": float_loss_perc
            }
            save_config(CONGESTION_CONFIG_FILE
    , config_dict)
            
            logger.info(f"Congestion set: Delay={float_delay_ms:.0f}ms, Loss={float_loss_perc:.1f}%.")

            # Send a confirmation/acknowledgment back to the client
            emit('command_ack', {'message': f"Congestion set: Delay={float_delay_ms:.0f}ms, Loss={float_loss_perc:.1f}%.", 'success': True})
        except ValueError:
            emit('command_ack', {'message': "Invalid delay/loss value.", 'success': False})

@socketio.on('start_experiment')
def handle_start_experiment(data):
    """Handles request to start an experiment via experiment_manager.sh."""
    load_type = data.get('load_type', 'none')
    if load_type not in ['iperf', 'stress', 'none']:
        load_type = 'none' 
        
    logger.info(f"Attempting to START experiment with load type: {load_type}")
    
    # Executes the shell script (which starts PID and load, and writes status file)
    os.system(f"sudo /opt/project/beta/experiment_manager.sh run {load_type}")
    
    # Reload status after execution (it should be RUNNING now)
    load_experiment_status() 
    
    with status_lock:
        emit('status_update', system_status) 

@socketio.on('stop_experiment')
def handle_stop_experiment():
    """Handles request to stop the current experiment and teardown network settings."""
    
    logger.info("Attempting to STOP current experiment and TEARDOWN network.")
    
    # Executes the shell script (which stops PID and load, cleans tc, and writes status file)
    os.system("sudo /opt/project/beta/experiment_manager.sh teardown")
    
    # Reload status after execution (it should be STOPPED now)
    load_experiment_status() 
    
    with status_lock:
        emit('status_update', system_status) 


def status_poller():
    """Continuously emits the current system status to all connected clients."""
    # Ensure the thread runs only when the server is active

    # --- SIMULATION/MOCK DATA LOOP (COMMENTED OUT) ---
    # To Use: uncomment this section and comment out the one below.
    """
    logger.info("Starting status poller thread (Simulation Mode)...")
    while not stop_event.is_set():
        current_time = time.time()
        
        # Simple oscillation for demonstration purposes
        setpoint = system_status['pid_setpoint']
        system_status['current_height'] = setpoint + 1.5 * math.sin(current_time / 4.0)
        
        # This fan output simulation will react to the current setpoint
        system_status['fan_output'] = (setpoint * 2) + 10 * math.cos(current_time / 2.5) 
        system_status['fan_output'] = max(0, min(100, system_status['fan_output'])) # Clamp to 0-100
        
        system_status['fan_rpm'] = int(system_status['fan_output'] * 15) # Mock RPM
    
        # Update timestamp for when this status was last collected/reported
        system_status['last_update'] = time.strftime('%H:%M:%S')

        # Emit the entire status object
        socketio.emit('status_update', system_status)
        
        time.sleep(1.0) # Update rate: 1 second
    """
    # --- END SIMULATION/MOCK DATA LOOP ---


    # --- REAL DATA LOOP ---
    # Ensure the simulation mode above is commented out. 
    logger.info("Starting status poller thread...")
    while not stop_event.is_set():
        # 1. Update from file
        load_experiment_status()

        # Update timestamp for when this status was last collected/reported
        system_status['last_update'] = time.strftime('%H:%M:%S')

        # 2. Emit status
        with status_lock:
            socketio.emit('status_update', system_status)
        
        time.sleep(1.0) # Update rate: 1 second


# --- TELEMETRY LISTENER THREADS ---
""" Replaced by two dedicated listener threads below. Keeping this for reference. """
"""
def telemetry_listener(host, port):
    # UDP server to listen for real-time telemetry updates (height, fan output, RPM) 
    # from the Sensor/PID node. Updates the global system_status.

    BUFFER_SIZE = 1024
    TIMEOUT = 0.5 # Wait time for new packets

    try:
        # 1. Setup UDP Socket
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind((host, port))
        sock.settimeout(TIMEOUT)
        logger.info(f"Telemetry Listener started on UDP {host}:{port}")
    except Exception as e:
        logger.error(f"Failed to start Telemetry Listener on {host}:{port}: {e}")
        return

    # 2. Main Loop
    while not stop_event.is_set():
        try:
            data, addr = sock.recvfrom(BUFFER_SIZE)
            
            # Decode the received JSON string
            telemetry_data = json.loads(data.decode('utf-8'))
            
            # --- UPDATE GLOBAL STATUS ---
            # Update values if present in the received telemetry
            current_height = telemetry_data.get("current_height")
            fan_output = telemetry_data.get("fan_output")
            fan_rpm = telemetry_data.get("fan_rpm")
            
            if current_height is not None:
                system_status['current_height'] = current_height
            if fan_output is not None:
                system_status['fan_output'] = fan_output
            if fan_rpm is not None:
                system_status['fan_rpm'] = fan_rpm

            # Log the reception of data (using DEBUG level to prevent log spam)
            logger.debug(f"Telemetry received from {addr[0]}. H: {system_status['current_height']:.1f}cm, Fan: {system_status['fan_output']:.1f}%")
            
        except socket.timeout:
            # Expected when no packet is received within the TIMEOUT period
            continue 
        except socket.error as e:
            logger.warning(f"Socket error in telemetry listener: {e}")
            time.sleep(1) # Slow down on persistent error
        except json.JSONDecodeError:
            logger.warning(f"Received malformed JSON data in telemetry listener.")
        except Exception as e:
            logger.error(f"Unexpected error in telemetry listener loop: {e}")
            time.sleep(1)
            
    # 3. Clean up
    logger.info("Telemetry Listener thread stopping.")
    sock.close()
"""

def sensor_data_listener(listen_ip, listen_port):
    """Listens for continuous sensor data (height, setpoint, delay, loss) from the sensor node."""
    global system_status
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind((listen_ip, listen_port))
        logger.info(f"Sensor Data Listener started on {listen_ip}:{listen_port}")
        while True:
            data, addr = sock.recvfrom(1024)
            data_dict = json.loads(data.decode('utf-8'))
            
            with status_lock:
                system_status["last_update_sensor"] = time.time() # Update timestamp
                # Update only the sensor-node reported fields
                system_status["current_height"] = data_dict.get("current_height", system_status["current_height"])
                system_status["pid_setpoint"] = data_dict.get("pid_setpoint", system_status["pid_setpoint"])
                system_status["delay"] = data_dict.get("delay", system_status["delay"])
                system_status["loss_rate"] = data_dict.get("loss_rate", system_status["loss_rate"])
                
    except Exception as e:
        logger.error(f"Sensor Data Listener failed: {e}")
    finally:
        sock.close()


def fan_data_listener(listen_ip, listen_port):
    """Listens for continuous fan data (RPM, output duty cycle) from the fan node."""
    global system_status
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind((listen_ip, listen_port))
        logger.info(f"Fan Data Listener started on {listen_ip}:{listen_port}")
        while True:
            data, addr = sock.recvfrom(1024)
            data_dict = json.loads(data.decode('utf-8'))
            
            with status_lock:
                system_status["last_update_fan"] = time.time() # Update timestamp
                # Update only the fan-node reported fields
                system_status["fan_rpm"] = data_dict.get("fan_rpm", system_status["fan_rpm"])
                system_status["fan_output"] = data_dict.get("fan_output", system_status["fan_output"])
                
    except Exception as e:
        logger.error(f"Fan Data Listener failed: {e}")
    finally:
        sock.close()


# --- MAIN EXECUTION ---

def main():
    """Loads config, initializes state, resets congestion, and starts the Flask/SocketIO server."""
    config = load_config()
    load_initial_pid_status() # Load saved values at startup

    # =========================================================================
    # --- STARTUP RESET LOGIC (Keeping this to ensure clean network state) ---
    logger.info("Resetting network congestion and delay to zero (0ms, 0.0%) for startup.")
    
    # Update in-memory status
    system_status['delay'] = 0.0
    system_status['loss_rate'] = 0.0

    # Save the zero-values to the configuration file
    initial_congestion_config = {
        "CONGESTION_DELAY": 0.0, # 0 milliseconds
        "PACKET_LOSS_RATE": 0.0  # 0.0 percent
    }
    save_config(CONGESTION_CONFIG_FILE, initial_congestion_config)
    
    # =========================================================================

    # Read network details from config
    web_app_ip = config.get('WEB_APP_IP', '0.0.0.0')
    web_app_port = config.get('WEB_APP_PORT', 8000)
    fan_ip = config.get('FAN_NODE_IP', '192.168.22.1')
    fan_port = config.get('FAN_COMMAND_PORT', 5005)
    sensor_ip = config.get('SENSOR_NODE_IP', '192.168.22.2')
    
    # The IP on which the Web App is listening for telemetry
    web_app_listen_ip = config.get('WEB_APP_IP', '0.0.0.0') 
    sensor_telemetry_port = config.get('SENSOR_DATA_LISTEN_PORT', 5006)
    fan_telemetry_port = config.get('FAN_DATA_LISTEN_PORT', 5007)


    # Load the actual telemetry listener port from config
    #global TELEMETRY_PORT
    #TELEMETRY_PORT = config.get('SENSOR_DATA_LISTEN_PORT', 5006)

    # --- LOGGING CONFIGURATION (Restored the requested detailed output) ---
    logger.info("Configuration loaded:")
    logger.info(f"  Status Listener: {web_app_ip}:{web_app_port}") 
    logger.info(f"  Telemetry Listener (Sensor): {web_app_ip}:{sensor_telemetry_port}")
    logger.info(f"  Telemetry Listener (Fan): {web_app_ip}:{fan_telemetry_port}")
    logger.info(f"  Fan IP: {fan_ip}:{fan_port}")

    # Start the data poller thread (emits system_status to dashboard clients)
    poller_thread = threading.Thread(target=status_poller)
    poller_thread.start()

    # Start the telemetry receiver thread (updates system_status from Sensor node)
    #telemetry_thread = threading.Thread(target=telemetry_listener, args=(web_app_ip, TELEMETRY_PORT))
    #telemetry_thread.daemon = True
    #telemetry_thread.start()

    # Start the new continuous telemetry listener threads
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
        telemetry_thread.join() # Ensure the telemetry thread is joined on exit
        logger.info("Sockets closed. Clean exit.")

if __name__ == '__main__':
    # This is the entry point when master_controller.py is executed
    main()