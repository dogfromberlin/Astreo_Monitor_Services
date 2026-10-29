"""Accesso a SQL Server con query parametrizzate.

- Connessioni brevi: `with connect(cfg) as conn:` apre, fa commit a fine blocco
  (rollback in caso di eccezione) e chiude sempre.
- Parametri sempre passati a pymssql (%s), mai concatenati nel testo SQL.
- Le date viaggiano come stringa ISO 8601 (vedi `ts()`) e nel SQL si usa
  CONVERT(..., %s, 126): così il risultato non dipende dalla lingua del login.
- Nessun sys.exit: gli errori diventano DatabaseError gestite dal chiamante.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
from contextlib import contextmanager
from typing import Any, Iterator

import pymssql

from .config import DatabaseConfig

log = logging.getLogger(__name__)

DatabaseError = pymssql.Error


def ts(value: dt.datetime) -> str:
    """Datetime -> stringa ISO 8601 accettata da CONVERT(..., 126)."""
    return value.replace(microsecond=0).isoformat(timespec="seconds")


def as_datetime(value: Any) -> dt.datetime | None:
    """Normalizza i valori data restituiti dal driver (datetime o stringa)."""
    if value is None or isinstance(value, dt.datetime):
        return value
    text = str(value).strip().replace(" ", "T", 1)
    if "." in text:  # datetime2 come stringa: tronco i decimali
        text = text.split(".")[0]
    return dt.datetime.fromisoformat(text)


@contextmanager
def connect(cfg: DatabaseConfig) -> Iterator[pymssql.Connection]:
    conn = pymssql.connect(
        server=cfg.host,
        port=str(cfg.port),
        user=cfg.user,
        password=cfg.password,
        database=cfg.database,
        login_timeout=cfg.login_timeout,
        timeout=cfg.timeout,
        as_dict=True,
        tds_version="7.3",
        appname="astreo-monitor",
    )
    try:
        yield conn
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:  # pragma: no cover
            pass
        raise
    finally:
        conn.close()


def query(conn, sql: str, params: tuple = ()) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return list(cur.fetchall())


def query_one(conn, sql: str, params: tuple = ()) -> dict | None:
    rows = query(conn, sql, params)
    return rows[0] if rows else None


def execute(conn, sql: str, params: tuple = ()) -> int:
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.rowcount


def execute_many(conn, sql: str, rows: list[tuple]) -> None:
    if not rows:
        return
    with conn.cursor() as cur:
        cur.executemany(sql, rows)


def ping(cfg: DatabaseConfig) -> bool:
    try:
        with connect(cfg) as conn:
            query(conn, "SELECT 1 AS ok")
        return True
    except Exception as exc:  # noqa: BLE001
        log.warning("Database non raggiungibile: %s", exc)
        return False


# ---------------------------------------------------------------------------
# Tabella monitor_state: piccolo archivio chiave/valore (JSON) condiviso dai job
# ---------------------------------------------------------------------------

def state_get(conn, key: str, default: Any = None) -> Any:
    row = query_one(conn, "SELECT [value] FROM monitor_state WHERE [key] = %s", (key,))
    if not row or row["value"] is None:
        return default
    try:
        return json.loads(row["value"])
    except ValueError:
        return default


def state_set(conn, key: str, value: Any) -> None:
    payload = json.dumps(value, default=str)
    updated = execute(
        conn,
        "UPDATE monitor_state SET [value] = %s, updated_at = SYSDATETIME() WHERE [key] = %s",
        (payload, key),
    )
    if not updated:
        execute(
            conn,
            "INSERT INTO monitor_state ([key], [value], updated_at) VALUES (%s, %s, SYSDATETIME())",
            (key, payload),
        )
