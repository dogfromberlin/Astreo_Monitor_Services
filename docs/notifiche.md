# Notifiche

Tre canali: **Email**, **Telegram**, **WhatsApp**. Si configurano in
**Impostazioni → Notifiche**; ogni canale si attiva e disattiva con il suo interruttore
e ha un pulsante **Invia prova**.

## Regole di avviso

Per ogni monitoraggio (Speedtest, Temperatura, Disco, Servizi, Backup database) la tabella
**Regole di avviso** decide *quando* avvisare:

| Impostazione | Effetto |
|---|---|
| **Solo se peggiora** | avviso quando lo stato si aggrava: OK→WARNING, WARNING→ALERT, →DOWN. Nessun avviso se resta uguale o migliora (ALERT→WARNING) |
| **A ogni cambio** | avviso a ogni variazione di stato |
| **Al rientro in OK** | avviso anche quando la situazione torna normale |
| **Promemoria (ore)** | se la situazione resta anomala (WARNING, ALERT o alternati) per queste ore dall'ultimo avviso, parte un promemoria e il conteggio riparte (0 = mai) |

Valori iniziali: Speedtest *solo se peggiora*, nessun avviso di rientro, promemoria a 36 ore;
gli altri *a ogni cambio*, con rientro, promemoria a 24 ore.

Esempio con lo speedtest (regola iniziale):

| Misure | Avviso |
|---|---|
| OK → WARNING | sì |
| WARNING → WARNING | no |
| WARNING → ALERT | sì |
| ALERT → WARNING | no |
| ALERT → ALERT | no |
| WARNING o ALERT ininterrotti per 36 ore dall'ultimo avviso | sì, promemoria; il conteggio riparte |
| → OK | no |

## Fascia di silenzio

In **Impostazioni → Notifiche → Fascia di silenzio**: inizio, fine e orario di recapito
(es. dalle 23:00 alle 07:00, recapito alle 08:00).

- Un avviso nato nella fascia viene trattenuto (tabella `notification_queue`) e recapitato
  all'orario indicato, **un solo messaggio per canale**: l'avviso originale con *(posticipato)*
  nell'oggetto, oppure un riepilogo se sono più di uno.
- Ogni avviso riporta l'orario di rilevamento; quelli posticipati anche l'orario di invio e la
  fascia che li ha trattenuti, ad esempio *Rilevato alle 02:14 del 31/10/2026 — Inviato alle
  08:00, posticipato per la fascia di silenzio 23:00–07:00*.
- Tra la fine della fascia e l'orario di recapito (07:00–08:00) gli avvisi nuovi partono subito.
- Il recapito lo esegue il job delle metriche, ogni 5 minuti.
- Il registro degli invii mostra gli avvisi *In coda*; il numero in attesa compare sotto la fascia.
- L'invio di prova non viene mai trattenuto.

## Quali avvisi su quali canali

La tabella in fondo alla scheda decide, per ogni evento, su quali canali arriva l'avviso:

| Evento | Quando |
|---|---|
| Speedtest | cambio di stato OK / WARNING / ALERT / DOWN, rientro, promemoria |
| Temperatura | temperatura massima oltre `[metrics] temp_warning` / `temp_alert`, rientro |
| Disco | disco principale oltre `disk_warning` / `disk_alert`, rientro |
| Servizi | un servizio con *Avvisami* si ferma o riparte |
| Backup database | backup fallito, ritorno a OK |
| IP pubblico | variazione dell'IP |
| Connessione (ping) | interruzione (DOWN), degrado (WARNING), ripristino con durata |
| Scadenze | certificato o token GitHub in scadenza (15 / 3 giorni), rinnovo |
| Container Docker | container con riavvio automatico fermo o in riavvio continuo, *unhealthy* |
| Pi-hole | blocco disattivato, Pi-hole che non risponde |

Un avviso parte su un canale solo se il canale è **attivo** e l'evento è **instradato** su
quel canale. Gli stessi interruttori per lo speedtest compaiono anche nella scheda Speedtest.

## Regola: solo al cambio di stato

Ogni controllo ha uno stato salvato in `monitor_state` (chiave `alert:<nome>`). L'avviso
parte quando lo stato cambia, quando resta anomalo e sono passate `reminder_hours` ore
dall'ultimo invio, oppure al primo avvio se lo stato è già anomalo.

## Email

Server SMTP, porta, sicurezza (SSL, STARTTLS, nessuna), utente, password, mittente,
destinatari e prefisso dell'oggetto si modificano da **Impostazioni → Notifiche → Email**.
La sezione `[email]` del config fornisce solo i valori iniziali.

Per Gmail serve una **password per le app**: https://myaccount.google.com/apppasswords

## Telegram (consigliato)

È il canale più affidabile: API ufficiale, gratuita, nessun limite pratico per questo uso.

1. In Telegram apri **@BotFather**, invia `/newbot`, scegli nome e username del bot.
   BotFather risponde con il **token** (formato `123456789:AA…`).
2. Apri la chat con il tuo nuovo bot e inviagli un messaggio qualsiasi (es. `ciao`):
   un bot non può scriverti finché non lo contatti tu.
3. Ricava il **Chat ID** (finestra SSH su <server>; il token non resta nella cronologia):
   ```bash
   read -rsp 'Token del bot: ' T; echo
   curl -s "https://api.telegram.org/bot$T/getUpdates" | python3 -c "import json,sys; [print(u['message']['chat']['id'], u['message']['chat'].get('first_name','')) for u in json.load(sys.stdin)['result'] if 'message' in u]"
   unset T
   ```
   Il numero stampato è il Chat ID.
