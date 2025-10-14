# beta/ (Sensor/Controller Node)

This subdirectory contains all code intended to run on the **Sensor/Controller Node (host: `beta` - Raspberry Pi Compute Module 4)**.

> [!CAUTION]
> Per this [reference](https://gpiozero.readthedocs.io/en/stable/api_input.html#distancesensor-hc-sr04):
>  
> The distance sensor requires two GPIO pins: one for the trigger (marked `TRIG` on the sensor) and another for the echo (marked `ECHO` on the sensor). However, a voltage divider is required to ensure the $5V$ from the `ECHO` pin doesn’t damage the Pi. Wire your sensor according to the following instructions: 
> 1. Connect the `GND` pin of the sensor to a ground pin on the Pi. 
> 2. Connect the `TRIG` pin of the sensor a GPIO pin. 
> 3. Connect one end of a $330Ω$ resistor to the `ECHO` pin of the sensor. 
> 4. Connect one end of a $470Ω$ resistor to the `GND` pin of the sensor. 
> 5. Connect the free ends of both resistors to another GPIO pin. This forms the required voltage divider. 
> 6. Finally, connect the VCC pin of the sensor to a $5V$ pin on the Pi. 

For this project, our particular wiring arrangement and resistance values are found in the [docs](/docs/) folder. 

Pi3B Pinout Referece: 
| | | | |
|---:|:---:|:---:|:---|
|   3V3|  (1)| (2) | 5V    |
| GPIO2|  (3)| (4) | 5V    |
| GPIO3|  (5)| (6) | GND   |
| GPIO4|  (7)| (8) | GPIO14|
|   GND|  (9)| (10)| GPIO15|
|GPIO17| (11)| (12)| GPIO18|
|GPIO27| (13)| (14)| GND   |
|GPIO22| (15)| (16)| GPIO23|
|   3V3| (17)| (18)| GPIO24|
|GPIO10| (19)| (20)| GND   |
| GPIO9| (21)| (22)| GPIO25|
|GPIO11| (23)| (24)| GPIO8 |
|   GND| (25)| (26)| GPIO7 |
| GPIO0| (27)| (28)| GPIO1 |
| GPIO5| (29)| (30)| GND   |
| GPIO6| (31)| (32)| GPIO12|
|GPIO13| (33)| (34)| GND   |
|GPIO19| (35)| (36)| GPIO16|
|GPIO26| (37)| (38)| GPIO20|
|   GND| (39)| (40)| GPIO21|
