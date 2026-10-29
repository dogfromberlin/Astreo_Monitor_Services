# Impostazioni

Vista **Impostazioni** della dashboard: `http://<IP-LAN>:5025/#impostazioni`.
Tre schede: Speedtest, Notifiche, Servizi.

I valori modificati qui sono salvati nel database (tabelle `app_settings` e
`monitored_services`) e hanno la precedenza sul file di configurazione, che fornisce solo
i valori iniziali. I job leggono le impostazioni a ogni esecuzione: non serve riavviare nulla.

## Speedtest

**Riquadro di stato**: stato (Attivo, Sospeso, Misura in corso), prossima misura
programmata, ultima misura con esito.

| Pulsante | Effetto |
|---|---|
| **Esegui ora** | avvia subito una misura (`astreo-speedtest.service`); il risultato arriva in circa un minuto |
| **Sospendi** | ferma le misure automatiche; la sospensione resta valida anche dopo un riavvio di astreo |
| **Riattiva** | riprende le misure automatiche |

Sospensione: si salva `speedtest.enabled = false` (il job, se parte, esce senza misurare) e
si ferma il timer `astreo-speedtest.timer`, così la *prossima misura* risulta vuota.

**Campi modificabili**

| Gruppo | Campi | Limiti |
|---|---|---|
| Soglie | download e upload, warning e alert (Mbps) | alert ≤ warning |
| Misura | connessioni parallele (1–16), giri (1–10), MB per connessione in download (1–200) e upload (1–100) | il riquadro mostra il traffico generato |
| Avvisi | canali per gli avvisi dello speedtest (Email, Telegram, WhatsApp), promemoria in ore (0 = mai) | |

L'orario delle misure (ogni 4 ore alle :05) resta nel timer systemd: vedi
[speedtest.md](speedtest.md).

### Permesso per Esegui ora / Sospendi

La dashboard gira come utente `<utente>`, che normalmente non può avviare o fermare unit di
sistema. La regola polkit `deploy/polkit/50-astreo-monitor.rules` glielo consente **solo**
per le unit di Astreo Monitor (`astreo-speedtest`, `astreo-metrics`, `astreo-publicip`,
`astreo-backup`, `astreo-maintenance`) e solo per start/stop/restart.

Installazione e verifica (finestra SSH su astreo):
```bash
cd ~/Astreo_Monitor_Services
sudo cp deploy/polkit/50-astreo-monitor.rules /etc/polkit-1/rules.d/
sudo systemctl restart polkit
systemctl --no-ask-password start astreo-metrics.service && echo "Permesso OK"
systemctl --no-ask-password stop nginx.service || echo "Correttamente negato per nginx"
```
Senza la regola i pulsanti rispondono con *manca la regola polkit*; la sospensione viene
comunque salvata.

## Notifiche

Vedi [notifiche.md](notifiche.md): attivazione dei canali, credenziali, *Invia prova*,
tabella **Quali avvisi su quali canali** e registro degli ultimi invii.

## Servizi

Vedi [servizi.md](servizi.md).

## Sicurezza

- Tutte le modifiche richiedono il login della dashboard.
- Sono accettate solo come JSON e solo se l'origine della richiesta è la dashboard stessa
  (protezione da richieste partite da altri siti, che il browser accompagnerebbe con le
  credenziali Basic Auth).
- I valori dei campi segreti (token Telegram, API key WhatsApp) non vengono mai restituiti:
  la dashboard mostra solo le ultime 4 cifre.
- Ogni modifica è registrata nel journal (`journalctl -u astreo-monitor-web | grep Impostazioni`).
