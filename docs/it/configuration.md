# Configurazione e utenti

<a id="file"></a>
## Il file di configurazione

`/etc/astreo-monitor/config.ini`, creato dall'installatore (modello di riferimento: `config.example.ini`).
Proprietario l'utente dei servizi, permessi `600`: contiene le credenziali del database. Non va mai messo in git.

Gran parte delle opzioni (soglie, notifiche, servizi, dispositivi, backup…) si modifica dalla dashboard in
**Impostazioni**: nel file restano accesso al database, server web, terminale e valori iniziali.

| Componente | Quando rilegge il file |
|---|---|
| Job (metriche, speedtest, backup…) | a ogni esecuzione |
| Dashboard e bot | all'avvio: dopo una modifica `sudo systemctl restart astreo-monitor-web.service astreo-telegram.service` |

<a id="sezioni"></a>
## Sezioni principali

| Sezione | Chiavi | Note |
|---|---|---|
| `[database]` | `engine` (`mssql`, `postgresql`, `sqlite`), `host`, `port`, `database`, `user`, `password`, `path` (SQLite) | utente dell'applicazione con soli permessi di lettura e scrittura; vedi [Database](database.md) |
| `[web]` | `host`, `port`, `username`, `password_hash`, `trusted_proxy`, `https_port`, `viewer_username`, `viewer_password_hash` | dietro nginx: `host = 127.0.0.1` e `trusted_proxy = 127.0.0.1` |
| `[email]` | valori iniziali | poi da Impostazioni → Notifiche |
| `[services]` | `chiave = unit \| etichetta` | solo elenco iniziale; poi da Impostazioni → Servizi |
| `[metrics]`, `[speedtest]`, `[publicip]` | soglie e parametri iniziali | — |
| `[backup]` | database da salvare, cartella locale, repository GitHub, quante copie conservare | destinazioni rclone da Impostazioni → Backup |
| `[terminal]` | `enabled`, `password_hash`, `session_minutes`, `allowed_networks` | vedi [HTTPS e terminale](https-terminal.md#terminale) |
| `[retention]` | giorni di conservazione per tipo di dato (`0` = per sempre) | vedi [Database](database.md#retention) |
| `[netpulse]` | `token_file` | solo per il widget Windows NetPulse |

<a id="utenti"></a>
## Utenti della dashboard

| Utente | Accesso |
|---|---|
| **Amministratore** (`[web] username`) | tutto |
| **Sola lettura** (`[web] viewer_username`, facoltativo) | viste Server e Connessione; niente Impostazioni, Log, Terminale, processi, dettaglio dei servizi, registro delle notifiche, né modifiche (risposta 403 dal server) |

```bash
sudo .venv/bin/python -m astreo_monitor.users list                  # utenti attuali
sudo .venv/bin/python -m astreo_monitor.users password              # cambia la password dell'amministratore
sudo .venv/bin/python -m astreo_monitor.users viewer famiglia       # crea o aggiorna l'utente in sola lettura
sudo .venv/bin/python -m astreo_monitor.users viewer --remove       # lo elimina
```
Le password sono chieste a terminale e salvate solo come hash; la dashboard viene riavviata da sola.
Il browser ricorda le credenziali: per provare l'utente in sola lettura usa una finestra in incognito.
