# Integrations and logs

<a id="token"></a>
## Integrations token

Two **read-only** addresses protected by a **dedicated token** (not the dashboard password; it opens nothing
else):

| Address | Format | For |
|---|---|---|
| `/metrics` | Prometheus text | Prometheus, Grafana, VictoriaMetrics |
| `/api/v1/status` | flat JSON | Home Assistant (REST sensors), scripts |

Generate the token in **Settings → Modules → Integrations**: it is shown only once, generating a new one
invalidates the previous one, **Revoke** disables integrations. Send it as `Authorization: Bearer <token>`.
Test on the server (replace `THE-TOKEN`):
```bash
curl -s --cacert /etc/astreo-monitor/astreo-ca.crt -H "Authorization: Bearer THE-TOKEN" https://127.0.0.1:5443/metrics | head
```

<a id="prometheus"></a>
## Prometheus and Grafana

```yaml
scrape_configs:
  - job_name: astreo
    scheme: https
    tls_config: { ca_file: /etc/prometheus/astreo-ca.crt }
    authorization: { credentials: THE-TOKEN }
    static_configs: [{ targets: ["192.0.2.10:5443"] }]
```
Main metrics: `astreo_cpu_percent`, `astreo_memory_used_percent`, `astreo_disk_used_percent`,
`astreo_temperature_celsius`, `astreo_service_up`, `astreo_connectivity_status`, `astreo_connectivity_rtt_ms`,
`astreo_speedtest_download_mbps`, `astreo_backup_ok`, `astreo_disk_smart_status`,
`astreo_updates_security_pending`, `astreo_expiry_days`, `astreo_check_up`, `astreo_check_latency_ms`.

<a id="home-assistant"></a>
## Home Assistant

```yaml
rest:
  - resource: https://192.0.2.10:5443/api/v1/status
    headers: { Authorization: !secret astreo_token }   # secrets.yaml: astreo_token: "Bearer THE-TOKEN"
    verify_ssl: /config/astreo-ca.crt
    scan_interval: 60
    sensor:
      - { name: Server CPU, value_template: "{{ value_json.cpu_percent }}", unit_of_measurement: "%" }
      - { name: Server connection, value_template: "{{ value_json.connection }}" }
      - { name: Server services down, value_template: "{{ value_json.services_down | length }}" }
```
For automations on alerts use the **Webhook** channel of the [notifications](notifications.md#canali).

<a id="log"></a>
## Logs view

Journal of the monitored services and of Astreo Monitor (administrator only), filtered by service, period,
minimum level and text, with automatic refresh every 10 seconds. Only those services can be read.
The service user must be able to read the system journal (usually through the `adm` group); otherwise:
```bash
sudo usermod -aG systemd-journal USER
sudo systemctl restart astreo-monitor-web.service
```
