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
# Commenting out for now to avoid overhead, and defining needed colors exclusively within log_message ${func}().
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

# --- Utility Functions ---

# Function log_message ${func}()
# Usage: log_message ${func} <reporting function> "<message>" LEVEL
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

    echo -e "${color}${timestamp} ${reporter} [${level}]${NC} ${message}"
}

# Function to define key variables and assign hostname if needed
who_am_i() {
    local func="who_am_i" # Define who I am for logger function

    # Disabling output for a quiet function
    #log_message ${func} "--- SET SIGNAL IP ---"

    # Check and set hostname if expected does not match received.
    # This ensures host variables are set if running a subsequent function
    local curr_name=$(nmcli general hostname)
    if [[ "${NODES[@]}" =~ "${curr_name}" ]]; then
        TARGET_NODE="${curr_name}"
    else
        log_message ${func} "--- SETUP HOSTNAME ---" INFO
        log_message ${func} "host _alpha_ = Fan Controller" INFO
        log_message ${func} "host _beta_  = Sensor Manager" INFO
        PS3='Select the hostname for this node: '

        select hostname_choice in "${NODES[@]}"; do
            if [[ " ${NODES[@]} " =~ " ${hostname_choice} " ]]; then
                TARGET_NODE="$hostname_choice"
                break
            else
                log_message ${func} "Invalid selection. Please try again." WARNING
            fi
        done

        # Apply hostname using nmcli (PERSISTENT WRITE)
        #log_message ${func} "Applying hostname to $TARGET_NODE..." INFO
        sudo nmcli general hostname "$TARGET_NODE" >/dev/null
        if [ $? -ne 0 ]; then
            log_message ${func} "Error setting hostname with nmcli." ERROR
            return 1
        else
            log_message ${func} "Hostname set successfully. (Requires reboot to finalize.)" INFO
        fi
    fi

    # Ensure peer variables are defined
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
    TARGET_NET_MASK="${TARGET_IP}/24"

    export TARGET_NODE TARGET_IP NEIGHBOR_NODE NEIGHBOR_IP TARGET_NET_MASK
}

# Function to display usage instructions
# NOTE: This function should be updated if changes/additions are made. 
show_usage() {
    local func="show_usage"
    log_message ${func} "--- SCRIPT USAGE ---" INFO
    echo "Usage: $0 -f [function_name]"
    echo
    echo "Available core functions:"
    printf "  %-25s %s\n" "install_project" "Installs services, copies scripts, and sets permissions."
    printf "  %-25s %s\n" "configure_signal_ip" "Connects to Wi-Fi and sets the static IP address."
    printf "  %-25s %s\n" "check_neighbor" "Pings the other node for network verification."
    printf "  %-25s %s\n" "generate_ssh_key" "Generates a key and attempts to copy it to the neighbor."
    #printf "  %-25s %s\n" "final_summary" "Prints the final node configuration."
    echo
    exit 1
}

# Function to ping the other node (for verification)
check_neighbor() {
    local func="check_neighbor"

    ping -c 2 "$NEIGHBOR_IP" >/dev/null

    if [ $? -eq 0 ]; then
        return 0
    else
        return 1
    fi
}

# --- Core Setup Functions ---

# Function to connect to WiFi and set static IP
configure_signal_ip() {
    local func="configure_signal_ip"
    log_message ${func} "--- STATIC SIGNAL IP CONFIGURATION ---" INFO

    # Check for existing active Wi-Fi connection
    # Default fields for this command are DEVICE,TYPE,STATE,CONNECTION. 
    # These can be changed/ordered with the global '--fields' option. 
    # For now, assume CONNECTION is the 4th column. 
    CONN_NAME=$(nmcli dev | grep "^${WIFI_IF}.* connected " | awk '{print $4}')

    if [ -n "$CONN_NAME" ]; then
        export CONN_NAME

        # There doesn't appear to be any negative effects to re-adding the IP address if
        # the connection profile already has it registered. So, could remove most of
        # this logic to make things more efficient.
        nmcli -g ip4.address connection show "$CONN_NAME" | grep "$TARGET_IP" >/dev/null
        if [ $? -eq 0 ]; then
            log_message ${func} "Signal IP already assigned." INFO
        else
            # /28 = .1 - .14
            sudo nmcli connection modify "$CONN_NAME" +ipv4.addresses "$TARGET_IP/28"
            if [ $? -ne 0 ]; then
                log_message ${func} "Failed to add signal IP ${TARGET_IP}. Check 'sudo nmcli connection show $CONN_NAME'." ERROR
                return 1
            else
                # Activate the connection
                sudo nmcli connection up "$CONN_NAME"
                log_message ${func} "Signal IP added and activated." INFO
                return 0
            fi
        fi
    else
        log_message ${func} "Could not determine Wi-Fi connection." ERROR
        return 1
    fi

    # Shouldn't get here
    return
}

