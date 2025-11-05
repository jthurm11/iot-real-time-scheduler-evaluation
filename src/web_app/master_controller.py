import time
import threading
import json
import socket
import subprocess
import os
from flask import Flask, render_template, request
from flask_socketio import SocketIO, emit, join_room, leave_room
import logging

# Set up logging for the Flask app
logging.basicConfig(level=logging.INFO, format='[Flask Master] %(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

# --- CONFIGURATION (Derived from user scripts) ---
ALPHA_NODE_HOST = "192.168.22.1"     # Fan Node IP (from sensor_PIDcontroller.py)
FAN_PORT = 5005                     # Port for fan UDP commands
UDP_DATA_PORT = 5006                # New dedicated port for real-time data ingestion from controllers
REMOTE_PROJ_PATH = "/opt/project"

# PID Constants (From pid_controller.py initialization)
PID_CONFIG = {
    'Kp': 0.25,
    'Ki': 0.15,
    'Kd': 0.005,
    'SETPOINT': 20.0, # Desired height (cm)
    'SAMPLE_TIME': 0.1 # Control interval (s)
}

# --- Global State Management ---
# This holds the latest complete snapshot of the system state
experiment_state = {
    'status': 'stopped', # 'running' or 'stopped'
    'tc_enabled': False,
    'load_test_running': 'none', # 'iperf', 'stress', or 'none'
    'config': PID_CONFIG,
    # 'data' fields will be updated by the UDP listener thread
    'data': {
        'sensor': {
            'distance': 0.0, 'setpoint': PID_CONFIG['SETPOINT'], 
            'pid_output': 0.0, 'pid_error': 0.0, 
            'applied_delay_s': 0.005, # Default from network_injector.py
            'applied_loss_p': 0.0,    # Default from network_injector.py
            'ts': 0
        },
        'fan': {
            'duty_cycle': 0, 
            'measured_rpm': 0, 
            'ts': 0
        }
    }
}

# --- Flask and SocketIO Initialization ---
app = Flask(__name__)
app.config['SECRET_KEY'] = 'iot_traffic_scheduler_key' 
socketio = SocketIO(app, cors_allowed_origins="*") 

# --- UDP Listener for Real-Time Data ---

def udp_listener_thread():
    """Listens on UDP_DATA_PORT (5006) for real-time JSON data from controllers."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    
    # Try binding to both 0.0.0.0 and 127.0.0.1 to cover local and network use
    try:
        sock.bind(('0.0.0.0', UDP_DATA_PORT))
        logger.info(f"UDP Listener started on port {UDP_DATA_PORT}. Awaiting data from controllers.")
    except Exception as e:
        logger.error(f"Failed to bind UDP socket: {e}")
        return

    while True:
        try:
            data, addr = sock.recvfrom(1024)
            data_str = data.decode('utf-8').strip()
            
            # Data should be a JSON string, e.g., '{"type": "sensor", ...}'
            if data_str:
                data_json = json.loads(data_str)
                data_type = data_json.get("type")
                
                if data_type == 'sensor':
                    # Update sensor data fields
                    experiment_state['data']['sensor'].update({
                        'distance': data_json.get('h', 0.0),
                        'setpoint': data_json.get('sp', PID_CONFIG['SETPOINT']),
                        'pid_output': data_json.get('out', 0.0),
                        'pid_error': data_json.get('err', 0.0),
                        'applied_delay_s': data_json.get('delay_s', 0.0),
                        'applied_loss_p': data_json.get('loss_p', 0.0),
                        'ts': time.time()
                    })
                    # Use applied_delay_s/loss_p to update the top-level delay/loss state
                    experiment_state['net_delay_ms'] = int(data_json.get('delay_s', 0.0) * 1000)
                    experiment_state['packet_loss_percent'] = data_json.get('loss_p', 0.0)

                elif data_type == 'fan':
                    # Update fan data fields
                    experiment_state['data']['fan'].update({
                        'duty_cycle': data_json.get('duty', 0),
                        'measured_rpm': data_json.get('rpm', 0),
                        'ts': time.time()
                    })
                
                # Broadcast the new data to all connected web clients via SocketIO
                # We send the entire 'data' object
                socketio.emit('realtime_data', experiment_state['data'], room='dashboard_room')

        except json.JSONDecodeError:
            logger.warning(f"Received malformed JSON data: {data.decode('utf-8')}")
        except Exception as e:
            logger.error(f"Error in UDP listener: {e}")
            time.sleep(1)


# --- Routes ---

@app.route('/')
def index():
    """Renders the main dashboard page."""
    return render_template('index.html', state=experiment_state)

# --- SocketIO Event Handlers for Controls ---

@socketio.on('connect')
def handle_connect():
    """Sends the current state upon connection."""
    logger.info(f'Client connected: {request.sid}')
    join_room('dashboard_room')
    emit('update_state', experiment_state) # Send current state to new client

@socketio.on('control_master')
def handle_master_control(data):
    """Handles the Start/Stop experiment command (via systemd)."""
    command = data.get('command')
    logger.info(f"Master control command: {command}")
    
    if command == 'start' and experiment_state['status'] != 'running':
        experiment_state['status'] = 'running'
        start_experiment_services() 
    elif command == 'stop' and experiment_state['status'] != 'stopped':
        experiment_state['status'] = 'stopped'
        stop_experiment_services()

    emit('update_state', experiment_state, room='dashboard_room')


@socketio.on('control_congestion')
def handle_congestion_control(data):
    """Handles dynamic adjustment of simulated Network Delay and Packet Loss."""
    # We trust the frontend data as it comes from a slider
    delay_ms = int(data.get('delay', 0))
    loss_perc = float(data.get('loss', 0.0))
    
    # The network_injector.py script needs to be runnable via command line
    # and update its internal global variables for delay/loss simulation.
    # The most robust way is to stop/restart the PID script or force it 
    # to reload the network_injector module/settings.
    
    # For now, we will assume a simple script call that updates the PID
    # script's configuration file or uses an IPC mechanism to change the values.
    # We will shell out to a script that modifies the settings in network_injector.py
    
    # Using the experiment_manager.sh as a guide, these changes are applied
    # when the PID loop starts, so we need a way to apply them dynamically 
    # without restarting. Since the controller is already running, we'll 
    # assume the local network_injector.py script is callable for this purpose.
    
    try:
        # Note: You need a CLI wrapper in network_injector.py to actually apply these settings
        subprocess.run([
            f'{REMOTE_PROJ_PATH}/beta/network_injector_cli.py', 
            '--set-delay', str(delay_ms), 
            '--set-loss', str(loss_perc)
        ])
        logger.info(f"Applied congestion: Delay={delay_ms}ms, Loss={loss_perc}%")
        
        # Update the state to reflect the commanded values immediately
        experiment_state['net_delay_ms'] = delay_ms
        experiment_state['packet_loss_percent'] = loss_perc
        experiment_state['data']['sensor']['applied_delay_s'] = delay_ms / 1000.0
        experiment_state['data']['sensor']['applied_loss_p'] = loss_perc

    except Exception as e:
        logger.error(f"Error applying congestion settings: {e}")

    emit('update_state', experiment_state, room='dashboard_room')


@socketio.on('control_scheduler')
def handle_scheduler_control(data):
    """Handles the Apply/Remove tc prioritization rules command."""
    command = data.get('command') # 'apply' or 'remove'
    logger.info(f"Scheduler control command: {command}")

    # Use the logic from experiment_manager.sh: setup_tc / teardown_tc
    try:
        if command == 'apply':
            subprocess.run(['sudo', f'{REMOTE_PROJ_PATH}/setup_nodes.sh', 'setup_tc'], check=True) # Assuming this script handles TC setup
            experiment_state['tc_enabled'] = True
        elif command == 'remove':
            subprocess.run(['sudo', f'{REMOTE_PROJ_PATH}/setup_nodes.sh', 'teardown_tc'], check=True) # Assuming this script handles TC teardown
            experiment_state['tc_enabled'] = False
        
        logger.info(f"Traffic Control rules {command.upper()} command sent.")

    except subprocess.CalledProcessError as e:
        logger.error(f"TC command failed: {e}")

    emit('update_state', experiment_state, room='dashboard_room')


@socketio.on('control_load')
def handle_load_control(data):
    """Handles the Start/Stop background load command."""
    command = data.get('command') # e.g., 'start_iperf', 'stop_load'
    logger.info(f"Load control command: {command}")

    # Use the logic from experiment_manager.sh: start_load / stop_load
    try:
        if command.startswith('start_'):
            load_type = command.split('_')[1]
            # Use the experiment_manager.sh 'run' command to start load
            subprocess.run(['sudo', f'{REMOTE_PROJ_PATH}/setup_nodes.sh', 'run', load_type, 'wlan0', ALPHA_NODE_HOST], check=True)
            experiment_state['load_test_running'] = load_type
        elif command == 'stop_load':
            # Use the experiment_manager.sh 'teardown' command to stop load and tc
            subprocess.run(['sudo', f'{REMOTE_PROJ_PATH}/setup_nodes.sh', 'teardown'], check=True) 
            experiment_state['load_test_running'] = 'none'
            experiment_state['tc_enabled'] = False # Teardown removes TC rules

    except subprocess.CalledProcessError as e:
        logger.error(f"Load command failed: {e}")
        experiment_state['load_test_running'] = 'error' # Indicate failure

    emit('update_state', experiment_state, room='dashboard_room')

# --- Helper Functions (Using systemd service names from user's directory structure) ---

def start_experiment_services():
    """Starts sensor_PIDcontroller.service locally and fan_controller.service remotely."""
    try:
        # Local: Start sensor (Beta Node)
        subprocess.run(['sudo', 'systemctl', 'start', 'sensor_controller.service'], check=True)
        # Remote: Start fan (Alpha Node)
        # Note: The user mentioned fan_controller.service on Alpha, but experiment_manager.sh uses sensor_controller.service on the Fan Node
        subprocess.run(['ssh', ALPHA_NODE_HOST, 'sudo', 'systemctl', 'start', 'fan_controller.service'], check=True) 
        logger.info("Experiment services START command sent successfully.")
    except subprocess.CalledProcessError as e:
        logger.error(f"Failed to start services: {e}")

def stop_experiment_services():
    """Stops sensor_PIDcontroller.service locally and fan_controller.service remotely."""
    try:
        # Local: Stop sensor (Beta Node)
        subprocess.run(['sudo', 'systemctl', 'stop', 'sensor_controller.service'], check=True)
        # Remote: Stop fan (Alpha Node)
        subprocess.run(['ssh', ALPHA_NODE_HOST, 'sudo', 'systemctl', 'stop', 'fan_controller.service'], check=True)
        logger.info("Experiment services STOP command sent successfully.")
    except subprocess.CalledProcessError as e:
        logger.error(f"Failed to stop services: {e}")

# --- Main Execution ---

if __name__ == '__main__':
    # Start the UDP data listening thread in the background
    threading.Thread(target=udp_listener_thread, daemon=True).start()
    
    # Run the SocketIO server
    # Running on 0.0.0.0 makes it accessible from the network
    socketio.run(app, host='0.0.0.0', port=5001, debug=True, allow_unsafe_werkzeug=True)