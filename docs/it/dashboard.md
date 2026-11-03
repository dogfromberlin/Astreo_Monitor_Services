# La dashboard

Si apre all'indirizzo indicato al termine dell'installazione, di norma `https://<server>:5443/`.

<a id="viste"></a>
## Viste

| Vista | Contenuto | Utente in sola lettura |
|---|---|---|
| **Server** | risorse in tempo reale, controlli, servizi, dispositivi, moduli, processi, storico con eventi | sì (senza processi) |
| **Connessione** | andamento, disponibilità, qualità e confronto della connessione Internet | sì |
| **Impostazioni** | speedtest, notifiche, servizi, dispositivi, backup, moduli | no |
| **Log** | journal dei servizi | no |
| **Terminale** | shell nel browser (solo HTTPS) | no |

In testata: nome del server, tempo dall'avvio, IP pubblico, ultimo speedtest e ultimo backup; sotto, la fila
dei servizi monitorati (verde attivo, rosso fermo).

<a id="impostazioni"></a>
## Impostazioni

| Scheda | Cosa si imposta |
|---|---|
| Speedtest | stato del timer, esegui ora, sospendi, soglie, parametri, controllo continuo della connessione |
| Notifiche | canali, regole di avviso, fascia di silenzio, instradamento, heartbeat, scadenze, dischi, registro degli invii |
| Servizi | quali servizi systemd monitorare, avviso, etichetta, ordine |
| Dispositivi | controlli di altri dispositivi e servizi |
| Backup | ultimo backup, esegui ora, destinazioni rclone |
| Moduli | Docker, Pi-hole, token delle integrazioni, eventi sui grafici |

Le modifiche valgono subito, senza riavvii. I valori segreti (password, token) non vengono mai mostrati:
lascia il campo com'è per conservarli, scrivi un valore nuovo per sostituirli.

<a id="lingua"></a>
## Lingua

Selettore **IT / EN** in fondo alla pagina: vale per dashboard, notifiche, bot Telegram e riepilogo
settimanale. I campi data e ora seguono invece la lingua del browser.

<a id="avvisi-pagina"></a>
## Avvisi in pagina

| Avviso | Cosa fare |
|---|---|
| *Connessione non cifrata* | aprire l'indirizzo HTTPS, oppure attivare HTTPS con `sudo bash update.sh --enable-https` |
| *Database da aggiornare* | eseguire la migrazione indicata (`python -m astreo_monitor.migrate`) |
| *La pagina è della versione …* | ricaricare con Ctrl+F5 |

<a id="smartphone"></a>
## Smartphone e tablet

La dashboard si adatta allo schermo (barra delle viste in basso). Si può installare come app: Chrome su
Android, menu ⋮ → **Installa app**; Safari su iPhone, Condividi → **Aggiungi alla schermata Home**. Con HTTPS
serve prima la CA installata sul telefono ([HTTPS e terminale](https-terminal.md#certificato)).
