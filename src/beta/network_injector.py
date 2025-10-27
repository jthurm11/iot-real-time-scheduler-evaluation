# Network Congestion Injection Module
# Simulates network degradation (latency and packet loss) between the PID controller
# and the fan actuator node.

import time
import random
import math

# --- CONFIGURATION (Adjust these values to simulate congestion) ---

# Static Delay (in seconds). This simulates latency.
# 0.05s is a good starting point for moderate congestion. Set to 0.0 for no delay.
CONGESTION_DELAY = 0.005 

# Packet Loss Rate (as a percentage 0.0 to 100.0).
# This simulates dropped packets due to heavy network load.
# Set to 0.0 for no loss. Set higher to simulate significant degradation.
PACKET_LOSS_RATE = 0.0 

# --- END CONFIGURATION ---

def inject_delay_and_check_loss():
    """
    Applies a delay and determines if the packet should be dropped.

    Returns:
        bool: True if the packet should be SENT, False if it should be DROPPED.
    """

    # 1. Inject Latency
    if CONGESTION_DELAY > 0:
        time.sleep(CONGESTION_DELAY)

    # 2. Check for Packet Loss
    if PACKET_LOSS_RATE > 0.0:
        # Check against the loss rate probability (0.0 to 100.0)
        if random.random() * 100.0 < PACKET_LOSS_RATE:
            # Packet loss occurred
            return False 

    # If no loss or loss rate is 0, the packet is sent
    return True

def get_current_status():
    """Returns the current congestion settings for logging/UI."""
    return {
        "delay_s": CONGESTION_DELAY,
        "loss_rate_perc": PACKET_LOSS_RATE
    }

# Ensure the delay is not more than the sample time of the PID controller
# (This is just a warning, as exceeding the sample time will slow down the whole loop)
if CONGESTION_DELAY > 0.1: # Assuming SAMPLE_TIME in sensor_PIDcontroller.py is 0.1s
    print(f"[Injector Warning] CONGESTION_DELAY ({CONGESTION_DELAY}s) is greater than the PID sample time.")
