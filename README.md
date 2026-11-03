# Astreo Monitor

Self-hosted monitoring for a Linux home server: a web dashboard, alerts on email / Telegram / WhatsApp,
nightly database backups with restore checks, and a few extras you usually have to glue together yourself.

> 🇮🇹 Versione italiana: [README.it.md](README.it.md)
>
> 📖 Full guide in English and Italian: [docs/en/index.md](docs/en/index.md) · [docs/it/index.md](docs/it/index.md)

## Features

| Area | What you get |
|---|---|
| **Server** | CPU, load, memory, disk, temperatures, processes, partitions; history charts with **events** (reboots, outages, IP changes, service stops, alerts) drawn on the timeline |
| **Services** | Any systemd unit: running / stopped, alerts when it stops and restarts, start / stop from the dashboard |
| **Devices and services** | Ping, TCP port and web page checks for other devices (router, NAS, websites…) with history and alerts ([docs](docs/en/devices.md)) |
| **Connection** | Ping to router and Internet every minute (outages, availability), periodic speedtest with thresholds, public IP changes |
| **Health** | Disk SMART status, pending security updates and required reboots, certificate and token expirations |
| **Data safety** | Nightly database backup with verified copies to NAS, network folders or cloud (rclone) and/or a private GitHub repository, plus a **monthly restore test** ([docs](docs/en/backup.md)) |
| **Alerts** | Email, Telegram, WhatsApp (CallMeBot), ntfy, Gotify, Discord, webhook; per-check rules (only when it gets worse / every change, reminders, recovery), quiet hours, external heartbeat (healthchecks.io) |
| **Telegram bot** | `/status`, `/connection`, `/speedtest`, `/services`, `/checks`, `/help` |
| **Modules** | Docker containers and Pi-hole (v6): shown only if present on the server |
| **Integrations** | Prometheus `/metrics` and a JSON status for Home Assistant, protected by a dedicated token ([docs](docs/en/integrations.md)) |
| **Logs** | Journal of the monitored services in the dashboard, with filters |
| **Users** | Administrator and an optional read-only user ([docs](docs/en/configuration.md#utenti)) |
| **Web terminal** | Shell in the browser behind a separate password (HTTPS only) |
| **Weekly summary** | Every Monday morning |
| **Online help** | **?** icon in every section opens the guide at the right chapter, in the chosen language |
| **Languages** | English and Italian (dashboard, notifications, bot, installer) |

## Requirements

- Ubuntu or Debian with systemd, Python 3.10+
- Database: **SQLite** (nothing to install), **PostgreSQL** (installed for you if local) or **SQL Server** (existing instance, Express is fine)
- Optional: nginx for HTTPS (a private CA is created with mkcert), Docker, Pi-hole

## Install

```bash
git clone https://github.com/dogfromberlin/Astreo_Monitor_Services.git
cd Astreo_Monitor_Services
sudo bash install.sh
```
The installer asks a few questions (language, database, HTTPS, terminal, modules, passwords), prepares the
database, generates systemd units / nginx / polkit files from templates, starts the services and runs a
health check. Details: [docs/en/installation.md](docs/en/installation.md).

## Update

```bash
sudo bash update.sh                     # from git
sudo bash update.sh /path/package.zip   # from a zip
sudo bash update.sh --enable-https      # add nginx, certificate and terminal to an HTTP install
```
Code → libraries → automated checks (stops here if they fail) → system files → database migration →
restart → health check.

## Check an installation

```bash
sudo .venv/bin/python -m astreo_monitor.doctor
```

## Development

```bash
bash scripts/verifica.sh        # pyflakes, JavaScript syntax, ~150 tests
```
Tests run on SQLite locally and on SQLite, PostgreSQL and SQL Server in GitHub Actions.
Database schema changes go through Alembic migrations (`astreo_monitor/migrations/`).
Translations: `astreo_monitor/i18n/en.json` (keys are the Italian texts) — see [docs/en/development.md](docs/en/development.md).
How to contribute: [CONTRIBUTING.md](CONTRIBUTING.md) · Security issues: [SECURITY.md](SECURITY.md).

## License

[MIT](LICENSE) © 2026 Marco (dogfromberlin)
