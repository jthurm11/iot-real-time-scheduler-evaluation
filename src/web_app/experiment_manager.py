# Experiment control module.
import threading
import subprocess
import json
import time
import sys
import psutil

# --- CONFIGURATION (Default values - should be managed by master controller) ---
IPERF_SERVER_IP = "192.168.1.1" 
IPERF_PORT = 5201 
IPERF_TEST_DURATION = 5 
IPERF_INTERVAL = IPERF_TEST_DURATION + 1 
STRESS_INTERVAL = 1 # How often the CPU usage is reported (for stress)
# -----------------------------------------------------------------------------

class ExperimentManager:
    """
    Base class for running background experiments (load generation or telemetry)
    in a dedicated thread. Handles start, stop, and safe access to metrics.
    """
    def __init__(self, name="ExperimentWorker"):
        self.metric_lock = threading.Lock()
        self.latest_metric = 0.0 # Stores the current experiment metric (e.g., Mbps, % CPU)
        self.is_running = threading.Event()
        self.worker_thread = threading.Thread(
            target=self._worker_loop, 
            daemon=True,
            name=name
        )
        self.load_process = None # To store subprocesses like stress-ng

    def get_latest_metric(self) -> float:
        """Safely reads the latest metric value for the master controller."""
        with self.metric_lock:
            return self.latest_metric

    def set_metric(self, value: float):
        """Safely updates the latest metric value from the worker thread."""
        with self.metric_lock:
            self.latest_metric = value

    def start(self):
        """Starts the background worker thread."""
        if not self.worker_thread.is_alive():
            self.is_running.clear()
            self.worker_thread.start()
            print(f"[{self.worker_thread.name}] Started background loop.")

    def stop(self):
        """Signals the thread and any active subprocesses to stop and joins the thread."""
        print(f"[{self.worker_thread.name}] Stopping...")
        self.is_running.set() # Signal worker loop to exit

        # Kill any active subprocesses (e.g., stress-ng)
        if self.load_process and self.load_process.poll() is None:
            self.load_process.terminate()
            try:
                self.load_process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.load_process.kill()
            print(f"[{self.worker_thread.name}] Active load process killed.")
            self.load_process = None
        
        # Wait for the worker thread to finish its operation
        self.worker_thread.join(timeout=IPERF_INTERVAL + 2) 

        # Reset metric on exit
        self.set_metric(0.0)
        print(f"[{self.worker_thread.name}] Shut down complete.")

    def _worker_loop(self):
        """Abstract method: This must be implemented by subclasses."""
        raise NotImplementedError("Subclasses must implement _worker_loop()")

    def __del__(self):
        self.stop() # Ensure cleanup on object deletion


class IperfExperiment(ExperimentManager):
    """Manages continuous iperf3 bandwidth measurement (Telemetry)."""
    
    def __init__(self, server_ip=IPERF_SERVER_IP, port=IPERF_PORT, duration=IPERF_TEST_DURATION, interval=IPERF_INTERVAL):
        super().__init__(name="IperfExperiment")
        self.server_ip = server_ip
        self.port = port
        self.duration = duration
        self.interval = interval

    def _run_iperf_test(self):
        """Executes a single iperf3 test and parses the result for bandwidth (Mbps)."""
        command = [
            'iperf3', '-c', self.server_ip, '-p', str(self.port), 
            '-t', str(self.duration), '-J', # JSON output
            '--forceflush'
        ]
        
        try:
            result = subprocess.run(command, capture_output=True, text=True, check=True, timeout=self.interval)
            iperf_json = json.loads(result.stdout)
            
            # Extract bandwidth from the 'sum_received' block
            bits_per_second = iperf_json['end']['sum_received']['bits_per_second']
            bandwidth_mbps = bits_per_second / 1000000.0
            
            return bandwidth_mbps
            
        except subprocess.CalledProcessError as e:
            # Server unreachable or test failure
            return 0.0 
        except Exception:
            # JSON parsing error or timeout
            return 0.0

    def _worker_loop(self):
        """Iperf worker loop: runs tests and updates the metric."""
        while not self.is_running.is_set():
            new_bandwidth = self._run_iperf_test()
            self.set_metric(new_bandwidth)
            print(f"[IperfExperiment] Measured: {new_bandwidth:.2f} Mbps")
            self.is_running.wait(timeout=self.interval)


class StressExperiment(ExperimentManager):
    """Manages running stress-ng (Load Generation) and reporting CPU utilization (Telemetry)."""
    
    def __init__(self, cpu_count=psutil.cpu_count(logical=False), interval=STRESS_INTERVAL):
        super().__init__(name="StressExperiment")
        self.cpu_count = cpu_count
        self.interval = interval
        # Command runs 100% load on all physical cores using matrix multiplication
        self.stress_command = ['stress-ng', '--cpu', str(self.cpu_count), '-l', '100', '--cpu-method', 'matrixprod'] 

    def _start_stress_process(self):
        """Starts the stress-ng process in the background."""
        try:
            # Use Popen to run non-blocking and manage the process life-cycle
            self.load_process = subprocess.Popen(
                self.stress_command, 
                stdout=subprocess.DEVNULL, 
                stderr=subprocess.DEVNULL,
                start_new_session=True # Important for clean termination
            )
            print(f"[StressExperiment] Stress-ng process started (PID: {self.load_process.pid}).")
        except FileNotFoundError:
            print("[StressExperiment] ERROR: 'stress-ng' not found. Cannot run stress test.", file=sys.stderr)
            self.load_process = None
        except Exception as e:
            print(f"[StressExperiment] ERROR starting stress-ng: {e}", file=sys.stderr)
            self.load_process = None

    def _worker_loop(self):
        """Stress worker loop: continuously monitors CPU usage while stress-ng runs."""
        
        self._start_stress_process()
        
        if not self.load_process:
            self.is_running.set() 
            return

        while not self.is_running.is_set():
            try:
                # psutil.cpu_percent() measures instantaneous usage over the last 'interval'
                cpu_usage_percent = psutil.cpu_percent(interval=self.interval)
                self.set_metric(cpu_usage_percent)
                print(f"[StressExperiment] Current CPU Usage: {cpu_usage_percent:.1f}%")
                
                # Check if stress-ng process has unexpectedly terminated
                if self.load_process.poll() is not None:
                     print("[StressExperiment] WARNING: Stress-ng process terminated prematurely.", file=sys.stderr)
                     self.set_metric(0.0)
                     self.is_running.set()
                     break
                
            except Exception:
                self.set_metric(0.0)
                
            self.is_running.wait(timeout=self.interval)