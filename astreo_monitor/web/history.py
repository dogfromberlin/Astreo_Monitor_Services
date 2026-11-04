"""Query sullo storico per i grafici, portabili su SQL Server, PostgreSQL e SQLite.

I dati sono aggregati per intervalli (bucket) dal database stesso: l'unica parte specifica
per database è l'espressione che arrotonda la data (db.bucket_expr).
"""
from __future__ import annotations

import datetime as dt

from sqlalchemy import and_, func, select

from .. import db, models

# Ampiezze di bucket ammesse (secondi): la più piccola che dà al massimo ~TARGET_POINTS punti
BUCKETS = [300, 600, 900, 1800, 3600, 7200, 10800, 21600, 43200, 86400]
TARGET_POINTS = 300


def bucket_seconds(start: dt.datetime, end: dt.datetime) -> int:
    span = (end - start).total_seconds()
    for b in BUCKETS:
        if span / b <= TARGET_POINTS:
            return b
    return BUCKETS[-1]


def _iso(value) -> str:
    return db.as_datetime(value).isoformat(timespec="seconds")


def _r(v, n=2):
    return None if v is None else round(float(v), n)


def _bucketed(conn, table, start, end, b, columns: dict, group_extra=(), host_id: int | None = None):
    """SELECT bucket, aggregati... raggruppati per bucket (e colonne extra), ordinati per bucket."""
    expr, epoch = db.bucket_expr(conn, table.c.timestamp, b)
    cond = [table.c.timestamp >= start, table.c.timestamp < end]
    if host_id is not None:
        cond.append(table.c.host_id == host_id)
    inner = select(expr.label("bucket"), *[table.c[c] for c in {*(col for col, _ in columns.values()), *group_extra}]) \
        .where(and_(*cond)).subquery()
    aggs = [fn(inner.c[col]).label(name) for name, (col, fn) in columns.items()]
    extra = [inner.c[g] for g in group_extra]
    q = select(inner.c.bucket, *extra, *aggs).group_by(inner.c.bucket, *extra).order_by(inner.c.bucket)
    out = db.rows(conn, q)
    for r in out:
        r["bucket"] = db.from_bucket(r["bucket"], epoch)
    return out


def metrics(conn, start: dt.datetime, end: dt.datetime, host_id: int = 1) -> dict:
    b = bucket_seconds(start, end)
    rows = _bucketed(conn, models.system_metrics, start, end, b, {
        "cpu": ("cpu_pct", func.avg), "cpu_max": ("cpu_pct", func.max), "load1": ("load1", func.avg),
        "mem": ("mem_used_pct", func.avg), "disk": ("disk_used_pct", func.avg)}, host_id=host_id)
    return {
        "bucket_s": b,
        "labels": [_iso(x["bucket"]) for x in rows],
        "cpu": [_r(x["cpu"]) for x in rows], "cpu_max": [_r(x["cpu_max"]) for x in rows],
        "load1": [_r(x["load1"]) for x in rows], "mem": [_r(x["mem"]) for x in rows], "disk": [_r(x["disk"]) for x in rows],
    }


def temperatures(conn, start: dt.datetime, end: dt.datetime, host_id: int = 1) -> dict:
    b = bucket_seconds(start, end)
    rows = _bucketed(conn, models.system_temperature, start, end, b,
                     {"t": ("temperature", func.avg)}, group_extra=("adapter", "device"), host_id=host_id)
    labels: list[str] = []
    index: dict[str, int] = {}
    series: dict[str, dict[str, float]] = {}
    for x in rows:
        label = _iso(x["bucket"])
        if label not in index:
            index[label] = len(labels)
            labels.append(label)
        series.setdefault(f"{x['adapter']} - {x['device']}", {})[label] = _r(x["t"], 1)
    return {"bucket_s": b, "labels": labels,
            "series": {n: [v.get(lbl) for lbl in labels] for n, v in sorted(series.items())}}


