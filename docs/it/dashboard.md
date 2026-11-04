# La dashboard

Si apre all'indirizzo indicato al termine dell'installazione, di norma `https://<server>:5443/`.

<a id="viste"></a>
## Viste

| Vista | Contenuto | Utente in sola lettura |
|---|---|---|
| **Panoramica** | pagina iniziale: stato in una frase, cose da controllare, server, connessione, backup, ultimi eventi | sì (senza azioni) |
| **Server** | elenco dei server; per ognuno risorse in tempo reale, storico con eventi, servizi, dischi, manutenzione e controlli, moduli, processi | sì (senza processi) |
| **Rete e connessione** | IP pubblico e sue variazioni, ultimo speedtest; andamento, disponibilità, qualità e confronto della connessione Internet | sì |
| **Dispositivi** | controlli di router, NAS, stampanti, siti web: stato, latenza, disponibilità, storico | sì |
| **Avvisi ed eventi** | eventi di tutti i server con filtri per periodo, server, tipo e gravità; notifiche inviate | sì (senza notifiche inviate) |
| **Backup** | sicurezza dei dati, ultimo backup con le copie, esegui ora | sì (solo il riepilogo) |
| **Impostazioni** | speedtest, notifiche, servizi, dispositivi, backup, moduli | no |
| **Log** | journal dei servizi | no |
| **Terminale** | shell nel browser (solo HTTPS) | no |

Le viste si scelgono dal menu laterale; sul telefono dalla barra in basso, dove le meno usate stanno sotto
**Altro**. I collegamenti diretti a una scheda delle impostazioni hanno la forma `#impostazioni/dispositivi`.

<a id="panoramica"></a>
## Panoramica

È la pagina che si apre per prima e si aggiorna da sola ogni 30 secondi.

| Riquadro | Cosa mostra |
|---|---|
| Stato | una frase sola: *Tutto funziona*, *Tutto funziona · 1 cosa da controllare* o *Attenzione*, con il riepilogo di server, servizi, connessione e backup |
| Numeri | server raggiungibili, servizi attivi, disponibilità della connessione negli ultimi 7 giorni, ora dell'ultimo backup |
| Da controllare | l'elenco qui sotto |
| Server | una scheda per server: CPU, memoria, disco più pieno, temperatura e servizi (prima quelli fermi); un clic apre il server |
| Connessione, Sicurezza dei dati, Ultimi eventi | ultimo speedtest, latenza e IP pubblico; backup, copia e prova di ripristino; gli eventi delle ultime 24 ore |

Il numero accanto a **Panoramica** nel menu indica quante cose ci sono da controllare.

<a id="da-controllare"></a>
## Da controllare

Raccoglie in un posto solo quello che richiede attenzione, in ordine di importanza (**Urgente**, **Da
guardare**, **Informazione**), e si svuota da solo quando il problema è risolto.

| Cosa compare | Quando |
|---|---|
| server non raggiungibile | l'agente non invia dati da più dei minuti impostati in *Server collegati* |
| servizio fermo | un servizio controllato, del server centrale o di un agente, non è attivo |
| disco o temperatura | oltre le soglie di avviso o di allarme |
| connessione | Internet assente o degradata |
| backup | ultimo backup non riuscito, nessun backup da più di 36 ore, prova di ripristino non riuscita |
| dispositivi | un controllo non risponde o risponde con un avviso |
| scadenze | certificati e token vicini alla scadenza |
| aggiornamenti | aggiornamenti di sicurezza da installare, riavvio necessario |

Ogni voce ha l'azione suggerita: aprire il server o la vista interessata, oppure **Non controllarlo più** per un
servizio che non serve più (lo toglie dai servizi controllati; si riattiva dalle impostazioni). L'utente in sola
lettura vede le voci ma non le azioni che modificano qualcosa.

<a id="tema"></a>
## Tema chiaro e scuro

