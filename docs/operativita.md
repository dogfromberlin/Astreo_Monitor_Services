# Operatività e diagnosi

Tutti i comandi vanno lanciati nella **finestra SSH su astreo**.

## Stato generale

```bash
systemctl status astreo-monitor-web.service --no-pager
systemctl list-timers 'astreo-*' --no-pager
curl -s http://127.0.0.1:5025/api/v1/health
```

## Log

```bash
# tutti i componenti, ultima ora
journalctl -u 'astreo-*' --since "1 hour ago" --no-pager
# un singolo job
journalctl -u astreo-speedtest.service -n 50 --no-pager
# solo errori e avvisi degli ultimi 7 giorni
journalctl -u 'astreo-*' -p warning --since "7 days ago" --no-pager
# in tempo reale
journalctl -u 'astreo-*' -f
```

## Lanciare un job subito

```bash
sudo systemctl start astreo-metrics.service
sudo systemctl start astreo-speedtest.service
sudo systemctl start astreo-publicip.service
sudo systemctl start astreo-maintenance.service
sudo systemctl start astreo-backup.service
```

Oppure a mano, con log dettagliato e senza scrivere nulla:
```bash
cd ~/Astreo_Monitor_Services
.venv/bin/python -m astreo_monitor.jobs.speedtest --config /etc/astreo-monitor/config.ini --dry-run --verbose
```

## Sospendere un job

```bash
sudo systemctl stop astreo-speedtest.timer       # fino al prossimo riavvio
sudo systemctl disable astreo-speedtest.timer    # anche dopo il riavvio
sudo systemctl enable --now astreo-speedtest.timer   # riattivare
```

## Problemi frequenti

| Sintomo | Causa probabile | Verifica |
|---|---|---|
| La pagina chiede sempre la password | hash errato in `[web] password_hash` | rigenerare l'hash (vedi configurazione.md) |
| Storico: "Database non disponibile" | SQL Server fermo o password errata | `systemctl status mssql-server`, `curl .../api/v1/health` |
| Job in errore `Login failed` | password in `[database]` diversa da quella del login SQL | client SQL: `ALTER LOGIN astreo_monitor_app WITH PASSWORD = '...'` |
| Nessuna email | `notify = false`, credenziali Gmail, nessun cambio di stato | `jobs.test_email`, journal con `-p warning` |
| Temperature vuote | `lm-sensors` mancante | `sensors -j`; `sudo apt install lm-sensors` |
| Backup in ALERT | permessi su `/srv/sqlbackup`, token `gh`, database offline | `jobs.db_backup --dry-run`, `journalctl -u astreo-backup` |
| *Esegui ora* / *Sospendi* rispondono "manca la regola polkit" | regola non installata | [impostazioni.md](impostazioni.md), sezione permesso |
| Widget Windows senza dati | nginx 8081 non aggiornato o token errato | [connessione.md](connessione.md), verifica |
| Terminale non si apre | vedi tabella in [terminale.md](terminale.md) | `systemctl status astreo-terminal` |
| Avvisi non arrivano di notte | fascia di silenzio attiva: arrivano all'orario di recapito | Impostazioni → Notifiche |
| Web non parte | porta occupata o config errata | `journalctl -u astreo-monitor-web -n 30`, `sudo ss -tlnp | grep 5025` |

## Aggiornare il codice

```bash
cd ~/Astreo_Monitor_Services
git pull
.venv/bin/python -m pip install -r requirements.txt
sudo cp deploy/systemd/astreo-* /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl restart astreo-monitor-web.service
```
I job usano il nuovo codice dalla loro esecuzione successiva.

## Disinstallare

```bash
sudo systemctl disable --now astreo-monitor-web.service astreo-metrics.timer astreo-speedtest.timer astreo-publicip.timer astreo-maintenance.timer astreo-backup.timer
sudo rm /etc/systemd/system/astreo-*
sudo systemctl daemon-reload
```
