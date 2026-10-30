# Terminale web

Vista **Terminale** della dashboard (`https://<IP-LAN>:5443/#terminale`): una shell sul
server come utente **<utente>**, dal browser del PC o dello smartphone.

## Sicurezza

Una shell come `<utente>` (nel gruppo `sudo`) equivale al controllo completo del server.
Per questo il terminale si apre solo se valgono **tutte** queste condizioni:

| Protezione | Come |
|---|---|
| Connessione cifrata | solo tramite nginx in HTTPS (porta 5443); da HTTP la dashboard rifiuta lo sblocco |
| Login della dashboard | Basic Auth, come il resto della pagina |
| Seconda password | password del terminale **diversa** da quella della dashboard (`[terminal] password_hash`) |
| Sessione a scadenza | `session_minutes` (default 15) dallo sblocco, legata all'IP; la shell si chiude anche dopo 15 minuti di inattività (`TMOUT=900`) |
| Reti ammesse | `[terminal] allowed_networks` e le righe `allow` di nginx: solo LAN e VPN |
| Tentativi limitati | 5 password errate ogni 15 minuti per IP, poi blocco temporaneo |
| ttyd non esposto | ascolta solo su `127.0.0.1:7681` e richiede una credenziale interna che conosce solo nginx |
| Origine verificata | ttyd `--check-origin`: rifiuta connessioni websocket partite da altri siti |
| Registro | sblocchi, blocchi, password errate e accessi negati finiscono nel journal |

Riavviare la dashboard chiude tutte le sessioni del terminale.

## Architettura

```
browser --HTTPS--> nginx :5443 ──/──────────> Astreo Monitor (127.0.0.1:5025)
                        │
                        └─/terminal/──> [auth_request → /api/v1/terminal/check]
                                        └─> ttyd (127.0.0.1:7681) → bash -l come <utente>
```

| File | Ruolo |
|---|---|
| `deploy/nginx/astreo-monitor.conf` | sito HTTPS sulla 5443, proxy della dashboard e del terminale |
| `deploy/systemd/astreo-terminal.service` | servizio ttyd |
| `/etc/astreo-monitor/terminal.env` | credenziale interna di ttyd (solo root) |
| `/etc/nginx/snippets/astreo-terminal-auth.conf` | stessa credenziale, che nginx aggiunge alle richieste verso ttyd |

## Uso

1. Apri la vista **Terminale** e inserisci la password del terminale.
2. In alto vedi il tempo rimanente della sessione; **Blocca terminale** la chiude subito.
3. Uscendo dalla vista la shell si chiude: rientrando si riapre una sessione nuova.
4. Su smartphone la testata si riduce per lasciare spazio alla shell; la tastiera del telefono
   funziona normalmente (per Ctrl+C usa una tastiera con tasto Ctrl, es. Hacker's Keyboard).

## Configurazione

```ini
[terminal]
enabled = true
password_hash = scrypt:...          # password del terminale, DIVERSA da quella della dashboard
session_minutes = 15
allowed_networks = <IP-LAN>/24, <IP-VPN>/24
```

Cambiare la password del terminale (finestra SSH su astreo):
```bash
cd ~/Astreo_Monitor_Services
read -rsp 'Nuova password del terminale: ' PW; echo
printf '%s' "$PW" | .venv/bin/python -c "import sys; from werkzeug.security import generate_password_hash as g; print(g(sys.stdin.read()))"
unset PW
nano /etc/astreo-monitor/config.ini        # incolla l'hash in [terminal] password_hash
sudo systemctl restart astreo-monitor-web.service
```

Disattivare il terminale: `enabled = false` in `[terminal]`, riavvio della dashboard e
`sudo systemctl disable --now astreo-terminal.service`.

## Diagnosi

```bash
systemctl status astreo-terminal.service --no-pager
journalctl -u astreo-monitor-web.service --since "1 hour ago" --no-pager | grep -i terminale
journalctl -u astreo-terminal.service -n 30 --no-pager
```

| Messaggio nella vista | Causa |
|---|---|
| *funziona solo con una connessione cifrata* | pagina aperta in HTTP: usa `https://…:5443` |
| *indirizzo … non ammesso* | IP fuori da `allowed_networks` |
| *Troppi tentativi errati* | 5 password errate: attendi 15 minuti |
| riquadro nero senza prompt | `astreo-terminal.service` fermo, o rete non ammessa nelle righe `allow` di nginx |
