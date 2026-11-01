# Installation

Requirements: **Ubuntu or Debian** with systemd, **Python 3.10+**, `sudo` access. SQL Server must already be
installed (Express is fine); PostgreSQL and SQLite are prepared by the installer.

## Install

```bash
git clone https://github.com/dogfromberlin/Astreo_Monitor_Services.git
cd Astreo_Monitor_Services
sudo bash install.sh
```

`install.sh` installs the base packages (python3-venv, zstd, smartmontools, ping), creates the Python
environment and starts the questions:

| Question | Default | Notes |
|---|---|---|
| Language | from `LANG` | dashboard, notifications, bot and command-line messages |
| Service user | whoever runs `sudo` | services do not run as root |
| Database | `sqlite` | `postgresql` (installed via apt if local) or `mssql` (existing instance: database and login are created) |
| HTTPS with nginx | yes | certificate from a private CA (mkcert); without HTTPS the dashboard works over HTTP with a warning and without the terminal |
| Server IPs and names | detected | written into the certificate |
| Web terminal | yes | HTTPS only; allowed networks detected from the interfaces (LAN, VPN) |
| Speedtest, backup, NetPulse | yes, yes, no | optional modules |
| Services to monitor | running ones that are recognised | editable later in Settings → Services |
| Passwords | — | dashboard and terminal (different) |

At the end: configuration in `/etc/astreo-monitor/config.ini`, answers in `/etc/astreo-monitor/install.ini`,
database schema created, services started and health check printed.

To avoid browser warnings with HTTPS, install the CA certificate on your devices: open
`https://<server>:<port>/astreo-ca.crt` and add it to the trusted root authorities (Windows: *Install
certificate → Current user → Trusted Root Certification Authorities*; Android: *Settings → Security →
Encryption & credentials → Install a certificate → CA certificate*).

## Update

```bash
sudo bash update.sh                     # from git
sudo bash update.sh /tmp/package.zip    # from a zip
```
Steps: code → libraries → checks (stops if they fail) → system files from templates → database migration →
restart → health check.

## Enable HTTPS and the terminal later

```bash
sudo bash update.sh --enable-https
```

## Files generated from templates

systemd units, nginx sites and the polkit rule are generated from `deploy/templates/` with the answers in
`install.ini`: **do not edit them by hand**. To change something edit `install.ini`, then:
```bash
sudo .venv/bin/python -m astreo_monitor.installer diff -v    # what would change
sudo .venv/bin/python -m astreo_monitor.installer apply      # apply
```

## Language of command-line messages

Taken from `ASTREO_LANG`, then from `language` in `install.ini`, then from the system `LANG`. Example:
`sudo ASTREO_LANG=en .venv/bin/python -m astreo_monitor.doctor`.
