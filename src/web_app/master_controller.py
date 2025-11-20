#!/usr/bin/env python3
from gevent import monkey
from gevent.pywsgi import WSGIServer
from geventwebsocket.handler import WebSocketHandler
monkey.patch_all()

# Standard libraries
import os
import subprocess
import json
import time
import math
import logging
import socket
import threading

# Third-party libraries
from flask import Flask, render_template, request, jsonify
from flask_socketio import SocketIO, emit

# --- Import Experiment Manager Components ---
from experiment_manager import IperfExperiment, StressExperiment, ExperimentManager 
# -------------------------------------------------

# --- CONFIGURATION PATHS ---
# The primary network config
NETWORK_CONFIG_FILE = '/opt/project/common/network_config.json'
# Config for PID Setpoint
SETPOINT_CONFIG_FILE = '/opt/project/common/setpoint_config.json'
# Config for Network Congestion & Experiment Type
CONGESTION_CONFIG_FILE = '/opt/project/common/congestion_config.json'

# --- NETWORK CONFIGURATION (Defaults) ---
# We've migrated to common json configuration files that get loaded by load_network_config. 
# These are all safe default values to use until load_network_config replaces them. 
fan_command_ip = "127.0.0.1"
fan_command_port = 5005
sensor_ip = "127.0.0.1"
sensor_command_port = 5004
sensor_telemetry_port = 5006
fan_telemetry_port = 5007
web_app_port = 8000
web_app_ip = "0.0.0.0" # Listen on all interfaces


# --- Global State for In-Process Experiment Control ---
# Tracks the currently running ExperimentManager instance
active_experiment: ExperimentManager | None = None 
experiment_lock = threading.Lock() # Protects access to the active_experiment object
# -----------------------------------------------------------