# Function to print final configuration summary
final_summary() {
    local func="final_summary" # Define who I am for logger function
    echo "======================================================="
    log_message ${func} "SETUP COMPLETE: $TARGET_NODE" INFO
    echo "======================================================="

    # Check current Wi-Fi SSID
    ACTIVE_SSID=$(nmcli -t -f active,ssid dev wifi list | grep yes | head -n 1 | cut -d: -f2)
    #ACTIVE_SSID=$(nmcli -g 802-11-wireless.ssid c show $CONN_NAME)

    # Get the static signal IP (matches SIGNAL_NET_PREFIX)
    #STATIC_IP_CLEAN=$(ip a show dev "$WIFI_IF" | grep 'inet ' | grep "$SIGNAL_NET_PREFIX" | awk '{print $2}' | cut -d/ -f1)

    # Get the DHCP assigned IP (does NOT match SIGNAL_NET_PREFIX)
    #DHCP_IP=$(ip a show dev "$WIFI_IF" | grep 'inet ' | grep -v "$SIGNAL_NET_PREFIX" | awk '{print $2}' | cut -d/ -f1)

    # Get all assigned IP4 addresses
    IP_ADDRS=$(nmcli -g ip4.address connection show $CONN_NAME)

    printf "%-25s %s\n" "Hostname:" "$TARGET_NODE"
    printf "%s\n" "-------------------------------------------------------"
    #printf "%-25s %s\n" "DHCP Assigned IP (Primary):" "$DHCP_IP"
    #printf "%-25s %s\n" "Static Control IP (Signal):" "$STATIC_IP_CLEAN"
    printf "%-25s %s\n" "Assigned IPs:" "$IP_ADDRS"
    printf "%-25s %s\n" "Connected Wi-Fi SSID:" "$ACTIVE_SSID"

    echo "======================================================="
    log_message ${func} "If hostname was changed, please reboot the system now" INFO
}

# Function to generate SSH keys for GitHub access.
generate_ssh_key() {
    local func="generate_ssh_key" # Define who I am for logger function
    log_message ${func} "--- GENERATING SSH KEY ---" INFO
    local ssh_file="$HOME/.ssh/id_ed25519"

    if ! [ -f "${ssh_file}" ]; then
        # Ensure the .ssh directory exists
        mkdir -p ~/.ssh

        # Quietly generate SSH key with no passphrase for automation.
        ssh-keygen -q -t ed25519 -f "$ssh_file" -C "$TARGET_NODE" -N ""
    fi
    pub_key=$(cat "${ssh_file}.pub")

    log_message ${func} "Action Required" DEBUG
    log_message ${func} "Add the following public key as a 'Deploy Key' to the GitHub repository:"
    echo
    echo "$pub_key"
    echo

    # Attempt to copy the public key to our neighbor. BatchMode won't prompt for a password.
    #ssh -o BatchMode=yes -o ConnectTimeout=5 $SERVICE_USER@"$NEIGHBOR_IP" "mkdir -p ~/.ssh && \
    ssh -o ConnectTimeout=5 "$NEIGHBOR_IP" "mkdir -p ~/.ssh && \
        echo \"$pub_key\" >> ~/.ssh/authorized_keys && \
        chmod 700 ~/.ssh && chmod 600 ~/.ssh/authorized_keys" 2>/dev/null

    if [ $? -ne 0 ]; then
        log_message ${func} "Error installing SSH keys to neighbor" WARNING
    fi
    return 0
}

# --- Service Deployment Functions ---

