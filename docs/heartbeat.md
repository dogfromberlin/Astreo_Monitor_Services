# Heartbeat esterno

Astreo non può avvisarti se è spento, bloccato o senza rete: gli avvisi partono da lui.
Il **heartbeat** risolve il problema: ogni 5 minuti il job delle metriche avvisa un servizio
esterno che astreo è vivo; se i segnali smettono di arrivare è **il servizio esterno** ad
avvisarti (email, Telegram, app).

Consigliato: **healthchecks.io**, gratuito fino a 20 controlli.

## Configurazione di healthchecks.io

1. Registrati su https://healthchecks.io.
2. **Add Check**: nome `astreo`; in *Schedule* imposta **Period 5 minutes** e **Grace 10 minutes**
   (l'avviso parte dopo circa 15 minuti senza segnali).
3. In **Integrations** attiva come vuoi essere avvisato: l'email è già attiva; per Telegram scegli
   *Telegram* e segui le istruzioni (si avvia una chat con il loro bot).
4. Copia il **ping URL** del controllo (`https://hc-ping.com/…`).
5. Nella dashboard: **Impostazioni → Notifiche → Heartbeat esterno**: incolla l'URL, attiva,
   **Salva notifiche**, poi **Invia ping di prova**. Su healthchecks.io il controllo diventa *up*.

## Cosa segnala

| Segnale | Quando | Avviso da healthchecks.io |
|---|---|---|
| ping normale | ogni 5 minuti, se le metriche sono state salvate | nessuno |
| `/fail` | il job gira ma con un problema (es. coda degli avvisi non recapitabile) | subito, *down* |
| nessun ping | astreo spento o bloccato, rete assente, database non raggiungibile | dopo periodo + tolleranza |

Il messaggio inviato contiene CPU, RAM e disco del momento: su healthchecks.io lo vedi nel
registro degli eventi del controllo.

Lo stato dell'ultimo ping è nella vista **Server → Controlli** e sotto il riquadro delle impostazioni.

L'URL di ping è un segreto (chi lo conosce può inviare segnali al tuo controllo): la dashboard
lo conserva nel database e non lo mostra per intero.
