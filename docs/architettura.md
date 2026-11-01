# Architettura

## Componenti

```
                 ┌───────────────────── <server> ─────────────────────┐
  Browser HTTPS ▶│ nginx :5443 ─▶ astreo-monitor-web (127.0.0.1:5025)│
  (e /terminal/) │ nginx :5443 ─▶ astreo-terminal (ttyd 127.0.0.1)   │
  (Basic Auth)   │   Flask: /  e  /api/v1/*                          │
                 │        │ legge in tempo reale: psutil, sensors,   │
                 │        │ systemctl (solo servizi in whitelist)    │
                 │        ▼                                          │
                 │   SQL Server astreo_monitor  ◀──────────────┐     │
                 │                                             │     │
                 │ timer systemd ──▶ job (oneshot) ────────────┘     │
                 │   astreo-metrics      ogni 5 min                  │
                 │   astreo-speedtest    ogni 4 ore (:05)            │
                 │   astreo-publicip     ogni 15 min                 │
                 │   astreo-maintenance  ogni notte alle 03:40       │
                 │   astreo-backup       ogni notte alle 02:30       │
                 │        │                                          │
                 │        ├──▶ SMTP (Gmail) solo a cambio di stato   │
                 │        └──▶ GitHub Releases (backup database)     │
                 └───────────────────────────────────────────────────┘
```

- **Web server** e **job** sono processi separati: un job lento (speedtest)
  non blocca mai la dashboard, e un errore in un job non ferma il web.
- I job non passano più da HTTP: li lancia systemd direttamente, senza root e
  senza password in chiaro.
- Configurazione unica in `/etc/astreo-monitor/config.ini`, fuori dal repo.
- Log unico su journald (`journalctl -u astreo-*`).

## Moduli

| Modulo | Responsabilità |
|---|---|
| `config.py` | Legge e valida il file INI, espone dataclass tipizzate |
| `db.py` | Connessioni brevi, query parametrizzate, tabella `monitor_state` |
| `notifier.py` | Invio email e `AlertState` (allarmi a cambio di stato) |
| `logging_setup.py` | Formato log unico su stdout |
| `collectors/system.py` | CPU, RAM, load, dischi, uptime, processi |
| `collectors/sensors.py` | Temperature da `sensors -j` (ripiego psutil) |
| `collectors/services.py` | `systemctl is-active` / `status` sulla whitelist |
| `jobs/base.py` | Argomenti comuni (`--config`, `--dry-run`, `--verbose`), lock |
| `jobs/*.py` | Un file per job |
| `web/app.py` | Route, autenticazione, gestione errori |
| `web/history.py` | Query aggregate a bucket per i grafici |
| `web/netpulse_compat.py` | API compatibili con il widget Windows NetPulse |
| `settings.py` | Impostazioni modificabili dalla dashboard (validazione, segreti) |
| `services_store.py` | Servizi monitorati salvati nel DB |
| `collectors/units.py` | Avvio/arresto delle sole unit di Astreo Monitor (polkit) |
