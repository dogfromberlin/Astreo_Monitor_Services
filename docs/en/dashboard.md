# The dashboard

It opens at the address shown at the end of the installation, usually `https://<server>:5443/`.

<a id="viste"></a>
## Views

| View | Content | Read-only user |
|---|---|---|
| **Server** | real-time resources, checks, services, devices, modules, processes, history with events | yes (without processes) |
| **Connection** | Internet connection trend, availability, quality and comparison | yes |
| **Settings** | speedtest, notifications, services, devices, backup, modules | no |
| **Logs** | service journal | no |
| **Terminal** | shell in the browser (HTTPS only) | no |

In the header: server name, uptime, public IP, last speedtest and last backup; below, the row of monitored
services (green running, red stopped).

<a id="impostazioni"></a>
## Settings

| Tab | What you set |
|---|---|
| Speedtest | timer status, run now, pause, thresholds, parameters, continuous connection check |
| Notifications | channels, alert rules, quiet hours, routing, heartbeat, expirations, disks, delivery log |
| Services | which systemd services to monitor, alert, label, order |
| Devices | checks of other devices and services |
| Backup | last backup, run now, rclone destinations |
| Modules | Docker, Pi-hole, integrations token, events on charts |

Changes apply immediately, no restarts. Secret values (passwords, tokens) are never shown: leave the field as
it is to keep them, type a new value to replace them.

<a id="lingua"></a>
## Language

**IT / EN** selector at the bottom of the page: it applies to the dashboard, notifications, Telegram bot and
weekly summary. Date and time fields follow the browser language instead.

<a id="avvisi-pagina"></a>
## Warnings on the page

| Warning | What to do |
|---|---|
| *Unencrypted connection* | open the HTTPS address, or enable HTTPS with `sudo bash update.sh --enable-https` |
| *Database needs updating* | run the migration shown (`python -m astreo_monitor.migrate`) |
| *The page is version …* | reload with Ctrl+F5 |

<a id="smartphone"></a>
## Smartphones and tablets

The dashboard adapts to the screen (view bar at the bottom). It can be installed as an app: Chrome on
Android, menu ⋮ → **Install app**; Safari on iPhone, Share → **Add to Home Screen**. With HTTPS the CA must be
installed on the phone first ([HTTPS and terminal](https-terminal.md#certificato)).
