# Systemd Setup for Gruenbeck Data Collector

This guide explains how to set up the Gruenbeck data collector as a systemd service with a timer.

## Prerequisites

- The Gruenbeck data collector repository is cloned to your local machine
- The virtual environment is set up (run `bash init_venv.sh` if not already done)
- The config.json file is properly configured

## Customizing User and Paths

The systemd service file needs to be customized with your specific user and installation path. A setup script is provided to make this process easy:

```bash
# Generate the service file with default values (current user and current directory)
./setup_systemd.py

# Or specify custom values
./setup_systemd.py --user your_username --install-path /path/to/gruenbeck
```

The script will generate a customized service file and print the next steps for installation.

## Installation Steps

1. Generate the customized service file as described above

2. Copy the service and timer files to the systemd user directory:

```bash
mkdir -p ~/.config/systemd/user/
cp gruenbeck-collector.service ~/.config/systemd/user/
cp gruenbeck-collector.timer ~/.config/systemd/user/
```

2. Reload the systemd daemon to recognize the new files:

```bash
systemctl --user daemon-reload
```

3. Enable and start the timer:

```bash
systemctl --user enable gruenbeck-collector.timer
systemctl --user start gruenbeck-collector.timer
```

4. Verify the timer is active:

```bash
systemctl --user list-timers gruenbeck-collector.timer
```

## System-wide Installation (Alternative)

If you prefer to run the service system-wide (as a system service rather than a user service), follow these steps instead:

1. Edit the service file to use an appropriate system user (e.g., replace `User=resux` with a system user that has appropriate permissions)

2. Copy the service and timer files to the systemd system directory (requires sudo):

```bash
sudo cp gruenbeck-collector.service /etc/systemd/system/
sudo cp gruenbeck-collector.timer /etc/systemd/system/
```

3. Reload the systemd daemon:

```bash
sudo systemctl daemon-reload
```

4. Enable and start the timer:

```bash
sudo systemctl enable gruenbeck-collector.timer
sudo systemctl start gruenbeck-collector.timer
```

5. Verify the timer is active:

```bash
sudo systemctl list-timers gruenbeck-collector.timer
```

## Managing the Service

### Running the Service Manually

To run the data collector manually (outside of the scheduled time):

```bash
# For user service
systemctl --user start gruenbeck-collector.service

# For system service
sudo systemctl start gruenbeck-collector.service
```

### Checking Service Status

To check the status of the service:

```bash
# For user service
systemctl --user status gruenbeck-collector.service

# For system service
sudo systemctl status gruenbeck-collector.service
```

### Viewing Logs

To view the logs from the service:

```bash
# For user service
journalctl --user -u gruenbeck-collector.service

# For system service
sudo journalctl -u gruenbeck-collector.service
```

### Stopping or Disabling the Timer

If you need to stop the timer temporarily:

```bash
# For user service
systemctl --user stop gruenbeck-collector.timer

# For system service
sudo systemctl stop gruenbeck-collector.timer
```

To disable the timer completely:

```bash
# For user service
systemctl --user disable gruenbeck-collector.timer

# For system service
sudo systemctl disable gruenbeck-collector.timer
```

## Benefits of Using Systemd

Using systemd instead of cron offers several advantages:

1. **Better logging**: All output is captured in the systemd journal
2. **Dependency management**: The service can be configured to start after network is available
3. **Failure handling**: Systemd can be configured to restart the service on failure
4. **Persistent timers**: If the system is off when the timer should run, it will run when the system comes back online
5. **Better monitoring**: Easy to check status and logs with systemctl commands
