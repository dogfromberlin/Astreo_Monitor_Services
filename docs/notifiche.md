# Notifiche email

Tutte le email passano da `astreo_monitor/notifier.py`, configurato in `[email]`.

## Regola: solo al cambio di stato

Ogni controllo (speedtest, temperatura, disco) ha uno stato salvato in
`monitor_state` (chiave `alert:<nome>`). Si invia un'email quando:

1. lo stato cambia (es. OK → WARNING, ALERT → OK);
2. lo stato resta anomalo e sono passate `reminder_hours` ore dall'ultima email
   (0 = nessun promemoria);
3. al primo avvio, solo se lo stato è già anomalo.

L'IP pubblico invia un'email a ogni variazione verificata.

| Mittente logico | Oggetto | Interruttore |
|---|---|---|
| Speedtest | `Connessione internet: WARNING/ALERT/DOWN`, `Connessione internet tornata OK` | `[speedtest] notify` |
| Temperatura | `Temperatura: WARNING/ALERT`, `Allarme temperatura rientrato` | `[metrics] notify` |
| Disco | `Disco: WARNING/ALERT`, `Allarme disco rientrato` | `[metrics] notify` |
| IP pubblico | `IP pubblico cambiato in x.x.x.x` | `[publicip] notify` |
| Prova | `Email di prova` | comando manuale |

`[email] enabled = false` blocca tutto. Con `notify = false` gli stati vengono
comunque registrati, così alla riattivazione non partono email per situazioni già note
(salvo il promemoria).

Le email della 1.x eliminate: mail a ogni speedtest, mail giornaliera alla rotazione
del log, mail con il log allegato a ogni errore.

## Verifica (finestra SSH su astreo)

```bash
cd ~/Astreo_Monitor_Services
.venv/bin/python -m astreo_monitor.jobs.test_email --config /etc/astreo-monitor/config.ini
```

Un invio fallito non interrompe il job: compare nel journal come `ERROR ... Invio email fallito`.

Stato degli allarmi (client SQL):
```sql
SELECT [key], [value], updated_at FROM astreo_monitor.dbo.monitor_state WHERE [key] LIKE 'alert:%';
```

## Gmail

Serve una **password per le app** (richiede la verifica in due passaggi):
https://myaccount.google.com/apppasswords → nome "astreo-monitor" → copiare i 16 caratteri
(senza spazi) in `[email] password`. Per revocarla si usa la stessa pagina.
