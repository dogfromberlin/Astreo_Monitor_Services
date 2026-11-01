"""Backup e verifica del ripristino, specifici per database.

| Database   | Backup                                        | Verifica del ripristino                          |
|------------|-----------------------------------------------|--------------------------------------------------|
| SQL Server | BACKUP DATABASE + RESTORE VERIFYONLY, zstd    | RESTORE in un DB temporaneo + DBCC CHECKDB       |
| PostgreSQL | pg_dump (formato custom, compresso)           | pg_restore in un DB temporaneo (serve CREATEDB)  |
| SQLite     | copia sicura (API di backup) + integrity_check| integrity_check sulla copia decompressa          |
"""
from __future__ import annotations

import hashlib
import logging
import os
import shutil
import sqlite3
import subprocess

from sqlalchemy import func, inspect, select, table as sa_table, text

from . import db
from .config import BackupConfig, DatabaseConfig

log = logging.getLogger(__name__)
TEST_PREFIX = "astreo_restoretest_"


class BackupError(Exception):
    pass


def sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def zstd(args: list[str], timeout: int) -> None:
    res = subprocess.run(["zstd", "-q", *args], capture_output=True, text=True, timeout=timeout, check=False)
    if res.returncode != 0:
        raise BackupError(f"zstd: {(res.stderr or res.stdout).strip()}")


def safe_name(name: str) -> str:
    return "".join(c if c.isalnum() or c == "_" else "_" for c in name)


def quote_mssql(name: str) -> str:
    return "[" + name.replace("]", "]]") + "]"


def result(name: str, path: str, raw_bytes: int) -> dict:
    return {"database": name, "file": os.path.basename(path), "bak_bytes": raw_bytes,
            "zst_bytes": os.path.getsize(path), "sha256": sha256(path)}


# =========================================================================== SQL Server
class MssqlRaw:
    """Connessione pymssql in autocommit, per BACKUP/RESTORE, con tutti i messaggi del server negli errori."""

    def __init__(self, dbc: DatabaseConfig, timeout: int):
        self.raw = db.engine(dbc, timeout).raw_connection()
        self.conn = self.raw.dbapi_connection
        self.conn.autocommit(True)

    def run(self, sql: str, params: tuple = (), fetch: bool = False):
        messages: list[tuple[int, str]] = []

        def handler(state, severity, server, proc, line, msg):
            messages.append((severity, msg.decode("utf-8", "replace") if isinstance(msg, bytes) else str(msg)))

        self.conn._conn.set_msghandler(handler)
        try:
            cur = self.conn.cursor(as_dict=True)
            cur.execute(sql, params)
            out = cur.fetchall() if fetch else None
            while cur.nextset():
                pass
            return out
        except Exception as exc:  # noqa: BLE001
            errors = [m for s, m in messages if s > 10]
            raise BackupError(" | ".join(errors) if errors else str(exc)) from exc
        finally:
            self.conn._conn.set_msghandler(None)

    def close(self):
        self.raw.close()


