import threading
import time
import socket
import json
import subprocess
import logging
import os
from flask import Flask, request, render_template
from flask_socketio import SocketIO, emit

# Set up logging for the master controller
logging.basicConfig(level=logging.INFO, format='[MASTER] %(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

# --- STATIC CONFIGURATION (Fixed Values) ---
STATIC_INTERFACE = 'wlan0'
STATIC_FAN_NODE_IP = '192.168.22.1'

# --- NETWORK CONFIGURATION ---
DATA_LISTEN_IP = '0.0.0.0'
DATA_LISTEN_PORT = 5006  # For real-time sensor and fan data
STATUS_LISTEN_IP = '0.0.0.0'
STATUS_LISTEN_PORT = 5007  # For experiment status updates (running/stopped)
WEB_SERVER_PORT = 8000
CONGESTION_CONFIG_FILE = 'congestion_config.json'
SETPOINT_CONFIG_FILE = 'setpoint_config.json' # New file for setpoint control

# Path to the experiment manager script
EXPERIMENT_MANAGER_SCRIPT = './experiment_manager.sh' 

# --- FLASK & SOCKETIO SETUP ---
app = Flask(__name__) 
socketio = SocketIO(app, 
                    cors_allowed_origins="*", 
                    logger=True, 
                    engineio_logger=True,
                    async_mode='threading' 
) 

# Shared event for signaling thread termination
stop_event = threading.Event()

# --- INITIALIZE CONFIG FILES ---
def initialize_congestion_config():
    """Ensures the congestion config file exists with default values."""
    default_config = {
        "delay_ms": 0,
        "loss_rate_perc": 0.0
    }
    if not os.path.exists(CONGESTION_CONFIG_FILE):
        try:
            with open(CONGESTION_CONFIG_FILE, 'w') as f:
                json.dump(default_config, f, indent=4)
            logger.info(f"Initialized {CONGESTION_CONFIG_FILE} with default values.")
        except IOError as e:
            logger.error(f"Failed to write initial config file: {e}")

def initialize_setpoint_config():
    """Ensures the setpoint config file exists with default value (20cm)."""
    # The default value must match the initial SETPOINT in sensor_PIDcontroller.py
    default_config = {
        "setpoint_cm": 20.0
    }
    if not os.path.exists(SETPOINT_CONFIG_FILE):
        try:
            with open(SETPOINT_CONFIG_FILE, 'w') as f:
                json.dump(default_config, f, indent=4)
            logger.info(f"Initialized {SETPOINT_CONFIG_FILE} with default setpoint.")
        except IOError as e:
            logger.error(f"Failed to write initial setpoint config file: {e}")

# --- SOCKETIO COMMAND HANDLERS ---

@socketio.on('start_experiment')
def handle_start_experiment(data):
    """Handles the START command from the web client."""
    
    load_type = data.get('load_type', 'none') 

    interface = STATIC_INTERFACE
    fan_node_ip = STATIC_FAN_NODE_IP
    
    command = [
        'sudo', 'bash', EXPERIMENT_MANAGER_SCRIPT, 
        'run', load_type, interface, fan_node_ip
    ]

    logger.info(f"Executing START command with LOAD_TYPE: {load_type} -> {' '.join(command)}")
    
    try:
        subprocess.Popen(command, 
                         stdout=subprocess.PIPE, 
                         stderr=subprocess.STDOUT)
        
        emit('command_ack', {
            'success': True,
            'message': f"Experiment start signal sent. Scenario: {load_type.capitalize()}"
        })
        
    except Exception as e:
        logger.error(f"Error starting experiment: {e}")
        emit('command_ack', {
            'success': False,
            'message': f"Error starting experiment: {str(e)}"
        })


@socketio.on('stop_experiment')
def handle_stop_experiment():
    """Handles the STOP command from the web client."""
    
    command = ['sudo', 'bash', EXPERIMENT_MANAGER_SCRIPT, 'teardown']

    logger.info(f"Executing STOP command: {' '.join(command)}")

    try:
        subprocess.Popen(command, 
                         stdout=subprocess.PIPE, 
                         stderr=subprocess.STDOUT)
                         
        emit('command_ack', {
            'success': True,
            'message': "Experiment teardown initiated."
        })
        
    except Exception as e:
        logger.error(f"Error stopping experiment: {e}")
        emit('command_ack', {
            'success': False,
            'message': f"Error stopping experiment: {str(e)}"
        })

@socketio.on('update_congestion')
def handle_congestion_update(data):
    """Receives slider values and updates the configuration file for the PID script."""
    delay_ms = data.get('delay_ms', 0)
    loss_rate_perc = data.get('loss_rate_perc', 0.0)
    
    new_config = {
        "delay_ms": delay_ms,
        "loss_rate_perc": loss_rate_perc
    }

    try:
        with open(CONGESTION_CONFIG_FILE, 'w') as f:
            json.dump(new_config, f, indent=4)
        
        logger.debug(f"Updated congestion config: Delay={delay_ms}ms, Loss={loss_rate_perc}%")
        
    except Exception as e:
        logger.error(f"Failed to update congestion config file: {e}")


@socketio.on('update_setpoint')
def handle_setpoint_update(data):
    """Receives the new setpoint value (cm) and updates the config file."""
    setpoint_cm = float(data.get('setpoint_cm', 20.0))
    
    new_config = {
        "setpoint_cm": setpoint_cm
    }

    try:
        with open(SETPOINT_CONFIG_FILE, 'w') as f:
            json.dump(new_config, f, indent=4)
        
        logger.info(f"Updated setpoint config: Setpoint={setpoint_cm} cm.")
        
        # Optional: Send a success message back to the UI, though it updates itself
        emit('command_ack', {
            'success': True,
            'message': f"Setpoint updated to {setpoint_cm} cm."
        })
        
    except Exception as e:
        logger.error(f"Failed to update setpoint config file: {e}")
        emit('command_ack', {
            'success': False,
            'message': f"Error updating setpoint: {str(e)}"
        })


# --- FLASK ROUTE ---

@app.route('/')
def index():
    """Renders the index.html template from the templates folder."""
    try:
        return render_template('index.html')
    except Exception as e:
        logger.error(f"Error rendering index.html template: {e}")
        return f"Internal Server Error: Could not load dashboard. Error: {e}", 500


# --- UDP LISTENER THREADS (Unchanged) ---

def udp_data_listener():
    """Listens for real-time sensor/fan data on UDP_LISTEN_PORT and forwards via SocketIO."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.bind((DATA_LISTEN_IP, DATA_LISTEN_PORT))
        logger.info(f"UDP Data Listener bound to {DATA_LISTEN_IP}:{DATA_LISTEN_PORT}")
    except Exception as e:
        logger.error(f"Failed to bind UDP data listener: {e}")
        return

    sock.settimeout(0.1)

    while not stop_event.is_set():
        try:
            data, addr = sock.recvfrom(1024)
            message = data.decode('utf-8')
            
            try:
                payload = json.loads(message)
                msg_type = payload.get('type')
                
                if msg_type in ['sensor', 'fan']:
                    with app.app_context():
                        socketio.emit(msg_type, payload)
                else:
                    logger.warning(f"Received unknown data type: {msg_type}")
                    
            except json.JSONDecodeError:
                logger.warning(f"Received non-JSON UDP data: {message}")

        except socket.timeout:
            continue
        except Exception as e:
            logger.error(f"Error in UDP data listener: {e}")
            break

    sock.close()
    logger.info("UDP Data Listener shut down.")


def udp_status_listener():
    """Listens for simple status updates on STATUS_LISTEN_PORT and forwards via SocketIO."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.bind((STATUS_LISTEN_IP, STATUS_LISTEN_PORT))
        logger.info(f"UDP Status Listener bound to {STATUS_LISTEN_IP}:{STATUS_LISTEN_PORT}")
    except Exception as e:
        logger.error(f"Failed to bind UDP status listener: {e}")
        return

    sock.settimeout(0.1)

    while not stop_event.is_set():
        try:
            data, addr = sock.recvfrom(1024)
            status = data.decode('utf-8').strip().lower()

            if status in ['running', 'stopped', 'error']:
                with app.app_context():
                    socketio.emit('experiment_status', {'status': status})
                    logger.info(f"Emitted new status: {status}")
            else:
                logger.warning(f"Received invalid status message: {status}")

        except socket.timeout:
            continue
        except Exception as e:
            logger.error(f"Error in UDP status listener: {e}")
            break

    sock.close()
    logger.info("UDP Status Listener shut down.")


def main():
    initialize_congestion_config()
    initialize_setpoint_config() # Initialize the new setpoint config
    logger.info("Starting UDP listeners in background threads...")
    
    data_thread = threading.Thread(target=udp_data_listener, daemon=True)
    status_thread = threading.Thread(target=udp_status_listener, daemon=True)
    
    data_thread.start()
    status_thread.start()
    
    logger.info(f"Starting Flask-SocketIO Web Server on port {WEB_SERVER_PORT}...")
    
    try:
        socketio.run(app, 
                     host='0.0.0.0', 
                     port=WEB_SERVER_PORT, 
                     debug=False,
                     allow_unsafe_werkzeug=True 
        )
        
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received. Shutting down...")
    except Exception as e:
        logger.error(f"Fatal error running web server: {e}")
        
    finally:
        stop_event.set()
        data_thread.join(timeout=2)
        status_thread.join(timeout=2)
        logger.info("All threads stopped. Master Controller exiting.")


if __name__ == '__main__':
    main()