"""Schema della versione 3.0 (prima migrazione), CONGELATO: non modificare.

Le modifiche successive vanno in nuove migrazioni, non qui né in models.py da sole.
"""
from __future__ import annotations

from sqlalchemy import (BigInteger, Boolean, Column, DateTime, Float, Index, Integer, MetaData, PrimaryKeyConstraint,
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
    Index("IX_system_metrics_ts", "timestamp", mssql_clustered=True),
)

system_temperature = Table(
    "system_temperature", metadata, *_id("system_temperature"),
    Column("timestamp", TS),
    Column("adapter", String(255)), Column("device", String(255)), Column("temperature", Float),
    Index("IX_system_temperature_ts", "timestamp", mssql_clustered=True),
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
    Index("IX_events_ts", "timestamp", mssql_clustered=True),
    Index("UX_events_ref", "ref", unique=True, mssql_where=Column("ref").isnot(None),
          postgresql_where=Column("ref").isnot(None), sqlite_where=Column("ref").isnot(None)),
)
