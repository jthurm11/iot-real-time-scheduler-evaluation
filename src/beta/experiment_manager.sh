#!/bin/bash
# Real-Time Traffic Scheduler Experiment Manager

# --- CONFIGURATION ---
# The network interface to apply tc rules to (e.g., eth0, wlan0)
INTERFACE="wlan0"
# The IP address of the Fan Node (the target of UDP fan commands)
FAN_NODE_IP="192.168.22.1"
# UDP Port used by the fan controller node
FAN_PORT=5005
# Full path to main PID control script
PID_SCRIPT_PATH="/opt/project/beta/sensor_PIDcontroller.py"
# Name of the service running the *Fan Node's* control logic (if applicable)
FAN_NODE_SERVICE="sensor_controller.service"
# File where the detached PID process logs output
PID_LOG_FILE="/tmp/sensor_pid_controller.log"
# --- END CONFIGURATION ---

# Function log_message <reporting function> "<message>" LEVEL
# Usage: log_message $FUNCNAME "<message>" <LEVEL>
#   - LEVEL := { INFO | WARNING | ERROR | DEBUG }
log_message() {
    local reporter="$1" message="$2"
    local level="${3:-INFO}" # Default to INFO if not provided
    local timestamp=$(date +"%Y-%m-%d %H:%M:%S")
    local NC='\033[0m'   # No color

    case "${level}" in
        "INFO")    color='\033[0;36m';;  # Cyan
        "WARNING") color='\033[0;33m';;  # Yellow
        "ERROR")   color='\033[0;31m';;  # Red
        "DEBUG")   color='\033[0;35m';;  # Magenta
        *)         color="${NC}" ;; # Default to no color for unknown levels
    esac

    # Output to stderr to separate logs from potential command output
    echo -e "${color}${timestamp} ${reporter} [${level}]${NC} ${message}" 1>&2
}

# Check for root permissions
if [ "$(id -u)" -ne 0 ]; then
    log_message $0 "This script must be run with sudo or as root to use 'tc' and manage services." ERROR
    exit 1
fi

# --- CORE FUNCTIONS ---

function check_config() {
    if [ -z "$INTERFACE" ] || [ -z "$FAN_NODE_IP" ]; then
        log_message $FUNCNAME "INTERFACE and FAN_NODE_IP must be set in the script's configuration section." ERROR
        exit 1
    fi
}

function setup_tc() {
    log_message $FUNCNAME "Setting up Traffic Control (tc) rules on $INTERFACE" INFO

    # 1. Clear any existing configuration (ensures a clean start)
    tc qdisc del dev "$INTERFACE" root 2>/dev/null

    # 2. Add the root Queueing Discipline (HTB)
    # default 20 means any traffic not explicitly filtered goes to Class 20
    log_message $FUNCNAME "  > Adding root HTB QDisc (handle 1: default 20)" INFO
    tc qdisc add dev "$INTERFACE" root handle 1: htb default 20

    # B. Define Control Traffic Class (Class 10 - High Priority)
    log_message $FUNCNAME "  > Defining Control Class 1:10 (High Priority, Prio 1)" INFO
    tc class add dev "$INTERFACE" parent 1: classid 1:10 htb rate 100mbit ceil 100mbit prio 1

    # 3. Filter: Send Fan Control UDP packets (to $FAN_NODE_IP:$FAN_PORT) to Class 10
    log_message $FUNCNAME "  > Filtering UDP traffic to $FAN_NODE_IP:$FAN_PORT into Class 1:10" INFO
    tc filter add dev "$INTERFACE" protocol ip parent 1: prio 1 u3 \
        match ip dst "$FAN_NODE_IP" \
        match ip protocol 17 0xff \
        match ip dport "$FAN_PORT" 0xffff \
        flowid 1:10

    # C. Define Degraded/Background Traffic Class (Class 20 - Low Priority)
    log_message $FUNCNAME "  > Defining Background Class 1:20 (Low Priority, Prio 2)" INFO
    tc class add dev "$INTERFACE" parent 1: classid 1:20 htb rate 100mbit ceil 100mbit prio 2

    log_message $FUNCNAME "Traffic Control setup COMPLETE (Control traffic prioritized)." INFO
}

function teardown_tc() {
    log_message $FUNCNAME "Tearing down Traffic Control (tc) rules on $INTERFACE" INFO

    # Disable tc: Clear all traffic control rules
    tc qdisc del dev "$INTERFACE" root 2>/dev/null

    log_message $FUNCNAME "Traffic Control TEARDOWN COMPLETE (Standard network behavior restored)." INFO
}

function stop_processes() {
    log_message $FUNCNAME "Stopping Existing Processes" INFO

    # 1. Stop Fan Node Service (if running)
    if systemctl is-active --quiet "$FAN_NODE_SERVICE"; then
        log_message $FUNCNAME "  > Stopping Fan Node service: $FAN_NODE_SERVICE" INFO
        systemctl stop "$FAN_NODE_SERVICE"
    else
        log_message $FUNCNAME "  > Fan Node service ($FAN_NODE_SERVICE) is not running." INFO
    fi

    # 2. Stop local PID control script (if running)
    PID_PROCESS=$(pgrep -f "$PID_SCRIPT_PATH")
    if [ -n "$PID_PROCESS" ]; then
        log_message $FUNCNAME "  > Stopping running PID controller (PIDs: $PID_PROCESS)" WARNING
        kill -9 "$PID_PROCESS" 2>/dev/null
    else
        log_message $FUNCNAME "  > No local PID controller found running." INFO
    fi
}

