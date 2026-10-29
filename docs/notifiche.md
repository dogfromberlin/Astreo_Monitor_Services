# Notifiche

Tre canali: **Email**, **Telegram**, **WhatsApp**. Si configurano in
**Impostazioni → Notifiche**; ogni canale si attiva e disattiva con il suo interruttore
e ha un pulsante **Invia prova**.

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

Un avviso parte su un canale solo se il canale è **attivo** e l'evento è **instradato** su
quel canale. Gli stessi interruttori per lo speedtest compaiono anche nella scheda Speedtest.

## Regola: solo al cambio di stato

Ogni controllo ha uno stato salvato in `monitor_state` (chiave `alert:<nome>`). L'avviso
parte quando lo stato cambia, quando resta anomalo e sono passate `reminder_hours` ore
dall'ultimo invio, oppure al primo avvio se lo stato è già anomalo.

## Email

Server SMTP, mittente e destinatari restano in `/etc/astreo-monitor/config.ini`,
sezione `[email]` (vedi [configurazione.md](configurazione.md)). Dalla dashboard si attiva
o disattiva il canale e si invia una prova.

Per Gmail serve una **password per le app**: https://myaccount.google.com/apppasswords

## Telegram (consigliato)

È il canale più affidabile: API ufficiale, gratuita, nessun limite pratico per questo uso.

1. In Telegram apri **@BotFather**, invia `/newbot`, scegli nome e username del bot.
   BotFather risponde con il **token** (formato `123456789:AA…`).
2. Apri la chat con il tuo nuovo bot e inviagli un messaggio qualsiasi (es. `ciao`):
   un bot non può scriverti finché non lo contatti tu.
3. Ricava il **Chat ID** (finestra SSH su astreo; il token non resta nella cronologia):
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
