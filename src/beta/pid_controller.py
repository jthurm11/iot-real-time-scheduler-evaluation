# wrote this code with the help of Arduino PID library by Brett Beauregard

import time

class PID:
    def __init__(self, Kp, Ki, Kd, setpoint=0.0, sample_time=0.1, output_limits=(0,255), controller_direction='DIRECT'):
        self.setpoint = setpoint
        self.sample_time = sample_time
        self.output_limits = output_limits
        self.controller_direction = controller_direction

        # JT: Changed to scale Ki by sample_time and Kd by (1/sample_time) during init
        self.Kp = Kp
        self.Ki = Ki * sample_time
        self.Kd = Kd / sample_time

        #keep track of state
        self._last_time = time.time()
        self._last_input = 0.0
        self._ITerm = 0.0
        self.output = 0.0
        self.in_auto = True

        # direction either DIRECT or REVERSE (not sure yet based on fact that sensor is on top)
        if controller_direction == 'REVERSE':
            self.Kp, self.Ki, self.Kd = -self.Kp, -self.Ki, -self.Kd


    # main function that handles all the PID math
    def compute(self, input_val):
        if not self.in_auto:
            return self.output

        now = time.time()
        time_change = now - self._last_time

        if (time_change >= self.sample_time):
            #compute all error variables
            error = self.setpoint - input_val
            self._ITerm += self.Ki * error

            min_out, max_out = self.output_limits
            if (self._ITerm > max_out): self._ITerm = max_out
            elif(self._ITerm < min_out): self._ITerm = min_out
            d_input = input_val - self._last_input

            # Compute output
            output = self.Kp * error + self._ITerm - self.Kd * d_input
            if (output > max_out): output = max_out
            elif(output < min_out): output = min_out
            self.output = output

            # Store state
            self._last_input = input_val
            self._last_time = now
            return self.output

        # If not enough time has passed, return last calculated output
        return self.output
    

    # set PID gain constants
    def set_tuning(self, Kp, Ki, Kd):
        if (Kp < 0 or Ki < 0 or Kd < 0): return

        self.Kp = Kp
        self.Ki = Ki * self.sample_time
        self.Kd = Kd / self.sample_time

        if (self.controller_direction == 'REVERSE'):
            self.Kp = -self.Kp
            self.Ki = -self.Ki
            self.Kd = -self.Kd


    # set sample time dynamically
    def set_sample_time(self, new_sample_time):
        #Change the PID update period and rescale Ki, Kd accordingly
        if (new_sample_time > 0):
            ratio = new_sample_time / self.sample_time
            self.Ki *= ratio
            self.Kd /= ratio
            self.sample_time = new_sample_time


    # set output limits
    def set_output_limits(self, min_out, max_out):
        if (min_out > max_out): return
        self.output_limits = (min_out, max_out)

        if (self.output > max_out): self.output = max_out
        elif(self.output < min_out): self.output = min_out

        if (self._ITerm > max_out): self._ITerm = max_out
        elif(self._ITerm < min_out): self._ITerm = min_out


    # sets mode as either Automatic or Manual
    def set_mode(self, mode):
        new_auto = (mode == 'AUTOMATIC')
        if new_auto and not self.in_auto:
            self.initialize()
        self.in_auto = new_auto

    # Initialize controller state
    def initialize(self):
        self._last_input = 0.0
        self._ITerm = self.output
        min_out, max_out = self.output_limits
        
        if (self._ITerm > max_out): self._ITerm = max_out
        elif(self._ITerm < min_out): self._ITerm = min_out


    # Reverse direction if needed (adding cuz unsure with sensor which direction to use)
    def set_controller_direction(self, direction):
        self.controller_direction = direction