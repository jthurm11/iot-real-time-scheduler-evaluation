#!/bin/bash
# This script configures the hostname, sets a static IP (192.168.1.x),
# establishes the Wi-Fi connection, and verifies network connectivity using nmcli
# for consistent deployment in a Debian Bookworm environment.
#
# --- USAGE ---
# USAGE (Run all tasks): ./setup_nodes.sh
# USAGE (Run single task): ./setup_nodes.sh -f [function_name]

# --- ANSI Color Codes (Initial Definitions) ---
# These are defined here to ensure colors are available from the very start.
# Commenting out for now to avoid overhead, and defining needed colors exclusively within log_message().
# export RED='\033[0;31m'
# export GREEN='\033[0;32m'
# export YELLOW='\033[0;33m'
# export BLUE='\033[0;34m'
# export MAGENTA='\033[0;35m'
# export CYAN='\033[0;36m'
# export NC='\033[0m' # No Color

# --- Aliases for Color Reference (Initial Definitions) ---
# export INFO_COLOR="${GREEN}"
# export WARNING_COLOR="${YELLOW}"
# export ERROR_COLOR="${RED}"
# export DEBUG_COLOR="${MAGENTA}"

# --- GLOBAL CONFIGURATION ---
WIFI_IF="wlan0"
CONN_NAME="primary-wifi"
NODES=("alpha" "beta")
SIGNAL_NET_PREFIX="192.168.22"
INSTALL_DIR="/opt/project"
SERVICE_USER="pi" # User that runs the python scripts

# --- Utility Functions ---

# Function log_message()
# Usage: log_message "<message>" LEVEL
#   - LEVEL := { INFO | WARNING | ERROR | DEBUG }
log_message() {
    local message="$1"
    local level="${2:-INFO}" # Default to INFO if not provided
    local timestamp=$(date +"%Y-%m-%d %H:%M:%S")
    local NC='\033[0m'   # No color

    case "${level}" in
        "INFO")    color='\033[0;32m';;  # Green
        "WARNING") color='\033[0;33m';;  # Yellow
        "ERROR")   color='\033[0;31m';;  # Red
        "DEBUG")   color='\033[0;35m';;  # Magenta
        *)         color="${NC}" ;; # Default to no color for unknown levels
    esac

    echo -e "${color}[${timestamp} - ${level}]${NC} ${message}"
    #echo -e "${color}${timestamp} - ${level} - ${NC}${message}"
}

# Function to assign static IP based on hostname
get_signal_ip() {
    #log_message "--- SET SIGNAL IP ---"
    case "$TARGET_HOSTNAME" in
        "alpha")
            TARGET_IP="${SIGNAL_NET_PREFIX}.1/24"
            DEST_NODE="beta"
            DEST_IP="${SIGNAL_NET_PREFIX}.2"
            ;;
        "beta")
            TARGET_IP="${SIGNAL_NET_PREFIX}.2/24"
            DEST_NODE="alpha"
            DEST_IP="${SIGNAL_NET_PREFIX}.1"
            ;;
    esac
    export TARGET_IP DEST_NODE DEST_IP
    #log_message "Control Signal IP set to: ${TARGET_IP}" DEBUG
}

# --- Core Setup Functions ---

# Function to select hostname
set_hostname() {
    log_message "--- HOSTNAME SELECTION AND IP ASSIGNMENT ---" INFO
    PS3='Select the hostname for this node: '

    select HOSTNAME_CHOICE in "${NODES[@]}"; do
        if [[ " ${NODES[@]} " =~ " ${HOSTNAME_CHOICE} " ]]; then
            TARGET_HOSTNAME="$HOSTNAME_CHOICE"
            break
        else
            log_message "Invalid selection. Please try again." WARNING
        fi
    done

    # Apply hostname using nmcli (PERSISTENT WRITE)
    log_message "Applying hostname to $TARGET_HOSTNAME..." INFO
    sudo nmcli general hostname "$TARGET_HOSTNAME" >/dev/null
    if [ $? -ne 0 ]; then
        log_message "Error setting hostname with nmcli." ERROR
        return 1
    else
        log_message "Hostname set successfully. (Requires reboot to finalize.)" INFO
    fi

    export TARGET_HOSTNAME
}

