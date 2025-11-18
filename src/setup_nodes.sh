#!/bin/bash
# This script configures the node hostname, sets a static IP (if NetworkManager is present),
# generates SSH keys, and installs node-specific project dependencies.
#
# --- USAGE ---
# USAGE (Run all tasks): ./setup_nodes.sh
# USAGE (Run single task): ./setup_nodes.sh -f [function_name]
# USAGE (Quiet output): ./setup_nodes.sh -l ERROR

# --- GLOBAL CONFIGURATION ---
WIFI_IF="wlan0"
CONN_NAME=""
NODES=("alpha" "beta")
SIGNAL_NET_PREFIX="192.168.22"
ALPHA_IP="${SIGNAL_NET_PREFIX}.1"
BETA_IP="${SIGNAL_NET_PREFIX}.2"
SERVICE_USER="ubuntu" # User that runs the python scripts
INSTALL_DIR="/opt/project"
GIT_DIR="${HOME}/Public"
GIT_ROOT="${GIT_DIR}/iot-real-time-scheduler-evaluation"
SCRIPT_DIR="${GIT_ROOT}/src"

# Default logging level (Can be set via -l flag: DEBUG, INFO, WARNING, ERROR)
DEFAULT_LOG_LEVEL="INFO"
LOG_LEVEL="" # Placeholder for the active level

# --- PACKAGE DEPENDENCIES (Node Specific) ---
# Define packages needed for Alpha (Fan Controller)
ALPHA_PACKAGES=(
    #"python3-matplotlib"
    "pigpiod"
    #"i2c-tools"
    "iperf3"
)
# Define packages needed for Beta (Sensor Manager)
BETA_PACKAGES=(
    "python3-rpi.gpio"
    "python3-flask"
    "python3-flask-socketio"
    "python3-gevent"
    "python3-gevent-websocket"
    "iperf3"
    "stress-ng"
    "python3-psutil"
)

# --- SYSTEMD SERVICES ---
ALPHA_SERVICES=(
    "pigpiod"
    "fan_controller"
    "iperf3"      # Runs server-side connection for background load
)
BETA_SERVICES=(
    "sensor_controller"
    "web_app"
    #"tc_controller"         # By default, we don't want rules applied
    #"experiment_controller" # By default, we don't want this running
)

# --- Utility Functions ---

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

        echo -e "${color}${timestamp} ${reporter} [${level}]${NC} ${message}"
    fi
}

# Function to define key variables and assign hostname if needed
who_am_i() {
    local func="who_am_i"
    
    # Use hostnamectl to get the current static/transient hostname
    local curr_name=$(hostnamectl hostname)
    
    # Check if hostname is already set to a known node
    if [[ "${NODES[@]}" =~ "${curr_name}" ]]; then
        TARGET_NODE="${curr_name}"
        log_message ${func} "Hostname detected as ${TARGET_NODE}." INFO
    else
        log_message ${func} "Hostname not set. Prompting for node selection..." INFO
        PS3='Select the hostname for this node: '

        select hostname_choice in "${NODES[@]}"; do
            if [[ " ${NODES[@]} " =~ " ${hostname_choice} " ]]; then
                TARGET_NODE="$hostname_choice"
                break
            else
                log_message ${func} "Invalid selection. Please try again." WARNING
            fi
        done

        # Apply hostname using hostnamectl (PERSISTENT WRITE)
        sudo hostnamectl set-hostname "$TARGET_NODE" >/dev/null
        if [ $? -ne 0 ]; then
            log_message ${func} "Error setting hostname with hostnamectl. Check if the utility is available." ERROR
            return 1
        else
            log_message ${func} "Hostname set to $TARGET_NODE. (Requires reboot to finalize.)" WARNING
        fi
    fi

    # Set peer variables based on TARGET_NODE
    case "$TARGET_NODE" in
        "alpha")
            TARGET_IP="${ALPHA_IP}"
            NEIGHBOR_NODE="beta"
            NEIGHBOR_IP="${BETA_IP}"
            ;;
        "beta")
            TARGET_IP="${BETA_IP}"
            NEIGHBOR_NODE="alpha"
            NEIGHBOR_IP="${ALPHA_IP}"
            ;;
    esac
    # Note: Using /28 mask here as it only needs 16 addresses, which is safer
    TARGET_NET_MASK="${TARGET_IP}/28" 

    export TARGET_NODE TARGET_IP NEIGHBOR_NODE NEIGHBOR_IP TARGET_NET_MASK
}

# --- Core Setup Functions ---

