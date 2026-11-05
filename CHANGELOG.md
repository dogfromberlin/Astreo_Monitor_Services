# Changelog

## 4.2.0.dev2 — data from the agents and CPU/memory alerts, stage 2 of 3 (test build, not a Release)

- **Agents 4.2** (Linux and Windows) also send, every 6 hours, the **health of the disks** (Linux: SMART with `smartmontools`; Windows: health status, temperature and wear of the physical disks) and **pending updates** with reboot required (Linux: apt; Windows: Windows Update), and every 5 minutes the **Docker containers** if Docker is present. Older agents keep working without these data.
- Server detail of a connected server: new **Maintenance** panel with disks, updates, reboot and containers; the same data appears in *To check* and raises the *Disk health*, *System updates* and *Docker containers* alerts.
- **CPU and memory alerts**, off by default (Settings → Notifications → CPU and memory alerts): general thresholds (CPU 90/98%, memory 90/97%), per-server thresholds in *Settings of this server*, *Alert after* 15 and 10 minutes by default; for the central server the alert lists the three heaviest processes. The dashboard bars now follow the thresholds of each server.
- Windows agent: the scheduled task limit goes from 2 to 15 minutes (the Windows Update search can be slow).
- Database migration 0006 (CPU and memory thresholds in `hosts`), applied by `update.sh`.
- Guide: agents (data sent, maintenance), notifications (CPU and memory) (IT/EN).

## 4.2.0.dev1 — settings per server and alert delay, stage 1 of 3 (test build, not a Release)

- **Alert after (minutes)** in every alert rule (Settings → Notifications): the alert is sent only if the problem lasts at least that many minutes in a row; if it clears earlier nothing is sent, not even the recovery. Useful for short line drops (e.g. Connection at 3 minutes) and services that restart by themselves. The dashboard and the history still show every problem. Default 0 = as before.
- **Settings of a server** (button in the server detail, or *Thresholds and alerts* in Settings → Connected servers): disk and temperature thresholds per server, including the central one; for connected servers also *Alert when unreachable* (off: a switched-off server shows as grey *off* information and sends no alerts) and minutes without data before it counts as unreachable. Empty fields use the general settings.
- Database migration 0005 (new columns in `hosts`), applied by `update.sh`.
- Guide: alert rules, settings of a server, connection (IT/EN).

## 4.1.0 — new front end

- **New look**: side menu with the new "Orbita Classica" logo, **light and dark theme** (follow the system, light or dark; saved per user and applied before the page is drawn), fonts Space Grotesk, Inter and JetBrains Mono, new favicon and app icons (the large app icons are provisional).
- **Overview** is the new start page: status in one sentence, key numbers (servers, services, 7-day connection availability, last backup), a **To check** list with suggested actions (open the server, *Stop checking it* for a service that is no longer needed), one card per server, connection, data safety and latest events; the number of things to check is shown next to Overview in the menu.
- **Sections**: Overview, Server (list of servers and detail with breadcrumb, resources, history, services, disks, maintenance and checks, modules, processes and sensors), Network and connection (public IP, speedtest and IP changes at the top), Devices, Alerts and events (events of all servers with filters by period, server, type and severity; notifications sent), Backup (data safety for everyone; last backup, copies and run now for the administrator), Logs, Terminal, Settings. Links such as `#impostazioni/dispositivi` open a settings tab directly.
- **Customise**: in the Overview and in the server detail, cards can be dragged (mouse or finger), moved with arrows and hidden; reset order, show hidden cards. The layout is saved per user, the same on computer and phone; the status strip and *To check* stay at the top.
- **Search** with **Ctrl K** (⌘ K on Mac): sections, servers, services, devices, settings tabs, guide pages and chapters, quick commands (theme, guide, customise).
- **Phones**: bottom bar with four views and **More** for the others, search and theme in the top bar, larger touch areas.
- New API: `GET /api/v1/overview`, `GET/PUT /api/v1/ui/prefs` (theme and layout; also allowed to the read-only user, for their own preferences only), `GET /api/v1/help-search`. Preferences are stored in `monitor_state`: no database migration.
- **Fixes**: a service removed from a connected server disappears immediately from the Overview, the Server view and the alerts, without waiting for the agent's next data; several scripts can now react to the same view (before, only the last one registered ran when opening it).
- Guide (IT/EN): Overview, To check, theme, customise, search and the new sections; README updated.

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
