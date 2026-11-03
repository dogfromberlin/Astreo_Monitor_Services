# Changelog

## 4.0.2

- Windows agent: the certificate check now compiles on PowerShell 7.5 / .NET 9 too (`Add-Type -IgnoreWarnings`, warning SYSLIB0057). Windows PowerShell 5.1, used by the agent on Windows, was not affected; the failing test had blocked the 4.0.0 and 4.0.1 Releases.
- Partitions panel of a connected server: clear message when the agent is older than 4.0.1 and sends only the system disk.

## 4.0.1

- Agents send **all fixed disks** (Linux mount points, Windows drives C:, D: …), shown in the Partitions panel of the chosen server; the disk alert considers the fullest one and names it.
- The installation box in Settings → Connected servers shows **every step** for Linux or Windows (download, extract, administrator PowerShell, unblock, command, checks) with a link to the guide; the guide has the same steps, plus how to update an agent or use a new token.

## 4.0.0 — several servers in one dashboard

- **Connected servers**: other Linux and Windows servers send their data to this one through a lightweight agent — CPU, memory, swap, disk, uptime, temperatures (Linux), chosen services, reboots.
- **Linux agent** (`sudo bash install.sh --agent …`): Python, systemd timer every minute, hardened unit, no listening port.
- **Windows agent** (`install-agent.ps1`): native PowerShell 5.1, scheduled task as SYSTEM, no Python needed.
- **Security**: one token per server (only its hash stored), send-only, the agent verifies the central certificate with its CA (fingerprint checked at install), per-item validation, size and rate limits.
- **Local queue** on the agents: data kept up to 24 hours while the central server is unreachable.
- **Dashboard**: overview of all servers at the top of the Server view, chosen server with its resources, services and history; new **Settings → Connected servers** tab (add, installation command, services, new token, delete).
- **Alerts**: server unreachable (default 10 minutes), disk, temperature and stopped services per server, with the server name in the subject; `/status` in the bot lists the connected servers.
- Database migration 0004 (table `hosts`, column `host_id`); new timer `astreo-hosts.timer`.

## 3.6.0

- **Online help**: a **?** icon next to every section opens the guide at the relevant chapter in a side panel, in the chosen language; links between pages work inside the panel (with back); **Guide** in the footer opens the index. Pages come from `docs/<lang>/`, so the help always matches the installed version.
- New dependency: Markdown 3.10.3.
- Tests: every `data-help` reference must exist in both languages; all CSS variables must be defined.
- Mobile: the bottom bar fits any number of views on one row.

## 3.5.0

- **Complete guide in English and Italian**: 16 pages in `docs/en/` and `docs/it/` (same names), reviewed and updated to the current features; older single-language pages merged or removed.
- Stable anchors on every chapter, ready for the online help.
- New documentation test: same pages, chapters, anchors, tables and code blocks in both languages; internal links and references from code, templates and READMEs must exist.

## 3.4.1

- **Security**: updated dependencies with known vulnerabilities — waitress 3.0.2 (HTTP server), requests 2.33.0, Flask 3.1.3, pytest 9.0.3 (tests only).
- `update.sh` also upgrades pip in the virtual environment.
- GitHub checks run `pip-audit` on every push; Dependabot configured for weekly dependency updates.

## 3.4.0

- **Prometheus** endpoint `/metrics` and **Home Assistant** JSON status `/api/v1/status`, protected by a dedicated read-only token (Settings → Modules → Integrations).
- New **Logs** view (administrator only): journal of monitored services and of Astreo Monitor, filtered by service, period, level and text, with auto-refresh.

## 3.3.0

- **Backup copies with rclone** to one or more destinations (NAS/SMB, SFTP, Backblaze B2, S3, Google Drive…, or a mounted path), verified with `rclone check`, with per-destination retention.
- New **Settings → Backup** tab: last backup with the result of each destination, next run, "run backup now", destinations with a test button.
- A failed copy turns the backup into ALERT.

## 3.2.0

- **Checks of other devices and services**: ping, TCP port and web page (expected codes, text, certificate expiry), configured in Settings → Devices, with a "test now" button.
- New panel in the Server view with status, latency and 24 h availability; history dialog; events on charts; alerts (event "Devices and services"); Telegram `/checks`; weekly summary.
- Database migration 0003 (tables `checks`, `check_results`); new timer `astreo-checks.timer`.
- Fix: portable boolean comparisons (SQL Server rejected `IS 1`), with a test rule.

## 3.1.0

- New notification channels: **ntfy**, **Gotify**, **Discord** and a generic **webhook** (JSON POST), routable per event like the others.
- **Read-only user**: Server and Connection views only; settings, terminal, processes, service details and every change are blocked (HTTP 403).
- `python -m astreo_monitor.users`: change the administrator password, create or remove the read-only user.

## 3.0.2

- Schema check: SQL Server restore-test procedures are required only when the backup is enabled (fixes the SQL Server test in CI).
- `update.sh` with a zip package also removes files that the new version no longer contains.
- Installation check: remaining texts translated.

## 3.0.1

- Installation check: waits a few seconds for the dashboard after a restart instead of reporting it as down.
- Tests: personal-data check written so that history rewriting tools do not alter it.

## 3.0.0 — first public release

- **Databases**: SQL Server, PostgreSQL or SQLite through one data layer (SQLAlchemy); automatic schema
  migrations (Alembic); backup and monthly restore test for each database.
- **Installer**: `install.sh` (guided), `update.sh` (one-command update with automatic checks), system files
  generated from templates, `adopt` for existing installations, optional HTTPS with a private CA.
- **Languages**: English and Italian for dashboard, notifications, Telegram bot, weekly summary and
  command-line tools.
- **Monitoring**: server resources and history with events on charts, systemd services, connection (ping
  every minute, speedtest, public IP), disk SMART, system updates, certificate/token expirations,
  Docker and Pi-hole modules.
- **Alerts**: email, Telegram, WhatsApp; per-check rules, quiet hours, external heartbeat, weekly summary.
- **Tools**: installation check (`doctor`), schema check, ~150 automated tests run on three databases.
