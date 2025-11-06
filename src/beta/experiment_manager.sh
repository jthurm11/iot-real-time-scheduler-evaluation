#!/bin/bash
# Real-Time Traffic Scheduler Experiment Manager

# --- CONFIGURATION FILE PATHS (Centralized) ---
CONFIG_DIR="/opt/project/common/"
NETWORK_CONFIG_FILE="${CONFIG_DIR}network_config.json"
PID_SCRIPT_PATH="/opt/project/beta/sensor_PIDcontroller.py"
PID_LOG_FILE="/tmp/sensor_pid_controller.log"
# --- END CONFIGURATION ---

# Global variables initialized after config load
INTERFACE=""
FAN_NODE_IP=""
FAN_PORT=""

# Function log_message <reporting function> "<message>" LEVEL
# Usage: log_message $FUNCNAME "<message>" <LEVEL>
log_message() {
    local reporter="$1" message="$2"
    local level="${3:-INFO}"
    local timestamp=$(date +"%Y-%m-%d %H:%M:%S")
    local NC='\033[0m'

    case "${level}" in
        "INFO")    color='\033[0;36m';;
        "WARNING") color='\033[0;33m';;
        "ERROR")   color='\033[0;31m';;
        "DEBUG")   color='\033[0;32m';;
        *)         color=$NC;;
    esac

    echo -e "${color}[${timestamp}][${level}][${reporter}] ${message}${NC}"
}

# Helper function to parse JSON using grep/awk (assumes simple key-value structure)
# Usage: get_json_value <filepath> <key>
get_json_value() {
    local filepath="$1" key="$2"
    # Use jq if available for robust parsing, otherwise fallback to awk/grep
    if command -v jq &> /dev/null; then
        jq -r ".$key" "$filepath" 2>/dev/null
    else
        grep -E "\"$key\"" "$filepath" | awk -F': ' '{print $2}' | sed 's/[",]//g' | tr -d ' '
    fi
}

# Load network configuration from JSON file
load_network_config() {
    if [ ! -f "$NETWORK_CONFIG_FILE" ]; then
        log_message $FUNCNAME "ERROR: Network config file not found at $NETWORK_CONFIG_FILE." ERROR
        exit 1
    fi
    
    FAN_NODE_IP=$(get_json_value "$NETWORK_CONFIG_FILE" "FAN_NODE_IP")
    FAN_PORT=$(get_json_value "$NETWORK_CONFIG_FILE" "FAN_PORT")
    INTERFACE=$(get_json_value "$NETWORK_CONFIG_FILE" "INTERFACE")
    
    if [ -z "$FAN_NODE_IP" ] || [ -z "$INTERFACE" ] || [ -z "$FAN_PORT" ]; then
        log_message $FUNCNAME "ERROR: Failed to parse required values (FAN_NODE_IP, FAN_PORT, or INTERFACE) from config." ERROR
        exit 1
    fi
    log_message $FUNCNAME "Loaded Config: IP=$FAN_NODE_IP, Port=$FAN_PORT, Interface=$INTERFACE." INFO
}

# Check if the mandatory environment is set up (tc, iperf3)
check_dependencies() {
    if ! command -v tc &> /dev/null; then
        log_message $FUNCNAME "tc (Traffic Control) could not be found. Please install iproute2." ERROR
        exit 1
    fi
    if ! command -v iperf3 &> /dev/null; then
        log_message $FUNCNAME "iperf3 could not be found. Please install iperf3." WARNING
    fi
}

# Traffic Control Setup
setup_tc() {
    log_message $FUNCNAME "Setting up TC rules on interface $INTERFACE..." INFO
    # 1. Clear existing rules
    teardown_tc
    
    # 2. Add the root qdisc (Hierarchical Token Bucket)
    # Set default to BE Class 20
    tc qdisc add dev $INTERFACE root handle 1: htb default 20 

    # 3. Create the Real-Time (RT) Class (Class 10) - High Priority, Low Latency
    # Fan port 5005 is used for control traffic.
    tc class add dev $INTERFACE parent 1: classid 1:10 htb rate 100kbit ceil 100kbit
    log_message $FUNCNAME "Created RT Class (1:10) at 100kbit/s for control traffic." INFO

    # 4. Create the Best-Effort (BE) Class (Class 20) - Low Priority, Congestion Sensitive
    tc class add dev $INTERFACE parent 1: classid 1:20 htb rate 1mbit ceil 10mbit
    log_message $FUNCNAME "Created BE Class (1:20) at 1Mbit/s for background traffic." INFO
    
    # 5. Add a simple FIFO queue discipline to the Best-Effort class to simulate simple queuing
    tc qdisc add dev $INTERFACE parent 1:20 handle 20: sfq perturb 10
    
    # 6. Create the FILTER for the Real-Time traffic
    # Filter: IP traffic destined for the Fan Node IP, on the FAN_PORT, should go to class 1:10
    tc filter add dev $INTERFACE protocol ip parent 1:0 prio 1 u32 \
        match ip dst $FAN_NODE_IP/32 \
        match ip dport $FAN_PORT 0xffff \
        flowid 1:10
    log_message $FUNCNAME "Applied filter: UDP traffic to $FAN_NODE_IP:$FAN_PORT -> RT Class 1:10." INFO
    
    log_message $FUNCNAME "TC setup complete. PID traffic is prioritized." INFO
}