# Function to copy files and set permissions
install_project() {
    local func="install_project" # Define who I am for logger function
    log_message ${func} "--- INSTALLING PROJECT FILES ---" INFO

    # Check that node-specific directory exists, because if not, 
    # either we're in the wrong place or the repo isn't installed.
    if ! [ -d $TARGET_NODE ]; then
        log_message ${func} "Cannot find project files. Ensure repo is installed." ERROR
        return 1
    fi

    # Create target directory and copy all files. 
    # Note that we only want common and node-specific scripts copied, 
    # so that incorrect services are not enabled in the next step.
    sudo mkdir -p "$INSTALL_DIR"
    sudo cp -r "$SCRIPT_DIR"/{common,$TARGET_NODE} "$INSTALL_DIR"/

    # Set proper ownership and permissions
    CURR_USER="$(id -un)"
    if [[ "$SERVICE_USER" != "$CURR_USER" ]]; then
        SERVICE_USER="$CURR_USER"
    fi
    sudo chown -R $SERVICE_USER:$SERVICE_USER "$INSTALL_DIR"
    sudo find "$INSTALL_DIR" -type f -name "*.py" -exec chmod +x {} \;

    log_message ${func} "Project files installed successfully to $INSTALL_DIR." INFO

    # Install and enable services
    declare -a installed_services
    for service_file in $(find "$INSTALL_DIR" -type f -name "*.service"); do
        local SERVICE_NAME="$(basename ${service_file})"
        local SERVICE_PATH="/etc/systemd/system/$SERVICE_NAME"
        local SCRIPT_PATH="$INSTALL_DIR/$SERVICE_NAME"

        # Expression #1 uses '#' delimiters due to file path expansion. 
        sudo sed -e "s#@@INSTALL_DIR@@#$INSTALL_DIR#g" \
            -e "s/@@SERVICE_USER@@/$SERVICE_USER/g" \
            ${service_file} | sudo tee $SERVICE_PATH >/dev/null

        # Add name of service to array, to enable in next step.
        installed_services+=("$SERVICE_NAME")
    done
    sudo systemctl daemon-reload
    for service in ${installed_services[@]}; do
        sudo systemctl enable --quiet --now "$service"
        if [ $? -ne 0 ]; then
            log_message ${func} "Error enabling service "$service"". ERROR
        else
            log_message ${func} "Service "$service" enabled succesfully." INFO
        fi
    done
    unset installed_services
    log_message ${func} "Project services installed and creation attempted." 
    return 0
}

# --- MAIN EXECUTION LOGIC ---
FUNC_TO_RUN=""

while getopts "f:h" opt; do
    case ${opt} in
        f)
            FUNC_TO_RUN="$OPTARG"
            ;;
        h)
            # Help was asked for
            show_usage
            ;;
        \?)
            # Invalid option provided
            show_usage
            ;;
        :)
            # Option requires an argument
            echo "Error: Option -${OPTARG} requires an argument." >&2
            show_usage
            ;;
    esac
done

# --- EXECUTION ---
# Ensure host & peer variables are defined
who_am_i
func="MAIN"

# Process the defined function.
if [ -n "$FUNC_TO_RUN" ]; then
    # Option -f provided: Execute the specified function using a case statement.
    log_message ${func} "Executing requested function: $FUNC_TO_RUN"

    case "$FUNC_TO_RUN" in
        who_am_i|log_message|show_usage)
            log_message ${func} "Utility function '$FUNC_TO_RUN' cannot be run directly." WARNING
            show_usage
            ;;
        install_project|configure_signal_ip|check_neighbor|generate_ssh_key)
            # Core functions are run here.
            "$FUNC_TO_RUN" || { log_message ${func} "Function failed: $FUNC_TO_RUN" ERROR; exit 1; }
            ;;
        *)
            log_message ${func} "Function '$FUNC_TO_RUN' not found or is not a core function." WARNING
            show_usage
            ;;
    esac
else
    # No argument provided. Running full setup sequence.
    # The full sequence is now explicitly defined here:
    configure_signal_ip || { log_message ${func} "Setup aborted due to function failure: configure_signal_ip" WARNING; exit 1; }
    check_neighbor || { log_message ${func} "Neighbor could not be reached: check_neighbor" WARNING; }
    generate_ssh_key || { log_message ${func} "Setup aborted due to function failure: generate_ssh_key" WARNING; exit 1; }
    install_project #|| { log_message ${func} "Setup aborted due to function failure: install_project" WARNING; exit 1; }
    final_summary
fi
