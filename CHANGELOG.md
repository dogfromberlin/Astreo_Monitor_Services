# Changelog

## 4.3.0.dev1 — commands to the services of connected servers, stage 1 of 2 (test build, not a Release)

- **Start, stop and restart** the checked services of a connected server from the dashboard: buttons next to each service in the server detail, **Start** in *To check* for a stopped service. The command travels in the answer to the agent's data (no port opened on the agent), starts within a minute, and its result comes back as an event in the server history.
- **Two consents**: *Allow start, stop and restart* in the settings of the server, and the agent installed with `-AllowCommands` (Windows) or `--allow-commands` (Linux). Without the local consent the agent refuses every command.
- **Signed commands**: RSA 2048 / SHA-256 with a key kept by the central server in `/etc/astreo-monitor/commands.key` (created by the installer, never in the database); the agent verifies with the public key received at installation over the pinned TLS. A command is valid for 10 minutes, bound to that agent, runs once and only for the checked services.
- Agents now contact the central server every minute even with nothing to send, so commands arrive within a minute. Windows agent 4.3.0.
- Database migration 0008 (`allow_commands`, `allow_update` in `hosts`).
- Guide: *Commands to services* in Connected servers (IT/EN).

## 4.2.1 — alerts sent outside the database transactions

- **Outbox for alerts**: a check now only writes the alert into the queue, in the same transaction as the alert state, and the message is sent right after the transaction is committed. The sending (network, timeouts of up to 30 seconds per channel) no longer keeps rows of the database locked for the dashboard and the other jobs, also during an Internet outage.
- **Automatic retries**: a message not delivered is retried after 1, 2, 5, 15 and 30 minutes, by every job that runs; an alert raised during a line drop arrives as soon as the line is back, with the detection and sending times. Before, a failed alert was only retried if the problem was still there at the next check.
- **No duplicates**: the alert state and the queued message are saved together (both or neither), and each message is reserved before sending, so two jobs finishing at the same time cannot send it twice.
- **`update.sh` pauses the jobs** during the update: the `astreo-*` timers are stopped before the code is replaced (a job already running finishes its round) and resumed at the end, also if the update stops halfway. Before, jobs could run the new code on the old database schema while the migration waited for the `sa` password.
- **More detail in `Transazione lunga`**: time in queries (waiting for the database), number of statements, time spent outside the database with the transaction open, slowest query.
- The quiet hours keep their behaviour (one grouped message at the chosen time); test messages from the dashboard are still sent immediately.
- Database migration 0007 (column `quiet` in `notification_queue`), applied by `update.sh`.
- Guide: *How alerts are sent* in Notifications (IT/EN).

## 4.2.0 — settings per server, data from the agents, alert delay

- **Alert after (minutes)** in every alert rule (Settings → Notifications): the alert is sent only if the problem lasts at least that many minutes in a row; if it clears earlier nothing is sent, not even the recovery (e.g. Connection at 3 minutes for short line drops). The dashboard and the history still show every problem. Default 0 = as before.
- **Settings of a server** (button in the server detail, or *Thresholds and alerts* in Settings → Connected servers): disk, temperature, CPU and memory thresholds per server, including the central one; for connected servers also *Alert when unreachable* (off: a switched-off server shows as grey *off* information and sends no alerts) and minutes without data before it counts as unreachable. Errors are shown inside the window.
- **CPU and memory alerts**, off by default (Settings → Notifications): general thresholds (CPU 90/98%, memory 90/97%), per-server thresholds, *Alert after* 15 and 10 minutes by default; for the central server the alert lists the three heaviest processes.
- **Agents 4.2** (Linux and Windows) also send the **health of the disks** and **pending updates** with reboot required every 6 hours, and the **Docker containers** every 5 minutes; new **Maintenance** panel in the detail of a connected server, entries in *To check* and alerts. Older agents keep working without these data. Windows: the scheduled task limit goes from 2 to 15 minutes.
- **Telegram bot**: `/stato name` and `/servizi name` (also `/status`, `/services`; the beginning of the name is enough) show one connected server.
- **Prometheus metrics with the `host` label** on every series, and the metrics of the connected servers (CPU, memory, disk, uptime, temperature, services, updates, reboot, `astreo_host_up`). Queries that compare the exact label set need a review.
- **Weekly summary**: one section per connected server (data received, reboots, services stopped, peaks, updates).
- **Backup**: the copy on GitHub is optional and configured in Settings → Backup (repository, how many to keep, *Test GitHub*); `config.ini` only gives the initial values. New **«No backup off the server»** warning in the Overview and in *To check* while there is no copy on GitHub or rclone (the local copy does not count), with *Remind me later*, *Keep the warning* and *Do not show again*.
- **Fix: saving settings could take 30 seconds.** After saving, the dashboard read the language with a second database connection while the first one still held the changed rows of `app_settings`: on SQL Server the second connection waited until its 30-second timeout (and jobs reading the settings waited too). The language is now read before the save.
- **Slow requests and long transactions in the log** (`Richiesta lenta`, `Transazione lunga`, with the time spent waiting for the database), to find intermittent slowdowns such as the slow confirmation when saving settings.
- Database migrations 0005 and 0006 (new columns in `hosts`), applied by `update.sh`.
- Guide (IT/EN): alert rules, settings of a server, agents and maintenance, CPU and memory alerts, backup on GitHub and «no backup» warning, metrics, bot, weekly summary, slow dashboard.

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
