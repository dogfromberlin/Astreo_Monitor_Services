"""Aggiornamento automatico dello schema del database (Alembic).

    python -m astreo_monitor.migrate [--config FILE] [--admin-user sa] [--status]

- Applica solo le migrazioni mancanti, nell'ordine giusto.
- SQL Server e PostgreSQL: servono i permessi per creare e modificare tabelle, quindi chiede
  utente e password di AMMINISTRATORE (non vengono salvati). SQLite: nessuna credenziale.
- Database 2.x esistente (tabelle create dagli script sql/001-009): viene riconosciuto e
  registrato come schema iniziale senza toccare i dati, poi si applicano le migrazioni successive.
- PostgreSQL: concede all'utente dell'applicazione i permessi sulle tabelle.
"""
from __future__ import annotations

import argparse
import getpass
import os
import sys

from alembic import command
from alembic.config import Config as AlembicConfig
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import inspect, text

from . import config as config_mod
from . import db, models
from . import i18n as _i18n

LANG = _i18n.cli_language()


def _(text: str, **values) -> str:
    """Traduzione dei messaggi a terminale (lingua: ASTREO_LANG, install.ini o LANG)."""
    return _i18n.t(text, LANG, **values)

HERE = os.path.dirname(os.path.abspath(__file__))
BASELINE = "0001"


def alembic_config() -> AlembicConfig:
    cfg = AlembicConfig()
    cfg.set_main_option("script_location", os.path.join(HERE, "migrations"))
    return cfg


def head_revision() -> str:
    return ScriptDirectory.from_config(alembic_config()).get_current_head()


def current_revision(conn) -> str | None:
    return MigrationContext.configure(conn).get_current_revision()


def status(conn) -> dict:
    """Stato dello schema: revisione attuale, ultima disponibile, tabelle mancanti."""
    insp = inspect(conn)
    present = set(insp.get_table_names())
    return {"current": current_revision(conn) if "alembic_version" in present else None,
            "head": head_revision(),
            "missing_tables": sorted(set(models.metadata.tables) - present),
            "legacy_2x": "alembic_version" not in present and set(models.metadata.tables) <= present}


def run(cfg, admin_user: str | None, admin_password: str | None, out=print) -> str:
    dbc = cfg.database
    eng = db.make_engine(dbc, user=admin_user, password=admin_password) if dbc.engine != "sqlite" else db.make_engine(dbc)
    acfg = alembic_config()
    with eng.connect() as conn:
        st = status(conn)
        out(_("Database: {p0} — revisione attuale {p1}, ultima {p2}", p0=dbc.engine, p1=st['current'] or _('nessuna'), p2=st['head']))
        if st["legacy_2x"]:
            out(_("Rilevato uno schema 2.x completo: lo registro come schema iniziale, i dati non vengono toccati."))
            acfg.attributes["connection"] = conn
            command.stamp(acfg, BASELINE)
            conn.commit()
        elif st["current"] is None and st["missing_tables"] != sorted(models.metadata.tables):
            raise SystemExit(_("Schema parziale (alcune tabelle ci sono, altre no): tabelle mancanti {p0}. Completa lo schema 2.x con gli script sql/ o usa un database vuoto, poi rilancia.", p0=', '.join(st['missing_tables'])))
        acfg.attributes["connection"] = conn
        command.upgrade(acfg, "head")
        conn.commit()
        if dbc.engine == "postgresql" and admin_user and admin_user != dbc.user:
            conn.execute(text(f'GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO "{dbc.user}"'))
            conn.execute(text(f'GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO "{dbc.user}"'))
            conn.commit()
            out(_("Permessi sulle tabelle concessi a {p0}.", p0=dbc.user))
        final = current_revision(conn)
    eng.dispose()
    out(_("Schema aggiornato alla revisione {p0}.", p0=final))
    return final


def main() -> None:
    parser = argparse.ArgumentParser(prog="astreo_monitor.migrate", description=_("Aggiorna lo schema del database"))
    parser.add_argument("-c", "--config")
    parser.add_argument("--admin-user", help=_("amministratore del database (default: sa per SQL Server, postgres per PostgreSQL)"))
    parser.add_argument("--status", action="store_true", help=_("mostra solo lo stato, senza modificare nulla"))
    args = parser.parse_args()
    cfg = config_mod.load(args.config)
    dbc = cfg.database
    if args.status:
        with db.connect(dbc) as conn:
            st = status(conn)
        print(_("Revisione attuale: {p0} — ultima disponibile: {p1}", p0=st['current'] or _('nessuna'), p1=st['head']))
        if st["missing_tables"]:
            print(_("Tabelle mancanti: ") + ", ".join(st["missing_tables"]))
        sys.exit(0 if st["current"] == st["head"] else 1)
    user = password = None
    if dbc.engine != "sqlite":
        user = args.admin_user or {"mssql": "sa", "postgresql": "postgres"}[dbc.engine]
        password = os.environ.get("ASTREO_DB_ADMIN_PASSWORD") or getpass.getpass(_("Password di {p0} su {p1}: ", p0=user, p1=dbc.host))
    try:
        run(cfg, user, password)
    except db.DatabaseError as exc:
        print(_("Errore del database: {p0}", p0=str(exc).splitlines()[0][:300]))
        sys.exit(1)


if __name__ == "__main__":
    main()
