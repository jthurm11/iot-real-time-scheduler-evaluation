# Network Congestion Injection Module
# Simulates network degradation (latency and packet loss) between the PID controller
# and the fan actuator node.

import time
import random
import json 
import os 
import logging

logger = logging.getLogger(__name__)

# --- CONFIGURATION PATH ---
# The Master Controller writes to this file
CONGESTION_CONFIG_FILE = "/opt/project/common/congestion_config.json"


# --- CONFIGURATION FUNCTIONS ---

def read_congestion_config():
    """
    Reads congestion settings from the JSON file. 
    The Master Controller writes delay in milliseconds (ms).
    This function converts it to seconds (s) for use with time.sleep().

    Returns:
        dict: A dictionary containing 'delay_s' (seconds) and 'loss_rate_perc' (%).
    """
    # Default values (0.0 delay in seconds, 0.0% loss)
    current_status = {
        "delay_s": 0.0,
        "loss_rate_perc": 0.0
    }
    
    if not os.path.exists(CONGESTION_CONFIG_FILE):
        # This is expected behavior if the Master Controller hasn't run yet
        return current_status

    try:
        with open(CONGESTION_CONFIG_FILE, 'r') as f:
            config = json.load(f)
            
            # Read delay from file (expected in MS) and convert to seconds (s)
            delay_ms = config.get("CONGESTION_DELAY", 0.0)
            current_status["delay_s"] = delay_ms / 1000.0  # Convert ms to s
            
            # Read loss rate (expected in %)
            current_status["loss_rate_perc"] = config.get("PACKET_LOSS_RATE", 0.0)
            
    except json.JSONDecodeError:
        logger.error(f"Error decoding JSON from congestion config file. Using default zero values.")
    except Exception as e:
        logger.error(f"An unexpected error occurred reading congestion config: {e}. Using default zero values.")
        
    return current_status


def inject_delay_and_check_loss():
    """
    1. Reads the latest congestion config from file.
    2. Applies a time delay (latency) via time.sleep().
    3. Determines if the packet should be dropped based on the loss rate.

    Returns:
        tuple: (bool: True if the packet should be SENT, False if it should be DROPPED, dict: Current status)
    """
    
    # 1. Read latest config dynamically from the file
    congestion_status = read_congestion_config()
    delay = congestion_status["delay_s"]
    loss_rate = congestion_status["loss_rate_perc"]

    # 2. Inject Latency
    if delay > 0:
        time.sleep(delay)

    # 3. Check for Packet Loss
    if loss_rate > 0.0:
        # Check against the loss rate probability (0.0 to 100.0)
        if random.random() * 100.0 < loss_rate:
            # Packet loss occurred
            return False, congestion_status

    # Packet is sent
    return True, congestion_status