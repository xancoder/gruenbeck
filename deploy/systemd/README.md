# Scheduling the Gruenbeck data collector

The collector (`src/data-collector.py`) should run once a week. This guide describes three ways:

| Way | Use it when |
|-----|-------------|
| [System service with timer](#system-service-recommended) | recommended: runs without a login, waits for the network, logs to the journal |
| [User service with timer](#user-service-alternative) | no root access, and the user stays logged in or lingering is enabled |
| [Cron](#cron-alternative) | systemd is not available |

The weekly run (Monday 16:00) follows the 14 day memory of the soft water system: more frequent
runs cause more writes, rarer runs leave less time to react to a failure. The run has to be
after the daily rollover of the soft water system. The rollover does not follow the device
clock: this device moves its values on every day at about 10:05 (measured with
`scripts/log_device_rollover.py`), so 16:00 is well after it. Before it writes anything,
the collector compares the new values with the days that are stored already. If they
differ, for example because a missed run that `Persistent=true` makes up in the morning
comes before the rollover, the run writes nothing and fails with an error mail; the next
weekly run collects the days again. The device clock (`D_C_4_2`) is only checked for a
warning in `log/gruenbeck_error.log` (missing, invalid or more than 15 minutes off).

The collector reports a failed run by its exit code (see the exit codes in the
[main README](../../README.md)), which systemd shows as failed unit state.

## Prerequisites

- The repository is cloned on the machine that runs the collector.
- The virtual environment exists in `./.venv` (`uv sync --no-dev`, see the
  [main README](../../README.md)); the unit calls `.venv/bin/python3`, so uv is not needed
  at run time. Create it as the user that runs the service, or make it readable for that user.
- `src/config.json` is configured. The collector reads it, writes `data/` and `log/` relative
  to the repository, so the user running the service needs read access to the repository and
  write access to `data/` and `log/`. The file contains the SMTP password: let the service user own it and
  restrict it with `chmod 600 src/config.json`.
- Run the commands below from the repository root.

## System service (recommended)

The service runs as a given user without any login; the timer starts it. The service itself
has no `[Install]` section, only the timer is enabled.

1. Generate the units. They are written to a new temporary directory, never into the
   repository (`--output-dir` chooses another directory outside of the repository):

   ```bash
   ./deploy/systemd/setup_systemd.py --user your_username --install-path /path/to/gruenbeck
   ```

   Without options the current user and this repository are used. Paths and user names must
   not contain whitespace or `%`.

2. Install the units with the commands printed by the script (the directory is the one the
   script reports):

   ```bash
   sudo install -m 644 -t /etc/systemd/system/ /tmp/gruenbeck-systemd-XXXX/gruenbeck-collector.service /tmp/gruenbeck-systemd-XXXX/gruenbeck-collector.timer
   sudo systemctl daemon-reload
   sudo systemctl enable --now gruenbeck-collector.timer
   ```

   Only the timer is enabled and started. Starting it does not run the collector.

3. Check that the timer is scheduled:

   ```bash
   systemctl list-timers gruenbeck-collector.timer
   ```

The service waits for `network-online.target`. With `Persistent=true` the timer runs a missed
Monday run right after the machine is back, so the run also happens after a weekend shutdown.

## User service (alternative)

Without root access the same units can be installed for the current user. Differences to the
system service:

- A user service has no `User=` setting and no `network-online.target`; delete both lines from
  the generated service. The collector then relies on its own retries (4 attempts, 5 seconds
  apart).
- A user service only runs while the user is logged in. To let the timer work without a login
  (like cron does) enable lingering once: `loginctl enable-linger "$USER"`.
- A missed run is made up directly after boot or login, possibly before the network is
  usable. If the retries are not enough, the run fails and is reported in the error mail and
  exit code; start it again with `systemctl --user start gruenbeck-collector.service`.

```bash
./deploy/systemd/setup_systemd.py --output-dir ~/gruenbeck-units
sed -i -e '/^User=/d' -e '/network-online.target/d' ~/gruenbeck-units/gruenbeck-collector.service
mkdir -p ~/.config/systemd/user/
cp ~/gruenbeck-units/gruenbeck-collector.service ~/gruenbeck-units/gruenbeck-collector.timer ~/.config/systemd/user/
loginctl enable-linger "$USER"
systemctl --user daemon-reload
systemctl --user enable --now gruenbeck-collector.timer
systemctl --user list-timers gruenbeck-collector.timer
```

The `--output-dir` must be outside of the repository. Use `systemctl --user` and
`journalctl --user` instead of `systemctl` and `journalctl` in the commands below.

## Managing the service

| Task | Command |
|------|---------|
| Run once now (outside of the schedule) | `sudo systemctl start gruenbeck-collector.service` |
| Status of the last run | `systemctl status gruenbeck-collector.service` |
| Logs of the service | `journalctl -u gruenbeck-collector.service` (add `sudo` if your user is not in the group `systemd-journal` or `adm`) |
| Next scheduled run | `systemctl list-timers gruenbeck-collector.timer` |
| Stop the schedule | `sudo systemctl disable --now gruenbeck-collector.timer` |
| Remove the units | `sudo rm /etc/systemd/system/gruenbeck-collector.service /etc/systemd/system/gruenbeck-collector.timer && sudo systemctl daemon-reload` |

The collector also writes warnings and errors to `log/gruenbeck_error.log` (relative to the
repository). The unit starts it without `-l`, so its log messages are in that file, not in
the journal.

## Cron (alternative)

```bash
crontab -e
```

```text
0 16 * * MON cd /path/to/gruenbeck && ./.venv/bin/python3 ./src/data-collector.py
```

Cron does not make up a run that was missed while the machine was off.

## Switching from cron to systemd

Remove the cron entry (`crontab -e`) when the timer is active. Otherwise the data is collected
and mailed twice. Check afterwards with `crontab -l` that the line is gone.
