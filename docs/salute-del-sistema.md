# Salute del sistema: dischi e aggiornamenti

## Dischi (SMART)

`smartctl` richiede i permessi di root, Astreo Monitor no. Per questo il lavoro è diviso in due:

| Componente | Utente | Cosa fa |
|---|---|---|
| `astreo-smart-collect.timer` → `/usr/local/sbin/astreo-smart-collect` | root | ogni 6 ore (alle :20) e all'avvio legge i dati SMART e scrive un file JSON per disco in `/var/lib/astreo-monitor/smart/`. Gira senza rete e con il file system in sola lettura |
| `astreo-health.timer` → job `system_health` | <utente> | alle :25 legge i JSON, valuta lo stato, salva e avvisa |

| Stato | Condizione |
|---|---|
| ALERT | autodiagnosi SMART fallita, settori in attesa o non correggibili, errori del supporto (NVMe) |
| WARNING | settori riallocati, usura SSD oltre la soglia (80%), temperatura oltre la soglia (60 °C) |
| OK | altrimenti |

Soglie in **Impostazioni → Notifiche → Dischi**. Regola di avviso iniziale: *solo se peggiora*,
con rientro, promemoria ogni 24 ore. Se i dati SMART sono più vecchi di 24 ore lo stato è
*non verificabile* (il timer di raccolta non gira).

Dettaglio completo (finestra SSH): `sudo smartctl -a /dev/sda`

## Aggiornamenti di sistema

Lo stesso job controlla, senza privilegi:
- gli aggiornamenti in sospeso dalla cache di apt (aggiornata ogni giorno da `apt-daily.timer`),
  distinguendo quelli di **sicurezza**;
- il file `/var/run/reboot-required`, creato quando un aggiornamento richiede un riavvio.

**WARNING** se ci sono aggiornamenti di sicurezza o serve un riavvio. Regola iniziale: *solo se
peggiora*, senza avviso di rientro, promemoria **settimanale**. L'avviso elenca i pacchetti e i
comandi da usare:
```bash
sudo apt update && sudo apt upgrade
sudo reboot        # solo se richiesto
```

Esecuzione immediata:
```bash
sudo systemctl start astreo-smart-collect.service
sudo systemctl start astreo-health.service
journalctl -u astreo-smart-collect.service -u astreo-health.service -n 20 --no-pager
```
