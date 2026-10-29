"""Elenco dei servizi monitorati, salvato nella tabella monitored_services."""
from __future__ import annotations

from . import db
from .collectors import services as svc
from .config import Config


def _normalize(unit: str) -> str:
    return unit if unit.endswith(".service") else unit + ".service"


def seed_if_empty(conn, cfg: Config) -> None:
    """Primo avvio: copia nel DB i servizi della sezione [services] del config."""
    row = db.query_one(conn, "SELECT COUNT(*) AS n FROM monitored_services")
    if row["n"]:
        return
    for i, s in enumerate(cfg.web.services):
        unit = _normalize(s.unit)
        if svc.valid_unit(unit):
            db.execute(
                conn,
                "INSERT INTO monitored_services (unit, label, enabled, notify, sort_order, updated_at) "
                "VALUES (%s, %s, 1, 0, %s, SYSDATETIME())",
                (unit, s.label[:100], (i + 1) * 10),
            )


def all_rows(conn) -> list[dict]:
    return db.query(conn, "SELECT unit, label, enabled, notify, sort_order FROM monitored_services ORDER BY sort_order, unit")


def monitored(conn, cfg: Config) -> list[dict]:
    seed_if_empty(conn, cfg)
    return [r for r in all_rows(conn) if r["enabled"]]


def upsert(conn, unit: str, *, enabled=None, notify=None, label=None) -> dict:
    if not svc.valid_unit(unit):
        raise ValueError(f"Nome di servizio non valido: {unit}")
    existing = db.query_one(conn, "SELECT unit, label, enabled, notify, sort_order FROM monitored_services WHERE unit = %s", (unit,))
    if existing is None:
        known = {u["unit"] for u in svc.catalog()}
        if unit not in known:
            raise ValueError(f"Il servizio {unit} non esiste su questo server")
        top = db.query_one(conn, "SELECT ISNULL(MAX(sort_order), 0) AS m FROM monitored_services")["m"]
        default_label = unit.removesuffix(".service")
        db.execute(
            conn,
            "INSERT INTO monitored_services (unit, label, enabled, notify, sort_order, updated_at) VALUES (%s, %s, %s, %s, %s, SYSDATETIME())",
            (unit, (label or default_label)[:100], 1 if enabled is None or enabled else 0, 1 if notify else 0, top + 10),
        )
    else:
        db.execute(
            conn,
            "UPDATE monitored_services SET label = %s, enabled = %s, notify = %s, updated_at = SYSDATETIME() WHERE unit = %s",
            (
                (label if label is not None else existing["label"])[:100] or unit,
                (1 if enabled else 0) if enabled is not None else existing["enabled"],
                (1 if notify else 0) if notify is not None else existing["notify"],
                unit,
            ),
        )
    return db.query_one(conn, "SELECT unit, label, enabled, notify, sort_order FROM monitored_services WHERE unit = %s", (unit,))


def reorder(conn, units: list[str]) -> None:
    for i, unit in enumerate(units):
        db.execute(conn, "UPDATE monitored_services SET sort_order = %s WHERE unit = %s", ((i + 1) * 10, unit))
