#!/usr/bin/env python3
import configparser
import sys
import os

# Defines the configuration file paths (runtime and development)
def find_config_file():
    """
    Determines the correct path to config.ini based on deployment location.
    Checks deployed path first, then development path, then current directory.
    """
    possible_paths = [
        # 1. Deployed path (Runtime: /opt/project/common/config.ini)
        "/opt/project/common/config.ini",
        # 2. Development path (Bakeoff: /src/common/config.ini)
        #    This uses the path relative to where this script is located.
        os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config.ini'),
        # 3. Fallback to current working directory
        './config.ini' 
    ]

    for path in possible_paths:
        if os.path.exists(path):
            return path

    return None

def get_param(section: str, key: str) -> str:
    """
    Function to safely retrieve a configuration value from config.ini.

    If the file or value cannot be found, a descriptive RuntimeError is raised.
    This function is intended for direct import into other Python modules.
    """
    config_file = find_config_file()

    if not config_file:
        raise FileNotFoundError(f"Configuration file (config.ini) not found at expected paths.")

    config = configparser.ConfigParser()
    config.read(config_file)

    try:
        # Use .get() to retrieve the string value
        return config.get(section, key)
    except (configparser.NoSectionError, configparser.NoOptionError) as e:
        raise RuntimeError(f"Could not retrieve value from {config_file}: {e}")

# ----------------------------------------------------------------------
# Command-line Execution Wrapper (Used by Bash/Subprocess)
# ----------------------------------------------------------------------
if __name__ == "__main__":
    # This block executes when the script is called directly (e.g., from Bash).
    if len(sys.argv) != 3:
        print("Error: Usage: python3 read_config.py <section> <key>", file=sys.stderr)
        sys.exit(1)

    section = sys.argv[1]
    key = sys.argv[2]

    try:
        # Call the reusable function and print the result to stdout
        value = get_param(section, key)
        print(value)
        sys.exit(0) # Success
    except (FileNotFoundError, RuntimeError) as e:
        # Print error message to stderr and exit with a non-zero code
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)