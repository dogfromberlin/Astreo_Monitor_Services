# Backup

<a id="come-funziona"></a>
## Come funziona

Ogni notte alle 02:30 (`astreo-backup.timer`) il database viene salvato, **verificato**, compresso e copiato:

| Database | Backup | Verifica mensile del ripristino |
|---|---|---|
| SQL Server | `BACKUP DATABASE` + `RESTORE VERIFYONLY`, zstd; più database con `[backup] databases` | ripristino in un database temporaneo + `DBCC CHECKDB` |
| PostgreSQL | `pg_dump` formato custom | `pg_restore` in un database temporaneo (serve il permesso CREATEDB) |
| SQLite | copia coerente con l'API di backup + `integrity_check`, zstd | decompressione + `integrity_check` |

Ogni backup è una cartella `backup-AAAAMMGG-HHMMSS` con i file, `SHA256SUMS` e `manifest.json`.
Esito e avviso (evento *Backup database*) in **Impostazioni → Backup**, nella vista Server e nel riepilogo.

<a id="destinazioni"></a>
## Destinazioni

| Destinazione | Dove si imposta | Quanti backup si conservano |
|---|---|---|
| Cartella locale | `[backup] local_dir` | `local_keep` (predefinito 7) |
| GitHub (Release di un repository **privato**) | `[backup] github_repo`, con la CLI `gh` autenticata | `github_keep` (predefinito 30) |
| rclone: NAS, cartella di rete, SFTP, Backblaze B2, S3, Google Drive… | **Impostazioni → Backup** | per destinazione (predefinito 30) |

Una copia non riuscita rende il backup **ALERT**, anche se la copia locale è andata bene.

<a id="rclone"></a>
## Copie con rclone

1. Sul server, come **utente dei servizi**: `sudo apt install -y rclone`, poi `rclone config` per creare un remote
   (es. `nas` di tipo `smb`, `b2`, `sftp`, `drive`…). Un disco o una condivisione già montati non richiedono un
   remote: basta il percorso assoluto. Tieni privata la configurazione: `chmod 600 ~/.config/rclone/rclone.conf`.
2. **Impostazioni → Backup**: una destinazione per riga (`remote:percorso` o percorso assoluto), quanti backup
   conservare, **Prova le destinazioni**, **Salva**. **Esegui backup ora** avvia subito un backup.

Google Drive su un server senza browser: in `rclone config` rispondi **n** ad *auto config* e completa
l'autorizzazione dal PC con `rclone authorize "drive"`.

<a id="verifica"></a>
## Verifica mensile del ripristino

La prima domenica del mese alle 04:30 (`astreo-restoretest.timer`) l'ultimo backup locale viene ripristinato in
un database temporaneo, controllato e poi eliminato. I database in uso non vengono mai toccati.
Su SQL Server servono le procedure di `sql/008_verifica_ripristino.sql` (l'installatore le crea).

<a id="ripristino"></a>
## Ripristinare un backup

Prima verifica i file: nella cartella del backup `sha256sum -c SHA256SUMS` (da GitHub: `gh release download
backup-AAAAMMGG-HHMMSS --repo UTENTE/REPOSITORY`; da rclone: `rclone copy remote:percorso/backup-… .`).
Ferma i servizi che scrivono nel database:
```bash
sudo systemctl stop astreo-monitor-web.service astreo-telegram.service
sudo systemctl stop 'astreo-*.timer'
```

| Database | Ripristino |
|---|---|
| SQLite | `zstd -d astreo_monitor.sqlite.zst -o /tmp/r.db` e sostituisci il file indicato in `[database] path` |
| PostgreSQL | `pg_restore --clean --if-exists --no-owner -h HOST -U UTENTE -d DATABASE astreo_monitor.dump` |
| SQL Server | `zstd -d astreo_monitor.bak.zst -o /srv/sqlbackup/r.bak`, poi come `sa`: `RESTORE DATABASE astreo_monitor FROM DISK = N'/srv/sqlbackup/r.bak' WITH REPLACE, RECOVERY` (con il database in `SINGLE_USER`) |

Consiglio: prova prima il ripristino con **un altro nome** di database, poi ripristina sopra quello in uso.
Al termine riavvia i servizi (`sudo bash update.sh` li riallinea tutti) e controlla con la diagnosi.
