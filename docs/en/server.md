# Server

<a id="risorse"></a>
## Resources and history

The metrics job (`astreo-metrics.timer`, every 5 minutes) records CPU, load, memory, swap, disk and
temperatures. CPU is the **exact average** of the 5 minutes (from the system counters), not an instant.
Temperatures are read with `sensors -j` (package `lm-sensors`), otherwise with psutil.

The **Server** view shows real-time values and the **history** (24 hours, 7, 30, 90 days, 1 year or a custom
range): CPU and load, memory and disk, temperatures, connection speed.

| Alarm | Value | Default thresholds (`[metrics]`) |
|---|---|---|
| Temperature | highest among the sensors | WARNING 85 °C, ALERT 95 °C |
| Disk | root disk | WARNING 85 %, ALERT 95 % |

<a id="servizi"></a>
## Services

The systemd services to monitor are chosen in **Settings → Services** (all units of the server, with search):
**Monitor** shows them in the Server view and in the Overview, **Notify me** sends an alert when they stop and when
they start again, label and order decide how they appear.
Clicking a service in the Server view shows `systemctl status` (administrator only).

For OpenVPN the real unit is usually `openvpn-server@server.service`: `openvpn.service` always looks active.

<a id="controlli"></a>
## Maintenance and checks

At-a-glance status of: connection (ping), external heartbeat, expiring certificates and tokens, disks, updates,
restore check. Details in [Connection](connection.md), [Notifications](notifications.md#heartbeat) and
[System health](health.md).

<a id="eventi"></a>
## Events on charts

Coloured vertical lines when something happened; hover to read what. Below the charts there is the list of the
period's events, with filters by type (which apply to the charts too).

| Event | Where it comes from |
|---|---|
| Server reboot | detected boot (and the history of `last -x reboot`) |
| Connection outage | continuous connection check |
| Public IP change | IP history |
| Service stopped or restarted | monitored services |
| Container, Pi-hole | modules |
| Devices and services | checks of other devices |
| Speedtest below threshold, alert sent | results and notification log |

They can be hidden from **Settings → Modules → Events on charts**.

<a id="processi"></a>
## Processes

The processes using the most CPU, refreshed every 10 seconds (administrator only: command lines may contain
sensitive data).
