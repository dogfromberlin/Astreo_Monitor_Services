# Integrations: Prometheus, Grafana, Home Assistant

Two **read-only** addresses protected by a **dedicated token** (not the dashboard password; it opens nothing else):

| Address | Format | For |
|---|---|---|
| `/metrics` | Prometheus text | Prometheus, Grafana, VictoriaMetrics |
| `/api/v1/status` | flat JSON | Home Assistant REST sensors, scripts |

Generate the token in **Settings → Modules → Integrations** (shown once; a new one invalidates the old one;
**Revoke** disables integrations). Send it as `Authorization: Bearer <token>`.

Prometheus:
```yaml
scrape_configs:
  - job_name: astreo
    scheme: https
    tls_config: { ca_file: /etc/prometheus/astreo-ca.crt }
    authorization: { credentials: THE-TOKEN }
    static_configs: [{ targets: ["192.0.2.10:5443"] }]
```

Home Assistant (`configuration.yaml`):
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
For automations on alerts use the **Webhook** notification channel instead.

## Service logs

**Logs** view (administrator only): journal of the monitored services and of Astreo Monitor, filtered by service,
period, level and text, with auto-refresh. The service user must be able to read the system journal (usually via
the `adm` group; otherwise `sudo usermod -aG systemd-journal USER` and restart the dashboard).
