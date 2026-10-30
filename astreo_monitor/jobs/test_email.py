"""Invia una email di prova per verificare la configurazione SMTP."""
from __future__ import annotations

import datetime as dt
import logging
import socket

from .. import __version__, db, notifier
from .. import settings as settings_mod
from ..config import Config
from .base import run

log = logging.getLogger("job.test_email")


def main(cfg: Config, dry_run: bool) -> int:
    email = cfg.email
    try:
        with db.connect(cfg.database) as conn:
            email = settings_mod.email_config(cfg, settings_mod.load(conn, cfg))
    except db.DatabaseError as exc:
        log.warning("Impostazioni email non leggibili dal DB, uso il config: %s", exc)
    if dry_run:
        log.info("Dry-run: invierei a %s tramite %s:%s (%s)", email.recipients, email.smtp_host, email.smtp_port, email.security)
        return 0
    ok = notifier.send_email(
        email,
        "Email di prova",
        f"Email di prova inviata da Astreo Monitor {__version__} su {socket.gethostname()} "
        f"alle {dt.datetime.now():%d/%m/%Y %H:%M}.\n\nSe la leggi, la configurazione SMTP funziona.",
    )
    return 0 if ok else 1


def entrypoint() -> None:
    run("test_email", "Invia una email di prova", main)


if __name__ == "__main__":
    entrypoint()
