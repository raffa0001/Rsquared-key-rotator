import subprocess
import os
import shutil

# --- CONFIGURATION: FILL THESE VALUES IN ---
# Your witness ID (e.g., "1.6.125")
WITNESS_ID = "1.6.125"
# Your NEW Public Key
PUB_KEY = "RQRX7DYbbNFfgE1vWFgfccCAQGV4JJ7j45mRtcm9sMhnyy1ApCTLUQ"
# Your NEW Private WIF Key
WIF_KEY = "5K8imQ64ry2ZBvNCWWJNLpU8TsYdHHuoHwUmHstk6JY8gStJV5G"
# --- END CONFIGURATION ---



# --- SCRIPT CONSTANTS ---
NODE_NAME = "rsquared-test-node"
DOCKER_IMAGE = "ghcr.io/r-squared-project/r-squared-core:1.0.0"
# Use a separate directory for the test to not interfere with your real data
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "witness_node_data_dir")


def prepare_environment():
    """Cleans up old container and ensures the data directory is ready."""
    print(f"--- Preparing Environment for '{NODE_NAME}' ---")
    print("Stopping and removing any existing test container...")
    # These commands stop and remove the old container so we can launch a new one
    # with the same name. They do not affect the data volume on your host.
    subprocess.run(["docker", "stop", NODE_NAME], capture_output=True, text=True)
    subprocess.run(["docker", "rm", NODE_NAME], capture_output=True, text=True)

    # --- MODIFIED SECTION ---
    print(f"Ensuring data directory exists (will not delete): {DATA_DIR}")
    # The 'exist_ok=True' flag means this command will do nothing if the
    # directory already exists, preserving its contents.
    os.makedirs(DATA_DIR, exist_ok=True)
    # --- END MODIFIED SECTION ---

    print("--- Preparation Complete ---\n")

def run_test():
    """Runs the docker command using the recommended list-of-arguments method."""

    # --- Argument Formatting ---
    # The witness_node expects a JSON string: "1.6.125"
    witness_id_arg = f'"{WITNESS_ID}"'
    # The witness_node expects a JSON array of strings: ["PUB_KEY","WIF_KEY"]
    private_key_arg = f'["{PUB_KEY}","{WIF_KEY}"]'

    print(">>> Using Method 1: List of arguments (Recommended)")
    # This is the robust method. Each part of the command is a separate element.
    # Python passes them directly to the 'docker' executable, avoiding shell errors.
    command_to_run = [
        "docker", "run", "-d", "--name", NODE_NAME, "--restart", "unless-stopped",
        "-p", "8090:8090", # Use a different port to not conflict with the main node
        "-v", f"{DATA_DIR}:/witness_node_data_dir",
        DOCKER_IMAGE, "witness_node",
        "--data-dir=/witness_node_data_dir",
        "--rpc-endpoint=0.0.0.0:8090",
        '--seed-nodes=["node01.rsquared.digital:2771","node02.rsquared.digital:2771"]',
        "--witness-id", witness_id_arg,
        "--private-key", private_key_arg
    ]

    # For printing, we join the list into a readable string
    print_command = ' '.join(f'"{arg}"' if ' ' in arg else arg for arg in command_to_run)

    print("\nExecuting command:")
    print(print_command)

    result = subprocess.run(command_to_run, shell=False, capture_output=True, text=True)

    print("\n--- RESULTS ---")
    print(f"Exit Code: {result.returncode}")
    if result.stdout:
        print(f"STDOUT (Container ID):\n{result.stdout.strip()}")
    if result.stderr:
        print(f"STDERR:\n{result.stderr.strip()}")

    if result.returncode == 0:
        print("\n✅ SUCCESS: The 'docker run' command was accepted by the Docker daemon.")
    else:
        print("\n❌ FAILURE: The 'docker run' command failed.")


if __name__ == "__main__":
    prepare_environment()
    run_test()

    print("\n--- Post-Run Check ---")
    print(f"To see container status, run: docker ps -a --filter name={NODE_NAME}")
    print(f"To see container logs, run:   docker logs {NODE_NAME}")