4. In **Impostazioni → Notifiche**: incolla token e Chat ID, attiva Telegram, **Salva
   notifiche**, poi **Invia prova**.
5. Nella tabella in fondo scegli quali eventi mandare su Telegram e salva.

## WhatsApp (tramite CallMeBot)

WhatsApp non offre un'API gratuita per inviare messaggi a sé stessi; si usa **CallMeBot**,
un servizio gratuito di terze parti pensato per questo. Funziona bene per avvisi personali,
ma non ha garanzie di servizio: tieni Telegram o l'email come canale principale.

1. Segui le istruzioni su https://www.callmebot.com/blog/free-api-whatsapp-messages/:
   aggiungi il numero del bot indicato nella pagina ai contatti del telefono e inviagli,
   via WhatsApp, il messaggio `I allow callmebot to send me messages`.
2. Il bot risponde con la tua **API key**.
3. In **Impostazioni → Notifiche**: numero con prefisso internazionale **senza +**
   (es. `39333…`), API key, attiva WhatsApp, **Salva notifiche**, **Invia prova**.

## ntfy, Gotify, Discord, webhook

| Canale | Cosa serve | Note |
|---|---|---|
| **ntfy** | server (`https://ntfy.sh` o il proprio) e un **argomento** (topic); token facoltativo per server o argomenti protetti | sul telefono: app ntfy, *Iscriviti all'argomento*. Su ntfy.sh pubblico l'argomento è l'unica protezione: sceglilo lungo e difficile da indovinare |
| **Gotify** | indirizzo del server e **token di un'applicazione** (Gotify → Apps → Create application) | priorità alta per ALERT, DOWN e backup falliti |
| **Discord** | **URL del webhook** del canale (Impostazioni del canale → Integrazioni → Webhook → Nuovo webhook → Copia URL) | messaggi oltre 2000 caratteri vengono troncati |
| **Webhook** | URL che riceve un `POST` JSON; segreto facoltativo inviato come `Authorization: Bearer …` | per Home Assistant, n8n, Node-RED o script propri |

Corpo del webhook generico:
```json
{"source": "disk", "subject": "Disco: WARNING", "body": "…", "host": "server", "time": "2026-11-01T10:00:00", "version": "3.1.0"}
```
Ogni canale si attiva e si prova da **Impostazioni → Notifiche**, e si sceglie per quali eventi usarlo nella
tabella *Quali avvisi su quali canali*. URL dei webhook e token sono trattati come segreti.

## Comandi dal bot Telegram

Con **Rispondi ai comandi** attivo (riquadro Telegram), il servizio `astreo-telegram.service`
risponde nella chat configurata:

| Comando | Risposta |
|---|---|
| `/stato` | CPU, RAM, disco, temperatura, connessione, servizi fermi, allarmi attivi |
| `/connessione` | ping per destinazione, disponibilità delle ultime 24 ore, ultimo speedtest |
| `/speedtest` | avvia uno speedtest e, dopo circa un minuto, invia il risultato |
| `/servizi` | stato di ogni servizio monitorato |
| `/controlli` | dischi, aggiornamenti, scadenze, backup, verifica del ripristino, heartbeat |
| `/aiuto` | elenco dei comandi |

Il bot risponde **solo** ai messaggi della chat impostata come Chat ID; i comandi da altre chat
vengono ignorati e registrati nel journal (`journalctl -u astreo-telegram`). Nei gruppi scrivi i
comandi così come sono o nella forma `/stato@astreo_monitor_bot`. Telegram mostra il menu dei
comandi toccando `/` nella chat.

Nota: con il servizio attivo, i comandi manuali `getUpdates` (usati per ricavare il Chat ID)
restituiscono un elenco vuoto, perché i messaggi li riceve il bot. Per ricavare un nuovo Chat ID
ferma prima il servizio: `sudo systemctl stop astreo-telegram.service`.

## Riepilogo settimanale

Ogni lunedì alle 08:00 (`astreo-summary.timer`), sui canali scelti per l'evento **Riepilogo
settimanale**: disponibilità e interruzioni, speedtest, CPU, RAM, disco e temperatura, avvisi
inviati per tipo, backup e verifica del ripristino, dischi, aggiornamenti, scadenze.
Il pulsante **Invia ora il riepilogo settimanale** lo manda subito, come prova.

## Segreti

Token Telegram e API key WhatsApp sono salvati nel database (`app_settings`) e non vengono
mai restituiti alla pagina, che mostra solo le ultime 4 cifre. Per cambiarli scrivi il nuovo
valore; lasciando il campo com'è il valore resta invariato.

## Registro degli invii

La scheda mostra gli ultimi 30 invii (canale, evento, esito ed eventuale errore), dalla
tabella `notification_log` (conservata 180 giorni). Un invio fallito non interrompe mai il
job che lo ha generato.

Dal client SQL:
```sql
SELECT TOP 50 * FROM astreo_monitor.dbo.notification_log ORDER BY [timestamp] DESC;
SELECT [key], [value], updated_at FROM astreo_monitor.dbo.monitor_state WHERE [key] LIKE 'alert:%';
```

## Prova da riga di comando

```bash
cd ~/Astreo_Monitor_Services
.venv/bin/python -m astreo_monitor.jobs.test_email --config /etc/astreo-monitor/config.ini
```
