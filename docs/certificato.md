# Certificato HTTPS (CA privata con mkcert)

La dashboard (porta 5443) usa un certificato firmato da una **CA privata** creata su astreo con
mkcert. Installata una volta la CA su un dispositivo, il browser considera la dashboard un sito
sicuro: niente avvisi, e su Android l'app si installa sulla schermata Home come un'app vera.

| File | Contenuto | Permessi |
|---|---|---|
| `/etc/astreo-monitor/ca/rootCA-key.pem` | chiave privata della CA: chi la possiede può creare certificati validi per i tuoi dispositivi | solo root |
| `/etc/astreo-monitor/ca/rootCA.pem` | certificato pubblico della CA | solo root (cartella) |
| `/etc/astreo-monitor/astreo-ca.crt` | copia pubblica, scaricabile da `https://<IP-LAN>:5443/astreo-ca.crt` | lettura per tutti |
| `/etc/nginx/ssl/astreo.crt`, `astreo.key` | certificato di astreo (circa 2 anni e 3 mesi) | chiave solo root |

Nomi coperti: `<IP-LAN>`, `astreo`, `astreo.local`, `netpulse.local`, `localhost`, `127.0.0.1`
e l'indirizzo VPN del server, se presente al momento della creazione.

## Installare la CA sui dispositivi

**PC Windows (Chrome, Edge e widget NetPulse)**
1. Apri `https://<IP-LAN>:5443/astreo-ca.crt` (l'ultima volta il browser avviserà: conferma).
2. Apri il file scaricato → **Installa certificato** → **Utente corrente** → *Colloca tutti i certificati
   nel seguente archivio* → **Sfoglia** → **Autorità di certificazione radice attendibili** → **Fine** →
   conferma l'avviso di sicurezza con **Sì**.
3. Chiudi e riapri il browser.

In alternativa, da PowerShell (finestra normale, non amministratore):
```powershell
Import-Certificate -FilePath "$HOME\Downloads\astreo-ca.crt" -CertStoreLocation Cert:\CurrentUser\Root
```
Firefox usa un archivio suo: *Impostazioni → Privacy e sicurezza → Certificati → Mostra certificati →
Autorità → Importa*, spunta *Considera attendibile per identificare siti web*.

**Android**
1. Con Chrome apri `https://<IP-LAN>:5443/astreo-ca.crt` e scarica il file.
2. *Impostazioni → Sicurezza e privacy → Altre impostazioni di sicurezza → Crittografia e credenziali →
   Installa un certificato → Certificato CA → Installa comunque* e scegli `astreo-ca.crt`
   (i nomi delle voci cambiano un po' tra produttori: cerca "certificato CA" nelle impostazioni).
3. Android mostra *La rete potrebbe essere monitorata*: è normale per una CA aggiunta dall'utente.
4. Riapri `https://<IP-LAN>:5443/`: niente avviso. Menu ⋮ → **Installa app**.

## Rinnovo del certificato di astreo

Il controllo scadenze avvisa a 15 e 3 giorni. Per rinnovare (finestra SSH su astreo):
```bash
VPNIP=$(ip -4 -o addr show tun0 2>/dev/null | awk '{print $4}' | cut -d/ -f1)
sudo CAROOT=/etc/astreo-monitor/ca mkcert -cert-file /etc/nginx/ssl/astreo.crt -key-file /etc/nginx/ssl/astreo.key \
  <IP-LAN> astreo astreo.local netpulse.local localhost 127.0.0.1 $VPNIP
sudo chmod 600 /etc/nginx/ssl/astreo.key
sudo nginx -t && sudo systemctl reload nginx
sudo systemctl start astreo-expiry.service
```
La CA resta la stessa: sui dispositivi non serve reinstallare nulla.

## Widget NetPulse (porta 8081)

La porta 8081 passa al nuovo certificato solo dopo aver installato la CA sul PC Windows (procedura in
[aggiornamento-2.5.md](aggiornamento-2.5.md), fase B). Il widget accetta il certificato perché Windows
lo considera attendibile; l'indirizzo `https://netpulse.local:8081` resta valido.
