#!/usr/bin/env python3
# REPLACED RPi.GPIO WITH SMBUS2 FOR EMC2301 CONTROL

import smbus2 
import socket
import select
import time
import math # Needed for tachometer calculations

# --- EMC2301 CONFIGURATION (Confirmed by CM4 IO Board Schematic) ---
# NOTE: The CM4 IO Board's I2C bus for the fan is typically I2C-10 (depending on baseboard)
# However, many standard Pi setups default to I2C-1. We'll use a standard bus and note the change.
I2C_BUS = 10                  # **MUST VERIFY:** Often I2C-10 on official CM4 IO Board
I2C_ADDR = 0x2F               # EMC2301 I2C Slave Address (0101111b)

# EMC2301 Register Addresses
FAN_PWM_REG = 0x30            # Fan 1 PWM Duty Cycle Register
TACH_HIGH_REG = 0x3E          # Fan 1 Tachometer Reading (High Byte)
TACH_COUNT_REG = 0x47         # Fan 1 Tach Count (Pulses per Revolution) - Default is 2 (2 PPR)
FAN_CONFIG_REG = 0x3C         # Fan Configuration Register (for enabling PWM mode)

# Fan constant based on EMC2301 datasheet (used for RPM calculation)
TACH_DIVISOR = 0.5            # 0.5 assumes the default TACH_COUNT is 2 pulses/rev

UDP_IP = "0.0.0.0"            # Listen on all interfaces
UDP_PORT = 5005
TIMEOUT = 0.01
BUFFER_SIZE = 1024

# --- I2C SETUP ---
try:
    bus = smbus2.SMBus(I2C_BUS)
    # 1. Set Fan to Manual PWM Mode (write to Fan Configuration Register 0x3C)
    # Bit D7=0 (manual mode), Bits D[6:5]=00 (PWM frequency 22.5kHz with default divisor)
    bus.write_byte_data(I2C_ADDR, FAN_CONFIG_REG, 0x00)
    print(f"[Fan] I2C Bus {I2C_BUS} initialized. EMC2301 in Manual PWM Mode.")
except Exception as e:
    print(f"[Fan] ERROR: Could not initialize I2C bus or EMC2301 chip. {e}")
    bus = None

# --- TACHOMETER READ FUNCTION ---
def read_fan_rpm(bus, i2c_addr):
    if bus is None:
        return -1
    
    try:
        # Read the 16-bit Tachometer value (High byte followed by Low byte)
        # Reading a 16-bit register (Reg 0x3E and 0x3F)
        tach_value = bus.read_word_data(i2c_addr, TACH_HIGH_REG)
        
        # The result of read_word_data is little-endian (LSB first), need to swap bytes
        # to get the Big-Endian (MSB first) order used by the chip.
        tach_value = ((tach_value & 0xFF) << 8) | ((tach_value >> 8) & 0xFF)
        
        if tach_value == 0xFFFF or tach_value == 0x0000:
            return 0  # Fan is likely stopped or error

        # RPM Calculation Formula from EMC2301 Datasheet:
        # RPM = (f_tach * 60) / (TACH_VALUE * TACH_PPR)
        # Where f_tach is the Tachometer Clock Frequency (typically 1.15 MHz)
        # Simplified: RPM = (1843200 / TACH_VALUE) * TACH_DIVISOR
        
        # The TACH_VALUE read from the register is inversely proportional to RPM
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
    # EMC2301 uses an 8-bit register for PWM duty (0x00 = 0%, 0xFF = 100%)
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
            try:
                data, addr = sock.recvfrom(BUFFER_SIZE)
                duty = float(data.decode().strip())
                duty = max(0, min(100, duty))  # clamp

                if duty != current_duty:
                    if set_pwm_duty(bus, I2C_ADDR, duty) == 0:
                        current_duty = duty
                    
                # Read and log the fan status regardless of packet arrival
                fan_rpm = read_fan_rpm(bus, I2C_ADDR)
                
                print(f"[Fan] Duty={current_duty:5.1f}% | RPM={fan_rpm:6d} | from {addr[0]}")
                
            except ValueError:
                print("[Fan] Invalid data received.")
            except Exception as e:
                print(f"[Fan] Error: {e}")
        else:
            # If no packet, still read RPM to monitor fan health
            fan_rpm = read_fan_rpm(bus, I2C_ADDR)
            print(f"[Fan] IDLE. Duty={current_duty:5.1f}% | RPM={fan_rpm:6d}")
            time.sleep(TIMEOUT * 10) # Slow down polling when idle

except KeyboardInterrupt:
    print("\n[Fan] Stopped manually.")
finally:
    if bus:
        set_pwm_duty(bus, I2C_ADDR, 0) # Set duty to 0% on exit
    sock.close()
    print("[Fan] Clean exit.")