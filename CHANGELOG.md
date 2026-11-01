# Changelog

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
