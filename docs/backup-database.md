# Backup dei database

Job: `astreo_monitor.jobs.db_backup` — timer `astreo-backup.timer`, ogni notte alle 02:30.
Se astreo è spento a quell'ora, il backup parte al riavvio (`Persistent=true`).

## Cosa fa

Per ogni database in `[backup] databases` (oggi `astreo_monitor` e `<altro-database>`):

1. `BACKUP DATABASE ... WITH COPY_ONLY, CHECKSUM` in `/srv/sqlbackup`. `COPY_ONLY` non
   interferisce con eventuali altre catene di backup.
2. `RESTORE VERIFYONLY ... WITH CHECKSUM`: verifica che il file sia leggibile e integro.
3. Compressione **zstd** (SQL Server Express non ha la compressione nativa) in
   `/home/<utente>/backups/sql/backup-AAAAMMGG-HHMMSS/<database>.bak.zst`; il `.bak`
   non compresso viene eliminato.
4. Calcolo SHA-256.

Poi scrive nella stessa cartella `SHA256SUMS` e `manifest.json` (database, dimensioni,
hash, versione SQL Server) e pubblica tutto come **Release** nel repository privato
`dogfromberlin/<repository-backup>`, con tag `backup-AAAAMMGG-HHMMSS`.

Retention: ultime `local_keep` (7) cartelle su astreo, ultime `github_keep` (30) Release su GitHub.

### Perché Release e non commit
Git conserva per sempre ogni versione di ogni file: con un backup binario al giorno il
repository crescerebbe senza limite, e GitHub rifiuta i file sopra i 100 MB. Le Release
accettano allegati grandi e si possono eliminare, quindi la retention funziona davvero.

## Esito e notifiche

- Stato salvato in `monitor_state` (chiave `backup:last`), visibile nella testata della
  dashboard alla voce *Ultimo backup*.
- Email **solo** se il backup fallisce (anche parzialmente) e quando torna OK, più un
  promemoria ogni `reminder_hours` se resta in errore. Vedi [notifiche.md](notifiche.md).
- Se l'upload su GitHub fallisce, la copia locale resta e lo stato è ALERT.

## Prerequisiti (già fatti all'installazione)

**SSH** — cartella condivisa tra SQL Server e `<utente>`:
```bash
sudo mkdir -p /srv/sqlbackup
sudo chown mssql:<utente> /srv/sqlbackup
sudo chmod 2770 /srv/sqlbackup
```
**SQL** — `sql/004_backup.sql` (ruolo `db_backupoperator` e permesso `CREATE DATABASE`
in master, richiesto da `RESTORE VERIFYONLY`).
**GitHub** — repository privato `<repository-backup>` con almeno un commit; il token usato
da `gh` deve avere *Contents: Read and write* su di esso.

## Comandi (finestra SSH su astreo)

```bash
cd ~/Astreo_Monitor_Services
# controlli senza fare il backup: database, cartelle, zstd, accesso a GitHub
.venv/bin/python -m astreo_monitor.jobs.db_backup --config /etc/astreo-monitor/config.ini --dry-run
# backup immediato
sudo systemctl start astreo-backup.service
journalctl -u astreo-backup.service -n 30 --no-pager
# elenco backup
ls -la /home/<utente>/backups/sql
gh release list --repo dogfromberlin/<repository-backup>
```

Per aggiungere un database: aggiungilo in `[backup] databases` e, nel client SQL, esegui
per quel database il blocco 2 di `sql/004_backup.sql` (con il suo nome al posto di `<altro-database>`).

---

## Verifica mensile del ripristino

Job `astreo_monitor.jobs.restore_test`, timer `astreo-restoretest.timer` (prima domenica del mese
alle 04:30). Per ogni database dell'ultimo backup locale:

1. controlla l'hash con `SHA256SUMS`;
2. ripristina il backup in un database temporaneo `astreo_restoretest_<nome>`, con `CHECKSUM`;
3. esegue `DBCC CHECKDB`;
4. conta tabelle e righe;
5. elimina il database temporaneo e il file decompresso.

I database in uso non vengono mai toccati. Per controllare ed eliminare i database temporanei
senza dare all'utente applicativo permessi di amministratore, `sql/008_verifica_ripristino.sql`
crea due procedure in `master`, firmate con un certificato, che accettano **solo** nomi
`astreo_restoretest_*`.

