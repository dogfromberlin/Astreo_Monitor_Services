# System health

<a id="dischi"></a>
## Disks (SMART)

Every 6 hours a read-only service (root, no network) reads the disks' SMART data; Astreo evaluates it without
privileges (`astreo-smart-collect.timer` and `astreo-health.timer`).

| State | Condition |
|---|---|
| ALERT | SMART self-test failed, pending or uncorrectable sectors, media errors (NVMe) |
| WARNING | reallocated sectors, SSD wear above the threshold (80 %), disk temperature above the threshold (60 °C) |
| OK | otherwise |

Thresholds in **Settings → Notifications → Disks**. Full details on the server: `sudo smartctl -a /dev/sda`.

<a id="aggiornamenti"></a>
## System updates

Same check, every 6 hours: pending updates (with **security** ones counted separately) and **required reboot**.
WARNING if there are security updates or a reboot is needed; weekly reminder.
With Ubuntu's automatic updates enabled, security updates install by themselves: what remains to report is
mostly the required reboot.
```bash
sudo apt update && sudo apt upgrade
sudo reboot        # only if required
```

<a id="scadenze"></a>
## Expirations

Every day at 09:00 (`astreo-expiry.timer`): HTTPS certificates of the dashboard (and of the NetPulse widget) and
the GitHub token used for backups. WARNING at 15 days, ALERT at 3 (editable in **Settings → Notifications →
Expirations**), daily reminder, renewal notice.

<a id="rinnovo-token"></a>
## Renewing the GitHub token

1. On https://github.com/settings/personal-access-tokens: the token used for backups → **Regenerate token** →
   copy the new value.
2. On the server, as the service user:
   ```bash
   read -rsp 'Regenerated token: ' T; echo
   printf '%s' "$T" | gh auth login --hostname github.com --git-protocol https --with-token
   unset T
   gh auth status
   sudo systemctl start astreo-expiry.service
   ```

<a id="rinnovo-certificato"></a>
## Renewing the HTTPS certificate

The certificate signed by the private CA lasts about 2 years. The CA stays the same: nothing needs to be
reinstalled on the devices. Procedure in [HTTPS and terminal](https-terminal.md#rinnovo).
