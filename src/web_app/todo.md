## 📌 Required Controller Script Modifications (For Integration)

For the real-time monitoring to work without writing to disk, you must modify your `sensor_PIDcontroller.py` and `fan_PIDcontroller.py` scripts.

### 1. In `sensor_PIDcontroller.py` (Beta Node):

1.  Add imports for `socket` and `json`.
2.  Define the master web app's UDP data endpoint:
    ```python
    WEB_APP_IP = "127.0.0.1"
    WEB_APP_PORT = 5006
    DATA_SOCK = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    ```
3.  Inside your main control loop, after computing the PID output and getting the sensor reading (`h_current`), format the data and send it:
    ```python
    # Data packet includes PID values and the current network settings being simulated
    data_packet = {
        "type": "sensor",
        "h": h_current,
        "sp": pid.setpoint,
        "out": output,
        "err": error,
        "delay_s": CONGESTION_DELAY, # Pulled from network_injector.py global
        "loss_p": PACKET_LOSS_RATE,   # Pulled from network_injector.py global
        "ts": time.time()
    }
    DATA_SOCK.sendto(json.dumps(data_packet).encode('utf-8'), (WEB_APP_IP, WEB_APP_PORT))
    ```

### 2. In `fan_PIDcontroller.py` (Alpha Node):

1.  Add imports for `socket` and `json`.
2.  Define the Beta node's UDP data endpoint (where the Flask app is running):
    ```python
    BETA_NODE_IP = "beta_node_ip" # Use the actual IP of the Beta Node
    WEB_APP_PORT = 5006
    DATA_SOCK = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    ```
3.  Inside your UDP command listener loop, after successfully reading the new duty cycle (`current_duty`) and measuring the fan RPM (`fan_rpm`), format and send the data:
    ```python
    data_packet = {
        "type": "fan",
        "duty": current_duty,
        "rpm": fan_rpm,
        "ts": time.time()
    }
    DATA_SOCK.sendto(json.dumps(data_packet).encode('utf-8'), (BETA_NODE_IP, WEB_APP_PORT))