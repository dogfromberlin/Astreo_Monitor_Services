# Eventi sui grafici

Sui grafici delle viste **Server** (CPU, memoria, temperature, velocità) e **Connessione**
(andamento, latenza, disponibilità) compaiono linee verticali colorate nei momenti in cui è
successo qualcosa. Passando il mouse su una linea compaiono descrizione e orario; sotto i grafici
c'è l'**elenco degli eventi del periodo**, con filtri per tipo (che valgono anche per i grafici).

| Evento | Colore | Da dove arriva |
|---|---|---|
| Riavvio del server | viola | job metriche (avvio rilevato) e, la prima volta, lo storico di `last -x reboot` |
| Interruzione della connessione | rosso | controllo continuo della connessione (ricavato dai ping) |
| Cambio di IP pubblico | blu | storico dell'IP pubblico |
| Servizio fermo / ripartito | giallo | cambi di stato dei servizi monitorati (job metriche) |
| Container fermo / avviato / riavviato | verde acqua | modulo Docker |
| Pi-hole | oliva | modulo Pi-hole |
| Speedtest sotto soglia | arancione | risultati dello speedtest |
| Avviso inviato | giallo | registro delle notifiche (solo quelli senza un evento proprio: temperatura, disco, backup, scadenze, dischi, aggiornamenti) |

Interruzioni, cambi di IP, speedtest e avvisi sono ricavati da dati già presenti: compaiono anche per
il passato. Riavvii, servizi, container e Pi-hole sono salvati nella tabella `events` (stessa
retention delle metriche).

Per nascondere gli eventi da tutti i grafici: **Impostazioni → Moduli → Eventi sui grafici**.
