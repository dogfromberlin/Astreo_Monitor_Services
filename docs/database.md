# Database

Astreo Monitor funziona con **SQL Server** (anche Express), **PostgreSQL** o **SQLite**: si sceglie con
`engine` nella sezione `[database]` del config. Tutto il codice usa lo stesso strato dati
(SQLAlchemy, tabelle definite in `astreo_monitor/models.py`); le parti specifiche per database sono
solo il raggruppamento per intervalli dei grafici e il backup (`astreo_monitor/backends.py`).

## Creare e aggiornare lo schema

**SSH**
```bash
cd ~/Astreo_Monitor_Services
.venv/bin/python -m astreo_monitor.migrate --status     # stato, senza modificare nulla
.venv/bin/python -m astreo_monitor.migrate              # applica le migrazioni mancanti
```
- **SQL Server / PostgreSQL**: chiede la password dell'amministratore (`sa` / `postgres`, oppure
  `--admin-user NOME`); non viene salvata. Con PostgreSQL concede poi all'utente dell'applicazione i
  permessi sulle tabelle.
- **SQLite**: nessuna credenziale; il file viene creato se non esiste.
- **Database 2.x esistente** (creato con gli script `sql/`): riconosciuto e registrato come schema
  iniziale senza toccare i dati.

Le migrazioni sono in `astreo_monitor/migrations/versions/`. La dashboard e la diagnosi segnalano uno
schema non aggiornato (banner, `/api/v1/health`, `python -m astreo_monitor.schema`).

## Backup e verifica del ripristino per database

| Database | Backup notturno | Verifica mensile del ripristino | Requisiti |
|---|---|---|---|
| SQL Server | `BACKUP DATABASE` + `RESTORE VERIFYONLY`, compresso con zstd | ripristino in un DB temporaneo + `DBCC CHECKDB` | `sql/004` e `sql/008`, cartella `[backup] sql_dir` condivisa con SQL Server |
| PostgreSQL | `pg_dump` formato custom | `pg_restore` in un DB temporaneo | `postgresql-client`; `CREATEDB` all'utente dell'applicazione (altrimenti verifica parziale) |
| SQLite | copia coerente con l'API di backup + `integrity_check`, zstd | decompressione + `integrity_check` | `zstd` |

Con SQL Server si possono salvare più database (`[backup] databases`); con PostgreSQL e SQLite si
salva il database di Astreo Monitor.

## Tabelle

Definite in `astreo_monitor/models.py`.

| Tabella | Scritta da | Contenuto |
|---|---|---|
| `system_metrics` | job metrics | CPU, load, RAM, swap, disco |
| `system_temperature` | job metrics | una riga per sensore |
| `speedtest_results` | job speedtest | download, upload, latenza, stato, provider |
| `public_ip_history` | job public_ip | variazioni dell'IP |
| `monitor_state` | tutti i job | stato chiave/valore JSON (IP corrente, allarmi, contatori CPU) |
| `app_settings` | dashboard | impostazioni modificate da Impostazioni (chiave/valore JSON) |
| `monitored_services` | dashboard | servizi monitorati, etichetta, avviso, ordine |
| `notification_log` | tutti i job | registro degli invii con stato inviata / fallita / in coda (180 giorni) |
| `notification_queue` | tutti i job | avvisi trattenuti dalla fascia di silenzio (30 giorni) |
| `connectivity_samples` | job connectivity | ping al minuto per destinazione (90 giorni) |
| `events` | job metrics | eventi mostrati sui grafici (riavvii, servizi, container, Pi-hole) |
| `alembic_version` | migrate | revisione dello schema |

Le date sono senza fuso orario, nell'ora locale del server.

## SQL Server: recovery model

Per dati di monitoraggio è adeguato il recovery model **SIMPLE**: il log transazionale si svuota da solo
e il ripristino è al momento dell'ultimo backup notturno ([backup-database.md](backup-database.md)):
```sql
ALTER DATABASE astreo_monitor SET RECOVERY SIMPLE;
```

## Retention

Job `astreo_monitor.jobs.maintenance`, timer `astreo-maintenance.timer` (ogni notte alle 03:40).
Cancella a blocchi di 5000 righe i dati più vecchi dei giorni in `[retention]`:

| Chiave | Tabella | Default |
|---|---|---|
| `metrics_days` | `system_metrics` | 365 |
| `temperature_days` | `system_temperature` | 365 |
| `speedtest_days` | `speedtest_results` | 0 (per sempre) |
| `publicip_days` | `public_ip_history` | 0 (per sempre) |

Volumi stimati con 5 minuti di campionamento: circa 105.000 righe/anno in
`system_metrics` e 630.000 in `system_temperature` (6 sensori).

Prova senza cancellare (finestra SSH su <server>):
```bash
cd ~/Astreo_Monitor_Services
.venv/bin/python -m astreo_monitor.jobs.maintenance --config /etc/astreo-monitor/config.ini --dry-run
```

## Query utili

```sql
USE astreo_monitor;
-- ultime metriche
SELECT TOP 10 * FROM system_metrics ORDER BY [timestamp] DESC;
-- media CPU per giorno, ultimi 30 giorni
SELECT CAST([timestamp] AS date) AS giorno, AVG(cpu_pct) AS cpu_media, MAX(cpu_pct) AS cpu_max
FROM system_metrics WHERE [timestamp] >= DATEADD(DAY, -30, SYSDATETIME())
GROUP BY CAST([timestamp] AS date) ORDER BY giorno;
-- dimensione tabelle
SELECT t.name, SUM(p.rows) AS righe FROM sys.tables t
JOIN sys.partitions p ON p.object_id = t.object_id AND p.index_id IN (0,1)
GROUP BY t.name ORDER BY t.name;
```
