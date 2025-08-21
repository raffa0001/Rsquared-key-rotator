import subprocess
import json
import os
import sys
import getpass
import time
import textwrap
import secrets
import re
import select
import configparser
from pathlib import Path
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

# --- CONFIGURATION ---
KEY_FILE = "witness_config.key"
DOCKER_IMAGE = "ghcr.io/r-squared-project/r-squared-core:1.0.0"
DOCKER_NETWORK = "rsquared-net"
NODE_NAME = "rsquared-node"
SERVICE_FILE = "witness-rotate.service"
TIMER_FILE = "witness-rotate.timer"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(SCRIPT_DIR, "witness_node_data_dir")
EXECUTION_CONFIG_FILE = "execution_config.json"
DOCKER_CONFIG_FILE = "docker_launch_config.ini"

# Default external nodes
DEFAULT_EXTERNAL_NODES = [
    "wss://node01.rsquared.digital:8090",
    "wss://node02.rsquared.digital:8090",
    "wss://node03.rsquared.digital:8090"
]

# --- Global flag for debug mode ---
DEBUG_MODE = False

# --- Execution configuration management ---
def load_execution_config():
    """Load execution configuration (Docker vs native, paths, RPC settings)."""
    if os.path.exists(EXECUTION_CONFIG_FILE):
        with open(EXECUTION_CONFIG_FILE, 'r') as f:
            return json.load(f)
    return None

def save_execution_config(config):
    """Save execution configuration to file."""
    with open(EXECUTION_CONFIG_FILE, 'w') as f:
        json.dump(config, f, indent=4)
    os.chmod(EXECUTION_CONFIG_FILE, 0o600)

def setup_execution_environment():
    """
    Interactive setup for execution environment (Docker vs native) and RPC endpoint
    (local vs external).
    """
    print("\n--- Execution Environment Setup ---")
    config = {}
    use_docker_input = input("Do you want to use Docker for execution? (Y/n): ").strip().lower()

    if use_docker_input == 'n':
        config["use_docker"] = False
        print("\n--- Native Binary Configuration ---")
        cli_wallet_path = None
        default_cli_paths = ["/usr/local/bin/cli_wallet", "/bin/cli_wallet", "cli_wallet"]
        for path in default_cli_paths:
            if subprocess.run(["which", path], capture_output=True).returncode == 0 or os.path.exists(path):
                cli_wallet_path = path
                print(f"Found cli_wallet at: {cli_wallet_path}")
                break
        if not cli_wallet_path:
            while True:
                cli_wallet_path = input("Please provide the full path to cli_wallet: ").strip()
                if os.path.exists(cli_wallet_path) and os.access(cli_wallet_path, os.X_OK):
                    break
                print(f"Error: {cli_wallet_path} not found or not executable. Please try again.")
        config["cli_wallet_path"] = cli_wallet_path

        witness_node_path = None
        default_node_paths = ["/usr/local/bin/witness_node", "/bin/witness_node", "witness_node"]
        for path in default_node_paths:
            if subprocess.run(["which", path], capture_output=True).returncode == 0 or os.path.exists(path):
                witness_node_path = path
                print(f"Found witness_node at: {witness_node_path}")
                break
        if not witness_node_path:
            while True:
                witness_node_path = input("Please provide the full path to witness_node: ").strip()
                if os.path.exists(witness_node_path) and os.access(witness_node_path, os.X_OK):
                    break
                print(f"Error: {witness_node_path} not found or not executable. Please try again.")
        config["witness_node_path"] = witness_node_path
    else:
        config["use_docker"] = True
        print("Selected Docker for execution.")

    print("\n--- RPC Endpoint Configuration ---")
    use_local_rpc_input = input("Do you want to connect to a local witness_node for RPC? (Y/n): ").strip().lower()

    if use_local_rpc_input == 'n':
        config["local_node"] = False
        print("\nAvailable external nodes:")
        for i, node in enumerate(DEFAULT_EXTERNAL_NODES, 1):
            print(f"  {i}. {node}")
        use_default = input(f"\nUse default external nodes? (Y/n): ").strip().lower()
        if use_default == 'n':
            external_rpc = input("Enter external WSS RPC endpoint: ").strip()
            if not external_rpc.startswith(('ws://', 'wss://')):
                print("Warning: RPC endpoint should start with ws:// or wss://")
        else:
            external_rpc = DEFAULT_EXTERNAL_NODES[0]
        config["rpc_endpoint"] = external_rpc
        print(f"cli_wallet will connect to external RPC: {external_rpc}")
    else:
        config["local_node"] = True
        if config["use_docker"]:
            config["rpc_endpoint"] = f"ws://{NODE_NAME}:8090"
        else:
            config["rpc_endpoint"] = "ws://127.0.0.1:8090"
        print(f"cli_wallet will connect to local RPC: {config['rpc_endpoint']}")

    save_execution_config(config)
    print(f"\n✅ Execution configuration saved to '{EXECUTION_CONFIG_FILE}'")
    return config

def get_execution_config():
    """Get execution configuration, prompting for setup if needed."""
    config = load_execution_config()
    if not config:
        config = setup_execution_environment()
    if not config.get("use_docker", True):
        paths_valid = True
        for path_key in ["cli_wallet_path", "witness_node_path"]:
            path = config.get(path_key)
            if not path or not os.path.exists(path) or not os.access(path, os.X_OK):
                print(f"Error: {path_key} '{path}' is no longer valid.")
                paths_valid = False
        if not paths_valid:
            print("Reconfiguring execution environment...")
            config = setup_execution_environment()
    return config