class Mssql:
    kind = "mssql"
    ext = ".bak.zst"

    def databases(self, dbc: DatabaseConfig, b: BackupConfig) -> list[str]:
        return list(b.databases)

    def check(self, dbc: DatabaseConfig, b: BackupConfig) -> tuple[list[str], str]:
        problems = []
        if not shutil.which("zstd"):
            problems.append("comando zstd non trovato (sudo apt install zstd)")
        if not os.path.isdir(b.sql_dir) or not os.access(b.sql_dir, os.R_OK | os.W_OK | os.X_OK):
            problems.append(f"cartella {b.sql_dir} mancante o non scrivibile (deve essere condivisa con SQL Server)")
        with db.connect(dbc) as conn:
            version = db.scalar(conn, text("SELECT CAST(SERVERPROPERTY('ProductVersion') AS varchar(32))"))
            online = {r["name"] for r in db.rows(conn, "SELECT name FROM sys.databases WHERE state_desc = 'ONLINE'")}
            for d in b.databases:
                if d not in online:
                    problems.append(f"{d}: database non trovato o non online")
                elif db.scalar(conn, text("SELECT HAS_PERMS_BY_NAME(:d, 'DATABASE', 'BACKUP DATABASE')"), {"d": d}) != 1:
                    problems.append(f"{d}: permesso BACKUP DATABASE mancante (sql/mssql_permessi_backup.sql)")
            if db.scalar(conn, text("SELECT HAS_PERMS_BY_NAME('master', 'DATABASE', 'CREATE DATABASE')")) != 1:
                problems.append("permesso CREATE DATABASE in master mancante, serve a RESTORE VERIFYONLY (sql/mssql_permessi_backup.sql)")
        return problems, f"SQL Server {version}"

    def backup(self, dbc, b, name, stamp, run_dir) -> dict:
        bak = os.path.join(b.sql_dir, f"{safe_name(name)}_{stamp}.bak")
        dst = os.path.join(run_dir, f"{name}{self.ext}")
        raw = MssqlRaw(dbc, b.timeout)
        try:
            raw.run(f"BACKUP DATABASE {quote_mssql(name)} TO DISK = %s WITH COPY_ONLY, CHECKSUM, INIT, NAME = %s",
                    (bak, f"astreo-monitor {stamp}"))
            raw.run("RESTORE VERIFYONLY FROM DISK = %s WITH CHECKSUM", (bak,))
            size = os.path.getsize(bak)
            zstd([f"-{b.zstd_level}", "-T0", "--rm", bak, "-o", dst], b.timeout)
            return result(name, dst, size)
        finally:
            raw.close()
            if os.path.exists(bak):
                os.remove(bak)

    def restore_test(self, dbc, b, path) -> dict:
        name = os.path.basename(path)[: -len(self.ext)]
        test_db = TEST_PREFIX + safe_name(name)
        bak = os.path.join(b.sql_dir, f"{test_db}.bak")
        out = {"database": name, "test_db": test_db}
        raw = MssqlRaw(dbc, b.timeout)
        try:
            zstd(["-d", "-f", path, "-o", bak], b.timeout)
            os.chmod(bak, 0o644)                       # SQL Server (utente mssql) deve poterlo leggere
            data_path = raw.run("SELECT CAST(SERVERPROPERTY('InstanceDefaultDataPath') AS nvarchar(260)) AS p", fetch=True)[0]["p"]
            files = raw.run("RESTORE FILELISTONLY FROM DISK = %s", (bak,), fetch=True)
            moves, params = [], []
            for i, f in enumerate(files):
                ext = "ldf" if f["Type"] == "L" else "mdf" if i == 0 else "ndf"
                moves.append("MOVE %s TO %s")
                params += [f["LogicalName"], os.path.join(data_path, f"{test_db}_{i}.{ext}")]
            raw.run("EXEC master.dbo.astreo_restoretest_drop @db = %s", (test_db,))
            raw.run(f"RESTORE DATABASE {quote_mssql(test_db)} FROM DISK = %s WITH {', '.join(moves)}, CHECKSUM, RECOVERY",
                    (bak, *params))
            counts = raw.run("EXEC master.dbo.astreo_restoretest_check @db = %s", (test_db,), fetch=True)
            out.update(status="OK", tables=len(counts), rows=int(sum(c["righe"] for c in counts)), check="DBCC CHECKDB pulito")
        except Exception as exc:  # noqa: BLE001
            out.update(status="ALERT", error=str(exc)[:400])
        finally:
            try:
                raw.run("EXEC master.dbo.astreo_restoretest_drop @db = %s", (test_db,))
            except Exception as exc:  # noqa: BLE001
                log.warning("Database di prova %s non eliminato: %s", test_db, exc)
            raw.close()
            if os.path.exists(bak):
                os.remove(bak)
        return out


# =========================================================================== PostgreSQL
def _pg_env(dbc: DatabaseConfig) -> dict:
    return {**os.environ, "PGPASSWORD": dbc.password, "PGCONNECT_TIMEOUT": str(dbc.login_timeout)}


def _pg_args(dbc: DatabaseConfig, name: str) -> list[str]:
    return ["-h", dbc.host, "-p", str(dbc.port), "-U", dbc.user, "-d", name]


