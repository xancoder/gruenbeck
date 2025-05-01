#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import getpass
import os
import sys


def main():
    # Parse command line arguments
    parser = argparse.ArgumentParser(
        description="Generate systemd service file for Gruenbeck data collector"
    )
    parser.add_argument(
        "--user",
        help="User to run the service as (default: current user)",
        default=getpass.getuser(),
    )
    parser.add_argument(
        "--install-path",
        help="Path where the repository is installed (default: current directory)",
        default=os.path.abspath(os.path.dirname(__file__)),
    )
    parser.add_argument(
        "--output-dir",
        help="Directory to write the generated service file to (default: current directory)",
        default=os.path.abspath(os.path.dirname(__file__)),
    )
    args = parser.parse_args()

    # Read the template
    template_path = os.path.join(
        args.install_path, "gruenbeck-collector.service.template"
    )
    try:
        with open(template_path, "r") as f:
            template = f.read()
    except FileNotFoundError:
        print(f"Error: Template file not found at {template_path}")
        sys.exit(1)

    # Replace placeholders
    service_content = template.replace("{{USER}}", args.user)
    service_content = service_content.replace("{{INSTALL_PATH}}", args.install_path)

    # Write the generated service file
    output_path = os.path.join(args.output_dir, "gruenbeck-collector.service")
    try:
        with open(output_path, "w") as f:
            f.write(service_content)
        print(f"Service file generated at {output_path}")
    except Exception as e:
        print(f"Error writing service file: {e}")
        sys.exit(1)

    # Print next steps
    print("\nNext steps:")
    print("1. Copy the service and timer files to the systemd user directory:")
    print(f"   mkdir -p ~/.config/systemd/user/")
    print(f"   cp {output_path} ~/.config/systemd/user/")
    print(
        f"   cp {os.path.join(args.install_path, 'gruenbeck-collector.timer')} ~/.config/systemd/user/"
    )
    print("2. Reload the systemd daemon:")
    print("   systemctl --user daemon-reload")
    print("3. Enable and start the timer:")
    print("   systemctl --user enable gruenbeck-collector.timer")
    print("   systemctl --user start gruenbeck-collector.timer")
    print("\nFor system-wide installation and more details, see SYSTEMD_SETUP.md")


if __name__ == "__main__":
    main()
