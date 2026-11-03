"""Definizione unica delle tabelle (SQLAlchemy Core), valida per SQL Server, PostgreSQL e SQLite.

Nomi e colonne coincidono con lo schema creato dagli script sql/001-009 delle versioni 2.x:
un database esistente viene riconosciuto senza modifiche ai dati (vedi migrate.py).
Ogni modifica a questo file richiede una nuova migrazione in astreo_monitor/migrations/versions/.
"""
from __future__ import annotations

from sqlalchemy import (BigInteger, Boolean, Column, DateTime, Float, Index, Integer, MetaData, PrimaryKeyConstraint,  # noqa: F401
                        SmallInteger, String, Table, Unicode, UnicodeText)
from sqlalchemy.dialects import mssql

metadata = MetaData()

# BIGINT autoincrementale; in SQLite l'autoincremento richiede INTEGER PRIMARY KEY
ID = BigInteger().with_variant(Integer(), "sqlite")
# Data e ora senza fuso (ora locale del server); in SQL Server DATETIME2(0)
TS = DateTime().with_variant(mssql.DATETIME2(precision=0), "mssql")
TEXT = UnicodeText().with_variant(mssql.NVARCHAR(None), "mssql")


def _id(table: str) -> tuple:
    return (Column("id", ID, autoincrement=True, nullable=False),
            PrimaryKeyConstraint("id", name=f"PK_{table}", mssql_clustered=False))


system_metrics = Table(
    "system_metrics", metadata, *_id("system_metrics"),
    Column("timestamp", TS, nullable=False),
    Column("cpu_pct", Float), Column("load1", Float), Column("load5", Float), Column("load15", Float),
    Column("mem_used_pct", Float), Column("mem_used_mb", Integer), Column("swap_used_pct", Float),
    Column("disk_used_pct", Float),
    Column("source", String(16), nullable=False, server_default="v2"),
    Column("host_id", Integer, nullable=False, server_default="1"),          # 4.0: 1 = server centrale
    Index("IX_system_metrics_ts", "timestamp", mssql_clustered=True),
    Index("IX_system_metrics_host", "host_id", "timestamp"),
)

system_temperature = Table(
    "system_temperature", metadata, *_id("system_temperature"),
    Column("timestamp", TS),
    Column("adapter", String(255)), Column("device", String(255)), Column("temperature", Float),
    Column("host_id", Integer, nullable=False, server_default="1"),
    Index("IX_system_temperature_ts", "timestamp", mssql_clustered=True),
    Index("IX_system_temperature_host", "host_id", "timestamp"),
)

speedtest_results = Table(
    "speedtest_results", metadata, *_id("speedtest_results"),
    Column("timestamp", TS, nullable=False),
    Column("download_mbps", Float), Column("upload_mbps", Float), Column("latency_ms", Float),
    Column("status", String(10)), Column("provider", String(32), nullable=False), Column("error", Unicode(400)),
    Index("IX_speedtest_results_ts", "timestamp", mssql_clustered=True),
)

public_ip_history = Table(
    "public_ip_history", metadata, *_id("public_ip_history"),
    Column("timestamp", TS, nullable=False),
    Column("ip", String(45), nullable=False), Column("previous_ip", String(45)),
    Index("IX_public_ip_history_ts", "timestamp", mssql_clustered=True),
)

monitor_state = Table(
    "monitor_state", metadata,
    Column("key", String(64), primary_key=True), Column("value", TEXT), Column("updated_at", TS, nullable=False),
)

app_settings = Table(
    "app_settings", metadata,
    Column("key", String(100), primary_key=True), Column("value", TEXT), Column("updated_at", TS, nullable=False),
)

monitored_services = Table(
    "monitored_services", metadata,
    Column("unit", String(255), primary_key=True), Column("label", Unicode(100), nullable=False),
    Column("enabled", Boolean, nullable=False, server_default="1"),
    Column("notify", Boolean, nullable=False, server_default="0"),
    Column("sort_order", Integer, nullable=False, server_default="0"),
    Column("updated_at", TS, nullable=False),
)

notification_log = Table(
    "notification_log", metadata, *_id("notification_log"),
    Column("timestamp", TS, nullable=False),
    Column("channel", String(16), nullable=False), Column("source", String(32), nullable=False),
    Column("subject", Unicode(200), nullable=False), Column("ok", Boolean, nullable=False),
    Column("error", Unicode(400)), Column("status", String(16)),
    Index("IX_notification_log_ts", "timestamp", mssql_clustered=True),
)

