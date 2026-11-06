"""Elenco dei servizi monitorati, salvato nella tabella monitored_services."""
from __future__ import annotations

from sqlalchemy import func, select, update

from . import db, models
from .collectors import services as svc
from .config import Config

T = models.monitored_services
COLS = (T.c.unit, T.c.label, T.c.enabled, T.c.notify, T.c.ondemand, T.c.sort_order)


def _normalize(unit: str) -> str:
    return unit if unit.endswith(".service") else unit + ".service"


def seed_if_empty(conn, cfg: Config) -> None:
    """Primo avvio: copia nel DB i servizi della sezione [services] del config."""
    if db.scalar(conn, select(func.count()).select_from(T)):
        return
    for i, s in enumerate(cfg.web.services):
        unit = _normalize(s.unit)
        if svc.valid_unit(unit):
            conn.execute(T.insert().values(unit=unit, label=s.label[:100], enabled=True, notify=False,
                                           sort_order=(i + 1) * 10, updated_at=db.now()))


def all_rows(conn) -> list[dict]:
    return db.rows(conn, select(*COLS).order_by(T.c.sort_order, T.c.unit))


def monitored(conn, cfg: Config) -> list[dict]:
    seed_if_empty(conn, cfg)
    return [r for r in all_rows(conn) if r["enabled"]]


def get(conn, unit: str) -> dict | None:
    return db.one(conn, select(*COLS).where(T.c.unit == unit))


def upsert(conn, unit: str, *, enabled=None, notify=None, label=None, ondemand=None) -> dict:
    if not svc.valid_unit(unit):
        raise ValueError(f"Nome di servizio non valido: {unit}")
    existing = get(conn, unit)
    if existing is None:
        known = {u["unit"] for u in svc.catalog()}
        if unit not in known:
            raise ValueError(f"Il servizio {unit} non esiste su questo server")
        top = db.scalar(conn, select(func.coalesce(func.max(T.c.sort_order), 0))) or 0
        conn.execute(T.insert().values(unit=unit, label=(label or unit.removesuffix(".service"))[:100],
                                       enabled=True if enabled is None else bool(enabled), notify=bool(notify),
                                       ondemand=bool(ondemand), sort_order=top + 10, updated_at=db.now()))
    else:
        conn.execute(update(T).where(T.c.unit == unit).values(
            label=((label if label is not None else existing["label"])[:100] or unit),
            enabled=bool(enabled) if enabled is not None else existing["enabled"],
            notify=bool(notify) if notify is not None else existing["notify"],
            ondemand=bool(ondemand) if ondemand is not None else existing["ondemand"],
            updated_at=db.now()))
    return get(conn, unit)


def reorder(conn, units: list[str]) -> None:
    for i, unit in enumerate(units):
        conn.execute(update(T).where(T.c.unit == unit).values(sort_order=(i + 1) * 10))
