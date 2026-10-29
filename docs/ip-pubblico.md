# IP pubblico

Job: `astreo_monitor.jobs.public_ip` — timer `astreo-publicip.timer`, ogni 15 minuti
(la 1.x controllava ogni 6 ore).

## Come funziona

1. Interroga i provider in `[publicip] providers` (default: checkip.amazonaws.com,
   api.ipify.org, ifconfig.me) con timeout `timeout`.
2. Ogni risposta è validata come indirizzo IP; quelle non valide sono scartate.
3. Vince il valore indicato dalla maggioranza. Se nessun provider risponde, o se le
   risposte non hanno una maggioranza, il controllo viene **saltato**: nessun dato
   aggiornato e nessuna email (la 1.x in questo caso registrava un IP vuoto e
   mandava un falso allarme, perdendo poi il cambio reale).
4. Se l'IP è diverso dall'ultimo noto: riga in `public_ip_history` e email.
   Al primo rilevamento si registra senza email.

L'IP corrente sta in `monitor_state` (chiave `publicip:current`) e sostituisce il
vecchio `ipaddress.json`.

## Dove vederlo

- Dashboard: testata (IP e da quando) e sezione *Variazioni dell'IP pubblico*.
- API: `GET /api/v1/network`.
- SQL: `SELECT * FROM public_ip_history ORDER BY [timestamp] DESC;`

## Comandi (finestra SSH su astreo)

```bash
cd ~/Astreo_Monitor_Services
.venv/bin/python -m astreo_monitor.jobs.public_ip --config /etc/astreo-monitor/config.ini --dry-run
sudo systemctl start astreo-publicip.service
journalctl -u astreo-publicip.service -n 20 --no-pager
```
