# Changelog

## 4.6.0.dev2 — UPS via SNMP and network search, stage 2 of 2 (test build, not a Release)

- **SNMP v2c source** for UPS units with a network card: standard UPS-MIB (RFC 1628: Eaton, Riello, Vertiv and others) with fallback to APC PowerNet-MIB. Minimal SNMP client in pure Python (GET only), no extra library.
- **Search the network** in *Add a UPS*: probes astreo's /24 and the server itself for NUT (3493), apcupsd (3551) and SNMP UPS units in 5-10 seconds, lists them with model and UPS names; **Use** fills in the form.

## 4.6.0.dev1 — UPS and power, stage 1 of 2 (test build, not a Release)

- **UPS of every major brand** through standard sources with a single data model (status, charge, runtime, load, voltages, temperature, model): **NUT** (Network UPS Tools: APC, Eaton, CyberPower, Riello, Vertiv, Tripp Lite, Salicru… connected to astreo, to a Synology/QNAP NAS or to any PC with NUT) and **apcupsd**. Sources are small interchangeable modules (`astreo_monitor/ups/`); SNMP comes in the next stage.
- New **Power** view: one card per UPS with charge, load, runtime, voltages, last blackout; charge and load trend (24 h, 7 d, 30 d); **Add a UPS** with **Find** (lists the UPS on a NUT server) and **Test**. Power card in the Overview.
- New alert event **UPS and power**: blackout (on battery) at once, low battery, power back with the blackout duration, battery to replace, overload, UPS unreachable (after 3 failed reads); blackout and power back also in the events, entries in *To check*, Telegram buttons and mutes as for every alert.
- Prometheus metrics `astreo_ups_*` with the `ups` label; blackouts of the week in the weekly summary.
- **No automatic shutdown**: Astreo only watches and alerts.
- New job `astreo-ups` (every minute); database migration 0012 (tables `ups_devices`, `ups_samples`, 90 days of history).
- Guide: new page *UPS and power*, with how to try everything without a UPS using NUT's `dummy-ups` driver (IT/EN).

## 4.5.0 — buttons under the Telegram alerts

- Telegram alerts carry buttons: **🔕 Mute 1 h** (service, server or event type of the alert), **▶ Start** for a stopped service of a connected server with commands allowed, **⚡ Switch on** for an unreachable server with a known MAC, **📊 Open** for the right page of the dashboard. After the tap the message is updated with the result; buttons answer only the configured chat and are valid for 48 hours.
- Database migration 0011 (`meta` in `notification_queue`: which alert a queued message belongs to).
- Guide: *Buttons under the alerts* in Notifications (IT/EN).

## 4.4.0 — mute for a while, disk full forecast, Wake-on-LAN

- **Mute alerts for a while** (30 minutes, 1, 2, 4 hours, until the next morning) for a service, a server, an event type or everything: **Mute** on each *To check* item and in the server detail, *Active mutes* in Alerts and events with **Resume**, Telegram `/silenzia` (`/mute`), `/silenzi` (`/mutes`), `/riattiva` (`/unmute`). Everything is still recorded; muted items show grey *muted until …* and do not count in the status sentence; when the mute ends, if the problem is still there, the alert is sent (respecting *Alert after*). The server detail shows the active mute with **Resume**, the Overview card a muted-bell icon.
- **Disk full forecast** from the last 14 days of the system disk of each server: *full in about N days* under the disk gauge and in the Overview cards, only for regular growth spread over the days (a one-off copy of large files does not trigger it); new alert event **Disk running out** (warning within the configurable days, 14 by default; alert under 3 days).
- **Switch a server on with Wake-on-LAN**: **Switch on** in the server detail and in the *To check* item, Telegram `/accendi` (`/wake`); agents 4.4 report MAC and IP of the main network card, which can be overridden in the server settings.
- **Fix, Windows agent**: with Docker installed but stopped, the agent stopped at every run (Windows PowerShell 5.1 treats a native command writing to stderr as a terminating error); external commands now never stop the agent, and any unexpected error is written to `agent.log` with line and message.
- Database migration 0010 (`wol_mac`, `wol_broadcast` in `hosts`).
- Guide (IT/EN): mute for a while, disk full forecast, switching a server on.

## 4.3.1 — agent update button always visible

- The server detail of a connected server always shows the agent button: *Update agent 4.2.0 → 4.3.1* when an update is possible, *Agent up to date* when it is already at the central version, and, when the update cannot start, a click explains why (permission *Allow updating the agent* off, agent not installed with `-AllowUpdate`, Linux agent, no data yet). Before, the button was simply hidden in those cases. The agent is never updated automatically.
- An agent installed with the first 4.3.0 test build knows the service commands but not the update: its refusal ("azione non ammessa") is now explained in the dashboard with what to do (reinstall it once by hand).

## 4.3.0 — commands to the services of connected servers, agent update from the dashboard, on-demand services

- **Start, stop and restart** the checked services of a connected server from the dashboard: services panel as a list of rows (full name, state on the right, **…** menu with the actions, lock for services protected by Windows), **Start** in *To check* for a stopped service. The command travels in the answer to the agent's data (no port opened on the agent) and starts within a minute; the result comes back as an event in the server history.
- **Two consents**: *Allow start, stop and restart* in the settings of the server, and the agent installed with `-AllowCommands` (Windows) or `--allow-commands` (Linux). The installation command of *New token* includes the options when the switches are on.
- **Signed commands**: RSA 2048 / SHA-256 with a key kept by the central server in `/etc/astreo-monitor/commands.key` (created by the installer, never in the database); the agent verifies with the public key received at installation over the pinned TLS. A command is valid for 10 minutes, bound to that agent, runs once and only for the checked services.
- **Update the Windows agent from the dashboard**: *Update agent to …* in the server detail (permission *Allow updating the agent* and `-AllowUpdate` on the agent); signed package with file hashes, syntax check, copy of the previous files. Linux agents: `install.sh --agent … --update` for now.
- **On-demand services**: chosen when the service is added (list of services with its box in *Settings → Connected servers* and *Add a server*; *On demand* column in Settings → Services for the central server). When stopped they are *idle*, with no alerts and no entry in *To check*.
- **Newly added services** show straight away as *waiting for the first check*, then *not detected* after 5 minutes, or *does not exist* for a wrong name (no alerts). The agent reports new services within a minute; **Refresh** makes the agent check again.
- **Settings → Connected servers** redesigned: one card per server, *Add a server* aligned on a two-by-two grid.
- Agents contact the central server every minute even with nothing to send; separate messages for "permission not given" and "command key missing"; failed commands logged as WARN; Docker installed but not running is shown as such without repeating errors.
- Form sections in Settings no longer grow wider than the page on narrower windows.
- Database migrations 0008 and 0009 (`allow_commands`, `allow_update`, `services_ondemand` in `hosts`; `ondemand` in `monitored_services`).
- Guide (IT/EN): commands to services, on-demand and newly added services, updating the agent from the dashboard.

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
