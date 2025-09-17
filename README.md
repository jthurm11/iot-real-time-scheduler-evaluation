# IoT-RTS (Real-Time Scheduler) Evaluation

This repository contains the code and documentation for a course project on the Architecture of Internet of Things (IoT).

![Raspberry Pi](https://img.shields.io/badge/-Raspberry_Pi-C51A4A?style=for-the-badge&logo=Raspberry-Pi)
![Python](https://img.shields.io/badge/python-3670A0?style=for-the-badge&logo=python&logoColor=ffdd54)
![C](https://img.shields.io/badge/c-%2300599C.svg?style=for-the-badge&logo=c&logoColor=white)

## Project Overview
The primary goal of this project is to experimentally evaluate how a **real-time traffic scheduler** improves the control quality of a physical system. The project uses a **ball-floating testbed** consisting of two Raspberry Pi boards to demonstrate the effects of network congestion and the subsequent performance gains from applying a real-time scheduler.

## Setup
The experimental setup includes a pre-built ball-floating testbed with two Raspberry Pis.
* One Raspberry Pi, equipped with a **depth sensor**, monitors the ball's position.
* The second Raspberry Pi, connected to a **PWM fan**, controls the ball's position.

The two Raspberry Pis communicate with each other over an Ethernet network.

## Project Phases
This project is divided into four main phases, each with a key milestone.

* **Phase 1: Project Initiation & PID Control Implementation**
    * **Milestone:** Proposal Submission (September 27)
    * **Activities:** Finalize the project plan, acquire necessary materials, and implement the baseline **PID controller** to stabilize the ball. 

* **Phase 2: Performance Degradation Baseline**
    * **Milestone:** Successful demonstration of network congestion and performance degradation.
    * **Activities:** Introduce network congestion on the Ethernet link and record the resulting control quality degradation. This establishes our baseline for performance. 

* **Phase 3: Real-Time Scheduler Evaluation**
    * **Milestone:** Implementation of the real-time traffic scheduler and collection of performance data.
    * **Activities:** Implement and apply a **real-time traffic scheduler** (e.g., Linux ETF or KeepON) to the network. Conduct experiments to compare the improved control performance against the degraded baseline. 

* **Phase 4: Analysis & Final Report**
    * **Milestone:** Final project report and presentation submission (December 12).
    * **Activities:** Analyze all collected data, focusing on key trade-offs in cost, power, and performance. Prepare the final report and presentation for submission. 

## Hardware and Software 
* **Hardware**:
  * **Testbed**: A pre-built ball-floating testbed .
  * **Compute**: Two Raspberry Pi boards. 
  * **Sensors**: A depth sensor for ball position monitoring.
  * **Actuators**: A PWM fan for position control.
  * **Networking**: Ethernet cables for communication.

* **Software**: 
  * **Operating System**: 
  * **Programming Languages**: **C** and **Python**. 
  * **Scheduling Tools**: Linux ETF scheduler or KeepON driver.
  * **Libraries**: Required libraries for PID control, sensor data acquisition, and fan control.

## Team
* **Abby Horning**
* **Jake Thurman**
* **Chuanyu Xue** (Project Owner)

## Project Motivation
The background, motivation and goals for this project are derived from Chuanyu's original idea:  
![Sample Project Summary Description](pictures/Project_Summary_2025.png)  

## License
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)  
This project is licensed under the [MIT License](LICENSE).  