# Traffic Control Teardown
teardown_tc() {
    log_message $FUNCNAME "Tearing down TC rules on interface $INTERFACE..." INFO
    # Delete the root qdisc
    tc qdisc del dev $INTERFACE root 2> /dev/null || log_message $FUNCNAME "TC rules not present or deletion failed." DEBUG
}

# Background Load Management
start_load() {
    local load_type="$1"
    if [ "$load_type" == "iperf" ]; then
        log_message $FUNCNAME "Starting iperf3 background load targeting $FAN_NODE_IP..." INFO
        # Note: iperf3 run in the background, targeting the Fan Node IP
        iperf3 -c $FAN_NODE_IP -u -b 10M -t 0 -P 1 > /dev/null 2>&1 &
        local pid=$!
        echo $pid > /tmp/iperf3_pid.txt
        log_message $FUNCNAME "iperf3 started with PID $pid" INFO
    elif [ "$load_type" == "stress" ]; then
        log_message $FUNCNAME "Starting CPU stress load..." INFO
        stress -c 4 -t 0 > /dev/null 2>&1 &
        local pid=$!
        echo $pid > /tmp/stress_pid.txt
        log_message $FUNCNAME "stress started with PID $pid" INFO
    elif [ "$load_type" == "none" ]; then
        log_message $FUNCNAME "No background load requested." INFO
    else
        log_message $FUNCNAME "Unknown load type: $load_type" ERROR
    fi
}

stop_load() {
    log_message $FUNCNAME "Stopping background load processes..." INFO
    if [ -f /tmp/iperf3_pid.txt ]; then
        kill $(cat /tmp/iperf3_pid.txt) 2> /dev/null
        rm /tmp/iperf3_pid.txt
        log_message $FUNCNAME "iperf3 stopped." INFO
    fi
    if [ -f /tmp/stress_pid.txt ]; then
        kill $(cat /tmp/stress_pid.txt) 2> /dev/null
        rm /tmp/stress_pid.txt
        log_message $FUNCNAME "stress stopped." INFO
    fi
}

# PID Controller Management
start_pid() {
    log_message $FUNCNAME "Starting PID controller script $PID_SCRIPT_PATH..." INFO
    # Use python3 and ensure it has necessary module paths
    python3 $PID_SCRIPT_PATH > $PID_LOG_FILE 2>&1 &
    local pid=$!
    echo $pid > /tmp/pid_controller_pid.txt
    log_message $FUNCNAME "PID controller started with PID $pid. Logs: $PID_LOG_FILE" INFO
}

stop_pid() {
    log_message $FUNCNAME "Stopping PID controller process..." INFO
    if [ -f /tmp/pid_controller_pid.txt ]; then
        # Use SIGINT for graceful shutdown
        kill -SIGINT $(cat /tmp/pid_controller_pid.txt) 2> /dev/null
        sleep 1 # Wait for graceful exit
        # Fallback kill if it didn't shut down
        kill $(cat /tmp/pid_controller_pid.txt) 2> /dev/null
        rm /tmp/pid_controller_pid.txt
        log_message $FUNCNAME "PID controller stopped." INFO
    fi
}

stop_processes() {
    stop_pid
    stop_load
}

# --- MAIN EXECUTION ---
check_dependencies
load_network_config # Load core network settings

if [ "$#" -lt 1 ]; then
    log_message $0 "Usage: sudo $0 <command> [load_type]" ERROR
    log_message $0 "Interface ($INTERFACE) and IP ($FAN_NODE_IP) are loaded from config." INFO
    echo ""
    echo "Load Types: iperf, stress, none"
    exit 1
fi

COMMAND="$1"

# Stop all processes before attempting a new command (except for 'run' where stop_load is called implicitly)
if [ "$COMMAND" != "run" ]; then
    stop_processes
fi

case "$COMMAND" in
    "setup")
        setup_tc
        ;;
    "teardown")
        stop_load
        teardown_tc
        ;;
    "run")
        LOAD_TYPE="${2:-none}" # Default to 'none' if no load type is provided
        
        start_load "$LOAD_TYPE"
        
        if [ "$LOAD_TYPE" != "none" ]; then
            log_message $0 "" INFO 
            setup_tc
        fi
        
        start_pid
        
        log_message $0 "=========================================================================" INFO
        log_message $0 "EXPERIMENT RUNNING: PID loop started, background load running (if any). Interface: $INTERFACE" INFO
        log_message $0 "Use 'sudo $0 teardown' to clean up." INFO
        log_message $0 "=========================================================================" INFO
        ;;
    *)
        log_message $0 "Invalid command: $COMMAND" ERROR
        log_message $0 "Available commands: setup, teardown, run" INFO
        exit 1
        ;;
esac