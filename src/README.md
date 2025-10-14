# src

This directory contains all the **active, working source code** for the IoT-RTS Evaluation Project. This code has been developed and/or modified by the project team. 

> [!TIP] 
> See the [Getting Started](#getting_started) 

It is organized by the two main nodes in the testbed:

## 1. alpha/ (Actuator Node)

This subdirectory contains all code intended to run on the **Actuator Node (host: `alpha` - Raspberry Pi Compute Module 4)**.

* **Primary Function:** Receives control signals from `beta/` and adjusts the fan's PWM output.
* **Key Files:**
    * `fan_controller.py` _(name TBD)_: Code to interface with and control the PWM fan.
    * Networking scripts for receiving control signals.

## 2. beta/ (Sensor/Controller Node)

This subdirectory contains all code intended to run on the **Sensor/Controller Node (host: `beta` - Raspberry Pi Compute Module 4)**.

* **Primary Function:** Runs the main control loop, measures ball position, calculates the PID output, and transmits control signals to `alpha/`.
* **Key Files:**
    * `pid_controller.py` _(name TBD)_: The core PID control loop implementation.
    * `sensor_read.py` _(name TBD)_: Code to interface with the ultrasonic depth sensor.
    * Networking scripts for sending control signals and logging data.

## 3. common/

This directory is reserved for any common utilities, helper functions, or libraries (e.g., custom logging functions) that are used by code on **both** the `alpha` and `beta` nodes.

## Getting Started 
> Bare Metal Setup 

This section provides the minimum steps required to clone the repository and run the setup script on a newly imaged Raspberry Pi (running Ubuntu or Raspberry Pi OS). The `setup_nodes.sh` script handles everything from setting the hostname to deploying services.

### Prerequisites 

* A Raspberry Pi with a fresh operating system installed and connected to the internet (preferably via Wi-Fi for initial setup).  
* The ubuntu user (or your main user) has sudo privileges.

### A. Install Git and Initial Setup 

The following commands should be run on the Raspberry Pi's command line: 

1. Update Packages and Install Git: 
```bash 
sudo apt update && sudo apt install git -y 
``` 

2. Create Repository Directory:
The `setup_nodes.sh` script expects the repository to be cloned locally.  
> [!IMPORTANT] 
> Only the `install_project` function will truly fail, the rest of the script should complete without issue. Still, it's recommended to clone the entire repo instead of just downloading/executing `setup_nodes.sh` by itself.  
```bash 
mkdir -p ~/Public && cd ~/Public 
```

3. Clone the Repository: 
```bash 
git clone https://github.com/jthurm11/iot-real-time-scheduler-evaluation.git 
``` 

### B. Run the Setup Script  

The `setup_nodes.sh` script will guide you through setting the hostname (`alpha` or `beta`) and perform the entire configuration sequence. 

1. Execute the Full Setup: 
```bash 
cd ~/Public/iot-real-time-scheduler-evaluation/src 
./setup_nodes.sh
``` 

* Action: The script will first ask you to select a hostname for the node. 
* Action: It will configure your static control network IP address. 
* Action: It will generate an SSH key and display it for you to add as a Deploy Key on the GitHub repository. 
    > NOTE: This is no longer necessary, as the repository is now public. 
* Action: It will install project files and enable the corresponding system services. 

2. Reboot to Finalize Hostname: 
If the hostname was changed during the setup, a reboot is required to apply the change fully.
```bash
sudo reboot
``` 

### C. Updating Code 
1. You can easily update the code on the Pi from the source directory. 

```bash
cd ~/Public/iot-real-time-scheduler-evaluation/src
git pull
``` 

2. If you added new services, modified unit files, or need to ensure fresh copies of scripts are installed, run the install_project function again. 

```bash
./setup_nodes.sh -f install_project 
```

> [!IMPORTANT] 
> This command will stop and restart all installed services after refreshing the systemd configuration.
