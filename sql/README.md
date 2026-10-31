# Script SQL (storico)

Dalla versione 3.0 lo schema del database si crea e si aggiorna **automaticamente** con:

```bash
.venv/bin/python -m astreo_monitor.migrate
```

Gli script di questa cartella restano come riferimento delle versioni 2.x e servono ancora
**solo con SQL Server**, per i permessi che le migrazioni non gestiscono:

| Script | A cosa serve ancora |
|---|---|
| `001_install.sql` | creare login e utente dell'applicazione su un'istanza nuova (vedi docs/database.md) |
| `004_backup.sql` | permessi di backup (`db_backupoperator`, `CREATE DATABASE` in master) |
| `008_verifica_ripristino.sql` | procedure firmate per la verifica mensile del ripristino |

Gli altri (002, 003, 005, 006, 007, 009) sono sostituiti dalle migrazioni.
