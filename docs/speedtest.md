# Speedtest

Job: `astreo_monitor.jobs.speedtest` — timer `astreo-speedtest.timer`, alle 00:05,
04:05, 08:05, 12:05, 16:05, 20:05.

## Come misura

Usa gli endpoint di test di Cloudflare (`speed.cloudflare.com`), pensati per questo scopo:

1. **Latenza**: mediana di 5 richieste minime (la prima, con l'handshake, è scartata).
   Se nessuna risponde lo stato è **DOWN**.
2. **Download**: `rounds` giri (default 3); in ogni giro `streams` connessioni parallele
   (default 4) scaricano `download_bytes` ciascuna (default 25 MB).
3. **Upload**: stessi giri, ogni connessione invia `upload_bytes` (default 10 MB) di dati casuali.
4. Il risultato è la **mediana** dei giri riusciti; i giri falliti si scartano.

Traffico per esecuzione con i default: circa 300 MB in download e 120 MB in upload
(la 1.x scaricava 1 GB). Più flussi in parallelo misurano meglio le linee veloci,
come fanno gli speedtest dei browser.

### Perché è cambiato
Nella 1.x l'upload risultava 700–1200 Mbps caricando file su servizi di hosting
pubblici (file.io): valori non realistici, il servizio rispondeva prima di aver
ricevuto tutto. Inoltre i download falliti contavano come 0 nella media e a
connessione assente non partiva alcuna email. Lo storico 1.x è importato con
`provider = 'legacy'`; in dashboard il suo upload non viene mostrato.

## Stati

| Stato | Condizione |
|---|---|
| OK | download ≥ `download_warning` e upload ≥ `upload_warning` |
| WARNING | download o upload sotto la soglia di warning |
| ALERT | sotto la soglia di alert, oppure una delle due misure non riuscita |
| DOWN | Cloudflare non raggiungibile |

Soglie attuali (riprese dalla 1.x): download 500 / 100, upload 200 / 50 Mbps.
La linea misura circa 350 Mbps in download, quindi con queste soglie lo stato è
sempre WARNING: è il motivo delle 6 email al giorno della 1.x.

## Notifiche

Email solo al cambio di stato (incluso il ritorno a OK) più un promemoria ogni
`reminder_hours` se lo stato resta anomalo. **Per la prima settimana `notify = false`**:
si raccolgono le misure reali, poi si ricalibrano le soglie.

### Ricalibrare le soglie dopo una settimana
Nel client SQL:
```sql
USE astreo_monitor;
SELECT COUNT(*) AS misure,
       MIN(download_mbps) AS dl_min, AVG(download_mbps) AS dl_media,
       MIN(upload_mbps)   AS ul_min, AVG(upload_mbps)   AS ul_media,
       AVG(latency_ms)    AS latenza_media
FROM speedtest_results
WHERE provider = 'cloudflare' AND status <> 'DOWN';
```
Regola pratica: `warning` circa il 70% della media, `alert` circa il 40%.
Poi nella finestra SSH su astreo:
```bash
nano /etc/astreo-monitor/config.ini     # [speedtest] soglie e notify = true
sudo systemctl restart astreo-monitor-web.service   # solo per aggiornare le soglie mostrate in dashboard
```

## Comandi (finestra SSH su astreo)

```bash
cd ~/Astreo_Monitor_Services
.venv/bin/python -m astreo_monitor.jobs.speedtest --config /etc/astreo-monitor/config.ini --dry-run
sudo systemctl start astreo-speedtest.service
journalctl -u astreo-speedtest.service -n 30 --no-pager
```
