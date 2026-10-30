"""Verifica mensile del ripristino: un backup mai ripristinato è un backup non provato.

Per ogni database dell'ultimo backup locale (cartella backup-* in [backup] local_dir):
  1. decomprime il .bak.zst in [backup] sql_dir;
  2. RESTORE DATABASE con un nome temporaneo (astreo_restoretest_<db>), WITH CHECKSUM;
  3. DBCC CHECKDB sul database ripristinato;
  4. conta tabelle e righe;
  5. elimina il database temporaneo e il file.
I database in uso non vengono mai toccati.
"""
from __future__ import annotations

import datetime as dt
import glob
import logging
import os
import subprocess

from .. import db, notifier
from .. import settings as settings_mod
from ..config import Config
from .base import run
from .db_backup import PREFIX, quote_name, sha256

log = logging.getLogger("job.restore_test")
TEST_PREFIX = "astreo_restoretest_"


def latest_backup_dir(local_dir: str) -> str | None:
    dirs = sorted(d for d in glob.glob(os.path.join(local_dir, PREFIX + "*")) if os.path.isdir(d))
    return dirs[-1] if dirs else None


def expected_hashes(folder: str) -> dict[str, str]:
    out = {}
    try:
        with open(os.path.join(folder, "SHA256SUMS"), encoding="utf-8") as f:
            for line in f:
                h, _, name = line.strip().partition("  ")
                out[name] = h
    except OSError:
        pass
    return out


def test_one(conn, zst: str, b, data_path: str) -> dict:
    src_db = os.path.basename(zst).removesuffix(".bak.zst")
    test_db = TEST_PREFIX + "".join(c if c.isalnum() or c == "_" else "_" for c in src_db)
    bak = os.path.join(b.sql_dir, f"{test_db}.bak")
    result = {"database": src_db, "test_db": test_db}
    try:
        res = subprocess.run(["zstd", "-q", "-d", "-f", zst, "-o", bak], capture_output=True, text=True, timeout=b.timeout)
        if res.returncode != 0:
            raise RuntimeError(f"zstd: {(res.stderr or res.stdout).strip()}")
        os.chmod(bak, 0o644)   # SQL Server (utente mssql) deve poterlo leggere

        files = db.query(conn, "RESTORE FILELISTONLY FROM DISK = %s", (bak,))
        moves, params = [], []
        for i, f in enumerate(files):
            ext = "ldf" if f["Type"] == "L" else "mdf" if i == 0 else "ndf"
            moves.append("MOVE %s TO %s")
            params += [f["LogicalName"], os.path.join(data_path, f"{test_db}_{i}.{ext}")]
        db.run_command(conn, "EXEC master.dbo.astreo_restoretest_drop @db = %s", (test_db,))   # residuo di una prova precedente
        db.run_command(conn, f"RESTORE DATABASE {quote_name(test_db)} FROM DISK = %s WITH {', '.join(moves)}, CHECKSUM, RECOVERY",
                       (bak, *params))
        # DBCC CHECKDB e conteggio tramite la procedura firmata (sql/008_verifica_ripristino.sql)
        counts = db.query(conn, "EXEC master.dbo.astreo_restoretest_check @db = %s", (test_db,))
        result.update(status="OK", tables=len(counts), rows=int(sum(c["righe"] for c in counts)),
                      biggest=[{"table": c["tabella"], "rows": int(c["righe"])} for c in
                               sorted(counts, key=lambda c: c["righe"], reverse=True)[:5]])
        log.info("%s: ripristino riuscito, CHECKDB pulito, %d tabelle e %d righe", src_db, result["tables"], result["rows"])
    except Exception as exc:  # noqa: BLE001
        result.update(status="ALERT", error=str(exc)[:400])
        log.error("%s: verifica del ripristino FALLITA: %s", src_db, exc)
    finally:
        try:
            db.run_command(conn, "EXEC master.dbo.astreo_restoretest_drop @db = %s", (test_db,))
        except Exception as exc:  # noqa: BLE001
            log.warning("Database di prova %s non eliminato: %s", test_db, exc)
        if os.path.exists(bak):
            os.remove(bak)
    return result


def main(cfg: Config, dry_run: bool) -> int:
    b = cfg.backup
    if b is None:
        log.error("Sezione [backup] mancante nella configurazione")
        return 2
    now = dt.datetime.now()
    folder = latest_backup_dir(b.local_dir)
    if not folder:
        log.error("Nessun backup locale in %s", b.local_dir)
        results, source = [{"database": "-", "status": "ALERT", "error": f"nessun backup in {b.local_dir}"}], None
    else:
        source = os.path.basename(folder)
        log.info("Backup da verificare: %s", source)
        hashes = expected_hashes(folder)
        results = []
        if dry_run:
            for z in sorted(glob.glob(os.path.join(folder, "*.bak.zst"))):
                ok = hashes.get(os.path.basename(z)) == sha256(z)
                log.info("  %s: hash %s", os.path.basename(z), "corretto" if ok else "DIVERSO")
            return 0
        with db.connect(cfg.database, autocommit=True, timeout=b.timeout) as conn:
            data_path = db.query_one(conn, "SELECT CAST(SERVERPROPERTY('InstanceDefaultDataPath') AS nvarchar(260)) AS p")["p"]
            for z in sorted(glob.glob(os.path.join(folder, "*.bak.zst"))):
                expected = hashes.get(os.path.basename(z))
                if expected and expected != sha256(z):
                    results.append({"database": os.path.basename(z), "status": "ALERT", "error": "hash diverso da SHA256SUMS: file danneggiato"})
                    continue
                results.append(test_one(conn, z, b, data_path))

    status = "ALERT" if any(r["status"] != "OK" for r in results) else "OK"
    with db.connect(cfg.database) as conn:
        values = settings_mod.load(conn, cfg)
        db.state_set(conn, "restoretest:last", {"time": now.isoformat(timespec="seconds"), "status": status,
                                                "backup": source, "results": results})
        state = notifier.AlertState(conn, "restoretest")
        ok, reason, _ = state.evaluate(status, settings_mod.policy(values, "restoretest"))
        if ok:
            subject = "Verifica del ripristino riuscita" if status == "OK" else "Verifica del ripristino FALLITA"
            lines = [f"Backup verificato: {source or 'nessuno'}", ""]
            for r in results:
                lines.append(f"- {r['database']}: " + (f"OK, {r['tables']} tabelle, {r['rows']} righe, CHECKDB pulito"
                                                     if r["status"] == "OK" else f"ERRORE: {r.get('error')}"))
            if notifier.dispatch(conn, cfg, "restoretest", subject, "\n".join(lines), detected_at=now):
                state.mark_notified()
        state.save()
    log.info("Verifica del ripristino: %s", status)
    return 0 if status == "OK" else 1


def entrypoint() -> None:
    run("restore_test", "Ripristina l'ultimo backup in un database temporaneo e lo verifica", main)


if __name__ == "__main__":
    entrypoint()
