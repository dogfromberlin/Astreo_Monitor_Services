"""Controllo dello schema del database: tabelle, colonne, versione delle migrazioni e permessi.

Per ogni problema indica come correggerlo (di norma: python -m astreo_monitor.migrate).
Usato all'avvio della dashboard, da /api/v1/health e dal comando di diagnosi.
Uso diretto: python -m astreo_monitor.schema [--config FILE]
"""
from __future__ import annotations

import argparse
import sys

from sqlalchemy import inspect, text

from . import db, models

MIGRATE = "python -m astreo_monitor.migrate"


def check(conn, backup_databases: list[str] | None = None) -> list[dict]:
    """Ritorna l'elenco dei problemi: [{"item", "problem", "fix"}]. Vuoto = schema completo."""
    from . import migrate
    problems = []
    insp = inspect(conn)
    present = {t.lower() for t in insp.get_table_names()}
    for name, table in models.metadata.tables.items():
        if name not in present:
            problems.append({"item": name, "problem": "tabella mancante", "fix": MIGRATE})
            continue
        cols = {c["name"].lower() for c in insp.get_columns(name)}
        missing = [c.name for c in table.columns if c.name.lower() not in cols]
        if missing:
            problems.append({"item": name, "problem": f"colonne mancanti: {', '.join(missing)}", "fix": MIGRATE})
    if "alembic_version" not in present:
        problems.append({"item": "versione dello schema", "problem": "mai registrata (database 2.x?)", "fix": MIGRATE})
    else:
        current, head = migrate.current_revision(conn), migrate.head_revision()
        if current != head:
            problems.append({"item": "versione dello schema", "problem": f"{current} invece di {head}", "fix": MIGRATE})

    if db.dialect(conn) == "mssql":                   # backup e verifica del ripristino di SQL Server
        for proc in ("master.dbo.astreo_restoretest_check", "master.dbo.astreo_restoretest_drop"):
            if db.scalar(conn, text("SELECT HAS_PERMS_BY_NAME(:p, 'OBJECT', 'EXECUTE')"), {"p": proc}) != 1:
                problems.append({"item": proc, "problem": "procedura mancante o senza permesso di esecuzione",
                                 "fix": "come sa: sql/008_verifica_ripristino.sql"})
        for name in backup_databases or []:
            if db.scalar(conn, text("SELECT HAS_PERMS_BY_NAME(:d, 'DATABASE', 'BACKUP DATABASE')"), {"d": name}) != 1:
                problems.append({"item": f"backup di {name}", "problem": "permesso BACKUP DATABASE mancante",
                                 "fix": "come sa: sql/004_backup.sql"})
    return problems


def fixes(problems: list[dict]) -> list[str]:
    return sorted({p["fix"] for p in problems})


def main() -> None:
    from . import config as config_mod
    parser = argparse.ArgumentParser(prog="astreo_monitor.schema", description="Controlla lo schema del database")
    parser.add_argument("-c", "--config")
    args = parser.parse_args()
    cfg = config_mod.load(args.config)
    with db.connect(cfg.database) as conn:
        problems = check(conn, cfg.backup.databases if cfg.backup and cfg.database.engine == "mssql" else None)
    if not problems:
        print("Schema del database completo e aggiornato.")
        return
    for p in problems:
        print(f"PROBLEMA  {p['item']}: {p['problem']}  ->  {p['fix']}")
    sys.exit(1)


if __name__ == "__main__":
    main()
