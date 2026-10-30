# Scadenze

Job: `astreo_monitor.jobs.expiry` — timer `astreo-expiry.timer`, ogni giorno alle 09:00
(e all'avvio, se astreo era spento a quell'ora).

## Cosa controlla

| Voce | Come |
|---|---|
| Certificati HTTPS | si collega a ogni `host:porta` in **Impostazioni → Notifiche → Scadenze** (predefiniti `127.0.0.1:5443` dashboard e `127.0.0.1:8081` widget NetPulse) e legge la data di scadenza |
| Token GitHub | chiede a GitHub, tramite `gh`, la scadenza del token usato per push e backup |

Stato per voce: **WARNING** a 15 giorni, **ALERT** a 3 giorni (modificabili). Regola di avviso
iniziale: *solo se peggiora*, con avviso di rientro (*rinnovato*) e promemoria ogni 24 ore.
Lo stato è visibile nella vista **Server → Controlli**.

Esecuzione immediata (finestra SSH su astreo):
```bash
sudo systemctl start astreo-expiry.service
journalctl -u astreo-expiry.service -n 10 --no-pager
```

## Rinnovo del token GitHub

1. **PC**: https://github.com/settings/personal-access-tokens → token **Astreo** →
   **Regenerate token** → scegli la scadenza (consigliata 1 anno) → copia il nuovo valore.
2. **SSH**:
   ```bash
   read -rsp 'Token rigenerato: ' T; echo
   printf '%s' "$T" | gh auth login --hostname github.com --git-protocol https --with-token
   unset T
   gh auth status
   sudo systemctl start astreo-expiry.service
   ```
Il giorno dopo (o subito, con l'ultimo comando) arriva l'avviso *Token GitHub (gh): rinnovato*.

## Rinnovo del certificato HTTPS (autofirmato)

Dashboard (5443) e widget NetPulse (8081) usano lo stesso certificato, `/etc/nginx/ssl/netpulse.crt`.

**SSH**
```bash
sudo cp /etc/nginx/ssl/netpulse.crt /etc/nginx/ssl/netpulse.crt.bak-$(date +%Y%m%d)
sudo cp /etc/nginx/ssl/netpulse.key /etc/nginx/ssl/netpulse.key.bak-$(date +%Y%m%d)
sudo openssl req -x509 -newkey rsa:2048 -nodes -days 825 \
  -subj "/CN=astreo" -addext "subjectAltName=IP:<IP-LAN>,DNS:astreo,DNS:netpulse.local" \
  -keyout /etc/nginx/ssl/netpulse.key -out /etc/nginx/ssl/netpulse.crt
sudo nginx -t && sudo systemctl reload nginx
sudo systemctl start astreo-expiry.service
```
Dopo il rinnovo il browser chiede di nuovo di accettare il certificato. **Controlla il widget
Windows**: se si fida di quel certificato specifico, va aggiornato anche sul PC (vedi la
documentazione del widget NetPulse).
