"""Pulizia periodica: cancella i dati più vecchi della retention configurata.

Cancellazione a blocchi (per id) per non gonfiare il log delle transazioni.
Retention 0 = conserva per sempre.
"""
from __future__ import annotations

import datetime as dt
import logging

from sqlalchemy import delete, func, or_, select

from .. import db, models
from ..config import Config
from .base import run

log = logging.getLogger("job.maintenance")

BATCH = 5000
TABLES = [
    # (tabella, attributo retention; None = valore fisso)
    (models.system_metrics, "metrics_days"),
    (models.system_temperature, "temperature_days"),
    (models.speedtest_results, "speedtest_days"),
    (models.public_ip_history, "publicip_days"),
    (models.connectivity_samples, "connectivity_days"),
    (models.events, "metrics_days"),
    (models.notification_log, None),
]
NOTIFICATION_LOG_DAYS = 180


def main(cfg: Config, dry_run: bool) -> int:
    for table, attr in TABLES:
        days = getattr(cfg.retention, attr) if attr else NOTIFICATION_LOG_DAYS
        if days <= 0:
            log.info("%s: retention disattivata, nessuna pulizia", table.name)
            continue
        limit = dt.datetime.now() - dt.timedelta(days=days)
        old = table.c.timestamp < limit
        with db.connect(cfg.database) as conn:
            if dry_run:
                n = db.scalar(conn, select(func.count()).select_from(table).where(old))
                log.info("%s: %d righe più vecchie di %d giorni (dry-run, nessuna cancellazione)", table.name, n, days)
                continue
        total = 0
        while True:
            with db.connect(cfg.database) as conn:       # una transazione per blocco
                ids = [r["id"] for r in db.rows(conn, select(table.c.id).where(old).limit(BATCH))]
                if ids:
                    conn.execute(delete(table).where(table.c.id.in_(ids)))
            total += len(ids)
            if len(ids) < BATCH:
                break
        log.info("%s: cancellate %d righe più vecchie di %d giorni", table.name, total, days)

    if not dry_run:
        Q = models.notification_queue
        limit = dt.datetime.now() - dt.timedelta(days=30)
        with db.connect(cfg.database) as conn:
            n = conn.execute(delete(Q).where(or_(Q.c.sent_at < limit, (Q.c.sent_at.is_(None)) & (Q.c.created_at < limit)))).rowcount
        log.info("notification_queue: cancellati %d avvisi recapitati o scaduti da oltre 30 giorni", max(n, 0))
    return 0


def entrypoint() -> None:
    run("maintenance", "Applica la retention cancellando i dati vecchi", main)


if __name__ == "__main__":
    entrypoint()
