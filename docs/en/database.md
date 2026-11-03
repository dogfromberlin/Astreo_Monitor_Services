# Database

<a id="motori"></a>
## Supported databases

| Database | When to choose it | Notes |
|---|---|---|
| **SQLite** | simple installations, a single server | no service to install; one file |
| **PostgreSQL** | if you already use it or want a "real" database without licences | the installer installs it if it is on the same server |
| **SQL Server** | if you already have an instance (Express is fine) | the installer creates the database and the application login |

The application always uses a **dedicated user** with read/write permissions only; administrator credentials are
only needed to create and update the schema and are not stored.

<a id="migrazioni"></a>
## Schema and migrations

The schema is created and updated with automatic migrations (Alembic): `update.sh` runs them by itself.
```bash
.venv/bin/python -m astreo_monitor.migrate --status     # current and latest available revision
.venv/bin/python -m astreo_monitor.migrate              # update (asks for the administrator password)
.venv/bin/python -m astreo_monitor.schema               # check tables, columns and permissions
```
If the schema is not aligned, the dashboard shows a warning with the command to run.

<a id="tabelle"></a>
## Tables

| Table | Content |
|---|---|
| `system_metrics`, `system_temperature` | resources and temperatures, every 5 minutes |
| `speedtest_results`, `connectivity_samples`, `public_ip_history` | connection |
| `checks`, `check_results` | checked devices and services and their results |
| `events` | events shown on the charts |
| `monitored_services`, `app_settings` | monitored services and dashboard settings |
| `notification_log`, `notification_queue` | delivery log and alerts held by quiet hours |
| `monitor_state` | current state of the checks (key/value) |
| `alembic_version` | schema revision |

<a id="retention"></a>
## Data retention

Every night at 03:40 (`astreo-maintenance.timer`) data older than the days set in `[retention]` is deleted:

| Data | Key | Default |
|---|---|---|
| Resources, events | `metrics_days` | 365 days |
| Temperatures | `temperature_days` | 365 days |
| Speedtest | `speedtest_days` | forever (`0`) |
| Public IP | `publicip_days` | forever (`0`) |
| Connection check, devices | `connectivity_days` | 90 days |

The notification log is kept for 180 days, queued alerts for 30.
