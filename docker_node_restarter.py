#!/usr/bin/env python3
"""
Node Restarter Script
Reads current Docker container arguments, allows editing, and restarts with new parameters.
Keys are hidden in terminal display for security.
"""

import subprocess
import json
import sys
import getpass
import re
import os

# Configuration
NODE_NAME = "rsquared-node"
DOCKER_IMAGE = "ghcr.io/r-squared-project/r-squared-core:1.0.0"
DOCKER_NETWORK = "rsquared-net"

def run_command(command, capture_output=True):
    """Execute a shell command and return the result."""
    try:
        result = subprocess.run(command, capture_output=capture_output, text=True)
        return result.stdout.strip(), result.stderr.strip(), result.returncode
    except Exception as e:
        print(f"Error executing command: {e}")
        return "", str(e), 1

def get_container_info(container_name):
    """Get container information using docker inspect."""
    stdout, stderr, returncode = run_command(["docker", "inspect", container_name])

    if returncode != 0:
        print(f"Error: Could not inspect container '{container_name}'")
        print(f"Make sure the container exists. Error: {stderr}")
        return None

    try:
        return json.loads(stdout)[0]
    except (json.JSONDecodeError, IndexError) as e:
        print(f"Error parsing container info: {e}")
        return None

def parse_container_args(container_info):
    """Parse container arguments into a structured format."""
    if not container_info or "Config" not in container_info:
        return None

    args = container_info["Config"]["Cmd"]

    # The first argument is the executable (witness_node)
    executable = args[0] if args else "witness_node"
    parsed_args = {"executable": executable, "arguments": {}, "flags": []}

    i = 1
    while i < len(args):
        arg = args[i]

        if arg.startswith("--"):
            # Check if this is a flag with a value
            if i + 1 < len(args) and not args[i + 1].startswith("--"):
                # This is a key-value pair
                key = arg[2:]  # Remove --
                value = args[i + 1]
                parsed_args["arguments"][key] = value
                i += 2
            else:
                # This is a standalone flag
                parsed_args["flags"].append(arg[2:])
                i += 1
        else:
            i += 1

    # Also get mount information
    mounts = container_info.get("Mounts", [])
    parsed_args["mounts"] = mounts

    # Get port bindings
    port_bindings = container_info.get("HostConfig", {}).get("PortBindings", {})
    parsed_args["ports"] = port_bindings

    return parsed_args

def hide_sensitive_value(key, value):
    """Hide sensitive information in values."""
    sensitive_keys = ["private-key", "witness-id"]

    if key in sensitive_keys:
        if key == "private-key":
            # For private key arrays, show structure but hide actual keys
            if value.startswith('[') and value.endswith(']'):
                return '[***HIDDEN_PUB_KEY***,***HIDDEN_PRIVATE_KEY***]'
            return "***HIDDEN***"
        elif key == "witness-id":
            return "***HIDDEN_WITNESS_ID***"

    return value

def display_current_config(parsed_args):
    """Display current configuration with sensitive data hidden."""
    print("\n=== Current Container Configuration ===")
    print(f"Executable: {parsed_args['executable']}")

    print("\nArguments:")
    for key, value in parsed_args["arguments"].items():
        display_value = hide_sensitive_value(key, value)
        print(f"  --{key}: {display_value}")

    if parsed_args["flags"]:
        print("\nFlags:")
        for flag in parsed_args["flags"]:
            print(f"  --{flag}")

    print("\nMounts:")
    for mount in parsed_args["mounts"]:
        if mount["Type"] == "bind":
            print(f"  {mount['Source']} -> {mount['Destination']}")

    print("\nPort Bindings:")
    for container_port, host_bindings in parsed_args["ports"].items():
        for binding in host_bindings:
            host_port = binding["HostPort"]
            print(f"  {host_port} -> {container_port}")

def get_user_modifications(parsed_args):
    """Interactive menu to modify container arguments."""
    modified_args = {
        "arguments": parsed_args["arguments"].copy(),
        "flags": parsed_args["flags"].copy()
    }

    while True:
        print("\n=== Modification Menu ===")
        print("1. Add/Edit argument")
        print("2. Remove argument")
        print("3. Add flag")
        print("4. Remove flag")
        print("5. Update private key")
        print("6. Update witness ID")
        print("7. Show current config")
        print("8. Continue with restart")
        print("9. Cancel")

        choice = input("\nSelect option (1-9): ").strip()

        if choice == "1":
            key = input("Enter argument name (without --): ").strip()
            value = input(f"Enter value for --{key}: ").strip()
            modified_args["arguments"][key] = value
            print(f"Set --{key} = {value}")

        elif choice == "2":
            key = input("Enter argument name to remove (without --): ").strip()
            if key in modified_args["arguments"]:
                del modified_args["arguments"][key]
                print(f"Removed --{key}")
            else:
                print(f"Argument --{key} not found")

        elif choice == "3":
            flag = input("Enter flag name (without --): ").strip()
            if flag not in modified_args["flags"]:
                modified_args["flags"].append(flag)
                print(f"Added --{flag}")
            else:
                print(f"Flag --{flag} already exists")

        elif choice == "4":
            flag = input("Enter flag name to remove (without --): ").strip()
            if flag in modified_args["flags"]:
                modified_args["flags"].remove(flag)
                print(f"Removed --{flag}")
            else:
                print(f"Flag --{flag} not found")

        elif choice == "5":
            print("Enter new private key pair:")
            pub_key = getpass.getpass("Public key: ")
            priv_key = getpass.getpass("Private key: ")
            if pub_key and priv_key:
                modified_args["arguments"]["private-key"] = f'["{pub_key}","{priv_key}"]'
                print("Private key updated")
            else:
                print("Invalid input - both keys required")

        elif choice == "6":
            witness_id = input("Enter new witness ID: ").strip()
            if witness_id:
                # Ensure proper formatting
                if not witness_id.startswith('"'):
                    witness_id = f'"{witness_id}"'
                modified_args["arguments"]["witness-id"] = witness_id
                print("Witness ID updated")

        elif choice == "7":
            print("\n=== Modified Configuration ===")
            for key, value in modified_args["arguments"].items():
                display_value = hide_sensitive_value(key, value)
                print(f"  --{key}: {display_value}")
            if modified_args["flags"]:
                print("Flags:")
                for flag in modified_args["flags"]:
                    print(f"  --{flag}")

        elif choice == "8":
            return modified_args

        elif choice == "9":
            print("Operation cancelled")
            return None

        else:
            print("Invalid choice")

