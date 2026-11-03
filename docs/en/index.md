# Astreo Monitor — guide

Self-hosted monitoring for a Linux server at home or in a small office: web dashboard, alerts, database
backups and checks of other devices. This guide is also the dashboard's **online help** (**?** icon in the
sections).

<a id="pagine"></a>
## Pages

| Page | Content |
|---|---|
| [Installation and update](installation.md) | requirements, `install.sh`, `update.sh`, HTTPS, files generated from templates |
| [Configuration and users](configuration.md) | `config.ini`, passwords, read-only user |
| [The dashboard](dashboard.md) | views, settings, languages, smartphones |
| [Server](server.md) | resources, temperatures, processes, services, events on charts |
| [Connection](connection.md) | continuous check, speedtest, public IP |
| [Connected servers](agents.md) | Linux and Windows agents, overview, alerts |
| [Devices and services](devices.md) | ping, TCP port and web page checks |
| [Notifications](notifications.md) | channels, alert rules, quiet hours, heartbeat, Telegram bot, summary |
| [System health](health.md) | disks (SMART), updates, expirations |
| [Backup](backup.md) | nightly backup, rclone and GitHub copies, verification and restore |
| [Database](database.md) | SQL Server, PostgreSQL, SQLite, migrations, retention |
| [Modules](modules.md) | Docker and Pi-hole |
| [Integrations and logs](integrations.md) | Prometheus, Home Assistant, Logs view |
| [HTTPS and terminal](https-terminal.md) | certificate from a private CA, web terminal |
| [Operations and troubleshooting](operations.md) | health check, journal, common problems, uninstall |
| [Development](development.md) | architecture, tests, translations, contributing |

<a id="concetti"></a>
## Basic concepts

| Concept | Meaning |
|---|---|
| **Job** | periodic tasks (metrics, speedtest, backup…) run by systemd timers |
| **States** | `OK`, `WARNING`, `ALERT` or `DOWN`; alerts are sent on state changes, according to the rules |
| **Event** | something that happened (reboot, outage, stopped service…), marked on the charts |
| **Modules** | optional sections shown only if the service is present (Docker, Pi-hole) |
