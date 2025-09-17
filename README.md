# IoT Real-Time Scheduler Evaluation

This repository contains the code and documentation for a course project on the Architecture of Internet of Things (IoT).

## Project Overview
The primary goal of this project is to experimentally evaluate how a **real-time traffic scheduler** improves the control quality of a physical system. The project uses a **ball-floating testbed** consisting of two Raspberry Pi boards to demonstrate the effects of network congestion and the subsequent performance gains from applying a real-time scheduler.

## Setup
The experimental setup includes a pre-built ball-floating testbed with two Raspberry Pis.
* One Raspberry Pi, equipped with a **depth sensor**, monitors the ball's position.
* The second Raspberry Pi, connected to a **PWM fan**, controls the ball's position.

The two Raspberry Pis communicate with each other over an Ethernet network.

## Project Phases
1.  **Baseline Control**: We implement a **PID controller** to stabilize the ball at a target position under ideal network conditions.
2.  **Congestion Introduction**: We intentionally introduce **network congestion** on the Ethernet connection and observe the degradation in the ball's control quality.
3.  **Scheduler Implementation**: We apply a real-time traffic scheduler (such as the Linux ETF scheduler) to the network and compare the improved control performance against the degraded baseline.

## Hardware and Software 
* **Hardware**:
  * **Testbed**: A pre-built ball-floating testbed .
  * **Compute**: Two Raspberry Pi boards.
  * **Sensors**: A depth sensor for ball position monitoring.
  * **Actuators**: A PWM fan for position control.
  * **Networking**: Ethernet cables for communication.

* **Software**: 
  * **Operating System**: _Linux distro...?_
  * **Programming Languages**: **C** and **Python**. 
  * **Scheduling Tools**: Linux ETF scheduler or KeepON driver.
  * **Libraries**: Required libraries for PID control, sensor data acquisition, and fan control.

## Team
* **Abby Horning**
* **Jake Thurman**
* **Chuanyu Xue** (Project Owner)

## Deliverables and Timeline

* **Weeks 1-3**: Familiarize ourselves with the hardware and implement the baseline **PID controller** to stabilize the ball.
* **Weeks 4-6**: Introduce network congestion and record the resulting control degradation, which will serve as our un-scheduled performance benchmark.
* **Weeks 7-9**: Implement a real-time traffic scheduler and compare the improved control performance against the baseline.
* **Weeks 10-12**: Collect and analyze final performance data, focusing on key trade-offs. We will use this information to create the final project report and presentation.


## Project Motivation
The background, motivation and goals for this project are derived from Chuanyu's original idea:  
![Sample Project Summary Description](pictures/Project_Summary_2025.png)  

## License
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)  
This project is licensed under the [MIT License](LICENSE).  