# Function to connect to WiFi and set static IP
configure_wifi() {
    log_message "--- WI-FI SCAN AND DHCP + SECONDARY STATIC CONFIGURATION ---" INFO

    # Check for existing active connection
    IS_WIFI_CONNECTED=$(nmcli dev | grep "${WIFI_IF}" | grep -w "connected")

    if [ -n "$IS_WIFI_CONNECTED" ]; then
        log_message "Wi-Fi device ($WIFI_IF) is already connected." WARNING
        read -r -p "Do you want to skip reconfiguring the Wi-Fi? (y/N): " SKIP_WIFI
        if [[ "$SKIP_WIFI" =~ ^[Yy]$ ]]; then
            log_message "Skipping Wi-Fi connection step."
            return 0
        fi
    fi

    # Scan and get input
    log_message "Available Networks:" INFO
    nmcli -f IN-USE,BSSID,SSID,SIGNAL,BARS dev wifi list

    read -p "Enter the desired Wi-Fi Network SSID (Name): " WIFI_SSID
    read -s -p "Enter the Wi-Fi Password: " WIFI_PASS
    echo ""

    log_message "Creating/Recreating persistent DHCP Wi-Fi connection ($CONN_NAME)..." INFO

    # Delete any existing connection with the same name before creation
    sudo nmcli connection delete "$CONN_NAME" 2>/dev/null

    # Create and configure the new profile
    sudo nmcli connection add type wifi con-name "$CONN_NAME" ifname "$WIFI_IF" ssid "$WIFI_SSID" \
        wifi-sec.key-mgmt wpa-psk wifi-sec.psk "$WIFI_PASS" \
        ipv4.method auto \
        autoconnect yes

    if [ $? -ne 0 ]; then
        log_message "Failed to create DHCP Wi-Fi profile. Check SSID/Password." ERROR
        return 1
    else
        log_message "Persistent DHCP Wi-Fi profile '$CONN_NAME' created." INFO
    fi

    # Activate the connection
    sudo nmcli connection up "$CONN_NAME"
    if [ $? -ne 0 ]; then
        log_message "Connection failed to activate. Check network status." WARNING
        return 1
    fi
    log_message "Primary DHCP Wi-Fi connection established." INFO

    # Add secondary IP for control signal
    get_signal_ip
    if [ -z "$TARGET_IP" ]; then
        log_message "Error: Hostname and IP must be set first. Run 'set_hostname' or the default script flow." ERROR
        return 1
    fi

    sudo nmcli connection modify "$CONN_NAME" +ipv4.addresses "$TARGET_IP"
    if [ $? -ne 0 ]; then
        log_message "Failed to add secondary static IP ${TARGET_IP}. Check 'sudo nmcli connection show $CONN_NAME'." ERROR
        return 1
    else
        log_message "Secondary static control IP added persistently and activated." INFO
    fi
}

# Function to ping the other node (for verification)
verify_connectivity() {
    log_message "--- CONNECTIVITY VERIFICATION ---" INFO

    # Ensure peer variables are defined
    if [ -z "$DEST_IP" ]; then
        get_signal_ip
    fi

    log_message "Attempting to ping opposite node ($DEST_NODE at $DEST_IP)..." INFO

    ping -c 3 "$DEST_IP"

    if [ $? -eq 0 ]; then
        log_message "SUCCESS: Connectivity verified with $DEST_NODE." INFO
    else
        log_message "FAILURE: Could not ping $DEST_NODE. Check network and IP settings on both devices." ERROR
    fi
}

