# Configurazione

File: `/etc/astreo-monitor/config.ini` (modello: `config.example.ini`).
Proprietario `<utente>`, permessi `600`. Non va mai messo in git.

Il percorso si può cambiare con `--config FILE` oppure con la variabile
`ASTREO_MONITOR_CONFIG` (le unit systemd la impostano già).

## Quando serve un riavvio

- **Job** (metriche, speedtest, IP, pulizia): rileggono il file a ogni
  esecuzione, nessun riavvio.
- **Web**: legge il file all'avvio. Dopo una modifica:
  ```bash
  sudo systemctl restart astreo-monitor-web.service
  ```

## Sezioni

### [database]
| Chiave | Descrizione |
|---|---|
| `host`, `port`, `database` | Server SQL (default porta 1433) |
| `user`, `password` | Utente dedicato `astreo_monitor_app` creato da `sql/001_install.sql` |
| `login_timeout`, `timeout` | Secondi di attesa per connessione e query |

### [email]
| Chiave | Descrizione |
|---|---|
| `enabled` | `false` disattiva tutte le email |
| `sender`, `recipients` | Mittente e destinatari (separati da virgola) |
| `smtp_host`, `smtp_port`, `security` | `ssl` (465), `starttls` (587) o `none` |
| `username`, `password` | Per Gmail: indirizzo e **password per le app** |
| `subject_prefix` | Prefisso dell'oggetto |

Verifica: `.venv/bin/python -m astreo_monitor.jobs.test_email`

### [web]
| Chiave | Descrizione |
|---|---|
| `host`, `port`, `threads` | Indirizzo di ascolto (default `0.0.0.0:5025`) |
| `username` | Utente Basic Auth |
| `password_hash` | Hash della password (mai la password in chiaro) |

Generare l'hash (finestra SSH su astreo):
```bash
cd ~/Astreo_Monitor_Services
.venv/bin/python -c "import getpass; from werkzeug.security import generate_password_hash as g; print(g(getpass.getpass('Nuova password dashboard: ')))"
```
Copiare l'intera riga stampata (inizia con `scrypt:`) dopo `password_hash = `.

### [services]
Una riga per servizio: `chiave = unit systemd | etichetta`. Vedi [servizi.md](servizi.md).

### [metrics]
Soglie degli allarmi su temperatura massima e disco `root_disk`, `notify`,
`reminder_hours`. Vedi [metriche-e-temperature.md](metriche-e-temperature.md).

### [speedtest]
Soglie in Mbps, parametri di misura, `notify`. Vedi [speedtest.md](speedtest.md).

### [publicip]
Elenco provider, timeout, `notify`. Vedi [ip-pubblico.md](ip-pubblico.md).

### [backup]
Database da salvare, cartelle, repository GitHub, retention, compressione e `notify`.
Vedi [backup-database.md](backup-database.md).

### [retention]
Giorni di conservazione per tabella (`0` = per sempre). Vedi [database.md](database.md).
