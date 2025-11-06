import os
import json
import time
import math
import logging
from threading import Thread, Event

# Third-party libraries
from flask import Flask, render_template, request, jsonify
from flask_socketio import SocketIO, emit

# --- CONFIGURATION PATHS ---
NETWORK_CONFIG_PATH = '/opt/project/common/network_config.json'

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

# --- DATA STORES (Placeholder for real-time data) ---
# Last known status of the system
system_status = {
    "last_update": "N/A",
    "pid_setpoint": 20.0,
    "current_height": 0.0,
    "fan_output": 0,
    "fan_rpm": 0,
    "delay": 0.0,
    "loss_rate": 0.0
}

# Define a placeholder port for the Telemetry Listener for logging purposes
TELEMETRY_PORT = 5006 

def load_config():
    """Loads and returns network configuration from the JSON file."""
    try:
        if os.path.exists(NETWORK_CONFIG_PATH):
            with open(NETWORK_CONFIG_PATH, 'r') as f:
                return json.load(f)
        else:
            logger.warning(f"Network config file not found at {NETWORK_CONFIG_PATH}. Using defaults.")
            return {}
    except Exception as e:
        logger.error(f"Could not load network config at {NETWORK_CONFIG_PATH}. Using defaults. Error: {e}")
        return {}

# --- SOCKETIO EVENT HANDLERS ---

@socketio.on('connect')
def handle_connect():
    """Handles new client connection."""
    logger.info("Client connected to dashboard.")
    # Emit initial status upon connection
    emit('status_update', system_status)

@socketio.on('request_status')
def handle_status_request():
    """Responds to client requests for the current status."""
    emit('status_update', system_status)

@socketio.on('set_setpoint')
def handle_setpoint_change(data):
    """Handles a request to change the PID setpoint."""
    try:
        new_setpoint = float(data.get('setpoint', system_status['pid_setpoint']))
        # In a real system, this would send a command to the PID controller process
        if 5.0 <= new_setpoint <= 50.0:
            system_status['pid_setpoint'] = new_setpoint
            logger.info(f"Setpoint updated to: {new_setpoint} cm")
            emit('status_update', system_status, broadcast=True)
            return {"status": "ok", "message": f"Setpoint set to {new_setpoint} cm"}
        else:
            return {"status": "error", "message": "Setpoint must be between 5.0 and 50.0 cm."}
    except ValueError:
        return {"status": "error", "message": "Invalid setpoint value."}

@socketio.on('set_congestion')
def handle_congestion_change(data):
    """Handles a request to change network congestion settings."""
    try:
        # In a real system, this would modify the global variables in network_injector.py
        new_delay = float(data.get('delay', system_status['delay']))
        new_loss = float(data.get('loss_rate', system_status['loss_rate']))
        
        # Validation (example limits)
        if 0.0 <= new_delay <= 0.2 and 0.0 <= new_loss <= 100.0:
            system_status['delay'] = new_delay
            system_status['loss_rate'] = new_loss
            logger.info(f"Congestion updated: Delay={new_delay}s, Loss={new_loss}%")
            emit('status_update', system_status, broadcast=True)
            return {"status": "ok", "message": "Congestion parameters updated."}
        else:
            return {"status": "error", "message": "Delay must be 0-0.2s, Loss must be 0-100%."}
    except ValueError:
        return {"status": "error", "message": "Invalid congestion value."}

# --- FLASK ROUTES ---

@app.route('/')
def index():
    """Serves the main dashboard page using the external template."""
    return render_template('index.html')

# --- POLLER THREAD (Simulates data fetching from PID loop) ---

stop_event = Event()

def status_poller():
    """Thread that periodically updates system_status and emits it to clients."""
    while not stop_event.is_set():
        # --- SIMULATION/MOCK DATA UPDATE ---
        current_time = time.time()
        
        # Simple oscillation for demonstration purposes
        setpoint = system_status['pid_setpoint']
        system_status['current_height'] = setpoint + 1.5 * math.sin(current_time / 4.0)
        system_status['fan_output'] = (setpoint * 2) + 10 * math.cos(current_time / 2.5) 
        system_status['fan_output'] = max(0, min(100, system_status['fan_output'])) # Clamp to 0-100
        system_status['fan_rpm'] = int(system_status['fan_output'] * 15) # Mock RPM
        system_status['last_update'] = time.strftime('%H:%M:%S')

        # Emit the new status to all connected clients
        socketio.emit('status_update', system_status)
        
        time.sleep(1.0) # Update rate: 1 second

poller_thread = Thread(target=status_poller)


# --- MAIN EXECUTION ---

def main():
    """Loads config and starts the Flask/SocketIO server."""
    config = load_config()

    # Read network details from config
    web_app_ip = config.get('WEB_APP_IP', '0.0.0.0')
    web_app_port = config.get('WEB_SERVER_PORT', 8000)
    fan_ip = config.get('FAN_NODE_IP', '192.168.22.1')
    fan_port = config.get('FAN_PORT', 5005)
    sensor_ip = config.get('SENSOR_NODE_IP', '192.168.22.2')

    # --- LOGGING CONFIGURATION (Restored the requested detailed output) ---
    logger.info("Configuration loaded:")
    logger.info(f"  Status Listener: {web_app_ip}:{web_app_port}") 
    logger.info(f"  Telemetry Listener: {web_app_ip}:{TELEMETRY_PORT}")
    logger.info(f"  Fan IP: {fan_ip}:{fan_port}")

    # Start the data poller thread
    poller_thread.start()

    logger.info(f"Master Controller is running. Access the dashboard at: http://{sensor_ip}:{web_app_port}")

    try:
        # allow_unsafe_werkzeug=True is useful in some containerized/embedded environments
        socketio.run(app, host=web_app_ip, port=web_app_port, allow_unsafe_werkzeug=True)
    except KeyboardInterrupt:
        logger.info("Controller stopped manually.")
    finally:
        stop_event.set()
        poller_thread.join()
        logger.info("Sockets closed. Clean exit.")

if __name__ == '__main__':
    main()
