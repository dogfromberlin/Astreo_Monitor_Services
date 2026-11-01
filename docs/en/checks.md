# Checks of other devices and services

| Type | What it verifies |
|---|---|
| **Ping** | the device answers on the network (3 packets) |
| **TCP port** | a service is listening on a port |
| **Web page** | the URL answers with an expected code (default 200-399), optionally contains a text, and its HTTPS certificate is not about to expire |

Configure them in **Settings → Devices** (name, type, host or URL, port, interval ≥ 30 s, timeout, consecutive
failures before DOWN, expected codes, text, certificate check). **Test now** runs a check without saving it.

States: **OK**; **WARNING** (works, but certificate expiring or half of the pings lost); **DOWN** after the set
number of consecutive failures (default 2).

Shown in **Server → Devices and services** (status, latency, 24 h availability; click for history), as events on
the charts, in alerts (event *Devices and services*), in the Telegram `/checks` command and in the weekly summary.
Job `astreo_monitor.jobs.checks`, timer `astreo-checks.timer` (every minute).
