# Backup

<a id="come-funziona"></a>
## How it works

Every night at 02:30 (`astreo-backup.timer`) the database is backed up, **verified**, compressed and copied:

| Database | Backup | Monthly restore check |
|---|---|---|
| SQL Server | `BACKUP DATABASE` + `RESTORE VERIFYONLY`, zstd; several databases with `[backup] databases` | restore into a temporary database + `DBCC CHECKDB` |
| PostgreSQL | `pg_dump` custom format | `pg_restore` into a temporary database (needs the CREATEDB permission) |
| SQLite | consistent copy with the backup API + `integrity_check`, zstd | decompression + `integrity_check` |

Every backup is a `backup-YYYYMMDD-HHMMSS` folder with the files, `SHA256SUMS` and `manifest.json`.
Result and alert (event *Database backup*) in **Settings → Backup**, in the Server view and in the summary.

<a id="destinazioni"></a>
## Destinations

| Destination | Where it is set | How many backups are kept |
|---|---|---|
| Local folder | `[backup] local_dir` | `local_keep` (default 7) |
| GitHub (Releases of a **private** repository) | `[backup] github_repo`, with the `gh` CLI authenticated | `github_keep` (default 30) |
| rclone: NAS, network share, SFTP, Backblaze B2, S3, Google Drive… | **Settings → Backup** | per destination (default 30) |

A failed copy turns the backup into **ALERT**, even if the local copy succeeded.

<a id="rclone"></a>
## Copies with rclone

1. On the server, as the **service user**: `sudo apt install -y rclone`, then `rclone config` to create a remote
   (e.g. `nas` of type `smb`, `b2`, `sftp`, `drive`…). A mounted disk or share needs no remote: just its absolute
   path. Keep the configuration private: `chmod 600 ~/.config/rclone/rclone.conf`.
2. **Settings → Backup**: one destination per line (`remote:path` or absolute path), how many backups to keep,
   **Test destinations**, **Save**. **Run backup now** starts a backup immediately.

Google Drive on a server without a browser: in `rclone config` answer **n** to *auto config* and complete the
authorisation from your PC with `rclone authorize "drive"`.

<a id="verifica"></a>
## Monthly restore check

On the first Sunday of the month at 04:30 (`astreo-restoretest.timer`) the latest local backup is restored into
a temporary database, checked and then deleted. The databases in use are never touched.
On SQL Server it needs the procedures in `sql/008_verifica_ripristino.sql` (created by the installer).

<a id="ripristino"></a>
## Restoring a backup

First verify the files: in the backup folder `sha256sum -c SHA256SUMS` (from GitHub: `gh release download
backup-YYYYMMDD-HHMMSS --repo USER/REPOSITORY`; from rclone: `rclone copy remote:path/backup-… .`).
Stop the services that write to the database:
```bash
sudo systemctl stop astreo-monitor-web.service astreo-telegram.service
sudo systemctl stop 'astreo-*.timer'
```

| Database | Restore |
|---|---|
| SQLite | `zstd -d astreo_monitor.sqlite.zst -o /tmp/r.db` and replace the file set in `[database] path` |
| PostgreSQL | `pg_restore --clean --if-exists --no-owner -h HOST -U USER -d DATABASE astreo_monitor.dump` |
| SQL Server | `zstd -d astreo_monitor.bak.zst -o /srv/sqlbackup/r.bak`, then as `sa`: `RESTORE DATABASE astreo_monitor FROM DISK = N'/srv/sqlbackup/r.bak' WITH REPLACE, RECOVERY` (with the database in `SINGLE_USER`) |

Tip: first try the restore under **another database name**, then restore over the one in use.
Afterwards restart the services (`sudo bash update.sh` realigns them all) and check with the health check.
