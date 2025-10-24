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

Below is an example of the required wiring circuit for this system.  

![Example sensor wiring](/pics/circuit_sensor.png) 
