"""Infrastruttura comune ai job: argomenti, configurazione, logging, lock."""
from __future__ import annotations

import argparse
import fcntl
import logging
import os
import sys
import tempfile
from typing import Callable

from .. import config as config_mod
from .. import db
from .. import logging_setup


def run(name: str, description: str, func: Callable[[config_mod.Config, bool], int]) -> None:
    parser = argparse.ArgumentParser(prog=f"astreo_monitor.jobs.{name}", description=description)
    parser.add_argument("-c", "--config", help="File di configurazione (default: $ASTREO_MONITOR_CONFIG o /etc/astreo-monitor/config.ini)")
    parser.add_argument("-n", "--dry-run", action="store_true", help="Esegue le misure senza scrivere su DB e senza inviare email")
    parser.add_argument("-v", "--verbose", action="store_true", help="Log di debug")
    args = parser.parse_args()

    logging_setup.setup(args.verbose)
    log = logging.getLogger(f"job.{name}")

    try:
        cfg = config_mod.load(args.config)
    except config_mod.ConfigError as exc:
        log.error("%s", exc)
        sys.exit(2)

    from .. import db as _db
    _db.start_stats(f"job {name}")                 # 4.2: "Transazione lunga" nel registro, con il nome del job
    # Lock: impedisce due esecuzioni contemporanee dello stesso job
    lock_path = os.path.join(tempfile.gettempdir(), f"astreo-monitor-{name}.lock")
    lock_file = open(lock_path, "w")  # noqa: SIM115
    try:
        fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        log.warning("Job %s già in esecuzione, esco", name)
        sys.exit(0)

    if args.dry_run:
        log.info("Modalità dry-run: nessuna scrittura su DB e nessuna email")
    try:
        code = func(cfg, args.dry_run)
    except db.DatabaseError as exc:
        log.error("Job %s: errore database: %s", name, exc)
        code = 1
    except Exception:  # noqa: BLE001
        log.exception("Job %s terminato con errore", name)
        code = 1
    finally:
        fcntl.flock(lock_file, fcntl.LOCK_UN)
        lock_file.close()
    sys.exit(code)
