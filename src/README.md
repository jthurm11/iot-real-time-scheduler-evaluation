# src

This directory contains all the **active, working source code** for the IoT-RTS Evaluation Project. This code has been developed and/or modified by the project team.

It is organized by the two main nodes in the testbed:

## 1. alpha/ (Actuator Node)

This subdirectory contains all code intended to run on the **Actuator Node (host: `alpha` - Raspberry Pi Compute Module 4)**.

* **Primary Function:** Receives control signals from `beta/` and adjusts the fan's PWM output.
* **Key Files:**
    * `fan_controller.py`: Code to interface with and control the PWM fan.
    * Networking scripts for receiving control signals.

## 2. beta/ (Sensor/Controller Node)

This subdirectory contains all code intended to run on the **Sensor/Controller Node (host: `beta` - Raspberry Pi Compute Module 4)**.

* **Primary Function:** Runs the main control loop, measures ball position, calculates the PID output, and transmits control signals to `alpha/`.
* **Key Files:**
    * `pid_controller.py`: The core PID control loop implementation.
    * `sensor_read.py`: Code to interface with the ultrasonic depth sensor.
    * Networking scripts for sending control signals and logging data.

## 3. shared_libs/ (Optional)

This directory is reserved for any common utilities, helper functions, or libraries (e.g., custom logging functions) that are used by code on **both** the `alpha` and `beta` nodes.