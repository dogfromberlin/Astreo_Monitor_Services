# Installation and update

<a id="requisiti"></a>
## Requirements

- **Ubuntu or Debian** with systemd, **Python 3.10** or newer, `sudo` access.
- **Database**: SQLite (nothing to install), PostgreSQL (installed by the installer if on the same server) or
  SQL Server (an existing instance, Express is fine).
- Optional: nginx for HTTPS, Docker, Pi-hole, rclone for backup copies.

<a id="installare"></a>
## Install

```bash
git clone https://github.com/dogfromberlin/Astreo_Monitor_Services.git
cd Astreo_Monitor_Services
sudo bash install.sh
```

`install.sh` installs the base packages (python3-venv, zstd, smartmontools, ping), creates the Python
environment and asks the questions:

| Question | Default | Notes |
|---|---|---|
| Language | from `LANG` | dashboard, notifications, bot and command-line messages |
| Service user | whoever runs `sudo` | services do not run as root |
| Database | `sqlite` | `postgresql` or `mssql` (SQL Server: database and login are created) |
| HTTPS with nginx | yes | certificate from a private CA; without HTTPS the dashboard works over HTTP with a warning and without the terminal |
| Server IPs and names | detected | written into the certificate |
| Web terminal | yes | HTTPS only; allowed networks detected from the interfaces |
| Speedtest, backup, NetPulse | yes, yes, no | optional modules |
| Services to monitor | running ones that are recognised | editable later in Settings → Services |
| Passwords | — | dashboard and terminal, different |

At the end: configuration in `/etc/astreo-monitor/config.ini`, answers in `/etc/astreo-monitor/install.ini`,
database schema created, services started and health check printed.

With HTTPS, install the CA on your devices to avoid browser warnings: see
[HTTPS and terminal](https-terminal.md#certificato).

<a id="aggiornare"></a>
## Update

```bash
cd Astreo_Monitor_Services
sudo bash update.sh                       # from git
sudo bash update.sh /path/package.zip
```
Steps: code (with a zip, files the new version no longer contains are removed too) → libraries and pip →
automated checks (it stops before touching services and database if they fail) → system files from templates
→ schema migration (with SQL Server it asks for the `sa` password) → restart → health check.

Zip packages of every version are in the repository **Releases** on GitHub, with their SHA256.

<a id="https-dopo"></a>
## Enable HTTPS and the terminal later

```bash
sudo bash update.sh --enable-https
```

<a id="modelli"></a>
## Files generated from templates

systemd units, nginx sites and the polkit rule are generated from `deploy/templates/` with the answers in
`install.ini`: **do not edit them by hand**. To change something edit `install.ini`, then:
```bash
sudo .venv/bin/python -m astreo_monitor.installer diff -v    # what would change
sudo .venv/bin/python -m astreo_monitor.installer apply      # apply
```
An installation older than 3.0 is "adopted" with `sudo .venv/bin/python -m astreo_monitor.installer adopt`,
which derives the answers from the existing files.

<a id="lingua-terminale"></a>
## Language of command-line messages

From `ASTREO_LANG`, then `language` in `install.ini`, then the system `LANG`. Example:
`sudo ASTREO_LANG=en .venv/bin/python -m astreo_monitor.doctor`.
