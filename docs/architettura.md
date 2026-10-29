# Architettura

## Componenti

```
                 ┌───────────────────── astreo ─────────────────────┐
  Browser ──────▶│ astreo-monitor-web.service  (waitress :5025)     │
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
  senza password nel crontab.
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

## Cosa cambia rispetto alla 1.x

| Problema 1.x | Soluzione 2.0 |
|---|---|
| `pws.py` in `screen` + `tee`, due scrittori sullo stesso log | servizio systemd, log su journald |
| `curl` da root con password nel `/etc/crontab` | timer systemd come utente `<utente>` |
| Handler email aggiunti a ogni chiamata (memory leak) | un solo modulo `notifier`, nessun handler di logging che invia mail |
| Endpoint senza autenticazione, `/services` su qualsiasi unit | Basic Auth su tutto (tranne `/api/v1/health`), whitelist servizi |
| SQL costruito concatenando stringhe, `sys.exit` nella libreria DB | query parametrizzate, eccezioni gestite |
| Tabelle heap senza indici, campionamento `id % 10` | indici clustered su timestamp, aggregazione a bucket temporali |
| CPU: snapshot di 0,5 s ogni 15 min | media esatta dell'intervallo ogni 5 min, più load/RAM/disco |
| Speedtest: upload non attendibile, nessun avviso a connessione giù, mail a ogni run | Cloudflare multi-flusso, stato DOWN, mail solo a cambio di stato |
| IP pubblico: falso allarme se `curl` fallisce | più provider, validazione, maggioranza |
| Credenziali in git, log e `__pycache__` versionati | config fuori repo, `.gitignore` corretto |
| Bootstrap 4/5 mischiati, IP hardcoded nel JS | HTML/CSS propri, solo Chart.js, URL relativi |