# Function to connect to WiFi and set static IP
configure_signal_ip() {
    local func="configure_signal_ip"
    log_message ${func} "--- STATIC SIGNAL IP CONFIGURATION ---" INFO

    # Simple check to see if the IP is already assigned
    if ip addr show "$WIFI_IF" | grep -q "$TARGET_IP"; then
        log_message ${func} "Static IP ${TARGET_IP} already assigned to ${WIFI_IF}. Skipping configuration." WARNING
        return 0
    fi 

    # Check for NetworkManager utility, as the rest of this function relies on nmcli
    if ! command -v nmcli &> /dev/null; then
        log_message ${func} "nmcli (NetworkManager) is required for this step but not found. Skipping IP configuration." ERROR
        log_message ${func} "You must manually configure the static IP ${TARGET_IP}/28 for the Wi-Fi connection." WARNING
        return 1
    fi

    # Find the active Wi-Fi connection name
    CONN_NAME=$(nmcli dev | grep "^${WIFI_IF}.* connected " | awk '{print $4}')

    if [ -n "$CONN_NAME" ]; then
        export CONN_NAME

        # Modify the connection profile to add the static IP.
        log_message ${func} "Modifying connection '${CONN_NAME}' to use static IP ${TARGET_NET_MASK}..." DEBUG
        sudo nmcli connection modify "$CONN_NAME" +ipv4.addresses "$TARGET_IP/28"

        if [ $? -ne 0 ]; then
            log_message ${func} "Failed to modify connection profile." ERROR
            return 1
        fi

        # Re-activate the connection to apply changes immediately.
        sudo nmcli connection up "$CONN_NAME" >/dev/null
        if [ $? -eq 0 ]; then
                log_message ${func} "Static IP configured via nmcli and connection re-activated." WARNING
            return 0
        else
                log_message ${func} "Failed to activate connection via nmcli." ERROR
            return 1
        fi
    else
        log_message ${func} "Could not find an active Wi-Fi connection on ${WIFI_IF}." WARNING
        return 1
    fi
}

# Function to generate SSH keys
generate_ssh_key() {
    local func="generate_ssh_key"
    local ssh_file="$HOME/.ssh/id_ed25519"

    log_message ${func} "--- CHECKING/GENERATING SSH KEY ---" INFO
    
    # Check for existing key and skip if found
    if [ -f "${ssh_file}" ]; then
        log_message ${func} "SSH key already exists at ${ssh_file}. Skipping generation." WARNING
    else
        # Ensure the .ssh directory exists
        mkdir -p ~/.ssh

        # Quietly generate SSH key with no passphrase for automation.
        ssh-keygen -q -t ed25519 -f "$ssh_file" -C "$TARGET_NODE" -N ""
        if [ $? -eq 0 ]; then
            log_message ${func} "SSH key generated successfully." WARNING
        else
            log_message ${func} "Error generating SSH key." ERROR
            return 1
        fi

        # Print manual copy instructions for the user
        log_message ${func} "ACTION REQUIRED: Copy public key to neighbor (${NEIGHBOR_NODE})" WARNING
        log_message ${func} "Run the following command MANUALLY on this machine to enable passwordless SSH:"
        echo -e "    ssh-copy-id ${SERVICE_USER}@${NEIGHBOR_IP}\n"
    fi
    return 0
}

