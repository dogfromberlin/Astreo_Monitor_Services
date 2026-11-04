# Connection

The **Network and connection** view gathers three sources: the **continuous check** (ping every minute), the
periodic **speedtest** and the **public IP**. At the top: current public IP, last speedtest and, opening *Public IP
changes*, the address changes. The period (6 hours … 1 year or custom range) applies to all tabs;
**Export CSV** downloads the period's speedtest measurements.

<a id="continuo"></a>
## Continuous check (ping every minute)

`astreo-connectivity.timer`: 5 quick pings to the router (`gateway`) and to the Internet (default 1.1.1.1 and
8.8.8.8). **Availability** tab: availability %, outages with duration, latency and loss charts.

| State | Condition |
|---|---|
| DOWN | no Internet target replies; the message tells router/local network from line/provider |
| WARNING | loss above the threshold (20 %) or average latency above the threshold (100 ms) |
| OK | otherwise |

During an outage alerts cannot go out: **Connection restored after N min** arrives afterwards, with start and
duration. Targets and thresholds in **Settings → Speedtest → Continuous check**.

<a id="speedtest"></a>
## Speedtest

`astreo-speedtest.timer`, every 4 hours (00:05, 04:05 …). It uses Cloudflare's test endpoints: latency (median
of 5 requests), then download and upload with several parallel connections (defaults: 3 rounds, 4 connections,
25 MB download and 10 MB upload each, about 300 MB and 120 MB per run); the result is the median of the
successful rounds.

| State | Condition |
|---|---|
| OK | download and upload above the warning thresholds |
| WARNING | download or upload below the warning threshold |
| ALERT | below the alert threshold, or a measurement failed |
| DOWN | Cloudflare unreachable |

The initial thresholds (download 500 / 100, upload 200 / 50 Mbps) must be **adapted to your line** after a few
days of measurements, in **Settings → Speedtest**: with thresholds too high the state stays WARNING.
From the same tab: **Run now**, **Pause** (stays paused after a reboot too), measurement parameters.

<a id="schede"></a>
## Tabs of the view

| Tab | Content |
|---|---|
| Trend | speed and latency with thresholds, latest measurements with their result |
| Availability | continuous check: availability, outages, latency and loss per target |
| Quality | below-threshold episodes (consecutive measurements), total time, longest episode |
| Comparison | the chosen period against the previous one or the same period 7 or 30 days earlier |

<a id="ip"></a>
## Public IP

`astreo-publicip.timer`, every 15 minutes: it asks several services (checkip.amazonaws.com, api.ipify.org,
ifconfig.me) and accepts the value given by the majority. When it changes: alert, history row and event on the
charts. If the services disagree the check is skipped, with no false alarms.

<a id="netpulse"></a>
## NetPulse Windows widget (optional module)

If enabled at installation, nginx on port 8081 serves the APIs compatible with the NetPulse taskbar widget
(`/api/latest`, `/api/query`, `/api/health`), protected by the token in `/etc/astreo-monitor/netpulse_token`.
