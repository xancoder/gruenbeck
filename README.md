# data collector - soft water system - Grünbeck

> This python script collects water consumption data from a "Grünbeck" soft water system and stores into csv file

## Getting Started

### clone git repository

```shell script
git clone https://github.com/xancoder/gruenbeck.git
```

### install dependencies into a virtual environment

```shell script
cd gruenbeck
bash init_venv.sh
```

### modify the config.json

The configuration file `./src/config.json` should be modified to your own needs and settings.

#### mail settings

The section `mail` configures the SMTP server used for the data mail and the error notifications:

| key | meaning |
|-----|---------|
| `smtpServer` | host name of the SMTP server |
| `smtpPort` | port of the SMTP server (number; a string like `"587"` is still accepted) |
| `smtpSecurity` | optional, `"ssl"` (implicit TLS, usually port 465) or `"starttls"` (usually port 587). If omitted, port 465 uses `ssl` and every other port uses `starttls` |
| `senderEmail`, `senderPassword` | login and sender address |
| `recipients` | list of recipient addresses |
| `subject` | subject of the data mail |

Temporary errors (connection lost, timeout, connection failed) are retried up to 3 times with a 5 seconds delay; permanent errors (wrong login, rejected sender or recipient) fail immediately.

### manually running

```shell script
./venv/bin/python3 ./src/data-collector.py -l
```

## Scheduling Options

### Option 1: Systemd Service (Recommended)

The script can be set up as a systemd service with a timer for better management, logging, and reliability.

First, generate a customized service file for your environment:

```shell script
# Generate with default values (current user and directory)
./setup_systemd.py

# Or customize with your specific values
./setup_systemd.py --user your_username --install-path /path/to/gruenbeck
```

Then install the service:

```shell script
# Install as a user service
mkdir -p ~/.config/systemd/user/
cp gruenbeck-collector.service ~/.config/systemd/user/
cp gruenbeck-collector.timer ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable gruenbeck-collector.timer
systemctl --user start gruenbeck-collector.timer
```

For detailed setup instructions and system-wide installation options, see [SYSTEMD_SETUP.md](SYSTEMD_SETUP.md).

### Option 2: Crontab (Legacy)

Alternatively, the script can be added to a cron job to store data automatically:

```shell script
crontab -e
```

Add the following line:

```shell script
0 16 * * MON cd /path/to/gruenbeck && ./venv/bin/python3 ./src/data-collector.py
```

In this example, the script starts every week on Monday at 16:00. The design decision on the weekly run is based on the 14-day memory of the soft water system. More frequent runs would cause more writes and less would leave less time in cause of failures.

NOTE: It is important that the soft water system has written the measurement of the day before 16:00. The default system starts this process around 12:00.
