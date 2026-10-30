# Connessione (ex NetPulse)

Vista **Connessione** della dashboard: `https://<IP-LAN>:5443/#connessione`.
Sostituisce la webapp NetPulse e usa le misure dello speedtest (tabella `speedtest_results`,
che contiene anche lo storico della 1.x).

## Periodo

Pulsanti 6 ore, 24 ore, 7 giorni (predefinito), 30 giorni, 90 giorni, 1 anno, oppure
intervallo libero *Dal/al*. Il periodo vale per tutte e tre le schede.
**Esporta CSV** scarica le misure del periodo (separatore `;`, decimali con virgola,
apribile direttamente con Excel).

## Andamento

- Indicatori: download e upload medi (con il minimo) e massimi, latenza media, numero di
  misure e misure con connessione assente.
- Grafico velocità con le soglie di **warning** tratteggiate, grafico della latenza.
- Tabella delle ultime 200 misure con l'esito (OK, WARNING, ALERT, DOWN; `storico 1.x`
  per i dati importati, di cui non si mostra l'upload, non attendibile).

## Disponibilità

Dati del **controllo continuo** (job `astreo_monitor.jobs.connectivity`, timer
`astreo-connectivity.timer`, ogni minuto): 5 ping a 0,2 s verso il router (`gateway`) e verso
Internet (predefiniti 1.1.1.1 e 8.8.8.8).

- Indicatori: disponibilità %, numero di interruzioni, durata totale e più lunga, latenza media
  del router e di Internet.
- Grafici di latenza e pacchetti persi per destinazione, con la soglia di perdita.
- Elenco delle **interruzioni**: minuti consecutivi in cui nessuna destinazione Internet risponde.

Stati e avvisi (evento *Connessione (ping)*):

| Stato | Condizione |
|---|---|
| DOWN | nessuna destinazione Internet risponde; il messaggio distingue *router/rete locale* da *linea/provider* |
| WARNING | perdita oltre la soglia (20%) o latenza media oltre la soglia (100 ms) |
| OK | altrimenti |

Durante un'interruzione gli avvisi non possono uscire: arriva **Connessione ripristinata dopo
N min**, con inizio e durata. Soglie e destinazioni in **Impostazioni → Speedtest → Controllo
continuo**. Dati conservati 90 giorni (`[retention] connectivity_days`).

## Qualità

Raggruppa le misure consecutive sotto la soglia di warning in **episodi**, separatamente
per download e upload (stessa logica di NetPulse). Per ciascuno: numero di episodi, tempo
totale sotto soglia, disponibilità percentuale, episodio più lungo ed elenco degli episodi.

- Una misura con connessione assente (DOWN) conta come sotto soglia.
- La durata di un episodio è calcolata sulla cadenza tipica delle misure (oggi 4 ore):
  un singolo campione sotto soglia vale 4 ore. Va letto con questa granularità.

## Confronto

Confronta il periodo selezionato con il periodo precedente di uguale durata, oppure con lo
stesso periodo 7 o 30 giorni prima. Mostra medie, massimi e latenza con la differenza
percentuale, e due grafici con le curve sovrapposte.

## Soglie

Le soglie sono quelle dello speedtest (Impostazioni → Speedtest): una sola fonte per
allarmi e grafici. In NetPulse erano separate (100 / 20 Mbps).

## Widget Windows

Il widget NetPulse per la barra delle applicazioni continua a funzionare senza modifiche:
nginx sulla porta 8081 inoltra le sue chiamate ad Astreo Monitor.

| Chiamata del widget | Servita da | Autenticazione |
|---|---|---|
| `https://…:8081/api/latest` | `/api/netpulse/latest` | token `Bearer` di NetPulse |
| `https://…:8081/api/query` | `/api/netpulse/query` | token `Bearer` di NetPulse |
| `https://…:8081/api/health` | `/api/netpulse/health` | nessuna |

Il token è in `/etc/astreo-monitor/netpulse_token` (`[netpulse] token_file`).
La configurazione nginx è in `deploy/nginx/netpulse.conf`.

Verifica (finestra SSH su astreo):
```bash
curl -sk https://127.0.0.1:8081/api/health; echo
curl -sk -H "Authorization: Bearer $(cat /etc/astreo-monitor/netpulse_token)" "https://127.0.0.1:8081/api/latest?hours=24&buckets=8"; echo
```
La prima risposta deve contenere `"backend":"astreo-monitor"`.
