"""Invia una email di prova per verificare la configurazione SMTP."""
from __future__ import annotations

import datetime as dt
import logging
import socket

from .. import __version__, notifier
from ..config import Config
from .base import run

log = logging.getLogger("job.test_email")


def main(cfg: Config, dry_run: bool) -> int:
    if dry_run:
        log.info("Dry-run: invierei a %s tramite %s:%s (%s)", cfg.email.recipients, cfg.email.smtp_host, cfg.email.smtp_port, cfg.email.security)
        return 0
    ok = notifier.send_email(
        cfg.email,
        "Email di prova",
        f"Email di prova inviata da Astreo Monitor {__version__} su {socket.gethostname()} "
        f"alle {dt.datetime.now():%d/%m/%Y %H:%M}.\n\nSe la leggi, la configurazione SMTP funziona.",
    )
    return 0 if ok else 1


def entrypoint() -> None:
    run("test_email", "Invia una email di prova", main)


if __name__ == "__main__":
    entrypoint()
