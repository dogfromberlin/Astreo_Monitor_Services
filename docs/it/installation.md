# Installazione e aggiornamento

<a id="requisiti"></a>
## Requisiti

- **Ubuntu o Debian** con systemd, **Python 3.10** o superiore, accesso `sudo`.
- **Database**: SQLite (nessuna installazione), PostgreSQL (installato dall'installatore se sullo stesso
  server) oppure SQL Server (un'istanza esistente, anche Express).
- Facoltativi: nginx per HTTPS, Docker, Pi-hole, rclone per le copie dei backup.

<a id="installare"></a>
## Installare

```bash
git clone https://github.com/dogfromberlin/Astreo_Monitor_Services.git
cd Astreo_Monitor_Services
sudo bash install.sh
```

`install.sh` installa i pacchetti di base (python3-venv, zstd, smartmontools, ping), crea l'ambiente
Python e fa le domande:

| Domanda | Predefinito | Note |
|---|---|---|
| Lingua | da `LANG` | dashboard, notifiche, bot e messaggi a terminale |
| Utente dei servizi | chi lancia `sudo` | i servizi non girano come root |
| Database | `sqlite` | `postgresql` o `mssql` (SQL Server: database e login vengono creati) |
| HTTPS con nginx | sì | certificato con una CA privata; senza HTTPS la dashboard funziona in HTTP con un avviso e senza terminale |
| IP e nomi del server | rilevati | finiscono nel certificato |
| Terminale web | sì | solo con HTTPS; reti ammesse rilevate dalle interfacce |
| Speedtest, backup, NetPulse | sì, sì, no | moduli facoltativi |
| Servizi da monitorare | quelli attivi riconosciuti | modificabili poi in Impostazioni → Servizi |
| Password | — | dashboard e terminale, diverse |

Al termine: configurazione in `/etc/astreo-monitor/config.ini`, risposte in `/etc/astreo-monitor/install.ini`,
schema del database creato, servizi avviati e diagnosi stampata.

Con HTTPS, per evitare gli avvisi del browser installa la CA sui dispositivi: vedi
[HTTPS e terminale](https-terminal.md#certificato).

<a id="aggiornare"></a>
## Aggiornare

```bash
cd Astreo_Monitor_Services
sudo bash update.sh                       # da git
sudo bash update.sh /percorso/pacchetto.zip
```
Passi: sospensione dei job (i timer `astreo-*` si fermano e un job già partito finisce il suo giro; alla fine
vengono riattivati, anche se l'aggiornamento si interrompe) → codice (con lo zip vengono rimossi anche i file che la nuova versione non contiene) → librerie e pip →
verifiche automatiche (se falliscono si ferma prima di toccare servizi e database) → file di sistema dai
modelli → migrazione dello schema (con SQL Server chiede la password di `sa`) → riavvio → diagnosi.

I pacchetti zip di ogni versione sono nelle **Release** del repository su GitHub, con il loro SHA256.

<a id="https-dopo"></a>
## Attivare HTTPS e terminale dopo

```bash
sudo bash update.sh --enable-https
```

<a id="modelli"></a>
## File generati dai modelli

Unit systemd, siti nginx e regola polkit si generano da `deploy/templates/` con le risposte di `install.ini`:
**non vanno modificati a mano**. Per cambiare qualcosa modifica `install.ini`, poi:
```bash
sudo .venv/bin/python -m astreo_monitor.installer diff -v    # cosa cambierebbe
sudo .venv/bin/python -m astreo_monitor.installer apply      # applica
```
Un'installazione precedente alla 3.0 si "adotta" con `sudo .venv/bin/python -m astreo_monitor.installer adopt`,
che ricava le risposte dai file presenti.

<a id="lingua-terminale"></a>
## Lingua dei comandi a terminale

Da `ASTREO_LANG`, poi da `language` in `install.ini`, poi da `LANG` del sistema. Esempio:
`sudo ASTREO_LANG=en .venv/bin/python -m astreo_monitor.doctor`.
