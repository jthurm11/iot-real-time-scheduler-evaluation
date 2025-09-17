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
* **Hardware**: A ball-floating testbed, two Raspberry Pi boards, a depth sensor, and a PWM fan.
* **Software**: The project utilizes **Linux** and is developed using **C** and **Python**.

## Team
* **Abby Horning**
* **Jake Thurman**

## Project Motivation
![Sample Project Summary Description](Project_Summary_2025.pdf)  

## License
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)  
This project is licensed under the [MIT License](LICENSE).  
