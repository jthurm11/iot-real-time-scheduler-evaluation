import threading
import subprocess
import time
import os
import psutil
import signal
import sys # Added for error printing in Iperf
from typing import Optional, Union, Any

# --- CONFIGURATION ---
IPERF_SERVER_IP = "192.168.22.1"
IPERF_SERVER_PORT = 5201

# --- BASE CLASS ---
class ExperimentManager:
    """
    Base class for managing long-running experiments with real-time metric updates.
    It manages the background process, the worker thread, and shared metric access.
    """
    # Default interval for the metric polling loop (can be overridden by the test script for speed)
    interval: float = 1.0 
    
    def __init__(self):
        self._metric: float = 0.0
        self._metric_lock = threading.Lock()
        self.is_running = threading.Event()
        self.worker_thread: Optional[threading.Thread] = None
        self.load_process: Optional[subprocess.Popen[Any]] = None

    def set_metric(self, value: float):
        """Thread-safe update of the latest metric value."""
        with self._metric_lock:
            self._metric = value

    def get_latest_metric(self) -> float:
        """Thread-safe retrieval of the latest metric value."""
        with self._metric_lock:
            return self._metric

    def _worker(self):
        """Worker function specific to each experiment (to be overridden)."""
        raise NotImplementedError("Subclasses must implement the _worker method.")
        
    def _on_experiment_finish(self):
        """
        NEW: Called when the experiment naturally completes (e.g., after a timeout).
        Subclasses MUST implement this to update the main application's state (e.g.,
        set load_type='none' and running_experiment='stopped').
        """
        raise NotImplementedError("Subclasses must implement _on_experiment_finish to update global state.")


    def start(self):
        """Starts the experiment worker thread."""
        if self.worker_thread and self.worker_thread.is_alive():
            print(f"[{self.__class__.__name__}] Already running.")
            return

        self.is_running.clear() # Clear the running flag (experiment is active)
        self.worker_thread = threading.Thread(target=self._worker, daemon=True)
        self.worker_thread.start()
        print(f"[{self.__class__.__name__}] Started background loop.")

    def stop(self):
        """
        Stops the worker thread and terminates the background load process, 
        ensuring file handles are closed to prevent resource warnings.
        """
        if self.is_running.is_set():
            # Already stopped or in the process of stopping
            return
            
        print(f"[{self.__class__.__name__}] Stopping...")
        
        # 1. Signal the worker thread to stop
        self.is_running.set() 
        
        # 2. Terminate the subprocess (if it exists and is running)
        if self.load_process and self.load_process.poll() is None:
            print(f"[{self.__class__.__name__}] Active load process attempting terminate...")
            self.load_process.terminate()
            try:
                # Give it a short time to terminate gracefully
                self.load_process.wait(timeout=2) 
            except subprocess.TimeoutExpired:
                print(f"[{self.__class__.__name__}] Termination timed out. Force killing.")
                self.load_process.kill()

        # 3. Explicitly close subprocess file handles to prevent ResourceWarning
        if self.load_process:
            if self.load_process.stdout:
                self.load_process.stdout.close()
            if self.load_process.stderr:
                self.load_process.stderr.close()
            
            # 4. Clean up the process object reference
            self.load_process = None

        print(f"[{self.__class__.__name__}] Shut down complete.")