Interruttore in alto a destra: **segui il sistema** (predefinito), **chiaro** o **scuro**. La scelta vale per
l'utente, quindi è la stessa dal computer e dal telefono; la pagina parte subito con il tema giusto.

<a id="personalizza"></a>
## Personalizza

Nella **Panoramica** e nel dettaglio di un **server** il pulsante **Personalizza** (in alto; sul telefono in basso a
destra) mette la pagina in modifica: ogni card ha una maniglia **Trascina**, le frecce per spostarla prima o dopo e
l'occhio per nasconderla. Le card si spostano dentro la propria sezione; la fascia di stato e *Da controllare*
restano sempre in alto.

| Pulsante | Cosa fa |
|---|---|
| Trascina | sposta la card con il mouse o con il dito |
| ↑ ↓ | sposta la card di un posto (comodo da tastiera e sul telefono) |
| Occhio | nasconde la card, o la rimostra; in modifica le card nascoste restano visibili, sbiadite |
| Ripristina ordine | torna all'ordine di partenza delle sezioni della pagina |
| Mostra card nascoste | rimostra tutte le card nascoste della pagina |
| Fine | chiude la modifica (anche Esc) |

La disposizione vale per l'utente, quindi è la stessa dal computer e dal telefono; l'ordine dei pannelli del
dettaglio vale per tutti i server. Le card aggiunte nelle versioni future compaiono in fondo alla loro sezione.

<a id="ricerca"></a>
## Ricerca

**Ctrl K** (**⌘ K** su Mac), oppure il campo **Cerca** in alto (sul telefono la lente), apre la ricerca: sezioni,
server, servizi, dispositivi, schede delle impostazioni, pagine e capitoli di questa guida, e comandi rapidi (tema,
guida, personalizza). Si scrive una parte del nome, si sceglie con ↑ ↓ e si apre con **Invio**; **Esc** chiude.
L'utente in sola lettura trova solo quello che può aprire.

<a id="impostazioni"></a>
## Impostazioni

| Scheda | Cosa si imposta |
|---|---|
| Speedtest | stato del timer, esegui ora, sospendi, soglie, parametri, controllo continuo della connessione |
| Server | server collegati con un agente, comando d'installazione, servizi controllati, nuovo token |
| Notifiche | canali, regole di avviso, fascia di silenzio, instradamento, heartbeat, scadenze, dischi, registro degli invii |
| Servizi | quali servizi systemd monitorare, avviso, etichetta, ordine |
| Dispositivi | controlli di altri dispositivi e servizi |
| Backup | ultimo backup, esegui ora, destinazioni rclone |
| Moduli | Docker, Pi-hole, token delle integrazioni, eventi sui grafici |

Le modifiche valgono subito, senza riavvii. I valori segreti (password, token) non vengono mai mostrati:
lascia il campo com'è per conservarli, scrivi un valore nuovo per sostituirli.

<a id="aiuto"></a>
## Aiuto in linea

L'icona **?** accanto al titolo di ogni sezione apre questa guida nel punto che la riguarda, in un pannello
laterale e nella lingua scelta; **Guida** in fondo al menu laterale apre l'indice. I collegamenti tra le pagine si
seguono senza uscire dalla dashboard (← per tornare indietro). È la stessa guida di `docs/` nel repository,
sempre della versione installata.

<a id="lingua"></a>
## Lingua

Selettore **IT / EN** in fondo al menu laterale (sul telefono in fondo alla pagina): vale per dashboard, notifiche, bot Telegram e riepilogo
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

La dashboard si adatta allo schermo: il menu laterale diventa la barra delle viste in basso. Si può installare come app: Chrome su
Android, menu ⋮ → **Installa app**; Safari su iPhone, Condividi → **Aggiungi alla schermata Home**. Con HTTPS
serve prima la CA installata sul telefono ([HTTPS e terminale](https-terminal.md#certificato)).
