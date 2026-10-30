"""Query sullo storico, aggregate a intervalli (bucket) calcolati da SQL Server."""
from __future__ import annotations

import datetime as dt

from .. import db

# Ampiezze di bucket ammesse (secondi): si sceglie la più piccola che dà
# al massimo ~TARGET_POINTS punti nel periodo richiesto.
BUCKETS = [300, 600, 900, 1800, 3600, 7200, 10800, 21600, 43200, 86400]
TARGET_POINTS = 300
EPOCH = "20000101"


def bucket_seconds(start: dt.datetime, end: dt.datetime) -> int:
    span = (end - start).total_seconds()
    for b in BUCKETS:
        if span / b <= TARGET_POINTS:
            return b
    return BUCKETS[-1]


def _bucket_expr(col: str) -> str:
    # %s ripetuto: pymssql sostituisce lato client, i valori sono interi validati
    return f"DATEADD(SECOND, (DATEDIFF(SECOND, '{EPOCH}', {col}) / %s) * %s, '{EPOCH}')"


def _iso(value) -> str:
    return db.as_datetime(value).isoformat(timespec="seconds")


def metrics(conn, start: dt.datetime, end: dt.datetime) -> dict:
    b = bucket_seconds(start, end)
    sql = f"""
    WITH x AS (
        SELECT {_bucket_expr('[timestamp]')} AS bucket,
               cpu_pct, load1, mem_used_pct, disk_used_pct
        FROM system_metrics
        WHERE [timestamp] >= CONVERT(datetime2(0), %s, 126)
          AND [timestamp] <  CONVERT(datetime2(0), %s, 126)
    )
    SELECT bucket, AVG(cpu_pct) AS cpu, MAX(cpu_pct) AS cpu_max, AVG(load1) AS load1,
           AVG(mem_used_pct) AS mem, AVG(disk_used_pct) AS disk
    FROM x GROUP BY bucket ORDER BY bucket
    """
    rows = db.query(conn, sql, (b, b, db.ts(start), db.ts(end)))

    def r(v):
        return None if v is None else round(float(v), 2)

    return {
        "bucket_s": b,
        "labels": [_iso(x["bucket"]) for x in rows],
        "cpu": [r(x["cpu"]) for x in rows],
        "cpu_max": [r(x["cpu_max"]) for x in rows],
        "load1": [r(x["load1"]) for x in rows],
        "mem": [r(x["mem"]) for x in rows],
        "disk": [r(x["disk"]) for x in rows],
    }


def temperatures(conn, start: dt.datetime, end: dt.datetime) -> dict:
    b = bucket_seconds(start, end)
    sql = f"""
    WITH x AS (
        SELECT {_bucket_expr('[timestamp]')} AS bucket, adapter, device, temperature
        FROM system_temperature
        WHERE [timestamp] >= CONVERT(datetime, %s, 126)
          AND [timestamp] <  CONVERT(datetime, %s, 126)
    )
    SELECT bucket, adapter, device, AVG(temperature) AS t
    FROM x GROUP BY bucket, adapter, device ORDER BY bucket
    """
    rows = db.query(conn, sql, (b, b, db.ts(start), db.ts(end)))
    labels: list[str] = []
    index: dict[str, int] = {}
    series: dict[str, dict[str, float]] = {}
    for x in rows:
        label = _iso(x["bucket"])
        if label not in index:
            index[label] = len(labels)
            labels.append(label)
        name = f"{x['adapter']} - {x['device']}"
        series.setdefault(name, {})[label] = round(float(x["t"]), 1)
    # Serie allineate sulle stesse etichette (null dove manca il dato)
    aligned = {name: [vals.get(lbl) for lbl in labels] for name, vals in sorted(series.items())}
    return {"bucket_s": b, "labels": labels, "series": aligned}