# --- IPERF EXPERIMENT ---
class IperfExperiment(ExperimentManager):
    """Manages an iperf3 client for real-time bandwidth monitoring."""
    def __init__(self, server_ip: str = IPERF_SERVER_IP, port: int = IPERF_SERVER_PORT):
        super().__init__()
        self.server_ip = server_ip
        self.port = port
        # Placeholder for the external state update function
        self.external_finish_callback = None 

    def set_finish_callback(self, func):
        """Allows setting a function (e.g., from the main Flask app) to update global state."""
        self.external_finish_callback = func

    def _on_experiment_finish(self):
        """
        Fulfills the abstract method: signals the main application that the test is done.
        """
        print(f"[{self.__class__.__name__}] UDP Test completed after 60s. Signalling global state update...")
        if self.external_finish_callback:
            # This function should call the logic to update global state: 
            # set load_type='none' and running_experiment='stopped'
            self.external_finish_callback()
        else:
            print(f"[{self.__class__.__name__}] WARNING: No external finish callback set. Global state must be manually updated.")


    def _worker(self):
        """Starts iperf3 UDP test for 60s and continuously reads and parses its output stream."""
        # --- COMMAND UPDATE FOR UDP, UNRESTRICTED BANDWIDTH, AND DURATION ---
        command = [
            'iperf3', 
            '-c', self.server_ip, 
            '-p', str(self.port), 
            '-u',               # Use UDP
            '-b', '0',          # Unrestricted bandwidth (0)
            '-t', '60',         # Duration of 60 seconds
            '-i', '0.2',        # Interval for metric updates
            '--forceflush'      # Force flushing output for immediate reading
        ]
        # --- END COMMAND UPDATE ---
        
        try:
            print(f"[{self.__class__.__name__}] Starting 60s UDP test: {' '.join(command)}")
            # Use bufsize=1 for line buffering
            self.load_process = subprocess.Popen(
                command, 
                stdout=subprocess.PIPE, 
                stderr=subprocess.PIPE, 
                text=True, 
                bufsize=1 
            )
        except FileNotFoundError:
            print(f"[{self.__class__.__name__}] ERROR: 'iperf3' command not found. Cannot run experiment.", file=sys.stderr)
            self.is_running.set() # Self-terminate on failure
            self.set_metric(0.0) # Clear metric
            self._on_experiment_finish() # Signal failure/stop
            return

        # Main reading loop
        while not self.is_running.is_set() and self.load_process.poll() is None:
            line = self.load_process.stdout.readline()

            if not line:
                # No more output means the process has finished or stdout is done.
                if self.load_process.poll() is not None:
                    break
                # Wait briefly if no output yet but process is still running
                time.sleep(0.1) 
                continue

            try:
                # We look for the line containing "bits/sec" or "Bytes/sec" AND the interval format "X.XX-Y.YY"
                if 'bits/sec' in line and '-' in line and 'sec' in line:
                    fields = line.split()
                    
                    try:
                        # Find the first field that looks like the unit (ends in /sec)
                        unit_index = next(i for i, f in enumerate(fields) if f.endswith('/sec'))
                        
                        # The rate is the field just before the unit field
                        if unit_index > 0:
                            rate_value = float(fields[unit_index - 1])
                            self.set_metric(rate_value)
                            
                    except (StopIteration, IndexError, ValueError):
                        # Line didn't match expected structure, ignore it
                        continue 

            except Exception as e:
                print(f"[{self.__class__.__name__}] Error processing iperf line: {e} | Line: {line.strip()}", file=sys.stderr)
                time.sleep(0.1) # Avoid tight loop on error

        # --- COMPLETION HANDLING ---
        print(f"[{self.__class__.__name__}] iperf3 process exited naturally or was stopped.")
        
        # If the process exited naturally (not self.is_running.is_set() was triggered)
        if not self.is_running.is_set():
            # Process finished after 60s timeout
            self._on_experiment_finish()

        # Clean up local state
        self.set_metric(0.0)
        self.stop() # Clean up self.load_process reference and close streams
        

