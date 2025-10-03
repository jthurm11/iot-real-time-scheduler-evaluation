#!/bin/bash
# This script configures the hostname, sets a static IP (192.168.1.x),
# establishes the Wi-Fi connection, and verifies network connectivity using nmcli
# for consistent deployment in a Debian Bookworm environment.
#
# USAGE (Run all tasks): ./setup_nodes.sh
# USAGE (Run single task): ./setup_nodes.sh [function_name]

# --- GLOBAL CONFIGURATION ---
WIFI_IF="wlan0"
WIFI_NAME="primary-wifi"
NODES=("alpha" "beta")
SIGNAL_NET="192.168.22"

# Function to select hostname
set_hostname() {
    echo "--- HOSTNAME SELECTION AND IP ASSIGNMENT ---"
    PS3='Select the hostname for this node: '

    select HOSTNAME_CHOICE in "${NODES[@]}"; do
        if [[ " ${NODES[@]} " =~ " ${HOSTNAME_CHOICE} " ]]; then
            TARGET_HOSTNAME="$HOSTNAME_CHOICE"
            break
        else
            echo "Invalid selection. Please try again."
        fi
    done

    # Apply hostname using nmcli
    echo -en "Applying hostname to $TARGET_HOSTNAME..."
    sudo nmcli general hostname "$TARGET_HOSTNAME" >/dev/null
    if [ $? -ne 0 ]; then 
        echo -e "Error setting hostname"
    else
        echo -e "Done"
    fi

    export TARGET_HOSTNAME
}

# Function to assign static IP based on hostname
set_signal_ip() { 
    case "$TARGET_HOSTNAME" in
        "alpha")
            TARGET_IP="${SIGNAL_NET}.1/24"
            ;;
        "beta")
            TARGET_IP="${SIGNAL_NET}.2/24"
            ;;
    esac

    export TARGET_IP
}

# Function to connect to WiFi and set static IP
configure_wifi() {
    if [ -z "$TARGET_IP" ]; then
        echo "Error: Hostname and IP must be set first. Run 'set_hostname' or the default script flow."
        return 1
    fi
    
    echo -e "\n--- WI-FI SCAN AND STATIC CONFIGURATION ---"
    
    # Check for existing active connection
    IS_WIFI_CONNECTED=$(nmcli dev | grep "${WIFI_IF}" | grep -w "connected")

    # TODO - Here down, change next to case statement
    if [ -n "$IS_WIFI_CONNECTED" ]; then
        echo "WARNING: Wi-Fi device ($WIFI_IF) is already connected."
        read -r -p "Do you want to skip reconfiguring the Wi-Fi? (y/N): " SKIP_WIFI
        if [[ "$SKIP_WIFI" =~ ^[Yy]$ ]]; then
            echo "Skipping Wi-Fi connection step."
            return 0
        fi
    fi

    # Scan and get input
    echo -e "\nAvailable Networks:"
    nmcli -f IN-USE,BSSID,SSID,SIGNAL,BARS dev wifi list
    
    read -p "Enter the desired Wi-Fi Network SSID (Name): " WIFI_SSID
    read -s -p "Enter the Wi-Fi Password: " WIFI_PASS
    echo ""

    echo -e "Configuring static Wi-Fi connection ($WIFI_NAME)..."

    # Delete any existing connection with the same name before creation
    sudo nmcli connection delete "$WIFI_NAME" 2>/dev/null

    # Create and configure the new static profile
    sudo nmcli connection add type wifi con-name "$WIFI_NAME" ifname "$WIFI_IF" ssid "$WIFI_SSID" \
        wifi-sec.key-mgmt wpa-psk wifi-sec.psk "$WIFI_PASS" \
        ipv4.method manual \
        ipv4.addresses "$TARGET_IP" \
        ipv4.gateway "$GATEWAY_IP" \
        ipv4.dns "$DNS_IP" \
        autoconnect yes

    if [ $? -ne 0 ]; then
        echo "CRITICAL WARNING: Failed to create/configure static Wi-Fi profile. Check SSID/Password."
        return 1
    else
        echo "Static Wi-Fi profile '$WIFI_NAME
    ' created and configured."
    fi

    # Activate the connection
    sudo nmcli connection up "$WIFI_NAME"
    if [ $? -eq 0 ]; then
        echo "Connection activated successfully."
    else
        echo "WARNING: Connection failed to activate. Check network status."
    fi
}