# --- HELPER FUNCTIONS ---
def run_command(command, command_input=None, quiet=False):
    """A helper function to run shell commands, handle errors, and return output."""
    if DEBUG_MODE and not quiet:
        print("\n" + "="*50)
        printable_command = ' '.join(f'"{arg}"' if ' ' in arg else arg for arg in command)
        print(f"DEBUG: Executing Command:\n{printable_command}")
        if command_input:
            print(f"DEBUG: Piping Input:\n---\n{command_input}\n---")
        print("="*50)
    try:
        result = subprocess.run(command, capture_output=True, text=True, input=command_input)
        if DEBUG_MODE and not quiet:
            print(f"DEBUG: Command STDOUT:\n---\n{result.stdout.strip()}\n---")
            print(f"DEBUG: Command STDERR:\n---\n{result.stderr.strip()}\n---")
            print(f"DEBUG: Command Exit Code: {result.returncode}")
        return result.stdout.strip(), result.stderr.strip()
    except FileNotFoundError as e:
        print(f"!! ERROR: Command not found: {e}")
        sys.exit(1)

def run_wallet_command(command, command_input, delay_before_input=5, quiet=False):
    """
    Runs an interactive command (like cli_wallet), waits for a specified delay,
    then sends input.
    """
    if DEBUG_MODE and not quiet:
        print("\n" + "="*50)
        printable_command = ' '.join(f'"{arg}"' if ' ' in arg else arg for arg in command)
        print(f"DEBUG: Executing Interactive Wallet Command:\n{printable_command}")
        print(f"DEBUG: Waiting {delay_before_input}s before sending input...")
        if command_input:
            print(f"DEBUG: Piping Input:\n---\n{command_input}\n---")
        print("="*50)
    try:
        process = subprocess.Popen(
            command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, universal_newlines=True
        )
        time.sleep(delay_before_input)
        stdout, stderr = process.communicate(input=command_input)
        if DEBUG_MODE and not quiet:
            print(f"DEBUG: Command STDOUT:\n---\n{stdout.strip()}\n---")
            print(f"DEBUG: Command STDERR:\n---\n{stderr.strip()}\n---")
            print(f"DEBUG: Command Exit Code: {process.returncode}")
        return stdout.strip(), stderr.strip()
    except FileNotFoundError as e:
        print(f"!! ERROR: Command not found: {e}")
        sys.exit(1)

def wait_for_enter(prompt="Press Enter to continue..."):
    """Pauses the script until the user presses Enter, only in debug mode."""
    if DEBUG_MODE:
        input(f"\n>> {prompt}")

def build_cli_wallet_command(exec_config, rpc_endpoint=None):
    """Build the appropriate cli_wallet command based on execution configuration."""
    if exec_config["use_docker"]:
        # --- FIX STARTS HERE ---
        # Load the Docker config to get the correct network and image names
        config = load_docker_config()
        docker_config = parse_docker_config(config)
        network_name = docker_config.get('network', DOCKER_NETWORK)
        image_name = docker_config.get('image', DOCKER_IMAGE)
        # --- FIX ENDS HERE ---

        return [
            "docker", "run", "-i", "--rm", "--network", network_name, # Now uses the defined variable
            "--mount", "type=tmpfs,destination=/wallet_data",
            image_name, "/usr/local/bin/cli_wallet", # Now uses the defined variable
            "--wallet-file=/wallet_data/wallet.json",
            "-s", rpc_endpoint or exec_config["rpc_endpoint"]
        ]
    else:
        return [exec_config["cli_wallet_path"], "-s", rpc_endpoint or exec_config["rpc_endpoint"]]

def build_key_generation_command(exec_config):
    """Build the appropriate key generation command based on execution configuration."""
    if exec_config["use_docker"]:
        return [
            "docker", "run", "--platform", "linux/amd64", "--rm",
            "--mount", "type=tmpfs,destination=/wallet_data",
            DOCKER_IMAGE, "/usr/local/bin/cli_wallet", "--suggest-brain-key"
        ]
    else:
        return [exec_config["cli_wallet_path"], "--suggest-brain-key"]

def launch_witness_node(exec_config, witness_mode=False, witness_id=None, private_key_pair=None):
    """Launch witness_node based on execution configuration."""
    if exec_config["use_docker"]:
        return launch_docker_witness_node(witness_mode, witness_id, private_key_pair)
    else:
        return launch_native_witness_node(exec_config, witness_mode, witness_id, private_key_pair)

def create_default_docker_config():
    """Create a default Docker configuration file with comments."""
    config_content = """# Docker Launch Configuration for R-Squared Witness Node
# Modify these settings to customize how your witness node is launched
# Lines starting with # are comments and will be ignored

[docker]
# Docker image to use for the witness node
image = ghcr.io/r-squared-project/r-squared-core:1.0.0

# Docker network name (created automatically if it doesn't exist)
network = rsquared-net

# Container restart policy: no, always, unless-stopped, on-failure
restart_policy = unless-stopped

[ports]
# Port mappings in format: host_port = container_port
# RPC endpoint port
8090 = 8090
# P2P endpoint port
2771 = 2771

[volumes]
# Volume mounts in format: host_path = container_path
# Main data directory (will be created if it doesn't exist)
witness_node_data_dir = /witness_node_data_dir

[witness_node_args]
# Arguments passed to witness_node executable
# These are the --argument=value pairs

# Data directory inside container
data-dir = /witness_node_data_dir

# RPC endpoint - allows external connections
rpc-endpoint = 0.0.0.0:8090

# P2P endpoint for blockchain communication
p2p-endpoint = 0.0.0.0:2771

# Seed nodes for initial connection to the network
# This should be a JSON array as a string
seed-nodes = ["node01.rsquared.digital:2771","node02.rsquared.digital:2771"]

[witness_mode_args]
# Additional arguments only used in witness mode
# witness-id and private-key are set dynamically by the script

[sync_mode_args]
# Additional arguments only used in sync/listener mode
# Replay blockchain from the beginning
replay-blockchain =

[advanced]
# Advanced Docker options

# Additional Docker run arguments (space-separated)
# Example: --memory=2g --cpus=1.5 --security-opt=no-new-privileges
extra_docker_args =

# Additional environment variables (comma-separated KEY=VALUE pairs)
# Example: LOG_LEVEL=debug,MAX_CONNECTIONS=100
environment_vars =
"""

    with open(DOCKER_CONFIG_FILE, 'w') as f:
        f.write(config_content)

    print(f"Created default Docker configuration: {DOCKER_CONFIG_FILE}")
    print("You can edit this file to customize your node deployment.")

