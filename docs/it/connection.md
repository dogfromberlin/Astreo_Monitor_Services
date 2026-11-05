# Connessione

La vista **Rete e connessione** raccoglie tre fonti: il **controllo continuo** (ping ogni minuto), lo **speedtest**
periodico e l'**IP pubblico**. In cima: IP pubblico attuale, ultimo speedtest e, aprendo *Variazioni dell'IP
pubblico*, i cambi di indirizzo. Il periodo (6 ore … 1 anno o intervallo libero) vale per tutte le schede;
**Esporta CSV** scarica le misure dello speedtest del periodo.

<a id="continuo"></a>
## Controllo continuo (ping ogni minuto)

`astreo-connectivity.timer`: 5 ping veloci verso il router (`gateway`) e verso Internet (predefiniti 1.1.1.1 e
8.8.8.8). Scheda **Disponibilità**: disponibilità %, interruzioni con durata, grafici di latenza e perdita.

| Stato | Condizione |
|---|---|
| DOWN | nessuna destinazione Internet risponde; il messaggio distingue router/rete locale da linea/provider |
| WARNING | perdita oltre la soglia (20 %) o latenza media oltre la soglia (100 ms) |
| OK | altrimenti |

Durante un'interruzione gli avvisi non possono uscire: arriva **Connessione ripristinata dopo N min**, con
inizio e durata. Destinazioni e soglie in **Impostazioni → Speedtest → Controllo continuo**. Se la linea ha
spesso cadute di un minuto, imposta **Avvisa dopo** (es. 3 minuti) nella regola *Connessione* di
[Notifiche](notifications.md#regole): le cadute brevi restano nello storico ma non mandano avvisi.

<a id="speedtest"></a>
## Speedtest

`astreo-speedtest.timer`, ogni 4 ore (00:05, 04:05 …). Usa gli endpoint di test di Cloudflare: latenza (mediana
di 5 richieste), poi download e upload con più connessioni in parallelo (predefiniti: 3 giri, 4 connessioni,
25 MB in download e 10 MB in upload ciascuna, circa 300 MB e 120 MB per misura); il risultato è la mediana
dei giri riusciti.

| Stato | Condizione |
|---|---|
| OK | download e upload sopra le soglie di warning |
| WARNING | download o upload sotto la soglia di warning |
| ALERT | sotto la soglia di alert, oppure una misura non riuscita |
| DOWN | Cloudflare non raggiungibile |

Le soglie iniziali (download 500 / 100, upload 200 / 50 Mbps) vanno **adattate alla propria linea** dopo
qualche giorno di misure, in **Impostazioni → Speedtest**: con soglie troppo alte lo stato resta sempre WARNING.
Dalla stessa scheda: **Esegui ora**, **Sospendi** (resta sospeso anche dopo un riavvio), parametri di misura.

<a id="schede"></a>
## Schede della vista

| Scheda | Contenuto |
|---|---|
| Andamento | velocità e latenza con le soglie, ultime misure con l'esito |
| Disponibilità | controllo continuo: disponibilità, interruzioni, latenza e perdita per destinazione |
| Qualità | episodi sotto soglia (misure consecutive), tempo totale, episodio più lungo |
| Confronto | il periodo scelto contro il precedente o lo stesso periodo 7 o 30 giorni prima |

<a id="ip"></a>
## IP pubblico

`astreo-publicip.timer`, ogni 15 minuti: interroga più servizi (checkip.amazonaws.com, api.ipify.org,
ifconfig.me) e accetta il valore indicato dalla maggioranza. Se cambia: avviso, riga nello storico ed evento
sui grafici. Se i servizi non concordano il controllo viene saltato, senza falsi allarmi.

<a id="netpulse"></a>
## Widget Windows NetPulse (modulo facoltativo)

Se attivato all'installazione, nginx sulla porta 8081 serve le API compatibili con il widget NetPulse per la
barra delle applicazioni (`/api/latest`, `/api/query`, `/api/health`), protette dal token in
`/etc/astreo-monitor/netpulse_token`.
