"""Verifica mensile del ripristino: un backup mai ripristinato è un backup non provato.

Per ogni file dell'ultimo backup locale (cartella backup-* in [backup] local_dir) controlla
l'hash e lo ripristina in modo specifico per database (vedi astreo_monitor/backends.py):
SQL Server in un DB temporaneo con DBCC CHECKDB, PostgreSQL con pg_restore in un DB
temporaneo, SQLite con integrity_check. I database in uso non vengono mai toccati.
"""
from __future__ import annotations

import datetime as dt
import glob
import logging
import os

from .. import backends, db, i18n, notifier
from .. import settings as settings_mod
from ..config import Config
from .base import run
from .db_backup import PREFIX

log = logging.getLogger("job.restore_test")


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


def main(cfg: Config, dry_run: bool) -> int:
    b = cfg.backup
    if b is None:
        log.error("Sezione [backup] mancante nella configurazione")
        return 2
    now = dt.datetime.now()
    folder = latest_backup_dir(b.local_dir)
    results, source = [], None
    if not folder:
        log.error("Nessun backup locale in %s", b.local_dir)
        results = [{"database": "-", "status": "ALERT", "error": f"nessun backup in {b.local_dir}"}]
    else:
        source = os.path.basename(folder)
        log.info("Backup da verificare: %s", source)
        hashes = expected_hashes(folder)
        for path in sorted(glob.glob(os.path.join(folder, "*"))):
            be = backends.for_file(path)
            if be is None:
                continue
            fname = os.path.basename(path)
            ok_hash = hashes.get(fname) == backends.sha256(path)
            if dry_run:
                log.info("  %s: hash %s", fname, "corretto" if ok_hash else "DIVERSO")
                continue
            if hashes.get(fname) and not ok_hash:
                results.append({"database": fname, "status": "ALERT", "error": "hash diverso da SHA256SUMS: file danneggiato"})
                continue
            if be.kind != cfg.database.engine:
                log.warning("%s: backup di %s, il database attuale è %s: verifica saltata", fname, be.kind, cfg.database.engine)
                continue
            r = be.restore_test(cfg.database, b, path)
            log.log(logging.INFO if r["status"] == "OK" else logging.ERROR, "%s: %s %s", r["database"], r["status"],
                    r.get("check") or r.get("error", ""))
            results.append(r)
        if dry_run:
            return 0

    severity = {"OK": 0, "WARNING": 1, "ALERT": 2}
    status = max((r["status"] for r in results), key=lambda s: severity.get(s, 2), default="ALERT")
    with db.connect(cfg.database) as conn:
        values = settings_mod.load(conn, cfg)
        db.state_set(conn, "restoretest:last", {"time": now.isoformat(timespec="seconds"), "status": status,
                                                "backup": source, "results": results})
        state = notifier.AlertState(conn, "restoretest")
        ok, reason, _ = state.evaluate(status, settings_mod.policy(values, "restoretest"))
        if ok:
            lang = i18n.lang_of(values)
            tr = i18n.translator(lang)
            subject = {"OK": tr("Verifica del ripristino riuscita"), "WARNING": tr("Verifica del ripristino parziale")}.get(
                status, tr("Verifica del ripristino FALLITA"))
            lines = [tr("Backup verificato: {nome}", nome=source or tr("nessuno")), ""]
            for r in results:
                lines.append(f"- {r['database']}: " + (
                    tr("OK, {tabelle} tabelle, {righe} righe, {controllo}", tabelle=r["tables"], righe=r["rows"],
                       controllo=i18n.translate_stored(r.get("check", ""), lang))
                    if r["status"] == "OK" else f"{r['status']}: {i18n.translate_stored(r.get('error') or '', lang)}"))
            if notifier.dispatch(conn, cfg, "restoretest", subject, "\n".join(lines), detected_at=now):
                state.mark_notified()
        state.save()
    log.info("Verifica del ripristino: %s", status)
    return 0 if status == "OK" else 1


def entrypoint() -> None:
    run("restore_test", "Ripristina l'ultimo backup in modo temporaneo e lo verifica", main)


if __name__ == "__main__":
    entrypoint()
