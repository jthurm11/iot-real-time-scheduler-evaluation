#!/usr/bin/env python3
# REPLACED RPi.GPIO WITH SMBUS2 FOR EMC2301/EMC2101 CONTROL

import smbus2 
import socket
import select
import time
import math

# --- FAN CONTROLLER CONFIGURATION ---
# Prioritized list of (I2C_BUS_ID, I2C_ADDRESS, CONFIG_REGISTER) tuples:
# 1. CM4 IO Board (Bus 10, EMC2301 at 0x2F, Config Register 0x3C) - High Priority
# 2. Pi 3B + EMC2101 HAT (Bus 1, EMC2101 at 0x4C, Config Register 0x4C) - Fallback
I2C_PRIORITY_COMBOS = [
    (10, 0x2F, 0x3C),  # CM4 I/O Board setup
    (1, 0x4C, 0x4C)    # Pi 3B/Legacy setup
]

# Shared Register Addresses (standard across EMC fan controllers)
FAN_PWM_REG = 0x30            # Fan 1 PWM Duty Cycle Register
TACH_HIGH_REG = 0x3E          # Fan 1 Tachometer Reading (High Byte)

# Fan constant based on EMC2101/2301 datasheet (used for RPM calculation)
TACH_DIVISOR = 0.5            # 0.5 assumes the default TACH_COUNT is 2 pulses/rev

# Variables to be set during successful initialization
bus = None
i2c_address = None
config_reg = None

UDP_IP = "0.0.0.0"            # Listen on all interfaces
UDP_PORT = 5005
TIMEOUT = 0.01
BUFFER_SIZE = 1024

# --- I2C SETUP WITH BUS/ADDRESS FALLBACK ---
# Try to initialize the I2C bus by checking the prioritized combos
for current_bus_id, current_i2c_addr, current_config_reg in I2C_PRIORITY_COMBOS:
    try:
        bus = smbus2.SMBus(current_bus_id)

        # 1. Attempt read at the specific address to confirm chip presence (Product ID Register)
        # If the chip is not present, this will throw an IOError or generic Exception
        product_id = bus.read_byte_data(current_i2c_addr, 0xFD)

        # 2. Configure the fan to Manual PWM Mode (write 0x00)
        bus.write_byte_data(current_i2c_addr, current_config_reg, 0x00)

        # Success! Set the final variables and exit the loop.
        i2c_address = current_i2c_addr
        config_reg = current_config_reg
        print(f"[Fan] I2C Bus {current_bus_id} initialized successfully at address 0x{i2c_address:X} (Config Reg: 0x{config_reg:X}).")
        break 

    except FileNotFoundError:
        # Bus not found (e.g., trying bus 10 on a Pi 3B without configuration)
        print(f"[Fan] I2C Bus {current_bus_id} not found. Trying next combo...")
        bus = None # Ensure bus is None for next attempt
    except IOError as e:
        # Chip not responding or other I/O error
        print(f"[Fan] I2C Bus {current_bus_id} at 0x{current_i2c_addr:X} initialization failed: {e}. Trying next combo...")
        bus = None
    except Exception as e:
        print(f"[Fan] I2C Bus {current_bus_id} failed with generic error: {e}. Trying next combo...")
        bus = None

if bus is None:
    print("[Fan] FATAL ERROR: Could not initialize I2C bus or EMC chip on any known bus/address.")

# --- TACHOMETER READ FUNCTION ---
def read_fan_rpm(bus, i2c_addr):
    if bus is None:
        return -1

    try:
        # Read the 16-bit Tachometer value
        tach_value = bus.read_word_data(i2c_addr, TACH_HIGH_REG)

        # Swap bytes (Little-Endian to Big-Endian)
        tach_value = ((tach_value & 0xFF) << 8) | ((tach_value >> 8) & 0xFF)

        if tach_value == 0xFFFF or tach_value == 0x0000:
            return 0  # Fan is likely stopped or error

        # RPM Calculation Formula from EMC Datasheet
        rpm = (1843200 / tach_value) * TACH_DIVISOR 

        return int(round(rpm))

    except IOError as e:
        # I2C communication error
        return -2 # Indicates read failure

# --- PWM WRITE FUNCTION ---
def set_pwm_duty(bus, i2c_addr, duty_percent):
    if bus is None:
        return -1

    # Scale 0-100% duty cycle to 8-bit register value (0-255)
    duty_byte = int(round(duty_percent * 2.55)) # 255/100 = 2.55
    duty_byte = max(0x00, min(0xFF, duty_byte))

    try:
        bus.write_byte_data(i2c_addr, FAN_PWM_REG, duty_byte)
        return 0
    except IOError as e:
        print(f"[Fan] I2C Write Error: {e}")
        return -1

# --- UDP SOCKET SETUP ---
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.bind((UDP_IP, UDP_PORT))
sock.setblocking(0)
print(f"[Fan] Listening for UDP control on port {UDP_PORT}")

# --- MAIN LOOP ---
current_duty = -1
try:
    while True:
        ready = select.select([sock], [], [], TIMEOUT)
        if ready[0]:
            # Drain all packets from the buffer, only keeping the last one
            latest_data = None
            # Use select with a zero timeout (0) to check for more packets immediately
            while ready[0]:
                data, addr = sock.recvfrom(BUFFER_SIZE)
                latest_data = data
                ready = select.select([sock], [], [], 0) 

            if latest_data:
                try:
                    data = latest_data # Process the freshest data
                    duty = float(data.decode().strip())
                    duty = max(0, min(100, duty))  # clamp

                    if duty != current_duty:
                        if set_pwm_duty(bus, i2c_address, duty) == 0:
                            current_duty = duty

                    # Read and log the fan status regardless of packet arrival
                    fan_rpm = read_fan_rpm(bus, i2c_address)
                    print(f"[Fan] Duty={current_duty:5.1f}% | RPM={fan_rpm:6d} | from {addr[0]}")

                except ValueError:
                    print("[Fan] Invalid data received.")
                except Exception as e:
                    print(f"[Fan] Error during processing: {e}")
        else:
            # If no packet, still read RPM to monitor fan health
            fan_rpm = read_fan_rpm(bus, i2c_address)
            print(f"[Fan] IDLE. Duty={current_duty:5.1f}% | RPM={fan_rpm:6d}")
            time.sleep(TIMEOUT * 10) # Slow down polling when idle

except KeyboardInterrupt:
    print("\n[Fan] Stopped manually.")
finally:
    # Ensure a valid address was found before attempting to write 0
    if bus and i2c_address is not None:
        set_pwm_duty(bus, i2c_address, 0) # Set duty to 0% on exit
    sock.close()
    print("[Fan] Clean exit.")