def speedtests(conn, start: dt.datetime, end: dt.datetime) -> dict:
    S = models.speedtest_results
    rows = db.rows(conn, select(S.c.timestamp, S.c.download_mbps, S.c.upload_mbps, S.c.latency_ms, S.c.status, S.c.provider)
                   .where(S.c.timestamp >= start, S.c.timestamp < end).order_by(S.c.timestamp))
    return {
        "labels": [_iso(x["timestamp"]) for x in rows],
        "download": [x["download_mbps"] for x in rows],
        # L'upload misurato dalla 1.x non è attendibile: non lo mostro (resta nel DB)
        "upload": [None if x["provider"] == "legacy" else x["upload_mbps"] for x in rows],
        "latency": [x["latency_ms"] for x in rows],
        "status": [x["status"] for x in rows],
        "provider": [x["provider"] for x in rows],
    }


def latest_speedtest(conn) -> dict | None:
    S = models.speedtest_results
    row = db.one(conn, select(S.c.timestamp, S.c.download_mbps, S.c.upload_mbps, S.c.latency_ms, S.c.status, S.c.provider)
                 .where(S.c.provider != "legacy").order_by(S.c.timestamp.desc()).limit(1))
    if row:
        row["timestamp"] = _iso(row["timestamp"])
    return row


def public_ip_history(conn, limit: int = 20) -> list[dict]:
    P = models.public_ip_history
    rows = db.rows(conn, select(P.c.timestamp, P.c.ip, P.c.previous_ip).order_by(P.c.timestamp.desc()).limit(limit))
    for r in rows:
        r["timestamp"] = _iso(r["timestamp"])
    return rows


def connectivity(conn, start: dt.datetime, end: dt.datetime) -> dict:
    """Latenza e perdita per destinazione (a bucket) e interruzioni della connessione Internet."""
    C = models.connectivity_samples
    b = bucket_seconds(start, end)
    if b < 300 and (end - start).total_seconds() <= 6 * 3600:
        b = 60
    if (end - start).total_seconds() <= 6 * 3600:
        b = 60
    rows = _bucketed(conn, C, start, end, b, {"rtt": ("rtt_avg_ms", func.avg), "loss": ("loss_pct", func.avg),
                                              "role": ("role", func.max)}, group_extra=("target",))
    labels, index, series = [], {}, {}
    for r in rows:
        lbl = _iso(r["bucket"])
        if lbl not in index:
            index[lbl] = len(labels)
            labels.append(lbl)
        sr = series.setdefault(r["target"], {"role": r["role"], "rtt": {}, "loss": {}})
        sr["rtt"][lbl] = _r(r["rtt"], 1)
        sr["loss"][lbl] = _r(r["loss"], 1)
    out_series = {t: {"role": v["role"], "rtt": [v["rtt"].get(x) for x in labels], "loss": [v["loss"].get(x) for x in labels]}
                  for t, v in series.items()}

    return {"bucket_s": b, "labels": labels, "series": out_series, **outages(conn, start, end)}


def outages(conn, start: dt.datetime, end: dt.datetime) -> dict:
    """Interruzioni della connessione Internet (minuti senza risposta da nessuna destinazione) e disponibilità."""
    C = models.connectivity_samples
    # minuti senza risposta da nessuna destinazione Internet = interruzione
    minutes = db.rows(conn, select(C.c.timestamp.label("ts"), func.max(C.c.received).label("best"))
                      .where(C.c.role == "internet", C.c.timestamp >= start, C.c.timestamp < end)
                      .group_by(C.c.timestamp).order_by(C.c.timestamp))
    found, cur = [], None
    for m in minutes:
        t = db.as_datetime(m["ts"])
        if m["best"] == 0:
            if cur and (t - cur["end"]).total_seconds() <= 150:
                cur["end"] = t
                cur["samples"] += 1
            else:
                cur = {"start": t, "end": t, "samples": 1}
                found.append(cur)
        else:
            cur = None
    down = sum(o["samples"] for o in found)
    total = len(minutes)
    return {
        "samples": total, "down_minutes": down,
        "availability": round(100 - down / total * 100, 3) if total else None,
        "outages": [{"start": o["start"].isoformat(timespec="minutes"), "end": o["end"].isoformat(timespec="minutes"),
                     "minutes": o["samples"]} for o in found],
    }
