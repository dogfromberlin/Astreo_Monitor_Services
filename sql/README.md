# Script SQL (solo SQL Server)

Lo schema del database si crea e si aggiorna **automaticamente** con le migrazioni:

```bash
.venv/bin/python -m astreo_monitor.migrate
```

Con SQL Server l'installatore concede anche i permessi per backup e verifica del ripristino. Gli script di
questa cartella servono solo se il database è stato preparato a mano:

| Script | A cosa serve |
|---|---|
| `mssql_permessi_backup.sql` | permessi di backup (`db_backupoperator`) e `CREATE DATABASE` in master per l'utente dell'applicazione |
| `008_verifica_ripristino.sql` | procedure firmate che permettono la verifica mensile del ripristino senza dare permessi di amministratore |
