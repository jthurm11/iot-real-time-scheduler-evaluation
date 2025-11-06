# Network Congestion Injection Module
# Simulates network degradation (latency and packet loss) between the PID controller
# and the fan actuator node.

import time
import random
import json 
import os 
import logging

logger = logging.getLogger(__name__)

# Global state to hold the configuration loaded from a file
_CURRENT_STATUS = {
    "delay_s": 0.0,
    "loss_rate_perc": 0.0
}

# --- CONFIGURATION FUNCTIONS ---

def load_config(filepath):
    """
    Loads congestion settings from a JSON file and updates the module's state.
    Expected JSON keys: 'CONGESTION_DELAY' (s), 'PACKET_LOSS_RATE' (%).
    """
    global _CURRENT_STATUS
    # Reset to defaults if file not found
    _CURRENT_STATUS["delay_s"] = 0.0
    _CURRENT_STATUS["loss_rate_perc"] = 0.0
    
    if not os.path.exists(filepath):
        logger.warning(f"Congestion config file not found at: {filepath}. Using default zero values.")
        return

    try:
        with open(filepath, 'r') as f:
            config = json.load(f)
            # Read required keys, defaulting to 0.0 if not present
            _CURRENT_STATUS["delay_s"] = config.get("CONGESTION_DELAY", 0.0)
            _CURRENT_STATUS["loss_rate_perc"] = config.get("PACKET_LOSS_RATE", 0.0)
            logger.info(f"Loaded congestion config: Delay={_CURRENT_STATUS['delay_s']}s, Loss={_CURRENT_STATUS['loss_rate_perc']}%")

    except json.JSONDecodeError:
        logger.error(f"Error decoding JSON from congestion config file: {filepath}. Using default zero values.")
    except Exception as e:
        logger.error(f"An unexpected error occurred reading congestion config: {e}. Using default zero values.")

def inject_delay_and_check_loss():
    """
    Applies a delay and determines if the packet should be dropped based on loaded config.

    Returns:
        bool: True if the packet should be SENT, False if it should be DROPPED.
    """
    delay = _CURRENT_STATUS["delay_s"]
    loss_rate = _CURRENT_STATUS["loss_rate_perc"]

    # 1. Inject Latency
    if delay > 0:
        time.sleep(delay)

    # 2. Check for Packet Loss
    if loss_rate > 0.0:
        # Check against the loss rate probability (0.0 to 100.0)
        if random.random() * 100.0 < loss_rate:
            # Packet loss occurred
            return False

    # If no loss or loss rate is 0, the packet is sent
    return True

def get_current_status():
    """Returns the current congestion settings for logging/UI."""
    return _CURRENT_STATUS