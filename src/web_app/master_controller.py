import os
import json
import time
import math
import logging
import socket
from threading import Thread, Event

# Third-party libraries
from flask import Flask, render_template, request, jsonify
from flask_socketio import SocketIO, emit

# --- CONFIGURATION PATHS ---
# The primary network config
NETWORK_CONFIG_PATH = '/opt/project/common/network_config.json'
# Config for PID Setpoint (read by sensor_PIDcontroller.py)
SETPOINT_CONFIG_PATH = '/opt/project/common/setpoint_config.json'
# Config for Network Congestion (read by network_injector.py/sensor_PIDcontroller.py)
CONGESTION_CONFIG_PATH = '/opt/project/common/congestion_config.json'

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
    "fan_output": 0.0, # Changed to float for consistency
    "fan_rpm": 0,
    "delay": 0.0,
    "loss_rate": 0.0
}

# Define a placeholder port for the Telemetry Listener for logging purposes
TELEMETRY_PORT = 5006

# --- CONFIGURATION & INIT ---

def load_config():
    """Loads and returns network configuration from the JSON file."""
    try:
        if os.path.exists(NETWORK_CONFIG_PATH):
            with open(NETWORK_CONFIG_PATH, 'r') as f:
                return json.load(f)
        else:
            logger.warning(f"Network config file not found at: {NETWORK_CONFIG_PATH}. Using defaults.")
            return {}
    except Exception as e:
        logger.error(f"Could not load network config at {NETWORK_CONFIG_PATH}. Using defaults. Error: {e}")
        return {}

def load_initial_pid_status():
    """Loads initial PID setpoint and congestion values from their respective config files."""
    global system_status
    # 1. Load Setpoint
    try:
        if os.path.exists(SETPOINT_CONFIG_PATH):
            with open(SETPOINT_CONFIG_PATH, 'r') as f:
                config = json.load(f)
                system_status['pid_setpoint'] = config.get("PID_SETPOINT", 20.0)
                logger.info(f"Loaded initial PID Setpoint: {system_status['pid_setpoint']} cm")
    except Exception as e:
        logger.warning(f"Failed to load initial setpoint config: {e}")

    # 2. Load Congestion
    try:
        if os.path.exists(CONGESTION_CONFIG_PATH):
            with open(CONGESTION_CONFIG_PATH, 'r') as f:
                config = json.load(f)
                # NOTE: The master controller now expects and stores delay in MS
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
            save_config(SETPOINT_CONFIG_PATH, config_dict)
            
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
            save_config(CONGESTION_CONFIG_PATH, config_dict)
            
            logger.info(f"Congestion set: Delay={float_delay_ms:.0f}ms, Loss={float_loss_perc:.1f}%.")

            # Send a confirmation/acknowledgment back to the client
            emit('command_ack', {'message': f"Congestion set: Delay={float_delay_ms:.0f}ms, Loss={float_loss_perc:.1f}%.", 'success': True})
        except ValueError:
            emit('command_ack', {'message': "Invalid delay/loss value.", 'success': False})

# --- THREAD CONTROL EVENT (Used by Poller and Listener) ---
stop_event = Event()

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
        # Update timestamp for when this status was last collected/reported
        system_status['last_update'] = time.strftime('%H:%M:%S')

        # Emit the entire status object
        socketio.emit('status_update', system_status)
        
        time.sleep(1.0) # Update rate: 1 second

poller_thread = Thread(target=status_poller)


# --- TELEMETRY LISTENER THREAD ---
def telemetry_listener(host, port):
    """
    UDP server to listen for real-time telemetry updates (height, fan output, RPM) 
    from the Sensor/PID node. Updates the global system_status.
    """
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
    save_config(CONGESTION_CONFIG_PATH, initial_congestion_config)
    
    # =========================================================================

    # Read network details from config
    web_app_ip = config.get('WEB_APP_IP', '0.0.0.0')
    web_app_port = config.get('WEB_APP_PORT', 8000)
    fan_ip = config.get('FAN_NODE_IP', '192.168.22.1')
    fan_port = config.get('FAN_COMMAND_PORT', 5005)
    sensor_ip = config.get('SENSOR_NODE_IP', '192.168.22.2')
    
    # Load the actual telemetry listener port from config
    telemetry_listen_port = config.get('SENSOR_DATA_LISTEN_PORT', TELEMETRY_PORT)
    # Update the global placeholder for correct logging
    global TELEMETRY_PORT
    TELEMETRY_PORT = telemetry_listen_port

    # --- LOGGING CONFIGURATION (Restored the requested detailed output) ---
    logger.info("Configuration loaded:")
    logger.info(f"  Status Listener: {web_app_ip}:{web_app_port}") 
    logger.info(f"  Telemetry Listener: {web_app_ip}:{TELEMETRY_PORT}")
    logger.info(f"  Fan IP: {fan_ip}:{fan_port}")

    # Start the data poller thread (emits system_status to dashboard clients)
    poller_thread.start()
    
    # Start the telemetry receiver thread (updates system_status from Sensor node)
    telemetry_thread = Thread(target=telemetry_listener, args=(web_app_ip, telemetry_listen_port))
    telemetry_thread.daemon = True
    telemetry_thread.start()

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