# --- STRESS EXPERIMENT ---
class StressExperiment(ExperimentManager):
    """Manages stress-ng load generation and psutil for real-time CPU monitoring."""
    # NOTE: Stress-ng is a continuous load, so it relies on the external 'stop' command.
    
    def __init__(self, cpu_count: int = 1):
        super().__init__()
        self.cpu_count = cpu_count
        # Placeholder for the external state update function
        self.external_finish_callback = None 

    def set_finish_callback(self, func):
        """Allows setting a function (e.g., from the main Flask app) to update global state."""
        self.external_finish_callback = func

    def _on_experiment_finish(self):
        """
        Fulfills the abstract method: signals the main application that the test is done.
        Since stress-ng is manually stopped, this is mostly for clean shutdown.
        """
        print(f"[{self.__class__.__name__}] Stress-ng stopped. Signalling global state update...")
        if self.external_finish_callback:
            # This function should call the logic to update global state: 
            # set load_type='none' and running_experiment='stopped'
            self.external_finish_callback()
        else:
            print(f"[{self.__class__.__name__}] WARNING: No external finish callback set. Global state must be manually updated.")

    def _worker(self):
        """Starts stress-ng and periodically polls CPU usage."""
        # Using timeout '0' means it runs until manually killed
        command = ['stress-ng', '--cpu', str(self.cpu_count), '--timeout', '0'] 
        
        try:
            print(f"[{self.__class__.__name__}] Stress-ng process starting...")
            # Stress-ng doesn't need its output read, so we silence stdout/stderr
            self.load_process = subprocess.Popen(
                command, 
                stdout=subprocess.DEVNULL, 
                stderr=subprocess.DEVNULL
            )
            print(f"[{self.__class__.__name__}] Stress-ng process started (PID: {self.load_process.pid}).")
        except FileNotFoundError:
            print(f"[{self.__class__.__name__}] ERROR: 'stress-ng' command not found. Cannot run experiment.", file=sys.stderr)
            self.is_running.set()
            self._on_experiment_finish() # Signal failure/stop
            return
        
        # CPU Monitoring Loop
        while not self.is_running.is_set():
            # Check if the stress process terminated prematurely
            if self.load_process.poll() is not None:
                print(f"[{self.__class__.__name__}] WARNING: Stress process terminated with code {self.load_process.returncode}.", file=sys.stderr)
                break 

            # Poll CPU usage across all cores (per-core is False)
            # Use interval=0 to get an instantaneous reading, relying on the loop's sleep
            cpu_usage = psutil.cpu_percent(interval=0) 
            self.set_metric(cpu_usage)

            # Wait for the next interval
            time.sleep(self.interval)

        # Cleanup on exit (This only runs if self.is_running.is_set() was triggered)
        self.set_metric(0.0)
        # Note: self.stop() handles process termination and sets self.is_running.set()
        # We need to call _on_experiment_finish() if it was *not* terminated externally,
        # but since stress-ng runs forever, we assume it's stopped externally.
        self._on_experiment_finish()
        self.stop()
        
# --- MAIN EXECUTION (Kept for testing purposes, but usually not run standalone) ---
if __name__ == "__main__":
    
    # --- Dummy Callback to show what needs to be implemented in your main app ---
    def global_state_update():
        print(">>> GLOBAL STATE UPDATED: Load type set to 'none', Experiment stopped. <<<")

    # --- Test 1: Iperf UDP 60s Test ---
    print("\n--- Starting Iperf UDP Test (60 seconds) ---")
    iperf_test = IperfExperiment()
    iperf_test.set_finish_callback(global_state_update)
    
    # Note: Requires an iperf3 server running at 192.168.22.1:5201
    iperf_test.start() 
    
    # Wait for the test to run and finish naturally (approx 60-65 seconds)
    print("Waiting for Iperf test to complete naturally...")
    time.sleep(5) # Shorter sleep for demonstration purposes, replace with 65s in reality
    
    if iperf_test.worker_thread.is_alive():
        print("\nTest running, waiting for worker thread to exit...")
        iperf_test.worker_thread.join(timeout=65) # Wait for the 60s duration + cleanup

    if not iperf_test.is_running.is_set():
        # This means the worker thread exited on its own and called stop() and the callback
        print("\nIperf test completed successfully and signaled global state change.")
    else:
        print("\nIperf test was manually stopped or timed out.")


    # --- Test 2: Stress-ng Test (Manual Stop) ---
    print("\n--- Starting Stress-ng Test (Manual Stop) ---")
    stress_test = StressExperiment(cpu_count=2)
    stress_test.set_finish_callback(global_state_update)
    stress_test.start()
    
    print("Stress test running for 5 seconds...")
    time.sleep(5)
    
    print("Manually stopping Stress test...")
    stress_test.stop()
    stress_test.worker_thread.join(timeout=2)
    
    print("Experiment Manager Tests Complete.")