# Function to print final configuration summary
final_summary() {
    log_message "=======================================================" INFO
    log_message "SETUP COMPLETE: $TARGET_HOSTNAME" INFO
    log_message "=======================================================" INFO

    # Check current Wi-Fi SSID
    ACTIVE_SSID=$(nmcli -t -f active,ssid dev wifi list | grep yes | head -n 1 | cut -d: -f2)
    #ACTIVE_SSID=$(nmcli -g 802-11-wireless.ssid c show $CONN_NAME)

    # Get the static signal IP (matches SIGNAL_NET_PREFIX)
    #STATIC_IP_CLEAN=$(ip a show dev "$WIFI_IF" | grep 'inet ' | grep "$SIGNAL_NET_PREFIX" | awk '{print $2}' | cut -d/ -f1)

    # Get the DHCP assigned IP (does NOT match SIGNAL_NET_PREFIX)
    #DHCP_IP=$(ip a show dev "$WIFI_IF" | grep 'inet ' | grep -v "$SIGNAL_NET_PREFIX" | awk '{print $2}' | cut -d/ -f1)

    # Get all assigned IP4 addresses
    IP_ADDRS=$(nmcli -g ip4.address connection show $CONN_NAME)

    printf "%-25s %s\n" "Hostname:" "$TARGET_HOSTNAME"
    printf "%s\n" "-------------------------------------------------------"
    #printf "%-25s %s\n" "DHCP Assigned IP (Primary):" "$DHCP_IP"
    #printf "%-25s %s\n" "Static Control IP (Signal):" "$STATIC_IP_CLEAN"
    printf "%-25s %s\n" "Assigned IPs:" "$IP_ADDRS"
    printf "%-25s %s\n" "Connected Wi-Fi SSID:" "$ACTIVE_SSID"

    log_message "=======================================================" INFO
    log_message "Please reboot the system now to finalize the hostname change: sudo reboot" INFO
}

# --- Service Deployment Functions ---