def load_docker_config():
    """Load Docker configuration from file, create default if it doesn't exist."""
    if not os.path.exists(DOCKER_CONFIG_FILE):
        print(f"Docker config file '{DOCKER_CONFIG_FILE}' not found. Creating default...")
        create_default_docker_config()

    config = configparser.ConfigParser(allow_no_value=True)
    config.read(DOCKER_CONFIG_FILE)

    return config

def parse_docker_config(config):
    """Parse the configuration file into a structured format."""
    docker_config = {
        'image': config.get('docker', 'image', fallback=DOCKER_IMAGE),
        'network': config.get('docker', 'network', fallback=DOCKER_NETWORK),
        'restart_policy': config.get('docker', 'restart_policy', fallback='unless-stopped'),
        'ports': {},
        'volumes': {},
        'witness_node_args': {},
        'witness_mode_args': {},
        'sync_mode_args': {},
        'extra_docker_args': [],
        'environment_vars': {}
    }

    # Parse ports
    if config.has_section('ports'):
        for host_port, container_port in config.items('ports'):
            docker_config['ports'][host_port] = container_port

    # Parse volumes
    if config.has_section('volumes'):
        for host_path, container_path in config.items('volumes'):
            # Convert relative paths to absolute
            if not os.path.isabs(host_path):
                host_path = os.path.join(SCRIPT_DIR, host_path)
            docker_config['volumes'][host_path] = container_path

    # Parse witness_node arguments
    if config.has_section('witness_node_args'):
        for arg, value in config.items('witness_node_args'):
            docker_config['witness_node_args'][arg] = value

    # Parse witness mode specific args
    if config.has_section('witness_mode_args'):
        for arg, value in config.items('witness_mode_args'):
            docker_config['witness_mode_args'][arg] = value

    # Parse sync mode specific args
    if config.has_section('sync_mode_args'):
        for arg, value in config.items('sync_mode_args'):
            docker_config['sync_mode_args'][arg] = value

    # Parse advanced options
    if config.has_section('advanced'):
        extra_args = config.get('advanced', 'extra_docker_args', fallback='').strip()
        if extra_args:
            docker_config['extra_docker_args'] = extra_args.split()

        env_vars = config.get('advanced', 'environment_vars', fallback='').strip()
        if env_vars:
            for env_pair in env_vars.split(','):
                if '=' in env_pair:
                    key, value = env_pair.strip().split('=', 1)
                    docker_config['environment_vars'][key.strip()] = value.strip()

    return docker_config

def build_docker_command_from_config(docker_config, witness_mode=False, witness_id=None, private_key_pair=None):
    """Build Docker command using configuration file settings."""

    # Ensure data directory exists
    for host_path in docker_config['volumes'].keys():
        os.makedirs(host_path, exist_ok=True)

    # Base docker command
    command = ["docker", "run", "-d", "--name", NODE_NAME]

    # Add restart policy
    if docker_config['restart_policy'] != 'no':
        command.extend(["--restart", docker_config['restart_policy']])

    # Add network
    command.extend(["--network", docker_config['network']])

    # Add port mappings
    for host_port, container_port in docker_config['ports'].items():
        command.extend(["-p", f"{host_port}:{container_port}"])

    # Add volume mounts
    for host_path, container_path in docker_config['volumes'].items():
        command.extend(["-v", f"{host_path}:{container_path}"])

    # Add environment variables
    for key, value in docker_config['environment_vars'].items():
        command.extend(["-e", f"{key}={value}"])

    # Add extra docker arguments
    command.extend(docker_config['extra_docker_args'])

    # Add image and executable
    command.extend([docker_config['image'], "witness_node"])

    # Add witness_node base arguments
    for arg, value in docker_config['witness_node_args'].items():
        if value is None or value == '':
            command.append(f"--{arg}")
        else:
            command.extend([f"--{arg}", value])

    # Add mode-specific arguments
    if witness_mode and witness_id and private_key_pair:
        # Witness mode arguments
        for arg, value in docker_config['witness_mode_args'].items():
            if value is None or value == '':
                command.append(f"--{arg}")
            else:
                command.extend([f"--{arg}", value])

        # Add dynamic witness arguments
        witness_id_arg = f'"{witness_id}"'
        private_key_arg = f'["{private_key_pair[0]}","{private_key_pair[1]}"]'
        command.extend(["--witness-id", witness_id_arg])
        command.extend(["--private-key", private_key_arg])
    else:
        # Sync mode arguments
        for arg, value in docker_config['sync_mode_args'].items():
            if value is None or value == '':
                command.append(f"--{arg}")
            else:
                command.extend([f"--{arg}", value])

    return command

