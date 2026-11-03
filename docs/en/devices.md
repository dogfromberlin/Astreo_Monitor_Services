# Devices and services

Checks of other devices and services on the network or the Internet: router, NAS, printers, cameras, websites,
services on other computers.

<a id="tipi"></a>
## Check types

| Type | What it verifies | Examples |
|---|---|---|
| **Ping** | the device answers on the network (3 packets) | router, NAS, printer |
| **TCP port** | a service is listening on a port | SMB 445, SSH 22, a database |
| **Web page** | expected response code (default 200-399), optional text on the page, HTTPS certificate expiry | website, web panel, Home Assistant |

<a id="configurazione"></a>
## Configuration

**Settings → Devices**: name, type, host or address, port (TCP), every how many seconds (minimum 30), timeout,
**consecutive failures before alerting** (default 2: a single lost ping is not a failure) and, for web pages,
expected codes, text to look for, certificate verification and warning days.
**Test now** runs the check without saving it.

<a id="stati"></a>
## States

| State | When |
|---|---|
| OK | the check succeeds |
| WARNING | it succeeds, but with an anomaly: certificate expiring, half of the pings lost |
| DOWN | it fails for the set number of consecutive times |

<a id="dove"></a>
## Where they appear

- **Server → Devices and services**: state, latency, availability over the last 24 hours; a click opens the
  history (24 hours, 7 or 30 days).
- Events on charts, alerts (event **Devices and services**), the bot's `/checks` command, weekly summary.

`astreo-checks.timer` runs every minute; each check follows its own interval. Results kept for 90 days.
