# Database

<a id="motori"></a>
## Database supportati

| Database | Quando sceglierlo | Note |
|---|---|---|
| **SQLite** | installazioni semplici, un solo server | nessun servizio da installare; un file |
| **PostgreSQL** | se lo usi già o vuoi un database "vero" senza licenze | l'installatore lo installa se è sullo stesso server |
| **SQL Server** | se hai già un'istanza (anche Express) | l'installatore crea database e login dell'applicazione |

L'applicazione usa sempre un **utente dedicato** con soli permessi di lettura e scrittura; le credenziali di
amministratore servono solo per creare e aggiornare lo schema e non vengono salvate.

<a id="migrazioni"></a>
## Schema e migrazioni

Lo schema si crea e si aggiorna con migrazioni automatiche (Alembic): `update.sh` le esegue da solo.
```bash
.venv/bin/python -m astreo_monitor.migrate --status     # revisione attuale e ultima disponibile
.venv/bin/python -m astreo_monitor.migrate              # aggiorna (chiede la password di amministratore)
.venv/bin/python -m astreo_monitor.schema               # controlla tabelle, colonne e permessi
```
Se lo schema non è allineato, la dashboard mostra un avviso con il comando da eseguire.

<a id="tabelle"></a>
## Tabelle

| Tabella | Contenuto |
|---|---|
| `system_metrics`, `system_temperature` | risorse e temperature, ogni 5 minuti |
| `speedtest_results`, `connectivity_samples`, `public_ip_history` | connessione |
| `checks`, `check_results` | dispositivi e servizi controllati e loro risultati |
| `events` | eventi mostrati sui grafici |
| `monitored_services`, `app_settings` | servizi monitorati e impostazioni della dashboard |
| `notification_log`, `notification_queue` | registro degli invii e avvisi trattenuti dalla fascia di silenzio |
| `monitor_state` | stato corrente dei controlli (chiave/valore) |
| `hosts` | server collegati (1 = il server centrale), con l'impronta del token di ciascun agente |
| `alembic_version` | revisione dello schema |

<a id="retention"></a>
## Conservazione dei dati

Ogni notte alle 03:40 (`astreo-maintenance.timer`) si eliminano i dati più vecchi dei giorni indicati in
`[retention]`:

| Dati | Chiave | Predefinito |
|---|---|---|
| Risorse, eventi | `metrics_days` | 365 giorni |
| Temperature | `temperature_days` | 365 giorni |
| Speedtest | `speedtest_days` | per sempre (`0`) |
| IP pubblico | `publicip_days` | per sempre (`0`) |
| Controllo della connessione, dispositivi | `connectivity_days` | 90 giorni |

Il registro delle notifiche si conserva 180 giorni, gli avvisi in coda 30.