# Replace the existing launch_docker_witness_node function with this version:
def launch_docker_witness_node(witness_mode=False, witness_id=None, private_key_pair=None):
    """Launch witness_node using Docker with configuration file settings."""
    print(f"Launching Docker node '{NODE_NAME}'...")

    # Stop and remove existing container
    run_command(["docker", "stop", NODE_NAME], quiet=True)
    run_command(["docker", "rm", NODE_NAME], quiet=True)

    # Load Docker configuration
    config = load_docker_config()
    docker_config = parse_docker_config(config)

    # Create network if it doesn't exist
    network_name = docker_config.get('network', DOCKER_NETWORK)
    run_command(["docker", "network", "create", network_name], quiet=True)
    image_name = docker_config.get('image', DOCKER_IMAGE)

    # Build command from configuration
    command = build_docker_command_from_config(
        docker_config, witness_mode, witness_id, private_key_pair
    )

    # Execute the command
    stdout, stderr = run_command(command)

    if stderr and ("Error" in stderr or "error" in stderr.lower()):
        print(f"   Docker launch failed. STDERR:\n{stderr}")
        return False
    else:
        print("   Docker node launched successfully.")
        if DEBUG_MODE:
            # Show command structure (with keys hidden) in debug mode
            debug_command = []
            hide_next = False
            for i, arg in enumerate(command):
                if hide_next:
                    if "--private-key" in command[i-1]:
                        debug_command.append("[***HIDDEN_KEYS***]")
                    elif "--witness-id" in command[i-1]:
                        debug_command.append("***HIDDEN_ID***")
                    else:
                        debug_command.append(arg)
                    hide_next = False
                elif arg in ["--private-key", "--witness-id"]:
                    debug_command.append(arg)
                    hide_next = True
                else:
                    debug_command.append(arg)

            print(f"DEBUG: Command executed: {' '.join(debug_command)}")

        return True

# Add this function to show current configuration
def show_docker_config():
    """Display current Docker configuration."""
    if not os.path.exists(DOCKER_CONFIG_FILE):
        print(f"No Docker configuration file found at '{DOCKER_CONFIG_FILE}'")
        return

    config = load_docker_config()
    docker_config = parse_docker_config(config)

    print(f"=== Docker Configuration ({DOCKER_CONFIG_FILE}) ===")
    print(f"Image: {docker_config['image']}")
    print(f"Network: {docker_config['network']}")
    print(f"Restart Policy: {docker_config['restart_policy']}")

    print("\nPort Mappings:")
    for host_port, container_port in docker_config['ports'].items():
        print(f"  {host_port} -> {container_port}")

    print("\nVolume Mounts:")
    for host_path, container_path in docker_config['volumes'].items():
        print(f"  {host_path} -> {container_path}")

    print("\nWitness Node Base Arguments:")
    for arg, value in docker_config['witness_node_args'].items():
        if value:
            print(f"  --{arg}: {value}")
        else:
            print(f"  --{arg}")

    if docker_config['witness_mode_args']:
        print("\nWitness Mode Arguments:")
        for arg, value in docker_config['witness_mode_args'].items():
            if value:
                print(f"  --{arg}: {value}")
            else:
                print(f"  --{arg}")

    if docker_config['sync_mode_args']:
        print("\nSync Mode Arguments:")
        for arg, value in docker_config['sync_mode_args'].items():
            if value:
                print(f"  --{arg}: {value}")
            else:
                print(f"  --{arg}")

    if docker_config['environment_vars']:
        print("\nEnvironment Variables:")
        for key, value in docker_config['environment_vars'].items():
            print(f"  {key}={value}")

    if docker_config['extra_docker_args']:
        print(f"\nExtra Docker Arguments: {' '.join(docker_config['extra_docker_args'])}")

