# Configuration and users

<a id="file"></a>
## The configuration file

`/etc/astreo-monitor/config.ini`, created by the installer (reference template: `config.example.ini`).
Owned by the service user, permissions `600`: it contains the database credentials. Never put it in git.

Most options (thresholds, notifications, services, devices, backup…) are changed from the dashboard in
**Settings**: the file keeps database access, web server, terminal and initial values.

| Component | When it re-reads the file |
|---|---|
| Jobs (metrics, speedtest, backup…) | at every run |
| Dashboard and bot | at startup: after a change `sudo systemctl restart astreo-monitor-web.service astreo-telegram.service` |

<a id="sezioni"></a>
## Main sections

| Section | Keys | Notes |
|---|---|---|
| `[database]` | `engine` (`mssql`, `postgresql`, `sqlite`), `host`, `port`, `database`, `user`, `password`, `path` (SQLite) | application user with read/write permissions only; see [Database](database.md) |
| `[web]` | `host`, `port`, `username`, `password_hash`, `trusted_proxy`, `https_port`, `viewer_username`, `viewer_password_hash` | behind nginx: `host = 127.0.0.1` and `trusted_proxy = 127.0.0.1` |
| `[email]` | initial values | then from Settings → Notifications |
| `[services]` | `key = unit \| label` | initial list only; then from Settings → Services |
| `[metrics]`, `[speedtest]`, `[publicip]` | initial thresholds and parameters | — |
| `[backup]` | databases to save, local folder, GitHub repository, how many copies to keep | rclone destinations from Settings → Backup |
| `[terminal]` | `enabled`, `password_hash`, `session_minutes`, `allowed_networks` | see [HTTPS and terminal](https-terminal.md#terminale) |
| `[retention]` | days to keep per kind of data (`0` = forever) | see [Database](database.md#retention) |
| `[netpulse]` | `token_file` | only for the NetPulse Windows widget |

<a id="utenti"></a>
## Dashboard users

| User | Access |
|---|---|
| **Administrator** (`[web] username`) | everything |
| **Read-only** (`[web] viewer_username`, optional) | Server and Connection views; no Settings, Logs, Terminal, processes, service details, notification log or changes (403 from the server) |

```bash
sudo .venv/bin/python -m astreo_monitor.users list                  # current users
sudo .venv/bin/python -m astreo_monitor.users password              # change the administrator password
sudo .venv/bin/python -m astreo_monitor.users viewer family         # create or update the read-only user
sudo .venv/bin/python -m astreo_monitor.users viewer --remove       # remove it
```
Passwords are asked on the terminal and stored only as hashes; the dashboard restarts by itself.
The browser remembers credentials: to try the read-only user use a private window.