class Postgres:
    kind = "postgresql"
    ext = ".dump"

    def databases(self, dbc, b) -> list[str]:
        return [dbc.database]

    def check(self, dbc, b) -> tuple[list[str], str]:
        problems = [f"comando {c} non trovato (sudo apt install postgresql-client)"
                    for c in ("pg_dump", "pg_restore") if not shutil.which(c)]
        with db.connect(dbc) as conn:
            version = db.scalar(conn, text("SHOW server_version"))
            if not db.scalar(conn, text("SELECT rolcreatedb FROM pg_roles WHERE rolname = current_user")):
                problems.append(f"l'utente {dbc.user} non ha CREATEDB: la verifica mensile del ripristino sarà parziale")
        return problems, f"PostgreSQL {version}"

    def backup(self, dbc, b, name, stamp, run_dir) -> dict:
        dst = os.path.join(run_dir, f"{name}{self.ext}")
        res = subprocess.run(["pg_dump", "-Fc", "-Z", "6", *_pg_args(dbc, name), "-f", dst], env=_pg_env(dbc),
                             capture_output=True, text=True, timeout=b.timeout, check=False)
        if res.returncode != 0:
            raise BackupError(f"pg_dump: {res.stderr.strip()[:300]}")
        chk = subprocess.run(["pg_restore", "--list", dst], capture_output=True, text=True, timeout=b.timeout, check=False)
        if chk.returncode != 0:
            raise BackupError(f"pg_restore --list: {chk.stderr.strip()[:300]}")
        return result(name, dst, os.path.getsize(dst))

    def restore_test(self, dbc, b, path) -> dict:
        name = os.path.basename(path)[: -len(self.ext)]
        test_db = TEST_PREFIX + safe_name(name).lower()
        out = {"database": name, "test_db": test_db}
        admin = db.make_engine(dbc, database="postgres")
        created = False
        try:
            with admin.connect().execution_options(isolation_level="AUTOCOMMIT") as c:
                c.execute(text(f'DROP DATABASE IF EXISTS "{test_db}"'))
                c.execute(text(f'CREATE DATABASE "{test_db}"'))
            created = True
            res = subprocess.run(["pg_restore", "--no-owner", "--no-privileges", "--exit-on-error",
                                  *_pg_args(dbc, test_db), path], env=_pg_env(dbc),
                                 capture_output=True, text=True, timeout=b.timeout, check=False)
            if res.returncode != 0:
                raise BackupError(f"pg_restore: {res.stderr.strip()[:300]}")
            tables, rows = _count_rows(db.make_engine(dbc, database=test_db))
            out.update(status="OK", tables=tables, rows=rows, check="pg_restore completato")
        except Exception as exc:  # noqa: BLE001
            if not created and "permission denied" in str(exc).lower():
                chk = subprocess.run(["pg_restore", "--list", path], capture_output=True, text=True, timeout=b.timeout)
                out.update(status="WARNING" if chk.returncode == 0 else "ALERT",
                           error=f"verifica parziale (solo lettura dell'archivio): concedi CREATEDB a {dbc.user}")
            else:
                out.update(status="ALERT", error=str(exc)[:400])
        finally:
            if created:
                try:
                    with admin.connect().execution_options(isolation_level="AUTOCOMMIT") as c:
                        c.execute(text(f'DROP DATABASE IF EXISTS "{test_db}"'))
                except Exception as exc:  # noqa: BLE001
                    log.warning("Database di prova %s non eliminato: %s", test_db, exc)
            admin.dispose()
        return out


# =========================================================================== SQLite
class Sqlite:
    kind = "sqlite"
    ext = ".sqlite.zst"

    def databases(self, dbc, b) -> list[str]:
        return [os.path.splitext(os.path.basename(dbc.path))[0]]

    def check(self, dbc, b) -> tuple[list[str], str]:
        problems = [] if shutil.which("zstd") else ["comando zstd non trovato (sudo apt install zstd)"]
        if not os.path.isfile(dbc.path):
            problems.append(f"file del database {dbc.path} non trovato")
        return problems, f"SQLite {sqlite3.sqlite_version}"

    def backup(self, dbc, b, name, stamp, run_dir) -> dict:
        tmp = os.path.join(run_dir, f"{name}.sqlite")
        dst = tmp + ".zst"
        src = sqlite3.connect(dbc.path, timeout=60)
        out = sqlite3.connect(tmp)
        try:
            src.backup(out)                            # copia coerente anche con il database in uso
            check = out.execute("PRAGMA integrity_check").fetchone()[0]
            if check != "ok":
                raise BackupError(f"integrity_check: {check}")
        finally:
            out.close()
            src.close()
        size = os.path.getsize(tmp)
        zstd([f"-{b.zstd_level}", "-T0", "--rm", tmp, "-o", dst], b.timeout)
        return result(name, dst, size)

    def restore_test(self, dbc, b, path) -> dict:
        name = os.path.basename(path)[: -len(self.ext)]
        tmp = os.path.join(os.path.dirname(path), f"{TEST_PREFIX}{name}.sqlite")
        out = {"database": name, "test_db": tmp}
        try:
            zstd(["-d", "-f", path, "-o", tmp], b.timeout)
            c = sqlite3.connect(tmp)
            check = c.execute("PRAGMA integrity_check").fetchone()[0]
            c.close()
            if check != "ok":
                raise BackupError(f"integrity_check: {check}")
            from sqlalchemy import create_engine
            tables, rows = _count_rows(create_engine(f"sqlite:///{tmp}"))
            out.update(status="OK", tables=tables, rows=rows, check="integrity_check ok")
        except Exception as exc:  # noqa: BLE001
            out.update(status="ALERT", error=str(exc)[:400])
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)
        return out


def _count_rows(engine) -> tuple[int, int]:
    with engine.connect() as c:
        names = inspect(c).get_table_names()
        total = sum(c.execute(select(func.count()).select_from(sa_table(n))).scalar() for n in names)
    engine.dispose()
    return len(names), int(total)


BACKENDS = {"mssql": Mssql(), "postgresql": Postgres(), "sqlite": Sqlite()}


def get(dbc: DatabaseConfig):
    return BACKENDS[dbc.engine]


def for_file(path: str):
    for be in BACKENDS.values():
        if path.endswith(be.ext):
            return be
    return None