# --- LOGGING SETUP ---
# Set up logging with the desired [Master] prefix
logging.basicConfig(level=logging.INFO, format='[Master] %(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

# --- WEB & SOCKETIO SETUP ---
app = Flask(__name__)
app.config['SECRET_KEY'] = 'your_secret_key_here' # Needed for session management
socketio = SocketIO(app, async_mode='gevent', cors_allowed_origins="*") 

# --- SYSTEM STATE ---
system_status = {
    "current_distance": 0.0,
    "current_rpm": 0,
    "fan_output_duty": 0.0,
    "pid_status": 'STOPPED',
    "pid_setpoint": 20.0,

    # oscillation visual support
    "oscillation_a": 20.0,
    "oscillation_b": 30.0,
    "pid_next_setpoint": 30.0,
    "pid_switch_in": 0.0,
    "oscillation_enabled": False,
    "oscillation_period": 20.0,

    "experiment_name": 'none',
    "tc_status": 'REMOVED',
    "delay": 0,
    "loss_rate": 0.0,
    "load_magnitude": 0.0,
    "master_timestamp": time.time()
}
status_lock = threading.Lock()
stop_event = threading.Event()


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

# --- INITIALIZE CONFIG FILES ---
def initialize_config_files():
    """Ensures the congestion/setpoint config files exists with default values."""
    update_status_file(CONGESTION_CONFIG_FILE, 'CONGESTION_DELAY', 0.0)
    update_status_file(CONGESTION_CONFIG_FILE, 'PACKET_LOSS_RATE', 0.0)
    update_status_file(SETPOINT_CONFIG_FILE, 'PID_SETPOINT', 20)
    #update_status_file(SETPOINT_CONFIG_FILE, 'PID_STATUS', 'STOPPED')

    # Ensure traffic rules are cleared on start
    command = ['systemctl', 'stop', 'tc_controller.service']
    subprocess.run(command, check=False, text=True, capture_output=True, timeout=5)
    update_status_file(CONGESTION_CONFIG_FILE, 'TC_STATUS', 'REMOVED')
    
    # Ensure load is cleared on start
    command = ['systemctl', 'stop', 'experiment_controller.service']
    subprocess.run(command, check=False, text=True, capture_output=True, timeout=5)
    update_status_file(CONGESTION_CONFIG_FILE, 'LOAD_TYPE', 'none')
    
    # Ensure in-process experiment is stopped on start
    run_experiment_handler_internal('stop_load', 'none')


# --- DATA LISTENERS ---

def sensor_data_listener(listen_ip, port):
    """Listens for ball distance and PID status updates from the sensor node."""
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
                    scaled_duty = 0.0
                    if raw_duty is not None and isinstance(raw_duty, (int, float)):
                        scaled_duty = round((raw_duty / 255.0) * 100, 1)

                    with status_lock:
                        system_status["current_distance"] = packet.get("current_distance", system_status["current_distance"])
                        system_status["fan_output_duty"] = scaled_duty
                        system_status["pid_status"] = packet.get("pid_status", system_status["pid_status"])

                        # FIELDS FOR OSCILLATION
                        system_status["oscillation_a"] = packet.get("oscillation_a", system_status["oscillation_a"])
                        system_status["oscillation_b"] = packet.get("oscillation_b", system_status["oscillation_b"])
                        system_status["pid_next_setpoint"] = packet.get("pid_next_setpoint", system_status["pid_next_setpoint"])
                        system_status["pid_switch_in"] = packet.get("pid_switch_in", system_status["pid_switch_in"])

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
                        system_status["current_rpm"] = packet.get("fan_rpm", system_status["current_rpm"])
                        system_status["master_timestamp"] = time.time()
                except json.JSONDecodeError:
                    logger.warning("Received invalid JSON from fan node.")
                except Exception as e:
                    logger.error(f"Error processing fan data: {e}")
        except Exception as e:
            logger.error(f"Fan listener error: {e}")
        finally:
            logger.info("Fan data listener stopped.")


# --- NEW: EXPERIMENT MANAGEMENT LOGIC ---
def experiment_finished_callback():
    """
    Called by an ExperimentManager thread when a timed experiment (like Iperf 60s UDP) 
    completes naturally. This updates the global state as if a 'stop_load' command 
    was received and processed.
    """
    global active_experiment
    global experiment_lock

    logger.info("[CALLBACK] Automatic STOP triggered by natural experiment completion.")
    
    with experiment_lock:
        # 1. Update the config file
        load_success = update_status_file(CONGESTION_CONFIG_FILE, 'LOAD_TYPE', 'none')

        # 2. Update the system status immediately
        with status_lock:
            system_status["experiment_name"] = 'none'
            system_status["load_magnitude"] = 0.0

        # 3. Clean up the active_experiment reference
        if active_experiment:
            # We don't call active_experiment.stop() here, as the worker 
            # thread calling this callback has already started the stop sequence.
            active_experiment = None
            
        if load_success:
            # Optionally emit an acknowledgement to the web app for UI confirmation
            # Note: Emitting from non-socket threads requires app/socket context.
            # If you are using Flask-SocketIO, you might need: 
            # socketio.emit('command_ack', {'success': True, 'message': 'Experiment completed naturally.'})
            emit('command_ack', {'success': True, 'message': f'Experiment finished.'})
            logger.info("[CALLBACK] Global state successfully reset to 'none'.")
        else:
            logger.error("[CALLBACK] Failed to update status file during natural stop.")

def run_experiment_handler_internal(action: str, new_load_type: str):
    """
    Manages the lifecycle of the background load/telemetry threads in-process.
    This replaces the systemctl calls for experiment_controller.service.
    """
    global active_experiment
    global experiment_lock
    
    # Standardize load type
    new_load_type = new_load_type.lower()
    
    with experiment_lock:
        current_load_type = active_experiment.worker_thread.name.replace('Experiment', '').lower() if active_experiment else 'none'
        
        # --- 1. Handle STOP Command ---
        if action == 'stop_load':
            if active_experiment:
                logger.info(f"[EXPERIMENT] Stopping active experiment: {current_load_type}")
                active_experiment.stop()
                active_experiment = None
                
            # Always zero out the load magnitude for immediate UI feedback
            with status_lock:
                system_status["load_magnitude"] = 0.0
            return

        # --- 2. Handle START Command ---
        if action == 'start_load':
            # A. Check if the same experiment is already running
            if current_load_type == new_load_type:
                logger.info(f"[EXPERIMENT] Load type '{new_load_type}' already running. Ignoring start command.")
                return

            # B. Stop existing experiment if running a different type
            if active_experiment:
                logger.info(f"[EXPERIMENT] Transitioning from '{current_load_type}' to '{new_load_type}'. Stopping current experiment.")
                active_experiment.stop()
                active_experiment = None

            # C. Initialize and start the new experiment
            new_experiment = None
            if new_load_type == 'iperf':
                new_experiment = IperfExperiment()
                new_experiment.set_finish_callback(experiment_finished_callback)
            elif new_load_type == 'stress':
                # Note: Stress test is manually stopped
                new_experiment = StressExperiment()
            elif new_load_type == 'none':
                logger.info("[EXPERIMENT] Passive mode selected (no load).")
                return
            else:
                logger.warning(f"[EXPERIMENT] Unknown load type '{new_load_type}'. Not starting.")
                return

            # D. Start the new experiment
            if new_experiment:
                active_experiment = new_experiment
                active_experiment.start()
                logger.info(f"[EXPERIMENT] New experiment '{new_load_type}' started in background.")


# --- SOCKETIO (WEB DASHBOARD) HANDLERS ---

@app.route('/')
def index():
    """Renders the main dashboard."""
    return render_template('index.html')
    
@socketio.on('set_oscillation')
def handle_oscillation_update(data):
    """Handles oscillation A/B/PERIOD updates from the dashboard."""

    osc_enabled = data.get('enabled')
    osc_a = data.get('a')
    osc_b = data.get('b')
    osc_period = data.get('period')

    ok = True

    # Only update values that were provided
    if osc_enabled is not None:
        ok &= update_status_file(SETPOINT_CONFIG_FILE, 'OSCILLATION_ENABLED', osc_enabled)

    if osc_a is not None:
        ok &= update_status_file(SETPOINT_CONFIG_FILE, 'OSCILLATION_A', osc_a)

    if osc_b is not None:
        ok &= update_status_file(SETPOINT_CONFIG_FILE, 'OSCILLATION_B', osc_b)

    if osc_period is not None:
        ok &= update_status_file(SETPOINT_CONFIG_FILE, 'OSCILLATION_PERIOD_SEC', osc_period)

    # Update server-side cache
    with status_lock:
        if osc_enabled is not None:
            system_status["oscillation_enabled"] = osc_enabled
        if osc_a is not None:
            system_status["oscillation_a"] = osc_a
        if osc_b is not None:
            system_status["oscillation_b"] = osc_b
        if osc_period is not None:
            system_status["oscillation_period"] = osc_period

    if ok:
        emit('command_ack', {'success': True, 'message': 'Oscillation settings updated.'})
    else:
        emit('command_ack', {'success': False, 'message': 'Failed to update oscillation settings.'})

@socketio.on('set_setpoint')
def handle_setpoint_update(data):
    """Handles setpoint changes from the dashboard."""
    new_setpoint = data.get('setpoint')
    if new_setpoint is not None:
        if update_status_file(SETPOINT_CONFIG_FILE, 'PID_SETPOINT', new_setpoint):
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
        if update_status_file(CONGESTION_CONFIG_FILE, 'CONGESTION_DELAY', delay) and \
           update_status_file(CONGESTION_CONFIG_FILE, 'PACKET_LOSS_RATE', loss):
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
    # Get action & load_type from the incoming data payload (sent by the web client)
    action = data.get('action')
    load_type = data.get('load_type', 'none').lower() # Default to 'none'

    # This handles the Start/Stop PID button 
    if action in ['start', 'stop']:
        new_pid_status = 'RUNNING' if action == 'start' else 'STOPPED'

        # Signal the PID controller via config file
        pid_success = update_status_file(SETPOINT_CONFIG_FILE, 'PID_STATUS', new_pid_status)

        if pid_success:
            emit('command_ack', {'success': True, 'message': f'PID set to {new_pid_status}. Controller should {action} shortly.'})
        else:
            emit('command_ack', {'success': False, 'message': f'Failed to signal PID {action}.'})

    # --- REFACTORED: Load Management ---
    if action in ['start_load', 'stop_load', 'stop']:
        # In case Stop PID is clicked, stop here as well
        load_action = 'start_load' if action == 'start_load' else 'stop_load'

        # 1. Manage the in-process experiment thread
        run_experiment_handler_internal(load_action, load_type)

        # 2. Update the config file (for external monitoring/scripts that rely on it)
        typeToLog = load_type if load_action == 'start_load' else 'none'
        load_success = update_status_file(CONGESTION_CONFIG_FILE, 'LOAD_TYPE', typeToLog)
        # Update the experiment_name in system_status immediately
        with status_lock:
            system_status["experiment_name"] = typeToLog

        # 3. Send acknowledgement
        if load_success and load_action != 'start_load':
            emit('command_ack', {'success': True, 'message': f'Experiment terminated. Load Magnitude reset.'})
        elif load_success:
            emit('command_ack', {'success': True, 'message': f'Experiment started: {load_type.upper()}.'})
        else:
             emit('command_ack', {'success': False, 'message': f'Failed to signal experiment action.'})


    # --- TC Management ---
    if action in ['apply_tc', 'remove_tc', 'stop']:
        # In case Stop PID is clicked, stop here as well
        tc_action = 'apply_tc' if action == 'apply_tc' else 'remove_tc'

        # Map the web action to the systemctl command
        systemctl_command = 'start' if tc_action == 'apply_tc' else 'stop'
        service_name = 'tc_controller.service'
        command = ['systemctl', systemctl_command, service_name]
        action_status = 'APPLIED' if tc_action == 'apply_tc' else 'REMOVED'

        try:
            # check=True raises an exception for non-zero exit codes (failure)
            # text=True handles input/output as strings
            # capture_output=True captures stdout/stderr
            # Add a timeout in case systemctl hangs
            subprocess.run(command, check=True, text=True, capture_output=True, timeout=5)
            
            # Write the applied ruleset to the config file.
            tc_status_success = update_status_file(CONGESTION_CONFIG_FILE, 'TC_STATUS', action_status)
            if not tc_status_success:
                emit('command_ack', {'success': False, 'message': 'Failed to write TC config.'})
                return
            with status_lock:
                system_status["tc_status"] = action_status
            emit('command_ack', {'success': True, 'message': f'Successfully executed: {systemctl_command.upper()} {service_name}.'})
        except subprocess.CalledProcessError as e:
            # Handle command failure (e.g., systemctl failed to start the service)
            error_msg = f"Systemctl failed: {e.stderr.strip()}"
            logger.error(f"ERROR executing TC command: {error_msg}")
            emit('command_ack', {'success': False, 'message': f'TC Action Failed: {error_msg}'})
        except subprocess.TimeoutExpired:
            # Handle timeout
            emit('command_ack', {'success': False, 'message': f'TC Action Timed Out. Systemctl unresponsive.'})
        except FileNotFoundError:
            # Handle case where 'systemctl' command itself is not found
            emit('command_ack', {'success': False, 'message': f'Systemctl command not found. Is Systemd installed?'})


# --- POLLER THREAD ---

def read_experiment_status():
    """Reads the current experiment type from the status file."""
    # Deprecated function is maintained but logic is unused.
    pass

def status_poller():
    """A thread that continuously emits the latest system status to all connected clients."""
    global system_status, active_experiment
    while not stop_event.is_set():
        
        # --- NEW: Get Telemetry (Load Magnitude) from active thread ---
        current_load_magnitude = 0.0
        current_load_name_from_thread = 'none'

        with experiment_lock:
            if active_experiment:
                current_load_magnitude = active_experiment.get_latest_metric()
                # Use the thread name to determine current experiment type
                current_load_name_from_thread = active_experiment.worker_thread.name.replace('Experiment', '').lower()
        # -----------------------------------------------------------------

        # Update the system_status object and then emit
        with status_lock:
            
            # Read PID status, Congestion settings, Load Type, and TC Status from config files
            try:
                with open(SETPOINT_CONFIG_FILE, 'r') as f:
                    setpoint_data = json.load(f)
                    system_status["pid_setpoint"] = setpoint_data.get('PID_SETPOINT', 20.0)
                    system_status["pid_status"] = setpoint_data.get('PID_STATUS', system_status["pid_status"])

                    # NEW: oscillation settings (keep them in sync with config + sensor)
                    system_status["oscillation_enabled"] = setpoint_data.get(
                        'OSCILLATION_ENABLED', system_status.get("oscillation_enabled", False)
                    )
                    system_status["oscillation_a"] = setpoint_data.get(
                        'OSCILLATION_A', system_status["oscillation_a"]
                    )
                    system_status["oscillation_b"] = setpoint_data.get(
                        'OSCILLATION_B', system_status["oscillation_b"]
                    )
                    system_status["oscillation_period"] = setpoint_data.get(
                        'OSCILLATION_PERIOD_SEC', system_status.get("oscillation_period", 20.0)
                    )
            except:
                pass # Use existing status if file read fails

            # Read congestion settings from config file
            try:
                with open(CONGESTION_CONFIG_FILE, 'r') as f:
                    congestion_data = json.load(f)
                    system_status["delay"] = congestion_data.get('CONGESTION_DELAY', 0)
                    system_status["loss_rate"] = congestion_data.get('PACKET_LOSS_RATE', 0.0)
                    system_status["experiment_name"] = congestion_data.get('LOAD_TYPE', 'none')
                    system_status["tc_status"] = congestion_data.get('TC_STATUS', 'REMOVED')
            except:
                pass # Use existing settings if file read fails
            
            # --- Overwrite Load Magnitude using in-process telemetry ---
            # This ensures real-time feedback of the background load's magnitude (Mbps or % CPU)
            system_status["load_magnitude"] = round(current_load_magnitude, 2)
            
            # Emit the current state
            # NOTE: We are emitting to the default namespace ('/')
            socketio.emit('status_update', system_status)
        
        # Poll every 250ms 
        time.sleep(0.25)

def telemetry_listener(listen_ip, port):
    """
    Deprecated: This function is kept for reference but should be replaced 
    by sensor_data_listener and fan_data_listener.
    """
    logger.warning("Telemetry Listener thread is deprecated and replaced by dedicated listeners.")
    pass

# --- MAIN EXECUTION ---
if __name__ == '__main__':
    initialize_config_files()
    load_network_config()

    # Start the status poller thread (sends system_status to dashboard clients)
    poller_thread = threading.Thread(target=status_poller)
    poller_thread.start()

    # Start the new continuous telemetry listener threads
    sensor_listener = threading.Thread(target=sensor_data_listener, args=(web_app_ip, sensor_telemetry_port), daemon=True)
    fan_listener = threading.Thread(target=fan_data_listener, args=(web_app_ip, fan_telemetry_port), daemon=True)
    sensor_listener.start()
    fan_listener.start()

    logger.info(f"Master Controller is running. Access the dashboard at: http://{sensor_ip}:{web_app_port}")

    try:
        logger.info("Starting SocketIO server with Gevent WSGI Server...")

        # The WSGIServer handles both Flask/HTTP and SocketIO connections
        http_server = WSGIServer((web_app_ip, web_app_port), app, handler_class=WebSocketHandler)
        http_server.serve_forever()

    except KeyboardInterrupt:
        logger.info("Controller stopped manually.") 
    except Exception as e:
        logger.error(f"Failed to start web server: {e}")
    finally:
        stop_event.set()
        # Cleanly stop the background experiment thread before exiting
        run_experiment_handler_internal('stop_load', 'none') 
        poller_thread.join()
        logger.info("Master Controller shutdown complete.")
