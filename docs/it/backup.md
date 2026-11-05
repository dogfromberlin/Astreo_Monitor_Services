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
Esito, copie ed **Esegui backup ora** nella sezione **Backup** (anche nella Panoramica, riquadro *Sicurezza dei
dati*); destinazioni rclone in **Impostazioni → Backup**; avviso con l'evento *Backup database*, anche nel riepilogo.

<a id="destinazioni"></a>
## Destinazioni

| Destinazione | Dove si imposta | Quanti backup si conservano |
|---|---|---|
| Cartella locale | `[backup] local_dir` | `local_keep` (predefinito 7) |
| GitHub (Release di un repository **privato**), facoltativa | **Impostazioni → Backup → Copia su GitHub**, con la CLI `gh` autenticata | a scelta (predefinito 30) |
| rclone: NAS, cartella di rete, SFTP, Backblaze B2, S3, Google Drive… | **Impostazioni → Backup** | per destinazione (predefinito 30) |

Una copia non riuscita rende il backup **ALERT**, anche se la copia locale è andata bene.

<a id="github"></a>
### Copia su GitHub

Facoltativa: si attiva in **Impostazioni → Backup → Copia su GitHub** con il repository (`proprietario/nome`) e il
numero di backup da conservare; **Prova GitHub** controlla che `gh` sia installato e autenticato per l'utente dei
servizi e che il repository sia raggiungibile (e avvisa se è pubblico). `[backup] github_repo` e `github_keep` di
`config.ini` valgono solo come valori iniziali.

<a id="nessun-backup"></a>
### Avviso «nessun backup»

La copia locale sta sullo stesso disco del database e non protegge da un suo guasto: finché non c'è almeno una copia
**fuori dal server** (GitHub o rclone) la Panoramica mostra l'avviso *Nessun backup fuori dal server*, anche in *Da
controllare*. Con una destinazione configurata ma senza ancora un backup riuscito l'avviso diventa *in attesa del
primo backup riuscito*; sparisce da solo al primo backup che arriva fuori dal server e ricompare se in seguito si
tolgono tutte le destinazioni.

| Pulsante | Effetto |
|---|---|
| Ricordamelo più tardi | lo nasconde fino alla prossima apertura della dashboard |
| Lascia l'avviso | lo tiene, in forma ridotta, finché un backup fuori dal server non riesce |
| Non mostrare più | lo spegne per tutti (solo amministratore); si riattiva in **Impostazioni → Backup** |

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
