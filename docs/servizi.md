# Servizi

Dalla 2.2 l'elenco dei servizi monitorati non è più nel file di configurazione: si gestisce
da **Impostazioni → Servizi** ed è salvato nella tabella `monitored_services`.

## Gestione dalla dashboard

La scheda elenca **tutti** i servizi systemd di astreo (attivi per primi), con campo di
ricerca e filtro *Solo monitorati*. Per ogni servizio:

| Colonna | Significato |
|---|---|
| Stato | LED verde se attivo, rosso se monitorato e fermo |
| Servizio | nome della unit e descrizione |
| Etichetta | nome mostrato nella testata e nella vista Server |
| Monitora | mostra il servizio nella testata e nella vista Server |
| Avvisami | notifica quando si ferma e quando riparte |
| Ordine | posizione nella testata (frecce su/giù) |

Le modifiche si salvano subito. Si possono monitorare solo unit che esistono davvero su astreo.

## Avvisi

Con *Avvisami* attivo, il job delle metriche (ogni 5 minuti) controlla il servizio: email o
messaggio quando passa da attivo a fermo e quando torna attivo, sui canali scelti per
l'evento **Servizi** in Impostazioni → Notifiche. Se resta fermo, promemoria ogni
`[metrics] reminder_hours` ore.

## Elenco iniziale

`sql/005_impostazioni.sql` crea l'elenco iniziale per astreo: OpenVPN
(`openvpn-server@server.service`, la unit reale: `openvpn.service` è fittizia e risulta
sempre attiva), SQL Server, Nginx, Apache, Docker, Pi-hole, Astreo Monitor; Ollama e
Medusa sono inseriti ma non monitorati perché non risultano in esecuzione.
Su un'installazione nuova, se la tabella è vuota, si parte dalla sezione `[services]` del config.

## Dettaglio

Clic su un servizio nella vista Server: output di `systemctl status <unit> -n 30`.
Se le righe di log non compaiono, `<utente>` non può leggere il journal di quel servizio:
```bash
sudo usermod -aG systemd-journal <utente>
sudo systemctl restart astreo-monitor-web.service
```
