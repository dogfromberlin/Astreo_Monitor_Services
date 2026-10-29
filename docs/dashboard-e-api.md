# Dashboard e API

Servizio: `astreo-monitor-web.service` (Flask su waitress).
Indirizzo: `http://<IP-LAN>:5025/` (il vecchio `/astreomonitor` reindirizza qui).

## Autenticazione

Basic Auth su tutte le pagine e le API, tranne `/api/v1/health`.
Utente e hash della password in `[web]` (vedi [configurazione.md](configurazione.md)).
Il browser chiede le credenziali una volta e le riusa per le chiamate della pagina.

## La dashboard

| Area | Contenuto | Aggiornamento |
|---|---|---|
| Testata | Hostname, uptime, IP pubblico, ultimo speedtest, LED dei servizi | 10 s / 5 min |
| Indicatori | CPU, memoria, disco `/`, temperatura massima, colorati per soglia | 10 s (temperatura 60 s) |
| Servizi | Stato di ogni servizio; clic per l'output di `systemctl status` | 60 s o pulsante *Aggiorna* |
| Processi | I 15 processi con più CPU | 10 s |
| Sensori, Partizioni | Temperature correnti, uso di ogni filesystem | 60 s / 10 s |
| Storico | CPU e load, RAM e disco, temperature, speedtest | a richiesta e ogni 5 min |

Periodi dello storico: 24 ore, 7, 30, 90 giorni, 1 anno, oppure intervallo libero.
I punti sono medie su intervalli (bucket) scelti in automatico: 5 minuti per 24 ore,
1 ora per 7 giorni, e così via, fino a circa 300 punti per grafico.

## API REST

Tutte rispondono JSON. In caso di errore: `{"error": "...", "detail": "..."}` con
codice 400 (parametri), 401 (credenziali), 404, 500 o 503 (database non raggiungibile).

| Metodo e percorso | Descrizione |
|---|---|
| `GET /api/v1/health` | Stato del servizio e del DB (senza autenticazione) |
| `GET /api/v1/system` | CPU, memoria, load, dischi, uptime |
| `GET /api/v1/processes?limit=15` | Processi ordinati per CPU (max 50) |
| `GET /api/v1/temperatures` | Sensori attuali e soglie |
| `GET /api/v1/services` | Stato di tutti i servizi in whitelist |
| `GET /api/v1/services/<chiave>` | Stato e output di `systemctl status` |
| `GET /api/v1/history/metrics` | Storico CPU (media e picco), load, RAM, disco |
| `GET /api/v1/history/temperatures` | Storico temperature per sensore |
| `GET /api/v1/history/speedtest` | Risultati speedtest |
| `GET /api/v1/network` | Ultimo speedtest, IP pubblico, variazioni IP, soglie |

Parametri di periodo per `/history/*`: `range=24h|7d|30d|90d|365d` (default 24h)
oppure `from=AAAA-MM-GGTHH:MM&to=AAAA-MM-GGTHH:MM`. Periodo massimo 400 giorni.

Esempi (finestra SSH su astreo o qualsiasi PC della LAN):
```bash
curl -s http://<IP-LAN>:5025/api/v1/health
curl -s -u <utente> http://<IP-LAN>:5025/api/v1/system
curl -s -u <utente> "http://<IP-LAN>:5025/api/v1/history/metrics?range=7d"
```
(`-u <utente>` senza password: curl la chiede a terminale.)

## Gestione del servizio

```bash
systemctl status astreo-monitor-web.service --no-pager
sudo systemctl restart astreo-monitor-web.service
journalctl -u astreo-monitor-web.service -n 100 --no-pager
```
Ogni richiesta viene registrata nel journal (IP, percorso, esito, durata);
i tentativi di accesso falliti sono a livello WARNING.

## Avvio manuale (test)

```bash
cd ~/Astreo_Monitor_Services
.venv/bin/python -m astreo_monitor.web --config /etc/astreo-monitor/config.ini --port 5026
```
`Ctrl+C` per fermarlo.