notification_queue = Table(
    "notification_queue", metadata, *_id("notification_queue"),
    Column("created_at", TS, nullable=False), Column("due_at", TS, nullable=False),
    Column("source", String(32), nullable=False), Column("channel", String(16), nullable=False),
    Column("subject", Unicode(200), nullable=False), Column("body", TEXT, nullable=False),
    Column("attempts", Integer, nullable=False, server_default="0"),
    Column("sent_at", TS), Column("error", Unicode(400)),
    Index("IX_notification_queue_due", "due_at", mssql_clustered=True),
)

connectivity_samples = Table(
    "connectivity_samples", metadata, *_id("connectivity_samples"),
    Column("timestamp", TS, nullable=False),
    Column("target", String(64), nullable=False), Column("role", String(16), nullable=False),
    Column("sent", SmallInteger, nullable=False), Column("received", SmallInteger, nullable=False),
    Column("loss_pct", Float, nullable=False), Column("rtt_avg_ms", Float), Column("rtt_max_ms", Float),
    Index("IX_connectivity_samples_ts", "timestamp", "target", mssql_clustered=True),
)

events = Table(
    "events", metadata, *_id("events"),
    Column("timestamp", TS, nullable=False),
    Column("kind", String(16), nullable=False), Column("severity", String(8), nullable=False),
    Column("title", Unicode(200), nullable=False), Column("detail", Unicode(400)), Column("ref", String(100)),
    Column("host_id", Integer, nullable=False, server_default="1"),
    Index("IX_events_ts", "timestamp", mssql_clustered=True),
    Index("UX_events_ref", "ref", unique=True, mssql_where=Column("ref").isnot(None),
          postgresql_where=Column("ref").isnot(None), sqlite_where=Column("ref").isnot(None)),
)


# --- 3.2: controlli di altri dispositivi e servizi (ping, porta TCP, pagina web) ---
checks = Table(
    "checks", metadata, *_id("checks"),
    Column("name", Unicode(100), nullable=False),
    Column("kind", String(8), nullable=False),            # ping | tcp | http
    Column("target", Unicode(400), nullable=False),       # host, host per tcp, URL per http
    Column("port", Integer),
    Column("interval_s", Integer, nullable=False, server_default="60"),
    Column("timeout_s", Integer, nullable=False, server_default="10"),
    Column("retries", SmallInteger, nullable=False, server_default="2"),   # fallimenti consecutivi prima di DOWN
    Column("expect_status", String(40)),                  # http: es. "200-399" (predefinito) o "200,204"
    Column("keyword", Unicode(200)),                      # http: testo che deve comparire nella pagina
    Column("verify_tls", Boolean, nullable=False, server_default="1"),
    Column("cert_warning_days", SmallInteger, nullable=False, server_default="14"),
    Column("enabled", Boolean, nullable=False, server_default="1"),
    Column("sort_order", Integer, nullable=False, server_default="0"),
    Column("updated_at", TS, nullable=False),
)

check_results = Table(
    "check_results", metadata, *_id("check_results"),
    Column("timestamp", TS, nullable=False),
    Column("check_id", BigInteger().with_variant(Integer(), "sqlite"), nullable=False),
    Column("ok", Boolean, nullable=False),
    Column("latency_ms", Float),
    Column("detail", Unicode(300)),
    Index("IX_check_results_ts", "timestamp", "check_id", mssql_clustered=True),
)


# --- 4.0: server monitorati (1 = il server centrale, gli altri inviano i dati con un agente) ---
hosts = Table(
    "hosts", metadata, *_id("hosts"),
    Column("name", Unicode(100), nullable=False),
    Column("kind", String(8), nullable=False),            # local | linux | windows
    Column("token_hash", String(64)),                      # sha256 del token dell'agente (mai il token)
    Column("services", Unicode(2000)),                     # servizi da controllare, separati da virgola
    Column("enabled", Boolean, nullable=False, server_default="1"),
    Column("sort_order", Integer, nullable=False, server_default="0"),
    Column("created_at", TS, nullable=False),
    Column("last_seen", TS),
    Column("agent_version", String(32)),
    Column("os_info", Unicode(200)),
    Index("UX_hosts_token", "token_hash", unique=True, mssql_where=Column("token_hash").isnot(None),
          postgresql_where=Column("token_hash").isnot(None), sqlite_where=Column("token_hash").isnot(None)),
)
