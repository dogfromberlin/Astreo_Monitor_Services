"""Pulizia periodica: cancella i dati più vecchi della retention configurata.

Cancellazione a blocchi (DELETE TOP) per non gonfiare il log transazionale.
Retention 0 = conserva per sempre.
"""
from __future__ import annotations

import logging

from .. import db
from ..config import Config
from .base import run

log = logging.getLogger("job.maintenance")

BATCH = 5000
TABLES = [
    # (tabella, attributo retention)
    ("system_metrics", "metrics_days"),
    ("system_temperature", "temperature_days"),
    ("speedtest_results", "speedtest_days"),
    ("public_ip_history", "publicip_days"),
    ("notification_log", None),  # registro invii: 180 giorni fissi
]
NOTIFICATION_LOG_DAYS = 180


def main(cfg: Config, dry_run: bool) -> int:
    with db.connect(cfg.database) as conn:
        for table, attr in TABLES:
            days = getattr(cfg.retention, attr) if attr else NOTIFICATION_LOG_DAYS
            if days <= 0:
                log.info("%s: retention disattivata, nessuna pulizia", table)
                continue
            where = f"[timestamp] < DATEADD(DAY, -{int(days)}, SYSDATETIME())"
            if dry_run:
                row = db.query_one(conn, f"SELECT COUNT(*) AS n FROM {table} WHERE {where}")
                log.info("%s: %d righe più vecchie di %d giorni (dry-run, nessuna cancellazione)", table, row["n"], days)
                continue
            total = 0
            while True:
                n = db.execute(conn, f"DELETE TOP ({BATCH}) FROM {table} WHERE {where}")
                conn.commit()
                total += max(n, 0)
                if n < BATCH:
                    break
            log.info("%s: cancellate %d righe più vecchie di %d giorni", table, total, days)
        if not dry_run:
            n = db.execute(conn, "DELETE FROM notification_queue WHERE sent_at < DATEADD(DAY, -30, SYSDATETIME()) "
                                 "OR (sent_at IS NULL AND created_at < DATEADD(DAY, -30, SYSDATETIME()))")
            log.info("notification_queue: cancellati %d avvisi recapitati o scaduti da oltre 30 giorni", max(n, 0))
    return 0


def entrypoint() -> None:
    run("maintenance", "Applica la retention cancellando i dati vecchi", main)


if __name__ == "__main__":
    entrypoint()
