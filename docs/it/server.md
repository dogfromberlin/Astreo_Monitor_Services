# Server

<a id="risorse"></a>
## Risorse e storico

Il job delle metriche (`astreo-metrics.timer`, ogni 5 minuti) registra CPU, load, memoria, swap, disco e
temperature. La CPU è la **media esatta** dei 5 minuti (dai contatori del sistema), non un istante.
Le temperature si leggono con `sensors -j` (pacchetto `lm-sensors`), altrimenti con psutil.

La vista **Server** mostra i valori in tempo reale e lo **storico** (24 ore, 7, 30, 90 giorni, 1 anno o un
intervallo a scelta): CPU e load, memoria e disco, temperature, velocità della connessione.

| Allarme | Valore | Soglie predefinite (`[metrics]`) |
|---|---|---|
| Temperatura | massima tra i sensori | WARNING 85 °C, ALERT 95 °C |
| Disco | disco radice | WARNING 85 %, ALERT 95 % |

<a id="servizi"></a>
## Servizi

I servizi systemd da monitorare si scelgono in **Impostazioni → Servizi** (tutte le unit del server, con
ricerca): **Monitora** li mostra nella vista Server e nella Panoramica, **Avvisami** manda un avviso quando si
fermano e quando ripartono, l'etichetta e l'ordine decidono come compaiono.
Un clic su un servizio nella vista Server mostra `systemctl status` (solo amministratore).

Per OpenVPN la unit reale è di norma `openvpn-server@server.service`: `openvpn.service` risulta sempre attiva.

<a id="controlli"></a>
## Manutenzione e controlli

Stato a colpo d'occhio di: connessione (ping), heartbeat esterno, certificati e token in scadenza, dischi,
aggiornamenti, verifica del ripristino. Dettagli in [Connessione](connection.md), [Notifiche](notifications.md#heartbeat)
e [Salute del sistema](health.md).

<a id="eventi"></a>
## Eventi sui grafici

Linee verticali colorate nei momenti in cui è successo qualcosa; passando il mouse si legge cosa. Sotto i
grafici c'è l'elenco degli eventi del periodo, con filtri per tipo (che valgono anche per i grafici).

| Evento | Da dove arriva |
|---|---|
| Riavvio del server | avvio rilevato (e storico di `last -x reboot`) |
| Interruzione della connessione | controllo continuo della connessione |
| Cambio di IP pubblico | storico dell'IP |
| Servizio fermo o ripartito | servizi monitorati |
| Container, Pi-hole | moduli |
| Dispositivi e servizi | controlli di altri dispositivi |
| Speedtest sotto soglia, avviso inviato | risultati e registro delle notifiche |

Si possono nascondere da **Impostazioni → Moduli → Eventi sui grafici**.

<a id="processi"></a>
## Processi

I processi che usano più CPU, aggiornati ogni 10 secondi (solo amministratore: le righe di comando possono
contenere dati riservati).
