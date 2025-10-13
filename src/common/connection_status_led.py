from gpiozero import LED, PingServer
from gpiozero.tools import negated
from signal import pause

green = LED(17)
red = LED(27)

# Define neighbor to ping. 
# Parameter 'event_delay' defines period between pings (default: 10 seconds).
neighbor = PingServer('google.com')

neighbor.when_activated = green.on
neighbor.when_deactivated = green.off
red.source = negated(green)

pause()