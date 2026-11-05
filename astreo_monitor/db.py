"""Accesso al database con SQLAlchemy: SQL Server, PostgreSQL e SQLite.

- Connessioni brevi: `with connect(cfg) as conn:` apre una transazione, fa commit a fine
  blocco (rollback in caso di eccezione) e chiude. Con autocommit=True niente transazione
  (necessario per BACKUP e RESTORE di SQL Server).
- Le query si scrivono con SQLAlchemy Core (tabelle in models.py): portabili sui tre database.
  Le poche parti specifiche (raggruppamento per intervalli, backup) usano dialect(conn).
- Nessun sys.exit: gli errori diventano DatabaseError gestite dal chiamante.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import os
import warnings
import contextvars
import time
from contextlib import contextmanager
from typing import Any, Iterator
from urllib.parse import quote_plus

from sqlalchemy import Integer, cast, create_engine, event, func, literal_column, select, text, update
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.pool import NullPool

from . import models
from .config import DatabaseConfig

log = logging.getLogger(__name__)

DatabaseError = SQLAlchemyError

# SQLAlchemy 2.0 non conosce ancora i numeri di versione di SQL Server 2025 (17.x): avviso innocuo
warnings.filterwarnings("ignore", message=r"Unrecognized server version info")
_engines: dict[str, Engine] = {}


def url(cfg: DatabaseConfig, user: str | None = None, password: str | None = None, database: str | None = None) -> str:
    """URL SQLAlchemy. user/password/database permettono di collegarsi come amministratore (migrate)."""
    u, p = quote_plus(user if user is not None else cfg.user), quote_plus(password if password is not None else cfg.password)
    name = database or cfg.database
    if cfg.engine == "sqlite":
        return f"sqlite:///{cfg.path}"
    if cfg.engine == "postgresql":
        return f"postgresql+psycopg://{u}:{p}@{cfg.host}:{cfg.port}/{name}"
    return f"mssql+pymssql://{u}:{p}@{cfg.host}:{cfg.port}/{name}?tds_version=7.3&charset=utf8"


def make_engine(cfg: DatabaseConfig, **kw) -> Engine:
    args: dict[str, Any] = {}
    if cfg.engine == "mssql":
        args = {"login_timeout": cfg.login_timeout, "timeout": kw.pop("timeout", None) or cfg.timeout,
                "appname": "astreo-monitor"}
    elif cfg.engine == "postgresql":
        args = {"connect_timeout": cfg.login_timeout, "application_name": "astreo-monitor"}
    else:
        os.makedirs(os.path.dirname(cfg.path) or ".", exist_ok=True)
        args = {"timeout": 30}
    eng = create_engine(url(cfg, kw.pop("user", None), kw.pop("password", None), kw.pop("database", None)),
                        connect_args=args, poolclass=NullPool, future=True)

    @event.listens_for(eng, "before_cursor_execute")
    def _t0(conn, cursor, statement, params, context, executemany):
        conn.info["t0"] = time.monotonic()

    @event.listens_for(eng, "after_cursor_execute")
    def _t1(conn, cursor, statement, params, context, executemany):
        st = _stats.get()
        if st is not None and "t0" in conn.info:
            dt_ = time.monotonic() - conn.info.pop("t0")
            st["query"] = st.get("query", 0.0) + dt_
            if dt_ > st.get("slowest", (0, ""))[0]:
                st["slowest"] = (dt_, " ".join(statement.split())[:120])

    @event.listens_for(eng, "connect")
    def _on_connect(dbapi_conn, _rec):
        cur = dbapi_conn.cursor()
        if cfg.engine == "mssql":
            cur.execute("SET DATEFORMAT ymd")          # date ISO interpretate sempre allo stesso modo
        elif cfg.engine == "sqlite":
            cur.execute("PRAGMA journal_mode=WAL")      # letture e scritture contemporanee (web + job)
            cur.execute("PRAGMA busy_timeout=30000")
        cur.close()
    return eng


def engine(cfg: DatabaseConfig, timeout: int | None = None) -> Engine:
    key = f"{url(cfg)}|{timeout}"
    if key not in _engines:
        _engines[key] = make_engine(cfg, timeout=timeout)
    return _engines[key]


# 4.2: misura dei tempi del database, per trovare le attese (registro "Richiesta lenta" / "Transazione lunga")
_stats: contextvars.ContextVar[dict | None] = contextvars.ContextVar("db_stats", default=None)
_label: contextvars.ContextVar[str] = contextvars.ContextVar("db_label", default="")
SLOW_TRANSACTION_S = 5.0


def start_stats(label: str) -> dict:
    """Inizia a contare i tempi del database per una richiesta o un job."""
    st = {"connect": 0.0, "query": 0.0, "slowest": (0.0, "")}
    _stats.set(st)
    _label.set(label)
    return st


def describe(st: dict) -> str:
    slow = st.get("slowest") or (0.0, "")
    out = f"connessione al database {st.get('connect', 0):.2f} s, query {st.get('query', 0):.2f} s"
    if slow[0] >= 0.5:
        out += f"; query più lenta {slow[0]:.2f} s: {slow[1]}"
    return out


@contextmanager
def connect(cfg: DatabaseConfig, autocommit: bool = False, timeout: int | None = None) -> Iterator[Connection]:
    eng = engine(cfg, timeout)
    st = _stats.get()
    t0 = time.monotonic()
    if autocommit:
        cm = eng.connect().execution_options(isolation_level="AUTOCOMMIT")
    else:
        cm = eng.begin()
    with cm as conn:
        opened = time.monotonic() - t0
        if st is not None:
            st["connect"] = st.get("connect", 0.0) + opened
        try:
            yield conn
        finally:
            took = time.monotonic() - t0
            if took > SLOW_TRANSACTION_S:
                logging.getLogger("db").warning("Transazione lunga: %.1f s in %s (apertura %.2f s)", took, _label.get() or "?", opened)


def dialect(conn) -> str:
    return conn.dialect.name           # mssql | postgresql | sqlite


# ------------------------------------------------------------------ helper
def rows(conn, stmt, params: dict | None = None) -> list[dict]:
    if isinstance(stmt, str):
        stmt = text(stmt)
    return [dict(r) for r in conn.execute(stmt, params or {}).mappings()]


def one(conn, stmt, params: dict | None = None) -> dict | None:
    r = rows(conn, stmt, params)
    return r[0] if r else None


def scalar(conn, stmt, params: dict | None = None):
    if isinstance(stmt, str):
        stmt = text(stmt)
    return conn.execute(stmt, params or {}).scalar()


def execute(conn, stmt, params: dict | list | None = None) -> int:
    if isinstance(stmt, str):
        stmt = text(stmt)
    return conn.execute(stmt, params or {}).rowcount


def as_datetime(value: Any) -> dt.datetime | None:
    if value is None or isinstance(value, dt.datetime):
        return value
    textv = str(value).strip().replace(" ", "T", 1)
    if "." in textv:
        textv = textv.split(".")[0]
    return dt.datetime.fromisoformat(textv)


def now() -> dt.datetime:
    return dt.datetime.now().replace(microsecond=0)


def ping(cfg: DatabaseConfig) -> bool:
    try:
        with connect(cfg) as conn:
            scalar(conn, select(literal_column("1")))
        return True
    except Exception as exc:  # noqa: BLE001
        log.warning("Database non raggiungibile: %s", exc)
        return False


# ------------------------------------------------ raggruppamento per intervalli
EPOCH_MSSQL = dt.datetime(2000, 1, 1)
EPOCH_UNIX = dt.datetime(1970, 1, 1)


def bucket_expr(conn, column, seconds: int):
    """Espressione che arrotonda `column` all'intervallo di `seconds`, come numero di secondi da un'epoca.

    Ritorna (espressione, epoca): bucket = epoca + timedelta(seconds=valore).
    """
    b = literal_column(str(int(seconds)))
    d = dialect(conn)
    if d == "mssql":
        return (func.datediff(text("second"), text("'20000101'"), column) / b) * b, EPOCH_MSSQL
    if d == "postgresql":
        return cast(func.floor(func.extract("epoch", column) / b) * b, Integer), EPOCH_UNIX
    return (cast(func.strftime("%s", column), Integer) / b) * b, EPOCH_UNIX


def from_bucket(value, epoch: dt.datetime) -> dt.datetime:
    return epoch + dt.timedelta(seconds=int(value))


# ------------------------------------------- stato chiave/valore (monitor_state)
def state_get(conn, key: str, default: Any = None) -> Any:
    t = models.monitor_state
    v = scalar(conn, select(t.c.value).where(t.c.key == key))
    if v is None:
        return default
    try:
        return json.loads(v)
    except ValueError:
        return default


def kv_set(conn, table, key: str, value: str) -> None:
    """Aggiorna o inserisce una riga chiave/valore (monitor_state, app_settings)."""
    n = conn.execute(update(table).where(table.c.key == key).values(value=value, updated_at=now())).rowcount
    if not n:
        conn.execute(table.insert().values(key=key, value=value, updated_at=now()))


def state_set(conn, key: str, value: Any) -> None:
    kv_set(conn, models.monitor_state, key, json.dumps(value, default=str))


def state_rows(conn, prefix: str = "") -> list[dict]:
    t = models.monitor_state
    q = select(t.c.key, t.c.value, t.c.updated_at)
    if prefix:
        q = q.where(t.c.key.like(prefix + "%"))
    return rows(conn, q)
