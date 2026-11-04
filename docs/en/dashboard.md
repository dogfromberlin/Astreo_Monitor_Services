# The dashboard

It opens at the address shown at the end of the installation, usually `https://<server>:5443/`.

<a id="viste"></a>
## Views

| View | Content | Read-only user |
|---|---|---|
| **Overview** | start page: status in one sentence, things to check, servers, connection, backup, latest events | yes (without actions) |
| **Server** | real-time resources, checks, services, devices, modules, processes, history with events | yes (without processes) |
| **Connection** | Internet connection trend, availability, quality and comparison | yes |
| **Settings** | speedtest, notifications, services, devices, backup, modules | no |
| **Logs** | service journal | no |
| **Terminal** | shell in the browser (HTTPS only) | no |

Views are chosen from the side menu (on the phone from the bar at the bottom). At the top of the **Server**
view: server name, uptime, public IP, last speedtest and last backup; below, the row of monitored services
(green running, red stopped).

<a id="panoramica"></a>
## Overview

It is the first page that opens, and it refreshes by itself every 30 seconds.

| Box | What it shows |
|---|---|
| Status | one sentence: *Everything is working*, *Everything is working · 1 thing to check* or *Attention*, with a summary of servers, services, connection and backup |
| Numbers | reachable servers, running services, connection availability over the last 7 days, time of the last backup |
| To check | the list below |
| Servers | one card per server: CPU, memory, fullest disk, temperature and services (stopped ones first); a click opens the server |
| Connection, Data safety, Latest events | last speedtest, latency and public IP; backup, copy and restore test; events of the last 24 hours |

The number next to **Overview** in the menu tells how many things there are to check.

<a id="da-controllare"></a>
## To check

It collects in one place what needs attention, most important first (**Urgent**, **Worth a look**, **Info**),
and empties itself when the problem is solved.

| What appears | When |
|---|---|
| server unreachable | the agent has sent no data for longer than the minutes set in *Connected servers* |
| service stopped | a checked service, on the central server or on an agent, is not running |
| disk or temperature | above the warning or alert thresholds |
| connection | Internet missing or degraded |
| backup | last backup failed, no backup for more than 36 hours, restore test failed |
| devices | a check does not respond or responds with a warning |
| expirations | certificates and tokens close to expiry |
| updates | security updates to install, reboot required |

Each item has the suggested action: open the server or the related view, or **Stop checking it** for a
service that is no longer needed (it removes it from the checked services; it can be enabled again in the
settings). The read-only user sees the items but not the actions that change something.

<a id="tema"></a>
## Light and dark theme

Switch at the top right: **follow the system** (default), **light** or **dark**. The choice applies to the
user, so it is the same on the computer and on the phone; the page starts straight away with the right theme.

<a id="impostazioni"></a>
## Settings

| Tab | What you set |
|---|---|
| Speedtest | timer status, run now, pause, thresholds, parameters, continuous connection check |
| Servers | servers connected through an agent, installation command, checked services, new token |
| Notifications | channels, alert rules, quiet hours, routing, heartbeat, expirations, disks, delivery log |
| Services | which systemd services to monitor, alert, label, order |
| Devices | checks of other devices and services |
| Backup | last backup, run now, rclone destinations |
| Modules | Docker, Pi-hole, integrations token, events on charts |

Changes apply immediately, no restarts. Secret values (passwords, tokens) are never shown: leave the field as
it is to keep them, type a new value to replace them.

<a id="aiuto"></a>
## Online help

The **?** icon next to each section title opens this guide at the relevant point, in a side panel and in the
chosen language; **Guide** at the bottom of the side menu opens the index. Links between pages are followed without
leaving the dashboard (← to go back). It is the same guide as `docs/` in the repository, always of the installed
version.

<a id="lingua"></a>
## Language

**IT / EN** selector at the bottom of the side menu (on the phone at the bottom of the page): it applies to the dashboard, notifications, Telegram bot and
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

The dashboard adapts to the screen: the side menu becomes the view bar at the bottom. It can be installed as an app: Chrome on
Android, menu ⋮ → **Install app**; Safari on iPhone, Share → **Add to Home Screen**. With HTTPS the CA must be
installed on the phone first ([HTTPS and terminal](https-terminal.md#certificato)).
