# Notifiche

<a id="canali"></a>
## Canali

| Canale | Cosa serve |
|---|---|
| **Email** | server SMTP, porta, sicurezza (SSL 465 / STARTTLS 587), utente e password; con Gmail una *password per le app* |
| **Telegram** (consigliato) | token di un bot (da **@BotFather**, comando `/newbot`) e Chat ID |
| **WhatsApp** | tramite il servizio gratuito CallMeBot: numero con prefisso senza `+` e API key; senza garanzie di servizio |
| **ntfy** | server (`https://ntfy.sh` o il proprio) e argomento; token facoltativo. Su ntfy.sh pubblico l'argomento è l'unica protezione: sceglilo lungo |
| **Gotify** | indirizzo del server e token di un'applicazione |
| **Discord** | URL del webhook del canale |
| **Webhook** | URL che riceve un `POST` JSON (`source`, `subject`, `body`, `host`, `time`, `version`); segreto facoltativo come `Authorization: Bearer` |

Ogni canale si attiva e si prova da **Impostazioni → Notifiche** (**Invia prova**). Token, password e URL dei
webhook sono segreti: non vengono mai mostrati.

<a id="telegram"></a>
## Configurare Telegram

1. In Telegram apri **@BotFather**, invia `/newbot`, scegli nome e username: ricevi il **token**.
2. Scrivi un messaggio qualsiasi al nuovo bot (un bot non può scriverti per primo); per un gruppo, aggiungi il
   bot al gruppo e scrivi `/start@nomedelbot`.
3. Ricava il **Chat ID** (sul server):
   ```bash
   read -rsp 'Token del bot: ' T; echo
   curl -s "https://api.telegram.org/bot$T/getUpdates" | python3 -c "import json,sys; [print(u[k]['chat']['id'], u[k]['chat'].get('title') or u[k]['chat'].get('first_name','')) for u in json.load(sys.stdin)['result'] for k in ('message','my_chat_member') if k in u]"
   unset T
   ```
   Per un gruppo il Chat ID è negativo.
4. **Impostazioni → Notifiche**: token, Chat ID, attiva, **Salva notifiche**, **Invia prova**.

<a id="instradamento"></a>
## Quali avvisi su quali canali

La tabella in fondo alla scheda Notifiche decide, per ogni evento (connessione, speedtest, temperatura, disco,
servizi, backup, IP pubblico, scadenze, dischi, aggiornamenti, verifica del ripristino, dispositivi, Docker,
Pi-hole, riepilogo settimanale), su quali canali arriva.

<a id="regole"></a>
## Regole di avviso

Per ogni monitoraggio:

| Opzione | Significato |
|---|---|
| **Solo se peggiora** | avvisa per OK → WARNING → ALERT/DOWN; nessun avviso se resta uguale o migliora |
| **A ogni cambio** | avvisa a ogni cambio di stato |
| **Avviso di rientro** | avvisa anche quando torna OK |
| **Promemoria (ore)** | ripete l'avviso se la situazione resta anomala per le ore indicate (0 = mai) |
| **Avvisa dopo (min)** | l'avviso parte solo se l'anomalia dura almeno questi minuti di fila (0 = subito) |

Con **Avvisa dopo** un problema che si risolve prima del tempo indicato non manda nulla, né l'avviso né il rientro:
utile per le brevi interruzioni della linea (Connessione a 3 minuti) o per un servizio che si riavvia da solo.
La dashboard e lo storico mostrano comunque ogni anomalia, anche quella di un minuto, e la contano nella
disponibilità. Il promemoria parte solo dopo che è partito il primo avviso.

<a id="cpu-memoria"></a>
## Avvisi di CPU e memoria

Spenti di serie: si attivano in **Impostazioni → Notifiche → Avvisi di CPU e memoria**. Soglie generali (CPU
avviso 90%, allarme 98%; memoria avviso 90%, allarme 97%) valide per tutti i server; ogni server può averne di sue
in **Impostazioni di questo server** ([server collegati](agents.md#impostazioni-server)).

CPU e memoria si misurano ogni 5 minuti, sul centrale e sugli agenti. Le regole *CPU* e *Memoria* hanno di serie
**Avvisa dopo** 15 e 10 minuti: l'avviso parte solo per un carico prolungato, non per i picchi di aggiornamenti o
backup. Per il server centrale l'avviso riporta anche i tre processi che usano più CPU o memoria. Con gli avvisi
attivi, il carico sopra soglia compare anche in *Da controllare*.

<a id="silenzio"></a>
## Fascia di silenzio

Inizio, fine e orario di recapito (es. 23:00–07:00, recapito alle 08:00). Gli avvisi nati nella fascia sono
trattenuti e recapitati all'orario indicato, **un messaggio per canale**, con l'orario di rilevamento.
L'invio di prova non viene mai trattenuto. Il registro degli invii mostra gli avvisi *In coda*.

<a id="heartbeat"></a>
## Heartbeat esterno

Astreo non può avvisarti se è spento o senza rete. L'heartbeat risolve: ogni 5 minuti avvisa un servizio
esterno che è attivo (es. **healthchecks.io**, gratuito); se i segnali smettono di arrivare è il servizio esterno
ad avvisarti. Su healthchecks.io: crea un controllo con periodo 5 minuti e tolleranza 10, copia il *ping URL*
in **Impostazioni → Notifiche → Heartbeat esterno**, attiva e **Invia ping di prova**.

<a id="bot"></a>
## Comandi del bot Telegram

Con **Rispondi ai comandi** attivo, il bot risponde **solo** nella chat configurata (i comandi da altre chat
sono ignorati e registrati):

| Comando | Risposta |
|---|---|
| `/stato` · `/status` | CPU, RAM, disco, temperatura, connessione, servizi fermi, allarmi attivi |
| `/connessione` · `/connection` | ping, disponibilità delle ultime 24 ore, ultimo speedtest |
| `/speedtest` | avvia uno speedtest e invia il risultato |
| `/servizi` · `/services` | stato dei servizi monitorati |
| `/controlli` · `/checks` | dischi, aggiornamenti, scadenze, backup, ripristino, heartbeat, dispositivi |
| `/aiuto` · `/help` | elenco dei comandi |

<a id="riepilogo"></a>
## Riepilogo settimanale

Ogni lunedì alle 08:00, sui canali scelti per *Riepilogo settimanale*: disponibilità e interruzioni, speedtest,
risorse, avvisi inviati, dispositivi, backup e verifica del ripristino, dischi, aggiornamenti, scadenze.
**Invia ora il riepilogo settimanale** lo manda subito, come prova.
