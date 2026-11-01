# Security policy

Astreo Monitor runs with access to your server (service control, an optional web terminal, database
credentials), so security reports are taken seriously.

## Reporting a vulnerability

Please **do not open a public issue**. Use GitHub's private reporting instead:
**Security → Report a vulnerability** on this repository. Include the version, a description, and steps to
reproduce if possible. You will get an answer within a few days.

## Supported versions

Only the latest release receives security fixes.

## Hardening notes

- Expose the dashboard only to your LAN / VPN; use HTTPS (`sudo bash update.sh --enable-https`).
- The web terminal requires HTTPS, a separate password and an allowed network list.
- Keep `/etc/astreo-monitor/config.ini` readable only by the service user (the installer sets `600`).
- Run `sudo .venv/bin/python -m astreo_monitor.doctor` after every update.
