from gpiozero import PWMOutputDevice
import time
import socket
import struct

s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.bind(('192.168.50.139', 12345))

fan_pwm = PWMOutputDevice(pin=18)
fan_pwm.value = 0.0

while True:
	s.listen(1)
	conn, addr = s.accept()
	data = conn.recv(1024)
	f = struct.unpack('>f', data)[0]
	print("data: ", f)
	time.sleep(0.001)
