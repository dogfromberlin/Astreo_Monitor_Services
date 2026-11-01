# Installazione guidata

Requisiti: **Ubuntu o Debian** con systemd, **Python 3.10+**, accesso `sudo`. Per SQL Server serve
un'istanza già installata (anche Express); PostgreSQL e SQLite li prepara l'installatore.

## Installare

```bash
git clone https://github.com/dogfromberlin/Astreo_Monitor_Services.git
cd Astreo_Monitor_Services
sudo bash install.sh
```

`install.sh` installa i pacchetti di base (python3-venv, zstd, smartmontools, ping), crea l'ambiente
Python e avvia le domande:

| Domanda | Predefinito | Note |
|---|---|---|
| Lingua | da `LANG` | dashboard, notifiche, bot e messaggi a terminale |
| Utente dei servizi | chi lancia `sudo` | i servizi non girano come root |
| Database | `sqlite` | `postgresql` (installato via apt se locale) o `mssql` (istanza esistente: crea database e login) |
| HTTPS con nginx | sì | certificato con CA privata (mkcert); senza HTTPS la dashboard funziona in HTTP, con un avviso, e senza terminale |
| IP e nomi del server | rilevati | finiscono nel certificato |
| Terminale web | sì | solo con HTTPS; reti ammesse rilevate dalle interfacce (LAN, VPN) |
| Speedtest, backup, NetPulse | sì, sì, no | moduli facoltativi |
| Servizi da monitorare | quelli attivi riconosciuti | modificabili poi da Impostazioni → Servizi |
| Password | — | dashboard e terminale (diverse) |

Al termine: configurazione in `/etc/astreo-monitor/config.ini`, risposte in
`/etc/astreo-monitor/install.ini`, schema del database creato, servizi avviati e diagnosi.

## Aggiornare

```bash
cd Astreo_Monitor_Services
sudo bash update.sh                     # da git
sudo bash update.sh /tmp/pacchetto.zip  # da uno zip
```
Passi: codice → librerie → verifiche (se falliscono si ferma) → file di sistema dai modelli →
migrazione dello schema → riavvio → diagnosi.

## Attivare HTTPS e terminale dopo

```bash
sudo bash update.sh --enable-https
```

## File generati dai modelli

Unit systemd, siti nginx e regola polkit si generano da `deploy/templates/` con le risposte di
`install.ini`: **non vanno modificati a mano**. Per cambiare qualcosa modifica `install.ini`, poi:
```bash
sudo .venv/bin/python -m astreo_monitor.installer diff -v    # cosa cambierebbe
sudo .venv/bin/python -m astreo_monitor.installer apply      # applica
```

## Installazioni 2.x esistenti

```bash
sudo .venv/bin/python -m astreo_monitor.installer adopt
```
Ricava le risposte dai file presenti (unit, nginx, certificato, config), crea `install.ini` e mostra le
differenze rispetto ai modelli; poi `installer apply` allinea i file.
