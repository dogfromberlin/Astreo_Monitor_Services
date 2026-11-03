# HTTPS and terminal

<a id="certificato"></a>
## Certificate from a private CA

With HTTPS, the installer creates with mkcert a **private CA** (in `/etc/astreo-monitor/ca/`, root only) and a
certificate for the server's IPs and names. Once the CA is installed on a device, the browser treats the
dashboard as a secure site: no warnings, and a smartphone can install it as an app.

The public copy of the CA is downloaded from `https://<server>:5443/astreo-ca.crt` (link *CA certificate* at the
bottom of the dashboard).

| Device | Installation |
|---|---|
| Windows (Chrome, Edge) | open the file → **Install certificate** → **Current user** → *Place all certificates in the following store* → **Trusted Root Certification Authorities** → **Finish** → **Yes**; reopen the browser |
| Firefox | *Settings → Privacy & Security → Certificates → View certificates → Authorities → Import*, tick *identify websites* |
| Android | *Settings → Security → Encryption & credentials → Install a certificate → CA certificate* (names vary between manufacturers) |
| iPhone / iPad | open the file in Safari → *Settings → Profile downloaded → Install*, then *General → About → Certificate Trust Settings* and enable the CA |

The CA's private key can create certificates trusted by your devices: do not copy it elsewhere.

<a id="rinnovo"></a>
## Renewing the certificate (or changing IPs and names)

The certificate lasts about 2 years; the expiry check warns at 15 and 3 days. To renew it (or after changing
`server_ips` / `server_names` in `/etc/astreo-monitor/install.ini`) move the current one away and run the HTTPS
setup again, which creates a new one with the same CA:
```bash
sudo mv /etc/nginx/ssl/astreo.crt /etc/nginx/ssl/astreo.crt.old
sudo mv /etc/nginx/ssl/astreo.key /etc/nginx/ssl/astreo.key.old
cd Astreo_Monitor_Services
sudo bash update.sh --enable-https
```
The paths are those of `cert_file` and `key_file` in `install.ini`. Nothing needs to be reinstalled on the devices.

<a id="terminale"></a>
## Web terminal

A shell in the browser (ttyd behind nginx) as the service user. Since it means control of the server, it opens
only if **all** these conditions hold:

| Protection | How |
|---|---|
| Encrypted connection | HTTPS only; unlocking is refused over HTTP |
| Second password | different from the dashboard one (`[terminal] password_hash`) |
| Expiring session | closes after `session_minutes` (default 15) without activity, with *Close terminal* or closing the tab |
| Allowed networks | `[terminal] allowed_networks`: LAN and VPN only |
| Limited attempts | 5 wrong passwords every 15 minutes per IP |
| ttyd not exposed | listens locally only and requires an internal credential known only to nginx |

To change the terminal password:
```bash
.venv/bin/python -c "import getpass; from werkzeug.security import generate_password_hash as g; print(g(getpass.getpass('Terminal password: ')))"
```
and copy the printed line into `[terminal] password_hash`, then `sudo systemctl restart astreo-monitor-web.service`.

<a id="problemi-terminale"></a>
## If the terminal does not open

| Message | Cause |
|---|---|
| *works only over an encrypted connection* | page opened over HTTP: use the `https://` address |
| *address … not allowed* | IP outside `allowed_networks` |
| *Too many wrong attempts* | wait 15 minutes |
| black box without a prompt | `astreo-terminal.service` stopped: `systemctl status astreo-terminal.service` |
| `ERROR on binding … 7681` in the log | the port is taken by the ttyd package service: `sudo systemctl disable --now ttyd.service` |
