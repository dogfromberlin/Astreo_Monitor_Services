# Integrazioni e log

<a id="token"></a>
## Token per le integrazioni

Due indirizzi in **sola lettura**, protetti da un **token dedicato** (diverso dalla password della dashboard;
non apre nient'altro):

| Indirizzo | Formato | Per |
|---|---|---|
| `/metrics` | testo di Prometheus | Prometheus, Grafana, VictoriaMetrics |
| `/api/v1/status` | JSON piatto | Home Assistant (sensori REST), script |

Il token si genera in **Impostazioni → Moduli → Integrazioni**: viene mostrato una sola volta, generarne uno
nuovo invalida il precedente, **Revoca** disattiva le integrazioni. Si invia come `Authorization: Bearer <token>`.
Prova sul server (sostituisci `IL-TOKEN`):
```bash
curl -s --cacert /etc/astreo-monitor/astreo-ca.crt -H "Authorization: Bearer IL-TOKEN" https://127.0.0.1:5443/metrics | head
```

<a id="prometheus"></a>
## Prometheus e Grafana

```yaml
scrape_configs:
  - job_name: astreo
    scheme: https
    tls_config: { ca_file: /etc/prometheus/astreo-ca.crt }
    authorization: { credentials: IL-TOKEN }
    static_configs: [{ targets: ["192.0.2.10:5443"] }]
```
Metriche principali: `astreo_cpu_percent`, `astreo_memory_used_percent`, `astreo_disk_used_percent`,
`astreo_temperature_celsius`, `astreo_service_up`, `astreo_connectivity_status`, `astreo_connectivity_rtt_ms`,
`astreo_speedtest_download_mbps`, `astreo_backup_ok`, `astreo_disk_smart_status`,
`astreo_updates_security_pending`, `astreo_expiry_days`, `astreo_check_up`, `astreo_check_latency_ms`.

<a id="home-assistant"></a>
## Home Assistant

```yaml
rest:
  - resource: https://192.0.2.10:5443/api/v1/status
    headers: { Authorization: !secret astreo_token }   # secrets.yaml: astreo_token: "Bearer IL-TOKEN"
    verify_ssl: /config/astreo-ca.crt
    scan_interval: 60
    sensor:
      - { name: Server CPU, value_template: "{{ value_json.cpu_percent }}", unit_of_measurement: "%" }
      - { name: Server connessione, value_template: "{{ value_json.connection }}" }
      - { name: Server servizi fermi, value_template: "{{ value_json.services_down | length }}" }
```
Per le automazioni sugli avvisi usa il canale **Webhook** delle [notifiche](notifications.md#canali).

<a id="log"></a>
## Vista Log

Journal dei servizi monitorati e di Astreo Monitor (solo amministratore), filtrabile per servizio, periodo,
livello minimo e testo, con aggiornamento automatico ogni 10 secondi. Si possono leggere solo quei servizi.
L'utente dei servizi deve poter leggere il journal di sistema (di norma è nel gruppo `adm`); altrimenti:
```bash
sudo usermod -aG systemd-journal UTENTE
sudo systemctl restart astreo-monitor-web.service
```
