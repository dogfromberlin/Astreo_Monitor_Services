# Database

SQL Server su astreo, database `astreo_monitor`, utente applicativo `astreo_monitor_app`
(ruoli `db_datareader` e `db_datawriter`). Gli script in `sql/` vanno eseguiti
come amministratore (`sa`) dal client SQL.

## Tabelle

| Tabella | Scritta da | Contenuto | Indice |
|---|---|---|---|
| `system_metrics` | job metrics | CPU, load, RAM, swap, disco | clustered su `timestamp` |
| `system_temperature` | job metrics | una riga per sensore | clustered su `timestamp` |
| `speedtest_results` | job speedtest | download, upload, latenza, stato, provider | clustered su `timestamp` |
| `public_ip_history` | job public_ip | variazioni dell'IP | clustered su `timestamp` |
| `monitor_state` | tutti i job | stato chiave/valore JSON (IP corrente, allarmi, contatori CPU) | PK su `key` |
| `cpu_percentage` | 1.x (dismessa) | storico CPU, importato in `system_metrics` | eliminabile con 003 |
| `fiber_optic_measurements` | 1.x (dismessa) | storico speedtest, importato in `speedtest_results` | eliminabile con 003 |

Le date sono ora locale di astreo. Nel codice viaggiano in formato ISO e sono
convertite con `CONVERT(..., 126)`: il risultato non dipende dalla lingua del login.

## Script

| File | Quando | Effetto |
|---|---|---|
| `backup.sql` | prima dell'installazione | backup completo in `/var/opt/mssql/data/astreo_monitor_pre_v2.bak` |
| `001_install.sql` | installazione | login/utente dedicati e nuove tabelle; non tocca le esistenti |
| `002_switch.sql` | test e switch | rinomina `timstamp` → `timestamp`, indici, import storico; rieseguibile |
| `003_drop_legacy.sql` | dopo 30 giorni, facoltativo | elimina `cpu_percentage` e `fiber_optic_measurements` |
| `004_backup.sql` | attivazione backup (2.1) | permessi di backup, recovery model SIMPLE per `astreo_monitor`, riduzione del log |

Tutti gli script sono idempotenti.

## Recovery model

`astreo_monitor` è in **SIMPLE** (da `004_backup.sql`): il log transazionale si svuota da
solo e non cresce. Il ripristino è al momento dell'ultimo backup notturno
([backup-database.md](backup-database.md)), adeguato per dati di monitoraggio.

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

Prova senza cancellare (finestra SSH su astreo):
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