def speedtests(conn, start: dt.datetime, end: dt.datetime) -> dict:
    rows = db.query(
        conn,
        """
        SELECT [timestamp], download_mbps, upload_mbps, latency_ms, status, provider
        FROM speedtest_results
        WHERE [timestamp] >= CONVERT(datetime2(0), %s, 126)
          AND [timestamp] <  CONVERT(datetime2(0), %s, 126)
        ORDER BY [timestamp]
        """,
        (db.ts(start), db.ts(end)),
    )
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
    row = db.query_one(
        conn,
        "SELECT TOP 1 [timestamp], download_mbps, upload_mbps, latency_ms, status, provider "
        "FROM speedtest_results WHERE provider <> 'legacy' ORDER BY [timestamp] DESC",
    )
    if not row:
        return None
    row["timestamp"] = _iso(row["timestamp"])
    return row


def public_ip_history(conn, limit: int = 20) -> list[dict]:
    rows = db.query(
        conn,
        "SELECT TOP (%s) [timestamp], ip, previous_ip FROM public_ip_history ORDER BY [timestamp] DESC",
        (limit,),
    )
    for r in rows:
        r["timestamp"] = _iso(r["timestamp"])
    return rows


def connectivity(conn, start: dt.datetime, end: dt.datetime) -> dict:
    """Latenza e perdita per destinazione (a bucket) e interruzioni della connessione Internet."""
    b = bucket_seconds(start, end)
    if b < 300 and (end - start).total_seconds() <= 6 * 3600:
        b = 60
    params = (db.ts(start), db.ts(end))
    rows = db.query(conn, f"""
        WITH x AS (
            SELECT {_bucket_expr('[timestamp]')} AS bucket, target, role, loss_pct, rtt_avg_ms
            FROM connectivity_samples
            WHERE [timestamp] >= CONVERT(datetime2(0), %s, 126) AND [timestamp] < CONVERT(datetime2(0), %s, 126)
        )
        SELECT bucket, target, MAX(role) AS role, AVG(rtt_avg_ms) AS rtt, AVG(loss_pct) AS loss, MAX(loss_pct) AS loss_max
        FROM x GROUP BY bucket, target ORDER BY bucket""", (b, b) + params)
    labels, index, series = [], {}, {}
    for r in rows:
        lbl = _iso(r["bucket"])
        if lbl not in index:
            index[lbl] = len(labels)
            labels.append(lbl)
        sr = series.setdefault(r["target"], {"role": r["role"], "rtt": {}, "loss": {}})
        sr["rtt"][lbl] = None if r["rtt"] is None else round(float(r["rtt"]), 1)
        sr["loss"][lbl] = round(float(r["loss"]), 1)
    out_series = {t: {"role": v["role"], "rtt": [v["rtt"].get(l) for l in labels], "loss": [v["loss"].get(l) for l in labels]}
                  for t, v in series.items()}

    # minuti senza risposta da nessuna destinazione Internet = interruzione
    minutes = db.query(conn, """
        SELECT [timestamp] AS ts, MAX(received) AS best FROM connectivity_samples
        WHERE role = 'internet' AND [timestamp] >= CONVERT(datetime2(0), %s, 126) AND [timestamp] < CONVERT(datetime2(0), %s, 126)
        GROUP BY [timestamp] ORDER BY [timestamp]""", params)
    outages, cur = [], None
    for m in minutes:
        t = db.as_datetime(m["ts"])
        if m["best"] == 0:
            if cur and (t - cur["end"]).total_seconds() <= 150:
                cur["end"] = t
                cur["samples"] += 1
            else:
                cur = {"start": t, "end": t, "samples": 1}
                outages.append(cur)
        else:
            cur = None
    down = sum(o["samples"] for o in outages)
    total = len(minutes)
    return {
        "bucket_s": b, "labels": labels, "series": out_series,
        "samples": total, "down_minutes": down,
        "availability": round(100 - down / total * 100, 3) if total else None,
        "outages": [{"start": o["start"].isoformat(timespec="minutes"), "end": o["end"].isoformat(timespec="minutes"),
                     "minutes": o["samples"]} for o in outages],
    }