Esito nella vista **Server → Controlli** e avviso (evento *Verifica del ripristino*).
Esecuzione immediata:
```bash
sudo systemctl start astreo-restoretest.service
journalctl -u astreo-restoretest.service -n 20 --no-pager
```

## Ripristino

Il ripristino si fa con l'utente `sa` dal client SQL. Le finestre sono le stesse:
**SSH** su astreo e **SQL** nel client.

### 1. Scegli e prepara il file

**Da copia locale** (ultimi 7 giorni) — **SSH**:
```bash
ls -la /home/<utente>/backups/sql
cd /home/<utente>/backups/sql/backup-AAAAMMGG-HHMMSS      # sostituisci con la cartella scelta
sha256sum -c SHA256SUMS
zstd -d astreo_monitor.bak.zst -o /srv/sqlbackup/restore_astreo_monitor.bak
ls -la /srv/sqlbackup
```

**Da GitHub** (ultimi 30 giorni) — **SSH**:
```bash
gh release list --repo dogfromberlin/<repository-backup>
mkdir -p /tmp/restore && cd /tmp/restore
gh release download backup-AAAAMMGG-HHMMSS --repo dogfromberlin/<repository-backup> --dir /tmp/restore
sha256sum -c SHA256SUMS
zstd -d astreo_monitor.bak.zst -o /srv/sqlbackup/restore_astreo_monitor.bak
ls -la /srv/sqlbackup
```
`sha256sum -c` deve rispondere `OK` per ogni file.

### 2a. Ripristino di prova con un altro nome (consigliato prima di tutto)

Non tocca il database in uso. **SQL**:
```sql
RESTORE FILELISTONLY FROM DISK = N'/srv/sqlbackup/restore_astreo_monitor.bak';
GO
RESTORE DATABASE astreo_monitor_restore
FROM DISK = N'/srv/sqlbackup/restore_astreo_monitor.bak'
WITH MOVE N'astreo_monitor'     TO N'/var/opt/mssql/data/astreo_monitor_restore.mdf',
     MOVE N'astreo_monitor_log' TO N'/var/opt/mssql/data/astreo_monitor_restore_log.ldf',
     RECOVERY, STATS = 25;
GO
SELECT COUNT(*) AS righe, MAX([timestamp]) AS ultimo FROM astreo_monitor_restore.dbo.system_metrics;
GO
```
I nomi dopo `MOVE` sono i *LogicalName* restituiti da `RESTORE FILELISTONLY`
(per `astreo_monitor` sono `astreo_monitor` e `astreo_monitor_log`).
Terminata la verifica: `DROP DATABASE astreo_monitor_restore;`

### 2b. Ripristino sopra il database in uso

Ferma prima chi scrive nel database. **SSH**:
```bash
sudo systemctl stop astreo-monitor-web.service astreo-metrics.timer astreo-speedtest.timer astreo-publicip.timer astreo-maintenance.timer astreo-backup.timer
```
**SQL**:
```sql
USE master;
GO
ALTER DATABASE astreo_monitor SET SINGLE_USER WITH ROLLBACK IMMEDIATE;
GO
RESTORE DATABASE astreo_monitor
FROM DISK = N'/srv/sqlbackup/restore_astreo_monitor.bak'
WITH REPLACE, RECOVERY, STATS = 25;
GO
ALTER DATABASE astreo_monitor SET MULTI_USER;
GO
```
Il login `astreo_monitor_app` resta valido: l'utente nel database è legato al login
tramite SID, e il backup viene dallo stesso server.

**SSH** — riavvia e pulisci:
```bash
sudo systemctl start astreo-monitor-web.service astreo-metrics.timer astreo-speedtest.timer astreo-publicip.timer astreo-maintenance.timer astreo-backup.timer
curl -s http://127.0.0.1:5025/api/v1/health; echo
rm -f /srv/sqlbackup/restore_astreo_monitor.bak
rm -rf /tmp/restore
```

Per `<altro-database>` la procedura è identica: file `<altro-database>.bak.zst`, *LogicalName* letti da
`RESTORE FILELISTONLY`, e in 2b fermando le applicazioni che lo usano invece dei servizi astreo.

### Ripristino su un altro server
Serve SQL Server 2025 (17.x) o successivo. Dopo il `RESTORE`, se l'utente applicativo
non riesce ad accedere, ricollegalo al login del nuovo server:
```sql
USE astreo_monitor;
ALTER USER astreo_monitor_app WITH LOGIN = astreo_monitor_app;
```
