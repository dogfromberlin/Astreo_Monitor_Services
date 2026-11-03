# HTTPS e terminale

<a id="certificato"></a>
## Certificato con CA privata

Con HTTPS, l'installatore crea con mkcert una **CA privata** (in `/etc/astreo-monitor/ca/`, solo root) e un
certificato per gli IP e i nomi del server. Installata una volta la CA su un dispositivo, il browser considera la
dashboard un sito sicuro: niente avvisi, e lo smartphone può installarla come app.

La copia pubblica della CA si scarica da `https://<server>:5443/astreo-ca.crt` (link *certificato CA* in fondo
alla dashboard).

| Dispositivo | Installazione |
|---|---|
| Windows (Chrome, Edge) | apri il file → **Installa certificato** → **Utente corrente** → *Colloca tutti i certificati nel seguente archivio* → **Autorità di certificazione radice attendibili** → **Fine** → **Sì**; riapri il browser |
| Firefox | *Impostazioni → Privacy e sicurezza → Certificati → Mostra certificati → Autorità → Importa*, spunta *identificare siti web* |
| Android | *Impostazioni → Sicurezza → Crittografia e credenziali → Installa un certificato → Certificato CA* (i nomi cambiano tra produttori) |
| iPhone / iPad | apri il file in Safari → *Impostazioni → Profilo scaricato → Installa*, poi *Generali → Info → Impostazioni certificati* e attiva la CA |

La chiave privata della CA permette di creare certificati validi per i tuoi dispositivi: non copiarla altrove.

<a id="rinnovo"></a>
## Rinnovare il certificato (o cambiare IP e nomi)

Il certificato dura circa 2 anni; il controllo delle scadenze avvisa a 15 e 3 giorni. Per rinnovarlo (o dopo aver
cambiato `server_ips` / `server_names` in `/etc/astreo-monitor/install.ini`) sposta quello attuale e rilancia la
configurazione HTTPS, che ne crea uno nuovo con la stessa CA:
```bash
sudo mv /etc/nginx/ssl/astreo.crt /etc/nginx/ssl/astreo.crt.vecchio
sudo mv /etc/nginx/ssl/astreo.key /etc/nginx/ssl/astreo.key.vecchio
cd Astreo_Monitor_Services
sudo bash update.sh --enable-https
```
I percorsi sono quelli di `cert_file` e `key_file` in `install.ini`. Sui dispositivi non serve reinstallare nulla.

<a id="terminale"></a>
## Terminale web

Una shell nel browser (ttyd dietro nginx) come utente dei servizi. Poiché equivale al controllo del server, si
apre solo se valgono **tutte** queste condizioni:

| Protezione | Come |
|---|---|
| Connessione cifrata | solo in HTTPS; da HTTP lo sblocco è rifiutato |
| Seconda password | diversa da quella della dashboard (`[terminal] password_hash`) |
| Sessione a scadenza | si chiude dopo `session_minutes` (predefinito 15) senza attività, con *Chiudi terminale* o chiudendo la scheda |
| Reti ammesse | `[terminal] allowed_networks`: solo LAN e VPN |
| Tentativi limitati | 5 password errate ogni 15 minuti per IP |
| ttyd non esposto | ascolta solo in locale e richiede una credenziale interna che conosce solo nginx |

Per cambiare la password del terminale:
```bash
.venv/bin/python -c "import getpass; from werkzeug.security import generate_password_hash as g; print(g(getpass.getpass('Password del terminale: ')))"
```
e copia la riga stampata in `[terminal] password_hash`, poi `sudo systemctl restart astreo-monitor-web.service`.

<a id="problemi-terminale"></a>
## Se il terminale non si apre

| Messaggio | Causa |
|---|---|
| *funziona solo con una connessione cifrata* | pagina aperta in HTTP: usa l'indirizzo `https://` |
| *indirizzo … non ammesso* | IP fuori da `allowed_networks` |
| *Troppi tentativi errati* | attendi 15 minuti |
| riquadro nero senza prompt | `astreo-terminal.service` fermo: `systemctl status astreo-terminal.service` |
| `ERROR on binding … 7681` nel log | la porta è occupata dal servizio del pacchetto ttyd: `sudo systemctl disable --now ttyd.service` |
