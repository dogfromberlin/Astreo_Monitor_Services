# Integrazioni: Prometheus, Grafana, Home Assistant

Due indirizzi in **sola lettura**, protetti da un **token dedicato** (diverso dalla password della dashboard;
non apre nient'altro):

| Indirizzo | Formato | Per |
|---|---|---|
| `/metrics` | testo di Prometheus | Prometheus, Grafana, VictoriaMetrics |
| `/api/v1/status` | JSON piatto | Home Assistant (sensori REST), script |

Il token si genera in **Impostazioni → Moduli → Integrazioni** (viene mostrato una sola volta; generarne uno
nuovo invalida il precedente; **Revoca** disattiva le integrazioni). Si invia come
`Authorization: Bearer <token>`. Prova (sul server):
```bash
curl -s --cacert /etc/astreo-monitor/astreo-ca.crt -H "Authorization: Bearer IL-TOKEN" https://127.0.0.1:5443/metrics | head
```

## Metriche principali (`/metrics`)

`astreo_cpu_percent`, `astreo_load1`, `astreo_memory_used_percent`, `astreo_disk_used_percent`,
`astreo_temperature_celsius{sensor}`, `astreo_service_up{unit,label}`, `astreo_connectivity_status`
(0 OK, 1 WARNING, 2 DOWN), `astreo_connectivity_rtt_ms{target,role}`, `astreo_connectivity_loss_percent`,
`astreo_speedtest_download_mbps` / `upload` / `latency_ms` / `timestamp_seconds`, `astreo_backup_ok`,
`astreo_backup_timestamp_seconds`, `astreo_disk_smart_status{device}`, `astreo_updates_security_pending`,
`astreo_reboot_required`, `astreo_expiry_days{name}`, `astreo_check_up{name,kind}`,
`astreo_check_latency_ms{name,kind}`, `astreo_info{version,hostname}`.

## Prometheus

```yaml
scrape_configs:
  - job_name: astreo
    scheme: https
    tls_config:
      ca_file: /etc/prometheus/astreo-ca.crt      # il certificato della CA scaricato dalla dashboard
    authorization:
      credentials: IL-TOKEN
    static_configs:
      - targets: ["192.0.2.10:5443"]
```
Grafana: aggiungi Prometheus come sorgente dati e costruisci i pannelli sulle metriche `astreo_*`.

## Home Assistant

In `configuration.yaml` (il certificato della CA va copiato nella cartella di configurazione di Home Assistant,
oppure usa `verify_ssl: false`):
```yaml
rest:
  - resource: https://192.0.2.10:5443/api/v1/status
    headers:
      Authorization: !secret astreo_token          # in secrets.yaml: astreo_token: "Bearer IL-TOKEN"
    verify_ssl: /config/astreo-ca.crt
    scan_interval: 60
    sensor:
      - name: Server CPU
        value_template: "{{ value_json.cpu_percent }}"
        unit_of_measurement: "%"
      - name: Server disco
        value_template: "{{ value_json.disk_percent }}"
        unit_of_measurement: "%"
      - name: Server connessione
        value_template: "{{ value_json.connection }}"
      - name: Server download
        value_template: "{{ value_json.speedtest.download_mbps }}"
        unit_of_measurement: "Mbit/s"
      - name: Server servizi fermi
        value_template: "{{ value_json.services_down | length }}"
```
Per reagire agli avvisi (automazioni) usa invece il canale **Webhook** delle notifiche, puntato a un
webhook di Home Assistant.

## Log dei servizi

Vista **Log** (solo amministratore): journal dei servizi monitorati e di Astreo Monitor, filtrabile per
servizio, periodo, livello e testo, con aggiornamento automatico. L'utente dei servizi deve poter leggere il
journal di sistema (di norma è nel gruppo `adm`); altrimenti:
```bash
sudo usermod -aG systemd-journal UTENTE
sudo systemctl restart astreo-monitor-web.service
```
