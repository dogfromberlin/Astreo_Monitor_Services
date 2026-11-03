# Operations and troubleshooting

<a id="diagnosi"></a>
## Installation health check

```bash
cd Astreo_Monitor_Services
sudo .venv/bin/python -m astreo_monitor.doctor
```
It checks configuration and permissions, database and schema, that the jobs wrote data recently, the dashboard
(running version and schema as seen by the dashboard), systemd services and timers, and that system files match
the templates. For every problem it prints the command to fix it. `update.sh` always runs it at the end.

Before installing a package it can be checked with `bash scripts/verifica.sh` (code, scripts, automated tests):
`update.sh` does it by itself and stops if the checks fail.

<a id="journal"></a>
## Logs from the terminal

Besides the [Logs view](integrations.md#log):
```bash
journalctl -u 'astreo-*' --since "1 hour ago" --no-pager          # all components, last hour
journalctl -u astreo-backup.service -n 50 --no-pager              # a single job
journalctl -u 'astreo-*' -p warning --since "7 days ago" --no-pager
journalctl -u astreo-monitor-web.service -f                       # live
```

<a id="job"></a>
## Running or pausing a job

```bash
sudo systemctl start astreo-backup.service           # run now
systemctl list-timers 'astreo-*' --no-pager          # next runs
sudo systemctl disable --now astreo-speedtest.timer  # pause (resume with enable --now)
```
Every job also accepts `--dry-run`: `.venv/bin/python -m astreo_monitor.jobs.db_backup --dry-run` checks without
doing anything.

<a id="problemi"></a>
## Common problems

| Symptom | Likely cause | Check |
|---|---|---|
| The page keeps asking for the password | password changed or wrong hash | `sudo .venv/bin/python -m astreo_monitor.users password` |
| *Database unavailable* | database stopped or wrong credentials | health check; `systemctl status mssql-server` or `postgresql` |
| No alerts | channel disabled, event not routed, quiet hours, no state change | Settings → Notifications: **Send test** and delivery log |
| Empty temperatures | `lm-sensors` missing | `sensors -j`; `sudo apt install lm-sensors` |
| Backup in ALERT | permissions, `gh` token, rclone destination unreachable | Settings → Backup; `jobs.db_backup --dry-run` |
| Connection always DOWN | ping not allowed to the service | health check (units generated from templates); `journalctl -u astreo-connectivity` |
| Docker module missing | service user not in the `docker` group | Settings → Modules, reason shown |
| Empty logs | system journal not readable | [Integrations and logs](integrations.md#log) |
| Terminal does not open | see the dedicated table | [HTTPS and terminal](https-terminal.md#problemi-terminale) |

<a id="disinstallare"></a>
## Uninstall

```bash
sudo systemctl disable --now 'astreo-*.timer' 'astreo-*.service'
sudo rm -f /etc/systemd/system/astreo-*.service /etc/systemd/system/astreo-*.timer /etc/polkit-1/rules.d/50-astreo-monitor.rules
sudo rm -f /etc/nginx/sites-enabled/astreo-monitor /etc/nginx/sites-enabled/netpulse && sudo systemctl reload nginx
sudo systemctl daemon-reload
```
Configuration, CA and database remain: delete them by hand (`/etc/astreo-monitor`, the database) only if no
longer needed.
