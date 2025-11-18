import time
import sys
import os
import signal
from experiment_manager import IperfExperiment, StressExperiment

# --- Configuration for Testing ---
# Set a short test duration so the script runs quickly
TEST_DURATION_SECONDS = 5 
IPERF_SERVER_IP = "127.0.0.1" # Use localhost for testing unless a server is guaranteed
# ---------------------------------

def run_test(experiment_type: str):
    """Initializes, runs, polls, and stops a single experiment type."""
    print(f"\n=======================================================")
    print(f"--- Starting Test for {experiment_type.upper()} ---")
    print(f"=======================================================")

    exp_instance = None

    # 1. Initialization
    if experiment_type == 'iperf':
        # NOTE: iperf3 must be installed and an iperf3 server must be running on IPERF_SERVER_IP:5201 
        # for this test to show non-zero results.
        print(f"[SETUP] Initializing IperfExperiment (Target: {IPERF_SERVER_IP})...")
        #exp_instance = IperfExperiment(server_ip=IPERF_SERVER_IP, duration=2)
        exp_instance = IperfExperiment()
    elif experiment_type == 'stress':
        # NOTE: stress-ng must be installed for this test to show non-zero results.
        print("[SETUP] Initializing StressExperiment...")
        #exp_instance = StressExperiment(interval=1)
        exp_instance = StressExperiment()
    else:
        print(f"[ERROR] Unknown experiment type: {experiment_type}")
        return

    # 2. Start the Experiment Thread
    try:
        exp_instance.start()
        print(f"[STATUS] Experiment started. Polling for {TEST_DURATION_SECONDS} seconds...")
        
        # 3. Polling Loop
        start_time = time.time()
        while time.time() - start_time < TEST_DURATION_SECONDS:
            # Safely retrieve the metric from the background thread
            metric = exp_instance.get_latest_metric()
            print(f"[{experiment_type.upper()} METRIC] Current Value: {metric:.2f} {'Mbps' if experiment_type == 'iperf' else '%'}")
            time.sleep(1)

    except Exception as e:
        print(f"[ERROR] An unexpected error occurred during test: {e}")
    finally:
        # 4. Stop and Cleanup
        if exp_instance:
            exp_instance.stop()
            # Verify metric resets after stopping
            final_metric = exp_instance.get_latest_metric()
            print(f"\n[CLEANUP] Experiment stopped successfully. Final metric check (should be 0.0): {final_metric:.1f}")

        print(f"--- Test for {experiment_type.upper()} Completed ---\n")


def main():
    """Main function to run all tests."""
    
    # Check if dependencies are likely installed for better test results
    if os.system("which iperf3 > /dev/null") != 0:
        print("\n[WARNING] iperf3 is not installed. IperfExperiment test will likely fail or return 0.0.")
    if os.system("which stress-ng > /dev/null") != 0:
        print("\n[WARNING] stress-ng is not installed. StressExperiment test will likely fail or return 0.0.")
    
    print("\nStarting Experiment Manager module verification...")

    # Run the Iperf test
    run_test('iperf')

    # Run the Stress test
    run_test('stress')

    print("All tests concluded.")

if __name__ == "__main__":
    main()