# Function to copy files and set permissions
install_project() {
    local func="install_project"
    log_message ${func} "--- INSTALLING PROJECT FILES & DEPENDENCIES ---" INFO

    # Determine which package set to use
    local PACKAGES_TO_INSTALL
    if [ "$TARGET_NODE" == "alpha" ]; then
        PACKAGES_TO_INSTALL=("${ALPHA_PACKAGES[@]}")
        SERVICES_TO_ENABLE=("${ALPHA_SERVICES[@]}")
    elif [ "$TARGET_NODE" == "beta" ]; then
        PACKAGES_TO_INSTALL=("${BETA_PACKAGES[@]}")
        SERVICES_TO_ENABLE=("${BETA_SERVICES[@]}")
    else
        log_message ${func} "Unknown target node '$TARGET_NODE'. Cannot install node-specific packages." ERROR
        return 1
    fi

    # Check for node-specific project directory
    if ! [ -d $SCRIPT_DIR/$TARGET_NODE ]; then
        log_message ${func} "Cannot find project files. Ensure repo is installed." ERROR
        return 1
    fi

    # Install Dependencies using the node-specific array
    log_message ${func} "Installing required system packages for ${TARGET_NODE}: ${PACKAGES_TO_INSTALL[*]}..." DEBUG
    sudo apt update >/dev/null 2>&1
    sudo apt install -y "${PACKAGES_TO_INSTALL[@]}"

    # Create target directory and copy all files
    sudo mkdir -p "$INSTALL_DIR"
    sudo cp -r "$SCRIPT_DIR"/{common,$TARGET_NODE} "$INSTALL_DIR"/

    # Set proper ownership and permissions
    CURR_USER="$(id -un)"
    if [[ "$SERVICE_USER" != "$CURR_USER" ]]; then
        SERVICE_USER="$CURR_USER"
    fi
    sudo chown -R $SERVICE_USER:$SERVICE_USER "$INSTALL_DIR"
    sudo find "$INSTALL_DIR" -type f -name "*.py" -exec chmod +x {} \;
    sudo find "$INSTALL_DIR" -type f -name "*.sh" -exec chmod +x {} \;

    log_message ${func} "Project files copied and ownership set to $INSTALL_DIR." WARNING

    # Install and enable services
    for service_file in $(find "$INSTALL_DIR" -type f -name "*.service"); do
        local SERVICE_NAME="$(basename ${service_file})"
        local SERVICE_PATH="/etc/systemd/system/$SERVICE_NAME"

        # Replace placeholders in service file: INSTALL_DIR and SERVICE_USER
        sudo sed -e "s#@@INSTALL_DIR@@#$INSTALL_DIR#g" \
            -e "s/@@SERVICE_USER@@/$SERVICE_USER/g" \
            ${service_file} | sudo tee $SERVICE_PATH >/dev/null
    done

    # Change placeholder pingserver to neighbor node in connection status script
    # This ensures the indicator light monitors the neighbor
    sed -i "s/google.com/$NEIGHBOR_IP/g" $INSTALL_DIR/common/connection_status_led.py
    log_message ${func} "Updated connection status script to ping ${NEIGHBOR_IP}." DEBUG

    # Enable and start services
    sudo systemctl daemon-reload
    for service in ${SERVICES_TO_ENABLE[@]}; do
        sudo systemctl enable --quiet --now "$service"
        if [ $? -ne 0 ]; then
            log_message ${func} "Error enabling service "$service"." ERROR
        else
            log_message ${func} "Service "$service" enabled successfully." INFO
        fi
    done
    
    # Enable I2C bus for Fan Controller (i2c-10 on CM4)
    ### NOTE: Keeping for reference, but disabling for now.
    # log_message ${func} "Checking I2C bus configuration..." INFO
    # if ! grep -q 'dtparam=i2c_vc=on' /boot/firmware/config.txt; then
    #     # Add the line if it's missing 
    #     sudo sed -i '$a\dtparam=i2c_vc=on' /boot/firmware/config.txt
    #     log_message ${func} "I2C setting added to config.txt. Requires reboot." WARNING
    # else
    #     log_message ${func} "I2C setting already configured." INFO
    # fi

    log_message ${func} "Project installation complete." WARNING
    return 0
}


# --- MAIN EXECUTION LOGIC ---
FUNC_TO_RUN=""
LOG_LEVEL="$DEFAULT_LOG_LEVEL" # Initialize LOG_LEVEL with default
func="MAIN"

while getopts "f:l:h" opt; do
    case ${opt} in
        f)
            FUNC_TO_RUN="$OPTARG"
            ;;
        l)
            # Normalize and set the log level
            LOG_LEVEL=$(echo "$OPTARG" | tr '[:lower:]' '[:upper:]')
            ;;
        h)
            log_message ${func} "Usage: $0 [-f function_name] [-l LOG_LEVEL]. Available functions: install_project, configure_signal_ip, generate_ssh_key" INFO
            log_message ${func} "LOG_LEVEL can be DEBUG, INFO (default), WARNING, or ERROR." INFO
            exit 0
            ;;
        \?)
            log_message ${func} "Invalid option provided." WARNING
            exit 1
            ;;
        :)
            log_message ${func} "Error: Option -${OPTARG} requires an argument." ERROR
            exit 1
            ;;
    esac
done

# Ensure host & peer variables are defined
who_am_i

# Process the defined function.
if [ -n "$FUNC_TO_RUN" ]; then
    # Execute single requested function
    case "$FUNC_TO_RUN" in
        install_project|configure_signal_ip|generate_ssh_key)
            "$FUNC_TO_RUN" || { log_message ${func} "Function failed: $FUNC_TO_RUN" ERROR; exit 1; }
            ;;
        *)
            log_message ${func} "Function '$FUNC_TO_RUN' not recognized or cannot be run directly. Exiting." WARNING
            exit 1
            ;;
    esac
else
    # Full Run: Execute the entire setup sequence
    log_message ${func} "Running full setup sequence for $TARGET_NODE." INFO
    
    # 1. Static IP Configuration (only if NetworkManager is present)
    configure_signal_ip || { log_message ${func} "Setup aborted: configure_signal_ip failed." ERROR; exit 1; }
    
    # 2. SSH Key Generation
    generate_ssh_key || { log_message ${func} "Setup aborted: generate_ssh_key failed." ERROR; exit 1; }
    
    # 3. Project Installation
    install_project || { log_message ${func} "Setup aborted: install_project failed." ERROR; exit 1; }
    
    log_message ${func} "Full setup sequence finished." INFO
fi