def build_restart_command(container_info, modified_args):
    """Build the docker run command with modified arguments."""

    # Extract original container configuration
    original_config = container_info["Config"]
    host_config = container_info["HostConfig"]

    command = ["docker", "run", "-d", "--name", NODE_NAME]

    # Add restart policy
    restart_policy = host_config.get("RestartPolicy", {}).get("Name", "no")
    if restart_policy != "no":
        command.extend(["--restart", restart_policy])

    # Add network
    network_mode = host_config.get("NetworkMode")
    if network_mode and network_mode != "default":
        command.extend(["--network", network_mode])

    # Add port bindings
    port_bindings = host_config.get("PortBindings", {})
    for container_port, host_bindings in port_bindings.items():
        for binding in host_bindings:
            host_port = binding["HostPort"]
            command.extend(["-p", f"{host_port}:{container_port}"])

    # Add volume mounts
    for mount in container_info.get("Mounts", []):
        if mount["Type"] == "bind":
            command.extend(["-v", f"{mount['Source']}:{mount['Destination']}"])

    # Add image
    command.append(DOCKER_IMAGE)

    # Add executable
    command.append("witness_node")

    # Add modified arguments
    for key, value in modified_args["arguments"].items():
        command.extend([f"--{key}", value])

    # Add flags
    for flag in modified_args["flags"]:
        command.append(f"--{flag}")

    return command

def restart_container(container_info, modified_args):
    """Stop current container and start with new configuration."""

    print(f"\nStopping container '{NODE_NAME}'...")
    run_command(["docker", "stop", NODE_NAME])
    run_command(["docker", "rm", NODE_NAME])

    # Build restart command
    restart_command = build_restart_command(container_info, modified_args)

    print("Restarting container with new configuration...")
    print("Command (with keys hidden):")

    # Display command with hidden sensitive data
    display_command = []
    hide_next = False
    for i, arg in enumerate(restart_command):
        if hide_next:
            if "--private-key" in restart_command[i-1]:
                display_command.append("[***HIDDEN_KEYS***]")
            elif "--witness-id" in restart_command[i-1]:
                display_command.append("***HIDDEN_ID***")
            else:
                display_command.append(arg)
            hide_next = False
        elif arg in ["--private-key", "--witness-id"]:
            display_command.append(arg)
            hide_next = True
        else:
            display_command.append(arg)

    print(" ".join(display_command))

    # Execute the restart
    stdout, stderr, returncode = run_command(restart_command)

    if returncode == 0:
        print(f"\nContainer '{NODE_NAME}' restarted successfully!")
        if stdout:
            print(f"Container ID: {stdout}")
    else:
        print(f"\nError restarting container: {stderr}")
        return False

    return True

def main():
    """Main function."""
    if len(sys.argv) > 1 and sys.argv[1] in ["-h", "--help"]:
        print("Usage: python3 node_restarter.py")
        print("Interactive script to modify and restart Docker witness node")
        return

    print("=== Docker Node Restarter ===")
    print(f"Looking for container: {NODE_NAME}")

    # Get current container info
    container_info = get_container_info(NODE_NAME)
    if not container_info:
        return

    # Check if container is running
    is_running = container_info["State"]["Running"]
    print(f"Container status: {'Running' if is_running else 'Stopped'}")

    # Parse current arguments
    parsed_args = parse_container_args(container_info)
    if not parsed_args:
        print("Error parsing container arguments")
        return

    # Display current configuration
    display_current_config(parsed_args)

    # Get modifications from user
    print("\nDo you want to modify the configuration?")
    if input("(y/N): ").lower() != 'y':
        print("No changes requested")
        return

    modified_args = get_user_modifications(parsed_args)
    if not modified_args:
        return

    # Confirm restart
    print("\nReady to restart container with new configuration")
    if input("Proceed? (y/N): ").lower() != 'y':
        print("Restart cancelled")
        return

    # Restart container
    if restart_container(container_info, modified_args):
        print("\nRestart completed successfully!")
    else:
        print("\nRestart failed!")

if __name__ == "__main__":
    main()