# Function to ping the other node (for verification)
verify_connectivity() {
    if [ "$TARGET_HOSTNAME" == "alpha" ]; then
        OTHER_NODE_IP="192.168.1.11"
        OTHER_NODE_NAME="beta"
    elif [ "$TARGET_HOSTNAME" == "beta" ]; then
        OTHER_NODE_IP="192.168.1.10"
        OTHER_NODE_NAME="alpha"
    else
        echo -e "\n--- 3. VERIFICATION ---"
        echo "Cannot verify connectivity: Hostname is not set to 'alpha' or 'beta'."
        return 1
    fi

    echo -e "\n--- 3. CONNECTIVITY VERIFICATION ---"
    echo "Attempting to ping the other node ($OTHER_NODE_NAME at $OTHER_NODE_IP)..."

    ping -c 3 "$OTHER_NODE_IP"

    if [ $? -eq 0 ]; then
        echo "SUCCESS: Connectivity verified with $OTHER_NODE_NAME."
    else
        echo "FAILURE: Could not ping $OTHER_NODE_NAME. Check network and IP settings on both devices."
    fi
}

# Function to print final configuration summary
final_summary() {
    echo -e "\n======================================================="
    echo " SETUP COMPLETE: $TARGET_HOSTNAME"
    echo "======================================================="

    # Get the applied IP 
    CURRENT_IP=$(ip a show dev "$WIFI_IF" | grep 'inet ' | awk '{print $2}' | cut -d/ -f1 | head -n 1)

    printf "%-25s %s\n" "Hostname:" "$TARGET_HOSTNAME"
    printf "-------------------------------------------------------\n"
    printf "%-25s %s\n" "Configured Static IP:" "${TARGET_IP%%/*}"
    printf "%-25s %s\n" "Active IP on WIFI_IF:" "$CURRENT_IP"
    
    # Check current Wi-Fi SSID
    ACTIVE_SSID=$(nmcli -t -f active,ssid dev wifi list | grep yes | head -n 1 | cut -d: -f2)
    printf "%-25s %s\n" "Connected Wi-Fi SSID:" "$ACTIVE_SSID"

    echo "======================================================="
    echo "Please reboot the system now to finalize the hostname change: sudo reboot"
}

# --- MAIN EXECUTION LOGIC ---

# Check and set hostname if expected does not match received.
CURR_NAME=$(nmcli general hostname)
if [[ "${NODES[@]}" =~ "${CURR_NAME}" ]]; then
    TARGET_HOSTNAME="${CURR_NAME}"
else
    set_hostname
fi


# Array of all functions to run by default
ALL_FUNCTIONS=(set_hostname configure_wifi verify_connectivity final_summary)

# Check for argument: if provided, run only that function
if [ ! -z "$1" ]; then
    if declare -f "$1" > /dev/null; then
        echo "Executing requested function: $1"
        # Run only the specified function
        "$1"
    else
        echo "Error: Function '$1' not found."
        echo "Available functions: ${ALL_FUNCTIONS[@]}"
    fi
else
    echo "No argument provided. Running full setup sequence."
    # Run all functions sequentially
    for func in "${ALL_FUNCTIONS[@]}"; do
        # We need set_hostname to run first to define TARGET_HOSTNAME/TARGET_IP
        if [ "$func" == "configure_wifi" ] || [ "$func" == "verify_connectivity" ] || [ "$func" == "final_summary" ]; then
            # Ensure hostname is set before moving to configuration/verification
            if [ -z "$TARGET_HOSTNAME" ]; then
                set_hostname
            fi
        fi
        
        # Execute the function
        "$func" || break # Stop if a critical function fails (currently, only configure_wifi uses this)
    done
fi