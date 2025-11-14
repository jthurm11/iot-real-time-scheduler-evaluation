#!/bin/bash
# Dedicated script for applying and tearing down TC (Traffic Control) rules.
# This script is intended to be called by the Systemd service unit (tc_controller.service).

# --- CONFIGURATION FILE PATHS ---
CONFIG_DIR="/opt/project/common/"
NETWORK_CONFIG_FILE="${CONFIG_DIR}network_config.json"
# --- END CONFIGURATION ---

# Global variables initialized after config load
INTERFACE=""
FAN_NODE_IP=""
FAN_COMMAND_PORT=""

# --- Logging Functions ---
# Default logging level (Can be set to: DEBUG, INFO, WARNING, ERROR)
LOG_LEVEL="INFO"

# Function to convert log level string to a number (higher = more severe)
get_log_level_numeric() {
    local level_str="$1"
    case "$level_str" in
        "ERROR")   echo 3 ;;
        "WARNING") echo 2 ;;
        "INFO")    echo 1 ;;
        "DEBUG")   echo 0 ;;
        *)         echo 1 ;; # Default to INFO if invalid
    esac
}

# Function log_message()
# Usage: log_message <reporting function> "<message>" [LEVEL]
log_message() {
    local reporter="$1" message="$2"
    local level="${3:-INFO}" # Default level for the message

    # Get numeric values for comparison
    local script_level_num=$(get_log_level_numeric "$LOG_LEVEL")
    local message_level_num=$(get_log_level_numeric "$level")

    # Only print if message severity is >= script's configured severity
    if [ "$message_level_num" -ge "$script_level_num" ]; then

        local timestamp=$(date +"%Y-%m-%d %H:%M:%S")
        local NC='\033[0m'   # No color

        case "${level}" in
            "INFO")    color='\033[0;36m';;  # Cyan
            "WARNING") color='\033[0;33m';;  # Yellow
            "ERROR")   color='\033[0;31m';;  # Red
            "DEBUG")   color='\033[0;35m';;  # Magenta
            *)         color="${NC}" ;;
        esac

        # Since we're using systemd, removing redundant logging pieces
        #echo -e "${color}${timestamp} ${reporter} [${level}]${NC} ${message}"
        echo -e "${color}[${level}]${NC} ${message}"
    fi
}

# Helper function to parse JSON
get_json_value() {
    local filepath="$1" key="$2"
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
        # Exit with a non-zero code if config is missing, as TC rules depend on it
        exit 1
    fi

    FAN_NODE_IP=$(get_json_value "$NETWORK_CONFIG_FILE" "FAN_NODE_IP")
    FAN_COMMAND_PORT=$(get_json_value "$NETWORK_CONFIG_FILE" "FAN_COMMAND_PORT")
    INTERFACE=$(get_json_value "$NETWORK_CONFIG_FILE" "INTERFACE")

    if [ -z "$FAN_NODE_IP" ] || [ -z "$INTERFACE" ] || [ -z "$FAN_COMMAND_PORT" ]; then
        log_message $FUNCNAME "ERROR: Failed to parse required values (FAN_NODE_IP, FAN_COMMAND_PORT, or INTERFACE) from config." ERROR
        exit 1
    fi
    log_message $FUNCNAME "Loaded Config: IP=$FAN_NODE_IP, Port=$FAN_COMMAND_PORT, Interface=$INTERFACE." DEBUG
}

# Traffic Control Teardown (must be defined first)
teardown_tc() {
    log_message $FUNCNAME "Tearing down TC rules on interface $INTERFACE..." INFO
    # Delete the root qdisc, suppressing errors if it doesn't exist
    tc qdisc del dev "$INTERFACE" root 2> /dev/null || log_message $FUNCNAME "TC rules not present or deletion failed." WARNING
    log_message $FUNCNAME "TC rules removed." INFO
}


# Traffic Control Setup (based on the more robust Option 2)
setup_tc() {
    # 1. Ensure clean slate
    teardown_tc

    log_message $FUNCNAME "Setting up TC rules on interface $INTERFACE..." INFO

    # 2. Add the root qdisc (Hierarchical Token Bucket)
    # Set default to BE Class 20
    tc qdisc add dev "$INTERFACE" root handle 1: htb default 20 2> /dev/null
    if [ $? -ne 0 ]; then
        # Quit early in case of error.
        log_message $FUNCNAME "Could not create root qdisc. Check permissions" ERROR
        return 1
    fi

    # 3. Create the Real-Time (RT) Class (Class 10) - High Priority, Low Latency
    # Strict limit: 100 kbit/s
    tc class add dev "$INTERFACE" parent 1: classid 1:10 htb rate 100kbit ceil 100kbit
    log_message $FUNCNAME "Created RT Class (1:10) strictly limited to 100kbit/s." DEBUG

    # 4. Create the Best-Effort (BE) Class (Class 20) - Congestion Sensitive
    # Guaranteed 1 Mbit/s, up to 10 Mbit/s if available
    tc class add dev "$INTERFACE" parent 1: classid 1:20 htb rate 1mbit ceil 10mbit
    log_message $FUNCNAME "Created BE Class (1:20): guaranteed 1Mbit/s, burst 10Mbit/s." DEBUG

    # 5. Add Stochastic Fairness Queueing (SFQ) to the BE class
    # SFQ ensures fairness among multiple background flows.
    tc qdisc add dev "$INTERFACE" parent 1:20 handle 20: sfq perturb 10
    log_message $FUNCNAME "Added SFQ QDisc to BE Class 1:20 for fair congestion sharing." DEBUG

    # 6. Create the FILTER for the Real-Time traffic
    # Filter: IP traffic destined for the Fan Node IP, on the FAN_COMMAND_PORT, should go to class 1:10
    tc filter add dev "$INTERFACE" protocol ip parent 1:0 prio 1 u32 \
        match ip dst "$FAN_NODE_IP"/32 \
        match ip dport "$FAN_COMMAND_PORT" 0xffff \
        flowid 1:10
    log_message $FUNCNAME "Applied filter: UDP traffic to $FAN_NODE_IP:$FAN_COMMAND_PORT -> RT Class 1:10." DEBUG

    log_message $FUNCNAME "TC setup complete. PID traffic is prioritized and rate-limited." INFO
}

# --- MAIN EXECUTION ---
load_network_config # Must run first to get INTERFACE, IP, and PORT
COMMAND="$1"

if [ "$#" -ne 1 ]; then
    log_message $0 "Usage: $0 <apply-tc|remove-tc>" ERROR
    exit 1
fi

case "$COMMAND" in
    "apply-tc")
        setup_tc
        ;;
    "remove-tc")
        teardown_tc
        ;;
    *)
        log_message $0 "Invalid command: $COMMAND" ERROR
        exit 1
        ;;
esac