def launch_native_witness_node(exec_config, witness_mode=False, witness_id=None, private_key_pair=None):
    """Launch witness_node using native binary with proper argument formatting."""
    print("Launching native witness_node...")
    os.makedirs(DATA_DIR, exist_ok=True)

    # Base command parts
    base_cmd = [
        exec_config["witness_node_path"],
        f"--data-dir={DATA_DIR}",
        "--rpc-endpoint=127.0.0.1:8090",
        "--p2p-endpoint=127.0.0.1:2771"
    ]

    if witness_mode and witness_id and private_key_pair:
        # For native, we can use the list format since there's no shell interpretation
        seed_nodes_arg = '["node01.rsquared.digital:2771","node02.rsquared.digital:2771"]'
        private_key_arg = f'["{private_key_pair[0]}","{private_key_pair[1]}"]'

        base_cmd.extend([
            f"--seed-nodes={seed_nodes_arg}",
            f"--private-key={private_key_arg}",
            f"--witness-id=\"{witness_id}\""  # Native needs the quotes
        ])
    else:
        # Sync mode
        seed_nodes_arg = '["node01.rsquared.digital:2771","node02.rsquared.digital:2771"]'
        base_cmd.extend([
            f"--seed-nodes={seed_nodes_arg}",
            "--replay-blockchain"
        ])

    print(f"   Command: {' '.join(base_cmd)}")

    try:
        result = subprocess.run(["netstat", "-tulpn"], capture_output=True, text=True)
        if ":8090" in result.stdout:
            print("   Port 8090 appears to be in use. Attempting to continue...")
    except:
        pass

    # For native, construct as shell command string to handle complex quoting
    command_str = " ".join(base_cmd)
    process = subprocess.Popen(command_str, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(3)

    if process.poll() is None:
        print("   Native witness_node started successfully.")
        pid_file = os.path.join(SCRIPT_DIR, "witness_node.pid")
        with open(pid_file, 'w') as f:
            f.write(str(process.pid))
        return True
    else:
        print("   Failed to start native witness_node.")
        return False

def launch_native_witness_node(exec_config, witness_mode=False, witness_id=None, private_key_pair=None):
    """Launch witness_node using native binary."""
    print("🔧 Launching native witness_node...")
    os.makedirs(DATA_DIR, exist_ok=True)

    base_command = [
        exec_config["witness_node_path"], f"--data-dir={DATA_DIR}",
        "--rpc-endpoint=127.0.0.1:8090", "--p2p-endpoint=127.0.0.1:2771"
    ]

    # Add seed nodes first (common to both modes)
    base_command.extend([
        '--seed-nodes=["node01.rsquared.digital:2771","node02.rsquared.digital:2771"]'
    ])

    if witness_mode and witness_id and private_key_pair:
        # Witness mode: NO --replay-blockchain, add witness-specific args
        private_key_arg = f'["{private_key_pair[0]}","{private_key_pair[1]}"]'
        base_command.extend([
            "--witness-id", f'"{witness_id}"',  # No extra quotes needed
            "--private-key", private_key_arg
        ])
    else:
        # Sync/listener mode: add --replay-blockchain
        base_command.append("--replay-blockchain")

    print(f"   Command: {' '.join(base_command)}")

    try:
        result = subprocess.run(["netstat", "-tulpn"], capture_output=True, text=True)
        if ":8090" in result.stdout:
            print("   ⚠️ Port 8090 appears to be in use. Attempting to continue...")
    except:
        pass

    process = subprocess.Popen(base_command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(3)

    if process.poll() is None:
        print("   ✅ Native witness_node started successfully.")
        pid_file = os.path.join(SCRIPT_DIR, "witness_node.pid")
        with open(pid_file, 'w') as f:
            f.write(str(process.pid))
        return True
    else:
        print("   ❌ Failed to start native witness_node.")
        return False

def stop_witness_node(exec_config):
    """Stop the witness_node based on execution configuration."""
    if exec_config["use_docker"]:
        print(f"🐳 Stopping Docker container '{NODE_NAME}'...")
        run_command(["docker", "stop", NODE_NAME], quiet=True)
        run_command(["docker", "rm", NODE_NAME], quiet=True)
    else:
        print("🔧 Stopping native witness_node...")
        pid_file = os.path.join(SCRIPT_DIR, "witness_node.pid")
        if os.path.exists(pid_file):
            with open(pid_file, 'r') as f: pid = f.read().strip()
            try:
                subprocess.run(["kill", pid], check=True)
                os.remove(pid_file)
                print("   ✅ Native witness_node stopped.")
            except subprocess.CalledProcessError:
                print("   ⚠️ Could not stop witness_node (may have already exited).")
        else:
            print("   ⚠️ No PID file found. Process may not be running.")

def is_node_ready(exec_config, max_retries=5, delay=5):
    """Actively checks if the witness node's RPC is responsive."""
    print("🩺 Checking if the node's RPC endpoint is ready...")
    check_command = build_cli_wallet_command(exec_config)
    check_input = "get_info\nquit\n"
    for attempt in range(max_retries):
        stdout, stderr = run_wallet_command(check_command, command_input=check_input, quiet=True)
        if "Underlying Transport Error" not in stderr and "get_info" in stdout:
            print("   ✅ Node RPC is responsive.")
            return True
        print(f"   Attempt {attempt + 1}/{max_retries}: Node not ready yet. Retrying in {delay} seconds...")
        time.sleep(delay)
    print("!! FATAL ERROR: Node RPC did not become responsive after multiple attempts.")
    return False

def extract_witness_id(wallet_output):
    """Extract witness ID from wallet output using multiple parsing strategies."""
    witness_id = None
    for line in wallet_output.splitlines():
        line = line.strip()
        if line.startswith("{") and line.endswith("}"):
            try:
                data = json.loads(line)
                if isinstance(data, dict) and "id" in data:
                    candidate_id = data["id"]
                    if isinstance(candidate_id, str) and candidate_id.startswith("1.6."):
                        witness_id = candidate_id
                        if DEBUG_MODE: print(f"DEBUG: Found witness ID via JSON parsing: {witness_id}")
                        break
            except json.JSONDecodeError: continue
    if not witness_id:
        pattern = r'"id":\s*"(1\.6\.\d+)"'
        matches = re.findall(pattern, wallet_output)
        if matches:
            witness_id = matches[0]
            if DEBUG_MODE: print(f"DEBUG: Found witness ID via regex: {witness_id}")
    if not witness_id:
        pattern = r'1\.6\.\d+'
        matches = re.findall(pattern, wallet_output)
        if matches:
            witness_id = matches[0]
            if DEBUG_MODE: print(f"DEBUG: Found witness ID via pattern matching: {witness_id}")
    return witness_id

def encrypt_data(data, password):
    """Encrypts a dictionary with a password and saves it to a file."""
    try:
        salt = os.urandom(16)
        kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=390000)
        key = kdf.derive(password.encode())
        aesgcm = AESGCM(key)
        nonce = os.urandom(12)
        data_bytes = json.dumps(data).encode('utf-8')
        encrypted_data = aesgcm.encrypt(nonce, data_bytes, None)
        with open(KEY_FILE, 'wb') as f:
            f.write(salt + nonce + encrypted_data)
        os.chmod(KEY_FILE, 0o600)
    except Exception as e:
        print(f"!! An error occurred during encryption: {e}")
        sys.exit(1)

def decrypt_data(password):
    """Reads the encrypted file and decrypts the data with a password."""
    try:
        with open(KEY_FILE, 'rb') as f:
            data = f.read()
    except FileNotFoundError:
        print(f"!! ERROR: Config file '{KEY_FILE}' not found. Please run with 'setup' first.")
        return None
    try:
        salt, nonce, encrypted_data = data[:16], data[16:28], data[28:]
        kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=390000)
        key = kdf.derive(password.encode())
        aesgcm = AESGCM(key)
        decrypted_bytes = aesgcm.decrypt(nonce, encrypted_data, None)
        return json.loads(decrypted_bytes.decode('utf-8'))
    except Exception:
        return None

