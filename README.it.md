# Astreo Monitor

> 🇬🇧 English version: [README.md](README.md)

Monitoraggio del server **astreo**: dashboard web in HTTPS (anche da smartphone), terminale web, API REST e job periodici che
salvano su SQL Server metriche di sistema, temperature, speedtest IP pubblico e backup notturno dei database,
con notifiche email solo al cambio di stato.

Versione 2.0: riscrittura completa della 1.x (`pws/`), vedi
[docs/architettura.md](docs/architettura.md) per le differenze.

## Funzionalità

| Funzionalità | Cosa fa | Documentazione |
|---|---|---|
| Dashboard e API | Pagina web a tre viste (Server, Connessione, Impostazioni), API REST | [dashboard-e-api.md](docs/dashboard-e-api.md) |
| Connessione (ex NetPulse) | Andamento, qualità e confronto della connessione; API per il widget Windows | [connessione.md](docs/connessione.md) |
| Impostazioni | Speedtest, notifiche (email, regole, fascia di silenzio) e servizi dalla dashboard | [impostazioni.md](docs/impostazioni.md) |
| Terminale | Shell nel browser via HTTPS, con seconda password e sessione a scadenza | [terminale.md](docs/terminale.md) |
| Servizi | Servizi systemd monitorati, scelti dalla dashboard, con avviso se si fermano | [servizi.md](docs/servizi.md) |
| Metriche e temperature | CPU (media esatta), load, RAM, disco, sensori ogni 5 minuti | [metriche-e-temperature.md](docs/metriche-e-temperature.md) |
| Speedtest | Download, upload, latenza ogni 4 ore con soglie | [speedtest.md](docs/speedtest.md) |
| Controllo continuo | Ping al minuto verso router e Internet, interruzioni e disponibilità | [connessione.md](docs/connessione.md) |
| Heartbeat esterno | Avviso da un servizio esterno se astreo si spegne o resta isolato | [heartbeat.md](docs/heartbeat.md) |
| Scadenze | Certificati HTTPS e token GitHub, con avviso a 15 e 3 giorni | [scadenze.md](docs/scadenze.md) |
| Salute del sistema | Dischi (SMART) e aggiornamenti di sicurezza / riavvio richiesto | [salute-del-sistema.md](docs/salute-del-sistema.md) |
| Certificato HTTPS | CA privata (mkcert): dashboard senza avvisi su PC e Android | [certificato.md](docs/certificato.md) |
| Moduli opzionali | Docker e Pi-hole: compaiono solo se presenti, visibilità configurabile | [moduli.md](docs/moduli.md) |
| Eventi sui grafici | Riavvii, interruzioni, cambi di IP, servizi, container, avvisi sulle linee del tempo | [eventi.md](docs/eventi.md) |
| Lingue | Italiano e inglese, selettore IT / EN nella dashboard | [traduzioni.md](docs/traduzioni.md) |
| Verifiche e diagnosi | Test prima dell'installazione, diagnosi dopo, controllo dello schema, GitHub Actions | [verifiche.md](docs/verifiche.md) |
| IP pubblico | Controllo ogni 15 minuti, storico e avviso al cambio | [ip-pubblico.md](docs/ip-pubblico.md) |
| Notifiche | Email, Telegram e WhatsApp a cambio di stato, instradabili per evento | [notifiche.md](docs/notifiche.md) |
| Database | Schema, script SQL, retention | [database.md](docs/database.md) |
| Backup database | Backup notturno verificato, compresso e copiato su GitHub, ripristino | [backup-database.md](docs/backup-database.md) |

Altri documenti:
[installazione e migrazione dalla 1.x](docs/installazione-e-migrazione.md),
[configurazione](docs/configurazione.md),
[operatività e diagnosi](docs/operativita.md),
[aggiornamento alla 2.2](docs/aggiornamento-2.2.md),
[aggiornamento alla 2.3](docs/aggiornamento-2.3.md),
[aggiornamento alla 2.3.1](docs/aggiornamento-2.3.1.md),
[aggiornamento alla 2.4](docs/aggiornamento-2.4.md),
[aggiornamento alla 2.5](docs/aggiornamento-2.5.md),
[aggiornamento alla 2.5.1](docs/aggiornamento-2.5.1.md),
[aggiornamento alla 2.6](docs/aggiornamento-2.6.md),
[aggiornamento alla 2.7](docs/aggiornamento-2.7.md),
[aggiornamento alla 3.0](docs/aggiornamento-3.0.md), [3.0.0b2](docs/aggiornamento-3.0b2.md),
[installazione guidata](docs/installazione-guidata.md) ([English](docs/en/installation.md)), [punti aperti](docs/roadmap.md).

## Struttura

```
astreo_monitor/
  config.py, db.py, notifier.py, logging_setup.py   moduli comuni
  settings.py, services_store.py                     impostazioni e servizi salvati nel DB
  collectors/   lettura dati locali (psutil, lm-sensors, systemctl)
  jobs/         job periodici (metrics, speedtest, public_ip, maintenance, db_backup, test_email)
  web/          Flask + waitress: dashboard e /api/v1
sql/            script di installazione, switch, pulizia, backup
deploy/         unit systemd, regola polkit, nginx per il widget NetPulse
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

Requisiti: Python 3.12, SQL Server raggiungibile, `lm-sensors` per le temperature, `zstd` e la CLI `gh` autenticata per i backup.
