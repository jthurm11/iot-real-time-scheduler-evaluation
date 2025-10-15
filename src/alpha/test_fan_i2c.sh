#!/bin/bash
#
# EMC2101 Fan Controller Diagnostic Script
#
# This script systematically attempts to force the EMC2101 into manual PWM mode
# and set the duty cycle to 100%. It uses I2C commands and logs results.
#

# --- GLOBAL CONFIGURATION ---
BUS=1             # I2C Bus number (usually 1 on Raspberry Pi)
ADDR="0x4c"       # I2C Address of the EMC2101
DEV_ID_REG="0xFD" # Device ID Register (Expected: 0x16 or 0x28)
CTRL_REG="0x03"   # Control Register
FAN_CONF_REG="0x48" # Fan Configuration Register (for LUT Enable/Disable)
FAN_OUT_REG="0x41" # Fan Output Configuration Register (for PWM/DAC/Manual)
PWM_FREQ_REG="0x47" # PWM Frequency Divisor Register
DUTY_REG="0x30"   # Manual PWM Duty Cycle Register

# Target Values
DUTY_MAX="0xff"   # 100% PWM Duty Cycle
PWM_MODE="0x04"   # Value to set 0x41 for PWM Mode
LUT_DISABLE="0x00" # Value to set 0x48 to disable LUT (Auto) mode
RESET_VAL="0x00"  # Value to clear 0x03 register

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

# --- I2C WRAPPER FUNCTIONS ---

check_retval() {
    local func_name="$1"
    if [ $? -ne 0 ]; then
        log_message "$func_name" "i2cset FAILED. Communication error or permissions issue." "ERROR"
        return 1
    else
        log_message "$func_name" "i2cset OK." "INFO"
        return 0
    fi
}

i2c_write() {
    local reg="$1" val="$2" write_type="$3" func_name="$4"
    log_message "$func_name" "Writing ${val} to Reg ${reg} (Type: ${write_type})..." "DEBUG"
    # Use -f (force) to bypass confirmation prompt
    sudo i2cset -y ${BUS} ${ADDR} ${reg} ${val} ${write_type}
    check_retval "$func_name"
}

# --- CONFIGURATION FUNCTIONS ---

read_device_id() {
    local func_name="${FUNCNAME[0]}"
    log_message "$func_name" "Reading Device ID (Reg ${DEV_ID_REG})..."
    device_id=$(sudo i2cget -y ${BUS} ${ADDR} ${DEV_ID_REG})
    log_message "$func_name" "Device ID Read: ${device_id}." "INFO"
    
    if [[ "${device_id}" == "0x28" ]]; then
        log_message "$func_name" "Chip identified as EMC2101-R. Attempting Unlock Code..." "WARNING"
        # Microchip/SMSC chips sometimes require a special write to register 0x28
        # This is a key register for the 'R' revision, often used for status/locks.
        # We'll use the write in a dedicated sequence instead of here.
        return 0 # Success for chip ID check
    else
        log_message "$func_name" "Chip ID is ${device_id}. Proceeding with standard config."
        return 0
    fi
}

clear_control_register() {
    local func_name="${FUNCNAME[0]}"
    i2c_write "${CTRL_REG}" "${RESET_VAL}" "b" "$func_name"
    # Verify the write stuck
    local current_val=$(sudo i2cget -y ${BUS} ${ADDR} ${CTRL_REG})
    if [[ "${current_val}" == "${RESET_VAL}" ]]; then
        log_message "$func_name" "Verified Reg ${CTRL_REG} cleared to ${RESET_VAL}." "INFO"
    else
        log_message "$func_name" "Verification FAILED: Reg ${CTRL_REG} is ${current_val} (expected ${RESET_VAL})." "ERROR"
    fi
}

disable_lut() {
    local func_name="${FUNCNAME[0]}"
    i2c_write "${FAN_CONF_REG}" "${LUT_DISABLE}" "b" "$func_name"
}

set_pwm_freq() {
    local func_name="${FUNCNAME[0]}"
    i2c_write "${PWM_FREQ_REG}" "0x02" "b" "$func_name"
    
    local current_val=$(sudo i2cget -y ${BUS} ${ADDR} ${PWM_FREQ_REG})
    log_message "$func_name" "PWM Freq Divisor Read: ${current_val}"
}

enable_fan_output() {
    local func_name="${FUNCNAME[0]}"
    i2c_write "${FAN_OUT_REG}" "${PWM_MODE}" "b" "$func_name"
}

duty_cycle_max() {
    local func_name="${FUNCNAME[0]}"
    i2c_write "${DUTY_REG}" "${DUTY_MAX}" "b" "$func_name"
}

duty_cycle_max_word_write() {
    local func_name="${FUNCNAME[0]}"
    # Attempt a Word Write (w) to the Duty Cycle Register
    # Value is 0xFF00, written as 0xFF followed by 0x00
    i2c_write "${DUTY_REG}" "0xff00" "w" "$func_name"
}

check_settings() {
    local func_name="${FUNCNAME[0]}"
    log_message "$func_name" "Verifying Duty Cycle Write (Reg ${DUTY_REG})..."
    local setting=$(sudo i2cget -y ${BUS} ${ADDR} ${DUTY_REG})
    
    log_message "$func_name" "Duty Cycle Read: ${setting} (Expected: ${DUTY_MAX})" "DEBUG"

    if [[ "${setting}" == "${DUTY_MAX}" ]]; then
        log_message "$func_name" "SUCCESS: Register accepted the write! Fan should be 100%." "INFO"
        return 0
    else
        log_message "$func_name" "FAILED: Register still reports ${setting}. Write was blocked or failed." "ERROR"
        return 1
    fi
}

# --- TESTING SEQUENCES ---

run_test_sequence() {
    local sequence_name="$1"
    local duty_func="$2" # Function to perform the final duty cycle write
    
    log_message "---" "--- Running Test: ${sequence_name} ---" "WARNING"
    
    # Standard Setup Steps
    clear_control_register
    disable_lut
    enable_fan_output
    set_pwm_freq
    
    # Critical Write Step (Varies per test)
    ${duty_func}
    sleep 1 # Wait for the register to settle
    
    # Verification
    check_settings
    
    log_message "---" "--- Test ${sequence_name} Complete ---" "WARNING"
}

# --- MAIN EXECUTION ---

read_device_id

# ------------------------------------------------------------------
# Test 1: Standard Byte Write (Most likely to succeed if configuration is correct)
# ------------------------------------------------------------------
run_test_sequence "Standard Byte Write (b) Sequence" "duty_cycle_max"


# ------------------------------------------------------------------
# Test 2: Word Write (w) (Tests for I2C protocol requirement)
# ------------------------------------------------------------------
# We repeat the setup, but use the 'w' flag for the final critical write.
run_test_sequence "Word Write (w) Sequence" "duty_cycle_max_word_write"

# ------------------------------------------------------------------
# Test 3: Unlock Code + Standard Byte Write (If previous tests fail)
# ------------------------------------------------------------------
log_message "---" "--- Running Test: Unlock Code Attempt ---" "WARNING"
log_message "UnlockTest" "Attempting specific unlock sequence for EMC2101-R..." "ERROR"

# 1. Attempt the soft-reset/unlock key write
i2c_write "0x28" "0x8b" "b" "UnlockTest"
sleep 0.5

# 2. Rerun the configuration sequence
run_test_sequence "Unlock Code + Standard Byte Write" "duty_cycle_max"

exit 0
