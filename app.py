from flask import Flask, render_template, request, jsonify, Response
from flask_httpauth import HTTPBasicAuth
import subprocess
import threading
import time
import re
from datetime import datetime, timezone
import os
import json
import getpass

# Assuming witness_manager.py is in the same directory
import witness_manager

# --- CONFIGURATION ---
AUTH_FILE = "user_credentials.json"

# --- AUTHENTICATION SETUP ---

def load_or_create_credentials():
    """
    Loads credentials from the auth file, or prompts the user to create them
    if the file does not exist. This is run once on server startup.
    """
    if os.path.exists(AUTH_FILE):
        print(f"🔐 Loading credentials from '{AUTH_FILE}'...")
        with open(AUTH_FILE, 'r') as f:
            return json.load(f)
    else:
        print("--- First-Time Setup: Web UI Credentials ---")
        print(f"Credential file '{AUTH_FILE}' not found.")
        print("Please create a username and password to secure the web interface.")

        username = input("Enter a username for the web UI [default: admin]: ").strip()
        if not username:
            username = "admin"

        while True:
            password = getpass.getpass("Enter a new password (will not be visible): ")
            if not password:
                print("Password cannot be empty. Please try again.")
                continue

            password_confirm = getpass.getpass("Confirm password: ")
            if password == password_confirm:
                break
            else:
                print("Passwords do not match. Please try again.")

        credentials = {username: password}

        with open(AUTH_FILE, 'w') as f:
            json.dump(credentials, f, indent=4)

        # Set restrictive file permissions (only owner can read/write)
        os.chmod(AUTH_FILE, 0o600)

        print(f"\n✅ Credentials saved to '{AUTH_FILE}'. Please restart the server to use them.")
        # Exit so the user can restart the script which will then load the new file.
        exit(0)

app = Flask(__name__)
auth = HTTPBasicAuth()

# Load credentials from file at startup
USERS = load_or_create_credentials()

@auth.verify_password
def verify_password(username, password):
    """Checks the provided credentials against the loaded USERS dictionary."""
    if username in USERS and USERS.get(username) == password:
        return username

# --- ORIGINAL WEB SERVER LOGIC ---

# In-memory store for progress updates
progress_updates = []
process_thread = None
generated_keys = {}

def add_progress_update(message):
    """Adds a timestamped message to the progress log."""
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    progress_updates.append(f"[{timestamp}] {message}")

def run_key_rotation_process(account_name, url, wif_key):
    """
    Fixed background process that handles the workflow correctly and stores keys globally.
    """
    global progress_updates, generated_keys  # Ensure both are global
    progress_updates = []  # Clear previous logs
    generated_keys = {}    # Clear previous keys

    try:
        # Get execution configuration
        exec_config = witness_manager.get_execution_config()
        add_progress_update(f"Execution mode: {'Docker' if exec_config['use_docker'] else 'Native'}")

        if exec_config.get("local_node", True):
            # --- LOCAL NODE PATH ---
            add_progress_update("--- Configuration: Using Local Node ---")
            add_progress_update("Starting local node for blockchain sync...")

            # Launch sync node
            witness_manager.launch_listener_node()

            # Wait for sync
            add_progress_update("Waiting for blockchain sync to complete...")
            monitor_node_sync(exec_config)
            add_progress_update("✅ Blockchain sync completed.")

            # Verify RPC is ready
            add_progress_update("🩺 Verifying local RPC is responsive...")
            if not witness_manager.is_node_ready(exec_config):
                add_progress_update("❌ Local RPC not responsive. Aborting.")
                add_progress_update("PROCESS_COMPLETE_FAILURE")
                return

        else:
            # --- EXTERNAL NODE PATH ---
            add_progress_update("--- Configuration: Using External Node ---")
            add_progress_update(f"🔗 Will connect to: {exec_config.get('rpc_endpoint')}")

            # Stop any local node that might be running
            witness_manager.stop_witness_node(exec_config)
            add_progress_update("Ensured no local node is running.")

            # Verify external RPC is ready
            add_progress_update("🩺 Verifying external RPC is responsive...")
            if not witness_manager.is_node_ready(exec_config):
                add_progress_update("❌ External RPC not responsive. Check your connection.")
                add_progress_update("PROCESS_COMPLETE_FAILURE")
                return

        # --- PERFORM KEY ROTATION ---
        add_progress_update("--- Starting Key Rotation ---")
        config = {
            "account_name": account_name,
            "url": url,
            "original_wif": wif_key
        }

        # Capture new return values and store globally
        success, new_pub_key, new_wif_key = witness_manager.perform_key_rotation(config, exec_config)

        if success and new_pub_key and new_wif_key:
            # Store keys globally for the web UI to access
            generated_keys = {"pub_key": new_pub_key, "wif_key": new_wif_key}
            add_progress_update("🎉 --- Key Rotation Completed Successfully! --- 🎉")
            add_progress_update("Witness node is now running with the new signing key.")
            add_progress_update("PROCESS_COMPLETE_SUCCESS")
        else:
            add_progress_update("❌ --- Key Rotation Failed --- ❌")
            add_progress_update("Check the logs above for specific error details.")
            add_progress_update("PROCESS_COMPLETE_FAILURE")

    except Exception as e:
        add_progress_update(f"❌ Unexpected error: {e}")
        add_progress_update("❌ --- Workflow Aborted --- ❌")
        add_progress_update("PROCESS_COMPLETE_FAILURE")

