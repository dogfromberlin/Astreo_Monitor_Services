# Backups

Every night the database is backed up locally (and optionally to a private GitHub repository as a release),
then verified; once a month the latest backup is restored into a temporary database and checked.

## Copies with rclone

Each backup can also be copied to one or more destinations with [rclone](https://rclone.org): NAS or network
share, SFTP, Backblaze B2, S3, Google Drive, OneDrive… Every copy is **verified** (`rclone check`) and the last N
backups (default 30) are kept on each destination.

1. As the **service user**: `sudo apt install -y rclone`, then `rclone config` to create a remote (e.g. `nas`
   of type `smb`, `b2`, `sftp`, `drive`…). A mounted disk or share needs no remote: use its absolute path.
   Keep `~/.config/rclone/rclone.conf` private (`chmod 600`).
2. **Settings → Backup**: one destination per line (`remote:path` or an absolute path), how many backups to keep,
   **Test destinations**, **Save**. **Run backup now** starts a backup immediately.

A failed copy turns the backup into **ALERT** (alert *Database backup*), even if the local copy succeeded.
