# Salute del sistema

<a id="dischi"></a>
## Dischi (SMART)

Ogni 6 ore un servizio di sola lettura (root, senza rete) legge i dati SMART dei dischi; Astreo li valuta senza
privilegi (`astreo-smart-collect.timer` e `astreo-health.timer`).

| Stato | Condizione |
|---|---|
| ALERT | autodiagnosi SMART fallita, settori in attesa o non correggibili, errori del supporto (NVMe) |
| WARNING | settori riallocati, usura dell'SSD oltre la soglia (80 %), temperatura del disco oltre la soglia (60 °C) |
| OK | altrimenti |

Soglie in **Impostazioni → Notifiche → Dischi**. Dettaglio completo sul server: `sudo smartctl -a /dev/sda`.

<a id="aggiornamenti"></a>
## Aggiornamenti di sistema

Stesso controllo, ogni 6 ore: aggiornamenti in sospeso (con quelli di **sicurezza** distinti) e **riavvio
richiesto**. WARNING se ci sono aggiornamenti di sicurezza o serve un riavvio; promemoria settimanale.
Con gli aggiornamenti automatici di Ubuntu attivi, quelli di sicurezza si installano da soli: resta da
segnalare soprattutto il riavvio richiesto.
```bash
sudo apt update && sudo apt upgrade
sudo reboot        # solo se richiesto
```

<a id="scadenze"></a>
## Scadenze

Ogni giorno alle 09:00 (`astreo-expiry.timer`): certificati HTTPS della dashboard (e del widget NetPulse) e
token GitHub usato per il backup. WARNING a 15 giorni, ALERT a 3 (modificabili in **Impostazioni → Notifiche →
Scadenze**), promemoria giornaliero, avviso di rinnovo avvenuto.

<a id="rinnovo-token"></a>
## Rinnovare il token GitHub

1. Su https://github.com/settings/personal-access-tokens: token usato per il backup → **Regenerate token** →
   copia il nuovo valore.
2. Sul server, come utente dei servizi:
   ```bash
   read -rsp 'Token rigenerato: ' T; echo
   printf '%s' "$T" | gh auth login --hostname github.com --git-protocol https --with-token
   unset T
   gh auth status
   sudo systemctl start astreo-expiry.service
   ```

<a id="rinnovo-certificato"></a>
## Rinnovare il certificato HTTPS

Il certificato firmato dalla CA privata dura circa 2 anni. La CA resta la stessa: sui dispositivi non serve
reinstallare nulla. Procedura in [HTTPS e terminale](https-terminal.md#rinnovo).
