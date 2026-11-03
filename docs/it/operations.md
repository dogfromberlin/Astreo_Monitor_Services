# Operatività e diagnosi

<a id="diagnosi"></a>
## Diagnosi dell'installazione

```bash
cd Astreo_Monitor_Services
sudo .venv/bin/python -m astreo_monitor.doctor
```
Controlla configurazione e permessi, database e schema, che i job abbiano scritto dati di recente, la dashboard
(versione in esecuzione e schema visto dalla dashboard), servizi e timer systemd, e che i file di sistema
coincidano con i modelli. Per ogni problema stampa il comando per risolverlo. `update.sh` la esegue sempre alla fine.

Prima di installare un pacchetto si può controllarlo con `bash scripts/verifica.sh` (codice, script, test
automatici): `update.sh` lo fa da solo e si ferma se le verifiche falliscono.

<a id="journal"></a>
## Log dal terminale

Oltre alla [vista Log](integrations.md#log):
```bash
journalctl -u 'astreo-*' --since "1 hour ago" --no-pager          # tutti i componenti, ultima ora
journalctl -u astreo-backup.service -n 50 --no-pager              # un singolo job
journalctl -u 'astreo-*' -p warning --since "7 days ago" --no-pager
journalctl -u astreo-monitor-web.service -f                       # in tempo reale
```

<a id="job"></a>
## Lanciare o sospendere un job

```bash
sudo systemctl start astreo-backup.service           # esegue subito
systemctl list-timers 'astreo-*' --no-pager          # prossime esecuzioni
sudo systemctl disable --now astreo-speedtest.timer  # sospende (riattiva con enable --now)
```
Ogni job accetta anche `--dry-run`: `.venv/bin/python -m astreo_monitor.jobs.db_backup --dry-run` controlla
senza fare nulla.

<a id="problemi"></a>
## Problemi frequenti

| Sintomo | Causa probabile | Verifica |
|---|---|---|
| La pagina chiede sempre la password | password cambiata o hash errato | `sudo .venv/bin/python -m astreo_monitor.users password` |
| *Database non disponibile* | database fermo o credenziali errate | diagnosi; `systemctl status mssql-server` o `postgresql` |
| Nessun avviso | canale non attivo, evento non instradato, fascia di silenzio, nessun cambio di stato | Impostazioni → Notifiche: **Invia prova** e registro degli invii |
| Temperature vuote | `lm-sensors` mancante | `sensors -j`; `sudo apt install lm-sensors` |
| Backup in ALERT | permessi, token `gh`, destinazione rclone non raggiungibile | Impostazioni → Backup; `jobs.db_backup --dry-run` |
| Connessione sempre DOWN | ping non consentito al servizio | diagnosi (unit generate dai modelli); `journalctl -u astreo-connectivity` |
| Modulo Docker assente | utente dei servizi fuori dal gruppo `docker` | Impostazioni → Moduli, motivo indicato |
| Log vuoti | journal di sistema non leggibile | [Integrazioni e log](integrations.md#log) |
| Terminale non si apre | vedi la tabella dedicata | [HTTPS e terminale](https-terminal.md#problemi-terminale) |

<a id="disinstallare"></a>
## Disinstallare

```bash
sudo systemctl disable --now 'astreo-*.timer' 'astreo-*.service'
sudo rm -f /etc/systemd/system/astreo-*.service /etc/systemd/system/astreo-*.timer /etc/polkit-1/rules.d/50-astreo-monitor.rules
sudo rm -f /etc/nginx/sites-enabled/astreo-monitor /etc/nginx/sites-enabled/netpulse && sudo systemctl reload nginx
sudo systemctl daemon-reload
```
Configurazione, CA e database restano: eliminali a mano (`/etc/astreo-monitor`, il database) solo se non servono più.