# Function to copy files and set permissions
install_project_files() {
    log_message "--- INSTALLING PROJECT FILES ---" INFO

    # Create target directory and copy all files
    sudo mkdir -p "$INSTALL_DIR"

    # Assumes the script is run from the /src directory or its parent, 
    # and /src contains all the python scripts.
    SCRIPT_DIR=$(dirname "$0")
    log_message "Copying files from '$SCRIPT_DIR' to '$INSTALL_DIR'." DEBUG

    sudo cp -r "$SCRIPT_DIR"/* "$INSTALL_DIR"

    # Set proper ownership and permissions
    CURR_USER="$(id -un)"
    if [[ "$SERVICE_USER" != "$CURR_USER" ]]; then
        SERVICE_USER="$CURR_USER"
    fi
    sudo chown -R $SERVICE_USER:$SERVICE_USER "$INSTALL_DIR"
    sudo find "$INSTALL_DIR" -type f -name "*.py" -exec chmod +x {} \;

    log_message "Project files installed successfully to $INSTALL_DIR." INFO
}

# Function to setup the network status LED service (Both Nodes)
setup_network_led_service() {
    log_message "--- SETTING UP NETWORK LED STATUS SERVICE ---" INFO

    local SERVICE_NAME="network-led-status.service"
    local SCRIPT_PATH="${INSTALL_DIR}/network_led_status.py"
    local SERVICE_FILE="/etc/systemd/system/$SERVICE_NAME"

    # Create the Systemd service file
    log_message "Creating $SERVICE_FILE..." DEBUG
    sudo cat <<EOF | sudo tee "$SERVICE_FILE" > /dev/null
[Unit]
Description=Network Status LED Monitor
After=network.target

[Service]
ExecStart=/usr/bin/env python3 $SCRIPT_PATH
WorkingDirectory=$INSTALL_DIR
StandardOutput=journal
StandardError=journal
Restart=always
User=$SERVICE_USER

[Install]
WantedBy=multi-user.target
EOF

    # Enable and start the service
    sudo systemctl daemon-reload
    sudo systemctl enable --now "$SERVICE_NAME" > /dev/null
    log_message "Service $SERVICE_NAME enabled." INFO
}

# Function to setup the fan controller service (Alpha Node ONLY)
setup_fan_controller_service() {
    if [ "$TARGET_HOSTNAME" != "alpha" ]; then
        log_message "Skipping fan controller setup: Not the alpha node." INFO
        return 0
    fi

    log_message "--- SETTING UP FAN CONTROLLER SERVICE (ALPHA ONLY) ---" INFO

    local SERVICE_NAME="fan-controller.service"
    local SCRIPT_PATH="${INSTALL_DIR}/alpha/fan_controller.py"
    local CONTROL_FILE="/tmp/fan_control_duty.txt"
    local SERVICE_FILE="/etc/systemd/system/$SERVICE_NAME"

    # 1. Create the temporary control file
    if [ ! -f "$CONTROL_FILE" ]; then
        log_message "Creating initial fan control file: $CONTROL_FILE" INFO
        echo "0" | sudo tee "$CONTROL_FILE" > /dev/null
        sudo chown $SERVICE_USER:$SERVICE_USER "$CONTROL_FILE"
    fi

    # 2. Create the Systemd service file
    log_message "Creating $SERVICE_FILE..." DEBUG
    sudo cat <<EOF | sudo tee "$SERVICE_FILE" > /dev/null
[Unit]
Description=Ball-Floating Fan Controller (PWM)
After=multi-user.target

[Service]
ExecStart=/usr/bin/env python3 $SCRIPT_PATH
WorkingDirectory=$INSTALL_DIR
StandardOutput=journal
StandardError=journal
Restart=always
User=$SERVICE_USER

[Install]
WantedBy=multi-user.target
EOF

    # 3. Enable and start the service
    sudo systemctl daemon-reload
    sudo systemctl enable --now "$SERVICE_NAME" > /dev/null
    log_message "Service $SERVICE_NAME enabled." INFO
}

# --- MAIN EXECUTION LOGIC ---

# Array of all functions to run by default
ALL_FUNCTIONS=(
    set_hostname
    install_project_files
    setup_network_led_service
    setup_fan_controller_service
    configure_wifi
    verify_connectivity
    final_summary
)
FUNC_TO_RUN=""

while getopts "f:p" opt; do
    case ${opt} in
        f)
            FUNC_TO_RUN="$OPTARG"
            ;;
        p)
            ALL_FUNCTIONS=(install_project_files setup_network_led_service setup_fan_controller_service)
            ;;
        \?)
            echo "Invalid option: -${OPTARG}" >&2
            echo "Usage: $0 [-f function_name]" >&2
            exit 1
            ;;
        :)
            echo "Option -${OPTARG} requires an argument." >&2
            echo "Usage: $0 [-f function_name]" >&2
            exit 1
            ;;
    esac
done

# --- EXECUTION ---
# Check and set hostname if expected does not match received.
# This ensures host variables are set if running a subsequent function
CURR_NAME=$(nmcli general hostname)
if [[ "${NODES[@]}" =~ "${CURR_NAME}" ]]; then
    TARGET_HOSTNAME="${CURR_NAME}"
else
    set_hostname
fi

# Ensure peer variables are defined
get_signal_ip

if [ ! -z "$FUNC_TO_RUN" ]; then
    # Option -f provided: Execute the specified function
    if declare -f "$FUNC_TO_RUN" > /dev/null; then
        log_message "Executing requested function: $FUNC_TO_RUN"
        "$FUNC_TO_RUN"
    else
        log_message "Function '$FUNC_TO_RUN' not found." WARNING
        echo "Available functions: ${ALL_FUNCTIONS[@]}"
        exit 1
    fi
else
    # Run full sequence
    log_message "No argument provided. Running full setup sequence."

    for func in "${ALL_FUNCTIONS[@]}"; do
        # Execute the function
        "$func" || { log_message "Setup aborted due to function failure: $func" WARNING; exit 1; }
    done
fi
