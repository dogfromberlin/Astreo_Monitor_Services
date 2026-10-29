# Astreo Monitor

Monitoraggio del server **astreo**: dashboard web, API REST e job periodici che
salvano su SQL Server metriche di sistema, temperature, speedtest e IP pubblico,
con notifiche email solo al cambio di stato.

Versione 2.0: riscrittura completa della 1.x (`pws/`), vedi
[docs/architettura.md](docs/architettura.md) per le differenze.

## Funzionalità

| Funzionalità | Cosa fa | Documentazione |
|---|---|---|
| Dashboard e API | Pagina web con risorse in tempo reale, servizi, processi, storico | [dashboard-e-api.md](docs/dashboard-e-api.md) |
| Servizi | Stato dei servizi systemd in whitelist | [servizi.md](docs/servizi.md) |
| Metriche e temperature | CPU (media esatta), load, RAM, disco, sensori ogni 5 minuti | [metriche-e-temperature.md](docs/metriche-e-temperature.md) |
| Speedtest | Download, upload, latenza ogni 4 ore con soglie | [speedtest.md](docs/speedtest.md) |
| IP pubblico | Controllo ogni 15 minuti, storico e avviso al cambio | [ip-pubblico.md](docs/ip-pubblico.md) |
| Notifiche | Email a cambio di stato con promemoria | [notifiche.md](docs/notifiche.md) |
| Database | Schema, script SQL, retention | [database.md](docs/database.md) |

Altri documenti:
[installazione e migrazione dalla 1.x](docs/installazione-e-migrazione.md),
[configurazione](docs/configurazione.md),
[operatività e diagnosi](docs/operativita.md).

## Struttura

```
astreo_monitor/
  config.py, db.py, notifier.py, logging_setup.py   moduli comuni
  collectors/   lettura dati locali (psutil, lm-sensors, systemctl)
  jobs/         job periodici (metrics, speedtest, public_ip, maintenance, test_email)
  web/          Flask + waitress: dashboard e /api/v1
sql/            script di installazione, switch, pulizia, backup
deploy/systemd/ unit .service e .timer
docs/           documentazione per funzionalità
config.example.ini   modello di configurazione (quella reale è in /etc/astreo-monitor/)
```

## Avvio rapido (sviluppo)

```bash
cd ~/Astreo_Monitor_Services
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
export ASTREO_MONITOR_CONFIG=/etc/astreo-monitor/config.ini
.venv/bin/python -m astreo_monitor.jobs.metrics --dry-run
.venv/bin/python -m astreo_monitor.web --port 5026
```

Requisiti: Python 3.12, SQL Server raggiungibile, `lm-sensors` per le temperature.
