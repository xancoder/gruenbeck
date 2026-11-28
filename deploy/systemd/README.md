# Scheduling the Gruenbeck data collector

The collector (command `gruenbeck-collect`) should run once a week. This guide describes three
ways:

| Way | Use it when |
|-----|-------------|
| [System service with timer](#system-service-recommended) | recommended: runs without a login, waits for the network, logs to the journal |
| [User service with timer](#user-service-alternative) | no root access, and the user stays logged in or lingering is enabled |
| [Cron](#cron-alternative) | systemd is not available |

The weekly run (Monday 16:00) follows the 14 day memory of the soft water system: more frequent
runs cause more writes, rarer runs leave less time to react to a failure. The run has to be
after the daily rollover of the soft water system. The rollover does not follow the device
clock: this device moves its values on every day at about 10:05 (measured with
`gruenbeck-log-rollover`), so 16:00 is well after it. Before it writes anything,
the collector compares the new values with the days that are stored already. If they
differ, for example because a missed run that `Persistent=true` makes up in the morning
comes before the rollover, the run writes nothing and fails with an error mail; the next
weekly run collects the days again. The device clock (`D_C_4_2`) is only checked for a
warning in `log/gruenbeck_error.log` (missing, invalid or more than 15 minutes off).

The collector reports a failed run by its exit code (see the exit codes in the
[main README](../../README.md)), which systemd shows as failed unit state.

## Prerequisites

- The repository is cloned on the machine that runs the collector.
- The virtual environment exists in `./.venv` (`uv sync --no-dev --locked`, see the
  [main README](../../README.md); `--locked` keeps `uv.lock` of the checkout as it is). `uv sync` installs the command `.venv/bin/gruenbeck-collect`
  that the unit calls, so uv is not needed at run time. Create it as the user that runs the
  service, or make it readable for that user.
- `src/config.json` is configured. The collector reads it, writes `data/` and `log/` relative
  to the repository, so the user running the service needs read access to the repository and
  write access to `data/` and `log/`. The file contains the SMTP password: let the service user own it and
  restrict it with `chmod 600 src/config.json`.
- The folders `data/` and `log/` exist (`mkdir -p data log`) and belong to the service user. The
  service is [hardened](#hardening) and may write only there; it cannot create them itself, and
  a missing folder stops the start with `status=226/NAMESPACE` in the journal.
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
   not contain whitespace or `%`. The service may write to `<install-path>/data` and
   `<install-path>/log` only; if `dataPath` or the log file (`--log-error`) is somewhere else,
   name the folders with `--write-path` (see [Hardening](#hardening)).

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

## Hardening

The generated service limits what the collector can do, because it talks to the network and
runs unattended. It needs nothing but the network and write access to two folders:

| Setting | Effect |
|---------|--------|
| `TimeoutStartSec=30min` | a `Type=oneshot` service has no time limit otherwise; a run takes a few minutes at most, also with all retries of the device and the mail |
| `ProtectSystem=strict`, `ProtectHome=read-only` | the whole file system is read-only, `/home` too |
| `ReadWritePaths=` | the exceptions: the data folder and the log folder (default `<install-path>/data` and `<install-path>/log`) |
| `PrivateTmp`, `PrivateDevices` | own `/tmp`, no access to hardware devices |
| `NoNewPrivileges`, `CapabilityBoundingSet=` (empty), `RestrictSUIDSGID`, `LockPersonality`, `RestrictRealtime`, `RestrictNamespaces` | no privileges, no capabilities, no namespaces |
| `ProtectKernelTunables`, `ProtectKernelModules`, `ProtectKernelLogs`, `ProtectControlGroups`, `ProtectClock`, `ProtectHostname` | no change to the kernel, the clock or the host name |
| `RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX AF_NETLINK` | IP sockets for the device and the mail server; `AF_UNIX` and `AF_NETLINK` are used by the name resolution of the C library |
| `SystemCallArchitectures=native` | no system calls of other architectures |
| `SystemCallFilter=@system-service`, `SystemCallErrorNumber=EPERM` | only the system calls of an ordinary service; any other call fails with the error `EPERM` instead of killing the process |
| `ProtectProc=invisible`, `ProcSubset=pid` | `/proc` shows only the processes of the service and no kernel settings |
| `MemoryDenyWriteExecute=true`, `Environment=PYTHON_JIT=0` | no memory that is writable and executable. The JIT compiler of CPython needs such memory: switched on, it stops Python with `Fatal Python error: … Cannot allocate core JIT code`. It is off by default, and `PYTHON_JIT=0` keeps it off even with a Python built to switch it on |
| `UMask=0027` | new files are not readable for other users: a new yearly file, a new log file after a rotation. A yearly file that exists keeps its mode when it is written (`shutil.copymode`). If another user reads the data folder (e.g. a web server), give that user the group of the service user, or set `UMask=0022` in the generated service |

`ReadWritePaths=` is the only setting that depends on the installation. If the `dataPath` of
`src/config.json` or the log file (`--log-error`) is not below the install path, give every
folder the collector writes to with `--write-path`; the folders replace the default, so name
`data` and `log` too if they are still used:

```bash
./deploy/systemd/setup_systemd.py --install-path /path/to/gruenbeck \
    --write-path /srv/water/data --write-path /path/to/gruenbeck/log
```

The folders must exist when the service starts (see the prerequisites). Do not install the
repository below `/tmp` or `/var/tmp`: `PrivateTmp` hides them from the service.

Check the generated unit before installing it (the first command needs the install path to
exist, the second one rates the settings without starting anything):

```bash
systemd-analyze verify /tmp/gruenbeck-systemd-XXXX/gruenbeck-collector.service
systemd-analyze security --offline=true /tmp/gruenbeck-systemd-XXXX/gruenbeck-collector.service
```

The overall exposure level of the generated unit is 1.6 (`OK`; the scale goes from 0 to 10,
lower is better; measured with systemd 262, other versions weigh the settings a little
differently). What is left is what the collector needs or what costs more than it gives:
the network (`PrivateNetwork`, `IPAddressDeny`), the users of the system (`PrivateUsers`) and
the read access to `/home`, where the repository is. Whether the Raspberry Pi accepts every
setting shows only a run there: after installing, start the service once
(`sudo systemctl start gruenbeck-collector.service`) and look at `systemctl status` and the
journal. A status `218/CAPABILITIES` or `226/NAMESPACE` means that this system does not allow a
setting or that a folder in `ReadWritePaths=` is missing.

## SMTP password as credential

By default the SMTP password is in `src/config.json` (`mail.senderPassword`), a file in the
repository directory that the service user can read. A systemd credential keeps it out of the
repository: systemd reads a file that only root can access when it starts the service and gives
the service a private copy through `$CREDENTIALS_DIRECTORY/smtp-password`. The collector
prefers it to `senderPassword` (see [mail settings](../../README.md#mail-settings)).

1. Create the file once, owned by root and readable only by root (the password is not kept in
   the shell history or in the process list):

   ```bash
   sudo install -d -m 700 /etc/gruenbeck
   sudo bash -c 'umask 077; read -rsp "SMTP password: " password; printf "%s" "$password" > /etc/gruenbeck/smtp-password'
   ls -l /etc/gruenbeck/smtp-password
   ```

2. Generate the units with the file; the service then has the line
   `LoadCredential=smtp-password:/etc/gruenbeck/smtp-password`, and the password is not in the unit:

   ```bash
   ./deploy/systemd/setup_systemd.py --user your_username --install-path /path/to/gruenbeck \
       --smtp-password-file /etc/gruenbeck/smtp-password
   ```

   Install the units as above and run `sudo systemctl daemon-reload`.

3. Start the service once (`sudo systemctl start gruenbeck-collector.service`) and check that the
   data mail arrives. The log file now has the warning that `senderPassword` in the
   configuration file is ignored: remove the key (and keep `chmod 600 src/config.json`).

A credential that is empty or unreadable stops the run with a configuration error in the log
file; no error mail can be sent without the password. To change the password, write the file
again; the next start of the service uses it.

The same works for the configuration file: set `GRUENBECK_CONFIG` for the service to read a
configuration outside of the repository, for example with `sudo systemctl edit
gruenbeck-collector.service`:

```ini
[Service]
Environment=GRUENBECK_CONFIG=/etc/gruenbeck/config.json
```

Relative paths in that file (`dataPath`) start at its folder, so use absolute paths there and
name the data folder in `--write-path` when it is not below the install path (see
[Hardening](#hardening)).

## User service (alternative)

Without root access the same units can be installed for the current user. Differences to the
system service:

- A user service has no `User=` setting and no `network-online.target`; delete both lines from
  the generated service. The collector then relies on its own retries (by default 6 attempts
  over about 2.5 minutes, see `retries` and `retryDelay` in the main README).
- A user service only runs while the user is logged in. To let the timer work without a login
  (like cron does) enable lingering once: `loginctl enable-linger "$USER"`.
- `--smtp-password-file` works for a user service too, with a file that the user can read
  (`chmod 600`); the user manager loads it like the system manager does.
- The hardening settings stay in the service. They work for a user service only if the user
  manager of systemd can set up a user namespace (the transient test unit with these settings
  ran on the development machine, systemd 262). There a user service did not apply
  `ProtectProc` and `ProcSubset` (`/proc` stayed complete); the system call filter,
  `MemoryDenyWriteExecute` and `UMask` did apply. If the start fails with `status=218/CAPABILITIES`
  or `226/NAMESPACE`, delete the whole hardening block from the generated service:
  `sed -i '/^# Hardening/,$d' ~/gruenbeck-units/gruenbeck-collector.service` (the block is at the end).
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
0 16 * * MON cd /path/to/gruenbeck && ./.venv/bin/gruenbeck-collect
```

Cron does not make up a run that was missed while the machine was off.

## Switching from cron to systemd

Remove the cron entry (`crontab -e`) when the timer is active. Otherwise the data is collected
and mailed twice. Check afterwards with `crontab -l` that the line is gone.