function start_pid() {
    log_message $FUNCNAME "Starting PID Controller: $PID_SCRIPT_PATH" INFO

    # Ensure log file is clean before launch
    > "$PID_LOG_FILE"

    # Use nohup and & as a generic, reliable backgrounding method.
    log_message $FUNCNAME "  > Launching PID controller in background. Output logged to $PID_LOG_FILE" INFO

    # May need to replace 'python3' with specific environment alias if using a venv
    nohup python3 "$PID_SCRIPT_PATH" &

    # The disowned PID process ID is stored in the background variable $!
    PID=$!
    log_message $FUNCNAME "  > PID Controller launched with PID: $PID" INFO
    log_message $FUNCNAME "  > To monitor output: tail -f $PID_LOG_FILE" INFO
}

function start_load() {
    local load_type="$1"
    log_message $FUNCNAME "Starting Background Load: $load_type" INFO

    case "$load_type" in
        "iperf")
            # Assumes iperf3 server is running on a remote machine (e.g., the Fan Node)
            # Run iperf3 client in the background, targeting the remote server
            log_message $FUNCNAME "  > Starting iperf3 client to generate background network load." INFO
            log_message $FUNCNAME "  > This requires an iperf3 server listening on the Fan Node or another destination." WARNING
            # Run for 600 seconds (10 minutes) and send output to /dev/null
            iperf3 -c "$FAN_NODE_IP" -t 600 -P 4 --daemon -I /tmp/iperf_load.pid
            log_message $FUNCNAME "  > iperf3 load started (PID in /tmp/iperf_load.pid)." INFO
            ;;
        "stress")
            # Generates CPU/memory load which can affect network stack latency
            log_message $FUNCNAME "  > Starting 'stress' utility to induce high CPU/Memory latency." INFO
            log_message $FUNCNAME "  > Install with: sudo apt install stress" WARNING
            # Stress 2 CPU cores, 1 memory process, run for 600s
            stress --cpu 2 --vm 1 --vm-bytes 128M -t 600 &
            log_message $FUNCNAME "  > Stress load started (PID: $!)." INFO
            ;;
        "none")
            log_message $FUNCNAME "  > No background load requested." INFO
            ;;
        *)
            log_message $FUNCNAME "Invalid load type '$load_type'. Must be 'iperf', 'stress', or 'none'." ERROR
            exit 1
            ;;
    esac
}

function stop_load() {
    log_message $FUNCNAME "Stopping Background Load" INFO

    # Stop iperf3 client
    if [ -f /tmp/iperf_load.pid ]; then
        kill $(cat /tmp/iperf_load.pid) 2>/dev/null
        rm /tmp/iperf_load.pid
        log_message $FUNCNAME "  > iperf3 load stopped." INFO
    fi

    # Stop 'stress' processes
    STRESS_PIDS=$(pgrep stress)
    if [ -n "$STRESS_PIDS" ]; then
        kill $STRESS_PIDS 2>/dev/null
        log_message $FUNCNAME "  > stress utility stopped." INFO
    fi
}

# --- MAIN EXECUTION ---

# Usage check
if [ "$#" -lt 2 ] || ([ "$1" == "run" ] && [ "$#" -lt 4 ]); then
    echo "Usage: sudo $0 <command> [load_type] [interface] [fan_ip]"
    echo ""
    echo "Commands:"
    echo "  setup     : Apply TC rules (prioritize control traffic)."
    echo "  teardown  : Remove all TC rules (restore standard network)."
    echo "  run       : Execute experiment: manage processes, apply TC (if needed), start load, and run PID."
    echo ""
    echo "Run Usage (mandatory arguments):"
    echo "  sudo $0 run <load_type> <interface> <fan_ip>"
    log_message $0 "  Example: sudo $0 run iperf eth0 192.168.1.100" INFO
    echo ""
    echo "Load Types: iperf, stress, none"
    exit 1
fi

COMMAND="$1"

# If running, update configuration from command line arguments
if [ "$COMMAND" == "run" ]; then
    LOAD_TYPE="$2"
    INTERFACE="$3"
    FAN_NODE_IP="$4"
    check_config # Check if interface and IP were passed
fi

stop_processes

case "$COMMAND" in
    "setup")
        setup_tc
        ;;
    "teardown")
        stop_load
        teardown_tc
        ;;
    "run")
        # 1. Start Background Load
        start_load "$LOAD_TYPE"
        
        # 2. Apply TC rules for "Improved Control" if requested
        if [ "$LOAD_TYPE" != "none" ]; then
            log_message $0 "" INFO # Newline for separation
            # When running with load, we default to the improved control setup.
            # For the degraded baseline, run the "none" load type with the teardown command first.
            setup_tc
        fi
        
        # 3. Start PID loop
        start_pid
        
        log_message $0 "=========================================================================" INFO
        log_message $0 "EXPERIMENT RUNNING: PID loop started, background load running (if any)." INFO
        log_message $0 "Use 'sudo $0 teardown' to clean up." INFO
        log_message $0 "=========================================================================" INFO
        ;;
    *)
        log_message $0 "Invalid command: $COMMAND" ERROR
        exit 1
        ;;
esac
