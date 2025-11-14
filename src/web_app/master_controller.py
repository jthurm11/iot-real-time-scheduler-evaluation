#!/usr/bin/env python3
# CRITICAL FIX: Import and monkey-patch eventlet for proper WebSocket support
import eventlet
eventlet.monkey_patch() 
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
TELEMETRY_PORT = 5006 # This will be the SENSOR_DATA_LISTEN_PORT
FAN_TELEMETRY_PORT = 5007 # This will be the FAN_DATA_LISTEN_PORT

# Global status for experiment tracking
CURRENT_EXPERIMENT = "none" # Tracks current load type
PID_STATUS = "STOPPED" # Tracks PID loop status (derived from experiment status)

# --- LOGGING SETUP ---
# Set up logging with the desired [Master] prefix
logging.basicConfig(level=logging.INFO, format='[Master] %(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

# --- WEB & SOCKETIO SETUP ---
app = Flask(__name__)
app.config['SECRET_KEY'] = 'your_secret_key_here' # Needed for session management
# Use message_queue if running multiple instances, but not needed for single instance
socketio = SocketIO(app, async_mode='eventlet') 

# --- SYSTEM STATE ---
system_status = {
    "current_height": 0.0,
    "current_rpm": 0,
    "fan_output_duty": 0.0,
    "pid_status": PID_STATUS,
    "pid_setpoint": 20.0,
    "experiment_name": CURRENT_EXPERIMENT,
    "delay": 0,
    "loss_rate": 0.0,
    "load_magnitude": 0,
    "master_timestamp": time.time()
}
status_lock = threading.Lock()
stop_event = threading.Event()

# --- NETWORK CONFIGURATION VARIABLES (Loaded by load_network_config) ---
fan_command_ip = "127.0.0.1"
fan_command_port = 5005
sensor_ip = "127.0.0.1"
sensor_command_port = 5004
sensor_telemetry_port = 5006
fan_telemetry_port = 5007
web_app_port = 8080
web_app_ip = "0.0.0.0" # Listen on all interfaces

# --- CONFIGURATION LOADING ---
def load_network_config():
    """Loads network configuration from the shared JSON file."""
    global fan_command_ip, fan_command_port, sensor_ip, sensor_command_port, \
           sensor_telemetry_port, fan_telemetry_port, web_app_port, web_app_ip
    
    try:
        with open(NETWORK_CONFIG_FILE, 'r') as f:
            config = json.load(f)
            
            fan_command_ip = config.get("FAN_COMMAND_IP", fan_command_ip)
            fan_command_port = config.get("FAN_COMMAND_PORT", fan_command_port)
            sensor_ip = config.get("SENSOR_IP", sensor_ip)
            sensor_command_port = config.get("SENSOR_COMMAND_PORT", sensor_command_port)
            sensor_telemetry_port = config.get("SENSOR_DATA_LISTEN_PORT", sensor_telemetry_port)
            fan_telemetry_port = config.get("FAN_DATA_LISTEN_PORT", fan_telemetry_port)
            web_app_port = config.get("WEB_APP_PORT", web_app_port)
            web_app_ip = config.get("WEB_APP_IP", web_app_ip)
            
            logger.info("Network configuration loaded.")
            
    except Exception as e:
        logger.warning(f"Could not load config file {NETWORK_CONFIG_FILE}. Using defaults. Error: {e}")

def update_status_file(filename, key, value):
    """Updates a single key in a JSON configuration file."""
    try:
        data = {}
        if os.path.exists(filename):
            with open(filename, 'r') as f:
                data = json.load(f)
        
        data[key] = value
        
        with open(filename, 'w') as f:
            json.dump(data, f, indent=4)
        logger.info(f"Updated {key} to {value} in {filename}")
        return True
    except Exception as e:
        logger.error(f"Failed to update {filename}: {e}")
        return False

# --- DATA LISTENERS ---

def sensor_data_listener(listen_ip, port):
    """Listens for ball height and PID status updates from the sensor node."""
    global system_status
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        try:
            sock.bind((listen_ip, port))
            logger.info(f"Listening for sensor data on UDP {listen_ip}:{port}")
            while not stop_event.is_set():
                data, _ = sock.recvfrom(1024)
                try:
                    packet = json.loads(data.decode())

                    # Fix: Extract the raw duty cycle (0-255) to show as percentage
                    raw_duty = packet.get("fan_output_duty")
                    if raw_duty is not None and isinstance(raw_duty, (int, float)):
                        scaled_duty = round((raw_duty / 255.0) * 100)

                    with status_lock:
                        system_status["current_height"] = packet.get("current_height", system_status["current_height"])
                        #system_status["fan_output_duty"] = packet.get("fan_output_duty", system_status["fan_output_duty"])
                        system_status["fan_output_duty"] = scaled_duty
                        system_status["pid_status"] = packet.get("pid_status", system_status["pid_status"])
                        system_status["master_timestamp"] = time.time()
                except json.JSONDecodeError:
                    logger.warning("Received invalid JSON from sensor node.")
                except Exception as e:
                    logger.error(f"Error processing sensor data: {e}")
        except Exception as e:
            logger.error(f"Sensor listener error: {e}")
        finally:
            logger.info("Sensor data listener stopped.")

def fan_data_listener(listen_ip, port):
    """Listens for RPM updates from the fan node."""
    global system_status
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        try:
            sock.bind((listen_ip, port))
            logger.info(f"Listening for fan data on UDP {listen_ip}:{port}")
            while not stop_event.is_set():
                data, _ = sock.recvfrom(1024)
                try:
                    packet = json.loads(data.decode())
                    with status_lock:
                        system_status["current_rpm"] = packet.get("rpm", system_status["current_rpm"])
                        system_status["master_timestamp"] = time.time()
                except json.JSONDecodeError:
                    logger.warning("Received invalid JSON from fan node.")
                except Exception as e:
                    logger.error(f"Error processing fan data: {e}")
        except Exception as e:
            logger.error(f"Fan listener error: {e}")
        finally:
            logger.info("Fan data listener stopped.")


# --- SOCKETIO (WEB DASHBOARD) HANDLERS ---

@app.route('/')
def index():
    """Renders the main dashboard."""
    return render_template('index.html')

@socketio.on('set_setpoint')
def handle_setpoint_update(data):
    """Handles setpoint changes from the dashboard."""
    new_setpoint = data.get('setpoint')
    if new_setpoint is not None:
        if update_status_file(SETPOINT_CONFIG_FILE, 'setpoint', new_setpoint):
            with status_lock:
                system_status["pid_setpoint"] = new_setpoint
            emit('command_ack', {'success': True, 'message': f'Setpoint updated to {new_setpoint} cm.'})
        else:
            emit('command_ack', {'success': False, 'message': 'Failed to write setpoint config.'})

@socketio.on('set_congestion')
def handle_congestion_update(data):
    """Handles congestion (delay/loss) changes from the dashboard."""
    delay = data.get('delay')
    loss = data.get('loss')
    
    if delay is not None and loss is not None:
        if update_status_file(CONGESTION_CONFIG_FILE, 'delay', delay) and \
           update_status_file(CONGESTION_CONFIG_FILE, 'loss', loss):
            with status_lock:
                system_status["delay"] = delay
                system_status["loss_rate"] = loss
            emit('command_ack', {'success': True, 'message': f'Congestion updated: Delay={delay}ms, Loss={loss}%.'})
        else:
            emit('command_ack', {'success': False, 'message': 'Failed to write congestion config.'})

@socketio.on('control_command')
def handle_control_command(data):
    """
    Handles generic commands like start/stop PID, apply/remove TC, 
    and start/stop load. These rely on external scripts reading the config.
    """
    action = data.get('action')
    load_type = data.get('load_type', 'none')

    if action == 'start':
        if update_status_file(SETPOINT_CONFIG_FILE, 'status', 'RUNNING'):
             emit('command_ack', {'success': True, 'message': 'PID set to RUNNING. Controller should start shortly.'})
        else:
            emit('command_ack', {'success': False, 'message': 'Failed to signal PID start.'})
            
    elif action == 'stop':
        if update_status_file(SETPOINT_CONFIG_FILE, 'status', 'STOPPED'):
             emit('command_ack', {'success': True, 'message': 'PID set to STOPPED. Controller should shut down shortly.'})
        else:
            emit('command_ack', {'success': False, 'message': 'Failed to signal PID stop.'})

    # The experiment_manager script handles the actual TC/Load execution based on config changes.
    elif action == 'start_load':
        if update_status_file(CONGESTION_CONFIG_FILE, 'load_type', load_type):
            emit('command_ack', {'success': True, 'message': f'Starting {load_type} background load.'})
        else:
            emit('command_ack', {'success': False, 'message': 'Failed to start background load.'})
    
    elif action == 'stop_load':
        if update_status_file(CONGESTION_CONFIG_FILE, 'load_type', 'none'):
            emit('command_ack', {'success': True, 'message': 'Stopping background load.'})
        else:
            emit('command_ack', {'success': False, 'message': 'Failed to stop background load.'})
            
    elif action in ['apply_tc', 'remove_tc']:
        if update_status_file(CONGESTION_CONFIG_FILE, 'tc_action', action):
            emit('command_ack', {'success': True, 'message': f'Signalled action: {action.replace("_", " ").upper()}.'})
        else:
            emit('command_ack', {'success': False, 'message': f'Failed to signal TC action: {action}.'})


# --- POLLER THREAD ---

def read_experiment_status():
    """Reads the current experiment type from the status file."""
    try:
        with open(EXPERIMENT_STATUS_FILE, 'r') as f:
            return f.read().strip()
    except FileNotFoundError:
        return "none"
    except Exception as e:
        logger.warning(f"Failed to read experiment status file: {e}")
        return "none"

def status_poller():
    """A thread that continuously emits the latest system status to all connected clients."""
    global system_status
    while not stop_event.is_set():
        # Read the latest experiment status from the file written by the experiment manager
        current_experiment_type = read_experiment_status()

        # Update the system_status object and then emit
        with status_lock:
            # Update the experiment name
            system_status["experiment_name"] = current_experiment_type
            
            # Read PID status from config file (as set by the dashboard)
            try:
                with open(SETPOINT_CONFIG_FILE, 'r') as f:
                    setpoint_data = json.load(f)
                    system_status["pid_status"] = setpoint_data.get('status', 'STOPPED')
            except:
                pass # Use existing status if file read fails

            # Read congestion settings from config file
            try:
                with open(CONGESTION_CONFIG_FILE, 'r') as f:
                    congestion_data = json.load(f)
                    system_status["delay"] = congestion_data.get('delay', 0)
                    system_status["loss_rate"] = congestion_data.get('loss', 0.0)
            except:
                pass # Use existing settings if file read fails
            
            # Emit the current state
            # NOTE: We are emitting to the default namespace ('/')
            socketio.emit('status_update', system_status)
        
        # Poll every 250ms (or whatever is appropriate for the system)
        eventlet.sleep(0.25) # Use eventlet.sleep instead of time.sleep

def telemetry_listener(listen_ip, port):
    """
    Deprecated: This function is kept for reference but should be replaced 
    by sensor_data_listener and fan_data_listener.
    """
    logger.warning("Telemetry Listener thread is deprecated and replaced by dedicated listeners.")
    pass

# --- MAIN EXECUTION ---
if __name__ == '__main__':
    load_network_config()

    # Start the status poller thread (sends system_status to dashboard clients)
    poller_thread = threading.Thread(target=status_poller)
    poller_thread.start()

    # Start the new continuous telemetry listener threads
    web_app_listen_ip = '0.0.0.0' # Always listen on all interfaces
    sensor_listener = threading.Thread(target=sensor_data_listener, args=(web_app_listen_ip, sensor_telemetry_port), daemon=True)
    fan_listener = threading.Thread(target=fan_data_listener, args=(web_app_listen_ip, fan_telemetry_port), daemon=True)
    sensor_listener.start()
    fan_listener.start()

    logger.info(f"Master Controller is running. Access the dashboard at: http://{sensor_ip}:{web_app_port}")

    try:
        # CRITICAL FIX: Running with Eventlet is mandatory for WebSockets
        logger.info("Starting SocketIO server with Eventlet...")
        # Since we monkey-patched eventlet, socketio.run automatically uses it.
        # We remove allow_unsafe_werkzeug=True.
        socketio.run(app, host=web_app_ip, port=web_app_port) 
    except KeyboardInterrupt:
        logger.info("Controller stopped manually.") 
    except Exception as e:
        logger.error(f"Failed to start web server: {e}")
    finally:
        stop_event.set()
        poller_thread.join()
        if sensor_listener.is_alive(): sensor_listener.join()
        if fan_listener.is_alive(): fan_listener.join()
        logger.info("Master Controller shutdown complete.")
