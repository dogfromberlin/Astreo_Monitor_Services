"""UPS controllati (tabella ups_devices), ultima lettura (monitor_state ups:<id>:last) e storico (ups_samples)."""
from __future__ import annotations

import datetime as dt
import ipaddress
import re

from sqlalchemy import delete, insert, select, update

from .. import db, models
from . import DEFAULT_PORTS, UpsError

D, S = models.ups_devices, models.ups_samples
HOST_RE = re.compile(r"^[A-Za-z0-9.-]{1,253}$")
NAME_RE = re.compile(r"^[A-Za-z0-9_.-]{1,100}$")
KEEP_DAYS = 90


def clean(data: dict, partial: bool = False) -> dict:
    out = {}
    if "name" in data or not partial:
        name = str(data.get("name") or "").strip()
        if not 1 <= len(name) <= 100:
            raise UpsError("Nome dell'UPS mancante")
        out["name"] = name
    if "backend" in data or not partial:
        b = str(data.get("backend") or "")
        if b not in DEFAULT_PORTS:
            raise UpsError("Tipo non valido (nut, apcupsd o snmp)")
        out["backend"] = b
    if "host" in data or not partial:
        h = str(data.get("host") or "").strip()
        try:
            ipaddress.ip_address(h)
        except ValueError:
            if not HOST_RE.match(h):
                raise UpsError("Indirizzo non valido") from None
        out["host"] = h
    if "port" in data:
        p = data.get("port")
        if p in (None, ""):
            out["port"] = None
        else:
            try:
                p = int(p)
            except (TypeError, ValueError):
                raise UpsError("Porta non valida") from None
            if not 1 <= p <= 65535:
                raise UpsError("Porta non valida")
            out["port"] = p
    if "ups_name" in data:
        n = str(data.get("ups_name") or "").strip()
        if n and not NAME_RE.match(n):
            raise UpsError("Nome dell'UPS sul server NUT non valido")
        out["ups_name"] = n or None
    if "community" in data:
        out["community"] = str(data.get("community") or "").strip()[:100] or None
    if "enabled" in data:
        out["enabled"] = bool(data["enabled"])
    return out


def listing(conn) -> list[dict]:
    out = []
    for d in db.rows(conn, select(D).order_by(D.c.sort_order, D.c.id)):
        d = dict(d)
        d["last"] = db.state_get(conn, f"ups:{d['id']}:last")
        d.pop("community", None) if not d.get("community") else d.update(community="•••")
        out.append(d)
    return out


def get(conn, uid: int) -> dict | None:
    return db.one(conn, select(D).where(D.c.id == uid))


def create(conn, data: dict) -> int:
    vals = clean(data)
    vals.update({k: v for k, v in clean({k: data[k] for k in ("port", "ups_name", "community") if k in data}, partial=True).items()})
    top = db.scalar(conn, select(D.c.sort_order).order_by(D.c.sort_order.desc()).limit(1)) or 0
    res = conn.execute(insert(D).values(**vals, enabled=True, sort_order=top + 10, created_at=db.now()))
    return int(res.inserted_primary_key[0])


def modify(conn, uid: int, data: dict) -> None:
    vals = clean(data, partial=True)
    if vals.get("community") == "•••":
        vals.pop("community")
    if vals:
        conn.execute(update(D).where(D.c.id == uid).values(**vals))


def remove(conn, uid: int) -> None:
    conn.execute(delete(S).where(S.c.ups_id == uid))
    conn.execute(delete(D).where(D.c.id == uid))
    for k in ("last", "blackout"):
        db.state_set(conn, f"ups:{uid}:{k}", None)


def history(conn, uid: int, since: dt.datetime) -> list[dict]:
    return db.rows(conn, select(S.c.timestamp, S.c.status, S.c.charge, S.c.runtime_s, S.c.load, S.c.input_v, S.c.output_v)
                   .where(S.c.ups_id == uid, S.c.timestamp >= since).order_by(S.c.timestamp))


def prune(conn, now: dt.datetime) -> None:
    conn.execute(delete(S).where(S.c.timestamp < now - dt.timedelta(days=KEEP_DAYS)))
