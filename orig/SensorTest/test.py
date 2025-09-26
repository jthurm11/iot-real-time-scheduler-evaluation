from gpiozero import DistanceSensor

ultrasonic = DistanceSensor(echo=0, trigger=7)

while True:
    print(ultrasonic.distance)

