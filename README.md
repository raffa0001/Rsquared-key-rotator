# Rsquared-key-rotator

R-Squared Witness Managemen

This is a comprehensive suite of tools designed to simplify the management of R-Squared witness nodes. It includes a command-line interface (CLI) for key rotation and witness node management, as well as a web-based UI for a more user-friendly experience.

Disclaimer: This project is currently under development and should be considered experimental. It may contain bugs and is subject to change. Use at your own risk.
Table of Contents

# Features

Automated Key Rotation: Securely rotate your witness signing keys.

Docker and Native Support: Flexibility to run your witness node in a Docker container or as a native process.

Web Interface: An easy-to-use web UI for managing your witness node, ideal for users who prefer a graphical interface.

Interactive CLI: A powerful command-line tool for more advanced users and automation.

Secure Credential Storage: Encrypts and securely stores your credentials.

# Prerequisites

Before you begin, ensure you have the following installed on your system:

    Python 3.6+

    Docker (if you plan to use the Docker-based setup)

    Git

# Installation

    Clone the repository:
    code Bash




    
git clone https://github.com/your-username/your-repository.git
cd your-repository

  

Install Python dependencies:
code Bash



    
pip install -r requirements.txt

  

(Note: You will need to create a requirements.txt file that includes Flask, Flask-HTTPAuth, and any other necessary libraries.)

Initial Setup:
Run the setup script to configure the execution environment (Docker or native) and create your initial credentials.
code Bash

    
    

        
    python3 witness_manager.py setup

      

# Usage

Command-Line Interface (CLI)

The witness_manager.py script is the main entry point for all command-line operations.

Available Commands:

    setup: Initial configuration of the witness manager.

    run: Execute a key rotation with your stored configuration.

    manual: Manually input your witness information for a one-time key rotation.

    config: Re-run the execution environment setup.

    docker-config: Create or edit the Docker launch configuration.

    show-docker-config: Display the current Docker configuration.

    uninstall: Remove all components of the witness manager.

Example:

To run a key rotation with your saved settings:
code Bash

    
python3 witness_manager.py run

  

# Web Interface

The web interface provides a user-friendly way to manage your witness node.

    Start the web server:
    code Bash

        
    python3 app.py


    Access the web UI:
    Open your web browser and navigate to https://127.0.0.1:5001.

    You will be prompted to log in with the credentials you created during the initial setup.

# Future Plans

I am actively working on improving this tool. Here are some of the planned features:

Nuitka/PyInstaller Compilation: I plan to investigate compiling 
the project with Nuitka or PyInstaller. 
This will create a standalone executable, making it more accessible to a 
wider range of users by simplifying the installation process.

Expanded Functionality: More features are planned to further 
simplify witness node management.

# Contributing

If you find this tool useful, vote for freedom-node!