def monitor_node_sync(exec_config):
    """
    Monitors the node synchronization based on execution configuration.
    For Docker: monitors docker logs
    For Native: monitors log files or uses periodic RPC calls
    """
    if exec_config["use_docker"]:
        monitor_docker_logs()
    else:
        monitor_native_node_sync(exec_config)

def monitor_docker_logs():
    """
    Monitors the docker logs of the witness node and streams progress to the UI.
    Checks for reindexing progress and block sync status.
    """
    # Use Popen to have real-time access to the output stream
    process = subprocess.Popen(
        ["docker", "logs", "-f", witness_manager.NODE_NAME],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, # Redirect stderr to stdout to capture all logs
        text=True,
        bufsize=1, # Line-buffered
        universal_newlines=True
    )

    last_log_time = time.time()

    for line in iter(process.stdout.readline, ''):
        line = line.strip()
        if not line:
            # If there's no output for a while, just continue
            if time.time() - last_log_time > 5:
                # Check if the process is still running
                if process.poll() is not None:
                    add_progress_update("Log stream ended unexpectedly. Checking node status...")
                    break
                last_log_time = time.time()
            continue

        # --- Stream relevant logs to the Web UI ---
        # Only forward lines that indicate progress to avoid spamming the UI
        if "reindex" in line or "Got block" in line:
            add_progress_update(f"Node Log: {line}")
            last_log_time = time.time()

        # --- Check for completion conditions ---
        if "Done reindexing" in line:
            add_progress_update("✅ Reindexing complete. Node is synced.")
            process.terminate() # Stop watching logs
            return

        handle_block_match = re.search(r'handle_block.*Got block: #\d+.*time: (.*?)\s', line)
        if handle_block_match:
            block_time_str = handle_block_match.group(1)
            try:
                block_time = datetime.strptime(block_time_str, "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
                current_time = datetime.now(timezone.utc)
                time_difference = (current_time - block_time).total_seconds()

                # Consider synced if within 5 minutes of the present
                if abs(time_difference) < 300:
                    add_progress_update(f"✅ Node is synced. Latest block time: {block_time_str}")
                    process.terminate() # Stop watching logs
                    return
            except ValueError:
                continue # Ignore lines with malformed dates

    # If the loop exits, terminate the process just in case
    if process.poll() is None:
        process.terminate()

def monitor_native_node_sync(exec_config):
    """
    Monitors native node synchronization by checking RPC responses.
    Uses periodic get_info calls to check sync status.
    """
    add_progress_update("Monitoring native node sync via RPC calls...")

    max_attempts = 120  # 2 hours with 60-second intervals
    attempt = 0

    while attempt < max_attempts:
        try:
            # Build command to check node info
            check_command = witness_manager.build_cli_wallet_command(exec_config)
            check_input = "get_info\nquit\n"

            stdout, stderr = witness_manager.run_command(check_command, command_input=check_input, quiet=True)

            if "Underlying Transport Error" not in stderr:
                # Try to parse the response to check sync status
                if "head_block_time" in stdout:
                    # Look for head_block_time in the output
                    time_match = re.search(r'"head_block_time":\s*"([^"]+)"', stdout)
                    if time_match:
                        block_time_str = time_match.group(1)
                        try:
                            block_time = datetime.strptime(block_time_str, "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
                            current_time = datetime.now(timezone.utc)
                            time_difference = (current_time - block_time).total_seconds()

                            add_progress_update(f"Latest block time: {block_time_str} (diff: {int(time_difference)}s)")

                            # Consider synced if within 5 minutes of the present
                            if abs(time_difference) < 300:
                                add_progress_update("✅ Native node is synced.")
                                return
                        except ValueError:
                            pass

                # If we can connect but can't parse time, still report progress
                add_progress_update(f"Node responding to RPC calls (attempt {attempt + 1}/{max_attempts})")
            else:
                add_progress_update(f"Waiting for node to start (attempt {attempt + 1}/{max_attempts})")

        except Exception as e:
            add_progress_update(f"Error checking node status: {e}")

        time.sleep(60)  # Wait 60 seconds between checks
        attempt += 1

    add_progress_update("⚠️ Sync monitoring timed out, but continuing with workflow...")

# --- FLASK ROUTES (PROTECTED) ---

@app.route('/')
@auth.login_required
def index():
    """Renders the main page, requires login."""
    return render_template('index.html')

@app.route('/start', methods=['POST'])
@auth.login_required
def start_process():
    """Starts the key rotation process in a background thread."""
    global process_thread, generated_keys # Add generated_keys
    if process_thread and process_thread.is_alive():
        return jsonify({"status": "error", "message": "A process is already running."}), 400

    # MODIFIED: Clear keys from any previous run before starting
    generated_keys = {}

    data = request.json
    account_name = data.get('account_name')
    url = data.get('url')
    wif_key = data.get('wif_key')

    if not all([account_name, wif_key]):
        return jsonify({"status": "error", "message": "Account name and WIF key are required."}), 400

    process_thread = threading.Thread(
        target=run_key_rotation_process,
        args=(account_name, url, wif_key)
    )
    process_thread.start()

    return jsonify({"status": "success", "message": "Process started."})

@app.route('/progress')
@auth.login_required
def progress():
    """Streams progress updates to the client."""
    def generate():
        last_index = 0
        while True:
            if last_index < len(progress_updates):
                for update in progress_updates[last_index:]:
                    yield f"data: {update}\n\n"
                last_index = len(progress_updates)
            time.sleep(1)

    return Response(generate(), mimetype='text/event-stream')


# --- NEW SECURE ENDPOINT FOR KEYS ---
@app.route('/get-keys')
@auth.login_required
def get_keys():
    """Returns the generated keys from the last successful run."""
    global generated_keys
    if generated_keys:
        return jsonify({"status": "success", "keys": generated_keys})
    else:
        return jsonify({"status": "error", "message": "No keys available or process was not successful."}), 404

@app.route('/config')
@auth.login_required
def config_page():
    """Returns current execution configuration."""
    try:
        exec_config = witness_manager.load_execution_config()
        if exec_config:
            # Don't expose sensitive paths, just the execution mode
            safe_config = {
                "use_docker": exec_config.get("use_docker", True),
                "local_node": exec_config.get("local_node", True),
                "configured": True
            }
        else:
            safe_config = {"configured": False}

        return jsonify({"status": "success", "config": safe_config})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

@app.route('/reconfigure', methods=['POST'])
@auth.login_required
def reconfigure():
    """Triggers execution environment reconfiguration."""
    try:
        # This will prompt the user to reconfigure
        # Note: This is tricky in a web environment, might need a different approach
        return jsonify({"status": "info", "message": "Please run 'python3 witness_manager.py config' from the command line to reconfigure."})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

if __name__ == '__main__':
    print("Starting Witness Manager Web UI...")

    # Check if execution config exists, if not, provide guidance
    if not os.path.exists(witness_manager.EXECUTION_CONFIG_FILE):
        print("\n⚠️ No execution configuration found.")
        print("Please run the following command first to configure the execution environment:")
        print("python3 witness_manager.py setup")
        print("or")
        print("python3 witness_manager.py config")
        print("\nThis will set up whether to use Docker or native binaries.")

        # Don't exit, but warn the user
        print("\n⚠️ Web UI will start but may not function properly until configured.")

    # For a more secure setup in a production environment,
    # consider using a proper WSGI server like Gunicorn or uWSGI
    # and a reverse proxy like Nginx.
    # The self-signed certificate is for local network encryption (HTTPS).
    app.run(host='0.0.0.0', port=5001, ssl_context='adhoc', debug=False)