def create_secure_password_file(password):
    """Creates a secure password file for systemd service access."""
    password_file = os.path.join(SCRIPT_DIR, ".witness_service_key")
    salt = os.urandom(32)
    password_bytes = password.encode('utf-8')
    encrypted_password = bytes(a ^ b for a, b in zip(password_bytes, (salt * ((len(password_bytes) // len(salt)) + 1))[:len(password_bytes)]))
    with open(password_file, 'wb') as f:
        f.write(salt + encrypted_password)
    os.chmod(password_file, 0o600)
    return password_file

def read_secure_password_file():
    """Reads and decrypts the secure password file."""
    password_file = os.path.join(SCRIPT_DIR, ".witness_service_key")
    if not os.path.exists(password_file): return None
    try:
        with open(password_file, 'rb') as f: data = f.read()
        if len(data) < 32: return None
        salt = data[:32]
        encrypted_password = data[32:]
        password_bytes = bytes(a ^ b for a, b in zip(encrypted_password, (salt * ((len(encrypted_password) // len(salt)) + 1))[:len(encrypted_password)]))
        return password_bytes.decode('utf-8')
    except Exception:
        return None

def generate_systemd_files(password):
    """Generates the systemd service and timer files with secure password handling."""
    script_path = os.path.abspath(__file__)
    user = getpass.getuser()
    python_executable = sys.executable
    password_file = create_secure_password_file(password)
    print(f"🔐 Secure password file created: {password_file}")
    service_content = f"""
    [Unit]
    Description=R-Squared Witness Key Rotation Service
    Wants=docker.service
    After=docker.service network-online.target
    [Service]
    Type=oneshot
    User={user}
    Group={user}
    WorkingDirectory={os.path.dirname(script_path)}
    ExecStart={python_executable} {script_path} service-run-secure
    """
    timer_content = f"""
    [Unit]
    Description=Run R-Squared Witness Key Rotation periodically
    [Timer]
    OnCalendar=daily
    Persistent=true
    RandomizedDelaySec=1h
    [Install]
    WantedBy=timers.target
    """
    with open(SERVICE_FILE, "w") as f: f.write(textwrap.dedent(service_content).strip())
    with open(TIMER_FILE, "w") as f: f.write(textwrap.dedent(timer_content).strip())
    print(f"✅ `{SERVICE_FILE}` and `{TIMER_FILE}` files have been generated.")
    print("🔒 Password is now stored securely and NOT visible in the service file.")
    print("\n--- To enable the automated service, run the following commands: ---")
    print(f"sudo mv {SERVICE_FILE} /etc/systemd/system/")
    print(f"sudo mv {TIMER_FILE} /etc/systemd/system/")
    print("sudo systemctl daemon-reload")
    print(f"sudo systemctl enable {TIMER_FILE}")
    print(f"sudo systemctl start {TIMER_FILE}")
    print(f"\nYou can check the timer status with: systemctl status {TIMER_FILE}")
    print(f"You can view logs of the last run with: sudo journalctl -u {SERVICE_FILE} -n 50 --no-pager")

def uninstall_workflow():
    """Stops the service and removes all related files and containers."""
    print("--- Witness Manager Uninstallation ---")
    exec_config = load_execution_config()
    print("🗑️ Stopping and disabling systemd timer and service...")
    run_command(["sudo", "systemctl", "stop", TIMER_FILE], quiet=True)
    run_command(["sudo", "systemctl", "disable", TIMER_FILE], quiet=True)
    print("🗑️ Removing systemd files...")
    service_path = f"/etc/systemd/system/{SERVICE_FILE}"
    timer_path = f"/etc/systemd/system/{TIMER_FILE}"
    if os.path.exists(service_path): run_command(["sudo", "rm", service_path])
    if os.path.exists(timer_path): run_command(["sudo", "rm", timer_path])
    run_command(["sudo", "systemctl", "daemon-reload"])
    print("   ✅ Systemd services removed.")
    if exec_config:
        stop_witness_node(exec_config)
    else:
        print("🐳 Stopping Docker container (if exists)...")
        run_command(["docker", "stop", NODE_NAME], quiet=True)
        run_command(["docker", "rm", NODE_NAME], quiet=True)
        print("🔧 Stopping native process (if exists)...")
        pid_file = os.path.join(SCRIPT_DIR, "witness_node.pid")
        if os.path.exists(pid_file):
            with open(pid_file, 'r') as f: pid = f.read().strip()
            try: subprocess.run(["kill", pid])
            except: pass
            finally: os.remove(pid_file)
    print("   ✅ Witness node stopped.")
    print("\n--- Data Cleanup (Optional) ---")
    if os.path.exists(EXECUTION_CONFIG_FILE):
        if input(f"❓ Do you want to remove '{EXECUTION_CONFIG_FILE}'? (y/N): ").lower() == 'y':
            os.remove(EXECUTION_CONFIG_FILE)
            print(f"   ✅ Removed '{EXECUTION_CONFIG_FILE}'.")
    if os.path.exists(KEY_FILE):
        if input(f"❓ Do you want to remove '{KEY_FILE}'? (y/N): ").lower() == 'y':
            os.remove(KEY_FILE)
            print(f"   ✅ Removed '{KEY_FILE}'.")
    password_file = os.path.join(SCRIPT_DIR, ".witness_service_key")
    if os.path.exists(password_file):
        if input(f"❓ Do you want to remove '{password_file}'? (y/N): ").lower() == 'y':
            os.remove(password_file)
            print(f"   ✅ Removed '{password_file}'.")
    if os.path.exists(DATA_DIR):
        if input(f"❓ Do you want to remove '{DATA_DIR}'? THIS IS IRREVERSIBLE. (y/N): ").lower() == 'y':
            run_command(["sudo", "rm", "-rf", DATA_DIR])
            print(f"   ✅ Removed '{DATA_DIR}'.")
    print("\n✅ Uninstallation complete.")

def setup_workflow():
    """First-time setup to encrypt config and launch the sync node."""
    print("--- Witness Manager First-Time Setup ---")
    exec_config = setup_execution_environment()
    if os.path.exists(KEY_FILE):
        print("\n!! WARNING: An existing config file ('witness_config.key') was found.")
        if input("!! Overwrite it? (y/N): ").lower() != 'y':
            print("   Aborting setup."); sys.exit(0)
        print("   Proceeding with new setup.")
    account_name = input("\nEnter your witness account name: ")
    url = input("Enter your witness URL (optional): ")
    if input("Store WIF key encrypted? (Y/n): ").strip().lower() == 'n':
        print("\nManual mode selected. Run with: python3 witness_manager.py manual")
        encrypt_data({"account_name": account_name, "url": url, "original_wif": ""}, "dummy")
    else:
        original_wif = getpass.getpass("Enter your ORIGINAL account WIF private key: ")
        password = getpass.getpass("Create a password to encrypt your config: ")
        encrypt_data({"account_name": account_name, "url": url, "original_wif": original_wif}, password)
        print("\n🔐 Configuration encrypted to 'witness_config.key'.")

    # --- CORRECTED LOGIC ---
    # Always prepare and launch the listener node, as the user is setting up a witness node on this machine.
    os.makedirs(DATA_DIR, exist_ok=True)
    if exec_config["use_docker"]:
        run_command(["docker", "network", "create", DOCKER_NETWORK], quiet=True)
    print("🔄 Launching listener node to sync the blockchain...")
    launch_witness_node(exec_config, witness_mode=False)
    print("\n--- ✅ Setup Complete! ---")
    print("The node is now syncing. This may take several hours.")
    print(f"Monitor its progress with: {'docker logs -f ' + NODE_NAME if exec_config['use_docker'] else 'Check the log files in ' + DATA_DIR}")
    print("\nIMPORTANT: Once the node is fully synchronized, proceed by running:")
    print(f"python3 {sys.argv[0]} run (for stored key) or python3 {sys.argv[0]} manual (for manual input)")

def launch_listener_node():
    """Launches the listen-only node for syncing."""
    print("Preparing environment for listener node...")
    exec_config = get_execution_config()
    os.makedirs(DATA_DIR, exist_ok=True)
    if exec_config["use_docker"]:
        run_command(["docker", "network", "create", DOCKER_NETWORK], quiet=True)
    print("🔄 Launching listener node for sync...")
    launch_witness_node(exec_config, witness_mode=False)
    print(f"   ✅ Node launched.")

def manual_mode_workflow():
    """Manual mode workflow where user inputs WIF key directly."""
    print("--- Witness Manager Manual Mode ---")
    exec_config = get_execution_config()
    account_name = input("Enter witness account name: ")
    url = input("Enter witness URL (optional): ")
    original_wif = getpass.getpass("Enter ORIGINAL account WIF private key: ")
    config = {"account_name": account_name, "url": url, "original_wif": original_wif}

    success, pub_key, wif_key = perform_key_rotation(config, exec_config)
    if success:
        prompt_for_key_save(pub_key, wif_key)
    return success

def perform_key_rotation(config, exec_config):
    """The core key rotation logic with robust error checking."""
    print(f"\n--- [{time.ctime()}] Starting Witness Key Rotation ---")
    print(f"🔍 Verifying WIF key and fetching Witness ID for '{config['account_name']}'...")
    temp_wallet_password = secrets.token_hex(16)
    wallet_commands = (
        f'set_password "{temp_wallet_password}"\n'
        f'unlock "{temp_wallet_password}"\n'
        f'import_key "{config["account_name"]}" "{config["original_wif"]}"\n'
        f'get_witness "{config["account_name"]}"\n'
        'quit\n'
    )
    wallet_command = build_cli_wallet_command(exec_config)
    stdout, stderr = run_wallet_command(wallet_command, command_input=wallet_commands)

    if "Invalid private key" in stdout or "exception" in stdout:
        log_details = f"--- Wallet Logs ---\nSTDOUT:\n{stdout}\n\nSTDERR:\n{stderr}\n--- End Logs ---"
        print("\n!! FATAL ERROR: The provided WIF key is invalid.")
        print(f"!! Please ensure the key is correct.\n{log_details}")
        return False, None, None  # CORRECTED RETURN

    witness_id = extract_witness_id(stdout)
    if not witness_id:
        log_details = f"--- Wallet Logs ---\nSTDOUT:\n{stdout}\n\nSTDERR:\n{stderr}\n--- End Logs ---"
        print(f"\n!! FATAL ERROR: Could not find a valid Witness ID from the node's output.\n{log_details}")
        return False, None, None  # CORRECTED RETURN
    print(f"   ✅ Key is valid. Fetched Witness ID: {witness_id}")
    wait_for_enter("Proceeding to generate new key...")

    print("🔑 Generating new signing key pair...")
    key_gen_command = build_key_generation_command(exec_config)
    key_json, error = run_command(key_gen_command)
    try:
        keys = json.loads(key_json)
        new_pub_key, new_wif_key = keys['pub_key'], keys['wif_priv_key']
    except (json.JSONDecodeError, KeyError) as e:
        print(f"!! ERROR: Failed to parse new keys from wallet output: {e}")
        return False, None, None  # CORRECTED RETURN
    print("   Done.")
    wait_for_enter("Proceeding to authorize new key on blockchain...")

    print("🚀 Authorizing new key on the blockchain...")
    auth_commands = (
        f'set_password "{temp_wallet_password}"\n'
        f'unlock "{temp_wallet_password}"\n'
        f'import_key "{config["account_name"]}" "{config["original_wif"]}"\n'
        f'update_witness "{config["account_name"]}" "{config["url"]}" "{new_pub_key}" true\n'
        'quit\n'
    )
    auth_command = build_cli_wallet_command(exec_config)
    if exec_config["use_docker"]:
        auth_command.append("-H")
    auth_stdout, auth_stderr = run_wallet_command(auth_command, command_input=auth_commands)

    if "exception" in auth_stdout or "error" in auth_stdout.lower() or "error" in auth_stderr.lower():
        log_details = f"--- Auth Logs ---\nSTDOUT:\n{auth_stdout}\n\nSTDERR:\n{auth_stderr}\n--- End Logs ---"
        print("\n!! FATAL ERROR: The blockchain REJECTED the key update transaction.")
        print("!! CAUSE: The WIF key you provided may not be the CURRENTLY ACTIVE signing key.")
        print(f"!! Please use the correct, active WIF key and try again.\n{log_details}")
        return False, None, None  # CORRECTED RETURN
    print("   ✅ Transaction accepted by the blockchain.")
    wait_for_enter("Proceeding to launch the local witness node with the new key...")

    print(f"🔄 Relaunching local witness node with new signing key...")
    stop_witness_node(exec_config)
    # Note: the `witness_id` variable is now correctly used here, without extra quotes
    launch_witness_node(exec_config, witness_mode=True, witness_id=witness_id,
                       private_key_pair=(new_pub_key, new_wif_key))

    print(f"\n✅ Key rotation complete! Your witness node is running with the new key.")
    # DO NOT PRINT KEYS HERE
    return True, new_pub_key, new_wif_key # CORRECTED RETURN

def prompt_for_key_save(new_pub_key, new_wif_key):
    """Asks the user if they want to save the new keys, with a 30-second timeout."""
    print("\n" + "="*50)
    print("IMPORTANT: A new key pair has been generated and activated.")
    print("Your old key is no longer the active signing key.")
    print("="*50)

    print("\n❓ Do you want to save the new keys to a file? (y/N) [30s timeout]: ", end='', flush=True)

    try:
        # Use select to wait for input on stdin for 30 seconds (works on Linux/macOS)
        rlist, _, _ = select.select([sys.stdin], [], [], 30)

        if rlist:
            answer = sys.stdin.readline().strip().lower()
        else:
            print("\nTimeout expired. Assuming 'No'.")
            answer = 'n'

        if answer == 'y':
            filename = "new_witness_keys.txt"
            try:
                with open(filename, "w") as f:
                    f.write(f"New Public Key: {new_pub_key}\n")
                    f.write(f"New Private WIF Key: {new_wif_key}\n")
                os.chmod(filename, 0o600)
                print(f"\n✅ Keys securely saved to '{filename}'. Protect this file!")
            except IOError as e:
                print(f"\n❌ Error: Could not write keys to file: {e}")
        else:
            print("\n⚠️ You chose not to save the keys. Please ensure you have backed them up.")
            print("   The script will now exit.")
    except (KeyboardInterrupt, SystemExit):
        print("\nOperation cancelled.")

def run_or_service_workflow(password, generate_service_files=False):
    """The main 'one-click' automation workflow."""
    config = decrypt_data(password)
    if not config:
        print("!! ERROR: Invalid password or corrupted config file. Run 'setup' again.")
        return False
    print("🔍 Configuration decrypted successfully.")
    exec_config = get_execution_config()

    success, pub_key, wif_key = perform_key_rotation(config, exec_config)

    if success and generate_service_files:
        # This block runs in interactive "run" mode.
        prompt_for_key_save(pub_key, wif_key)
        print("\n--- Systemd Service File Generation ---")
        if input("Generate systemd timer for daily key rotation? (Y/n): ").strip().lower() != 'n':
            generate_systemd_files(password)

    return success

if __name__ == "__main__":
    if "--debug" in sys.argv:
        DEBUG_MODE = True
        sys.argv.remove("--debug")

    valid_commands = [
        "setup", "run", "manual", "service-run", "service-run-secure",
        "uninstall", "config", "docker-config", "show-docker-config"
    ]

    if len(sys.argv) < 2 or sys.argv[1] not in valid_commands:
        print("Usage: python3 witness_manager.py [command] [--debug]")
        print("Commands:")
        print("  setup              - First-time setup")
        print("  run                - Run with stored config")
        print("  manual             - Manual mode with direct input")
        print("  service-run        - Service mode with password")
        print("  service-run-secure - Service mode with secure password")
        print("  uninstall          - Remove all components")
        print("  config             - Reconfigure execution environment")
        print("  docker-config      - Create/edit Docker launch configuration")
        print("  show-docker-config - Display current Docker configuration")
        sys.exit(1)

    mode = sys.argv[1]

    if mode == "setup":
        setup_workflow()
    elif mode == "config":
        print("--- Reconfiguring Execution Environment ---")
        setup_execution_environment()
    elif mode == "docker-config":
        print("--- Docker Launch Configuration ---")
        if os.path.exists(DOCKER_CONFIG_FILE):
            print(f"Docker configuration file '{DOCKER_CONFIG_FILE}' already exists.")
            if input("Recreate it? This will overwrite current settings (y/N): ").lower() == 'y':
                create_default_docker_config()
            else:
                print(f"Edit '{DOCKER_CONFIG_FILE}' manually to customize Docker launch settings.")
        else:
            create_default_docker_config()
    elif mode == "show-docker-config":
        show_docker_config()
    elif mode == "run":
        if not os.path.exists(KEY_FILE):
            print("No config found. Running in manual mode.")
            manual_mode_workflow()
        elif input("Use stored config? (Y/n): ").strip().lower() == 'n':
            manual_mode_workflow()
        else:
            password = getpass.getpass("Enter encryption password: ")
            run_or_service_workflow(password, generate_service_files=True)
    elif mode == "manual":
        manual_mode_workflow()
    elif mode == "service-run":
        if len(sys.argv) < 3:
            print("ERROR: service-run requires a password argument.", file=sys.stderr)
            sys.exit(1)
        run_or_service_workflow(sys.argv[2], generate_service_files=False)
    elif mode == "service-run-secure":
        password = read_secure_password_file()
        if not password:
            print("ERROR: Could not read secure password file.", file=sys.stderr)
            sys.exit(1)
        run_or_service_workflow(password, generate_service_files=False)
    elif mode == "uninstall":
        uninstall_workflow()
