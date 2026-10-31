"""Endpoint compatibili con il vecchio proxy NetPulse, usati dal widget Windows.

nginx sulla porta 8081 inoltra /api/<x> a /api/netpulse/<x>: il widget continua
a usare lo stesso indirizzo, lo stesso certificato e lo stesso token.
Formato delle risposte identico a NetpulseProxy.py (/health, /latest, /query).
"""
from __future__ import annotations

import datetime as dt
import hmac

from flask import Blueprint, current_app, jsonify, request

from sqlalchemy import select

from .. import db, models

bp = Blueprint("netpulse", __name__, url_prefix="/api/netpulse")
MAX_ROWS = 200000


def _token_ok() -> bool:
    cfg = current_app.config["ASTREO_CFG"]
    if cfg.netpulse is None:
        return False
    auth = request.headers.get("Authorization", "")
    given = auth[7:].strip() if auth.startswith("Bearer ") else request.args.get("token", "")
    return bool(given) and hmac.compare_digest(given, cfg.netpulse.token)


def _unauthorized():
    return jsonify({"error": "Non autorizzato — token non valido o assente"}), 401


def _iso(v) -> str | None:
    v = db.as_datetime(v)
    return v.isoformat(sep=" ") if v else None


def _rows(conn, start: dt.datetime, end: dt.datetime) -> list[dict]:
    S = models.speedtest_results
    rows = db.rows(conn, select(S.c.timestamp, S.c.upload_mbps, S.c.download_mbps)
                   .where(S.c.timestamp >= start, S.c.timestamp <= end).order_by(S.c.timestamp).limit(MAX_ROWS))
    return [{"timestamp": _iso(r["timestamp"]), "upload": r["upload_mbps"], "download": r["download_mbps"]} for r in rows]


def bucket_series(rows: list[dict], dt_from: dt.datetime, dt_to: dt.datetime, buckets: int = 32) -> list[dict]:
    """Stessa logica del proxy NetPulse: n. di intervalli adattato alla cadenza reale."""
    buckets = max(2, min(int(buckets or 32), 512))
    inizio, durata = dt_from.timestamp(), dt_to.timestamp() - dt_from.timestamp()
    if durata <= 0 or not rows:
        return []
    istanti = sorted(dt.datetime.fromisoformat(r["timestamp"]).timestamp() for r in rows if r.get("timestamp"))
    if not istanti:
        return []
    if len(istanti) >= 2:
        passi = sorted(istanti[i] - istanti[i - 1] for i in range(1, len(istanti)))
        passo = passi[len(passi) // 2] or 1.0
    else:
        passo = durata
    attesi = int(durata / passo) if passo > 0 else buckets
    buckets = max(2, min(buckets, max(attesi, 2)))
    acc = [{"up": 0.0, "down": 0.0, "n": 0} for _ in range(buckets)]
    for r in rows:
        if not r.get("timestamp") or r.get("upload") is None or r.get("download") is None:
            continue
        i = int((dt.datetime.fromisoformat(r["timestamp"]).timestamp() - inizio) / durata * buckets)
        if 0 <= i < buckets:
            acc[i]["up"] += r["upload"]
            acc[i]["down"] += r["download"]
            acc[i]["n"] += 1
    out = []
    for i, a in enumerate(acc):
        centro = inizio + (i + 0.5) * (durata / buckets)
        out.append({
            "timestamp": dt.datetime.fromtimestamp(centro).isoformat(sep=" ", timespec="seconds"),
            "upload": round(a["up"] / a["n"], 3) if a["n"] else None,
            "download": round(a["down"] / a["n"], 3) if a["n"] else None,
            "samples": a["n"],
        })
    return out


@bp.get("/health")
def health():
    cfg = current_app.config["ASTREO_CFG"]
    return jsonify({"status": "ok", "backend": "astreo-monitor", "token_configured": cfg.netpulse is not None,
                    "time": dt.datetime.now().isoformat(timespec="seconds")})


@bp.get("/latest")
def latest():
    if not _token_ok():
        return _unauthorized()
    cfg = current_app.config["ASTREO_CFG"]
    with db.connect(cfg.database) as conn:
        S = models.speedtest_results
        rows = db.rows(conn, select(S.c.timestamp, S.c.upload_mbps, S.c.download_mbps).order_by(S.c.timestamp.desc()).limit(2))
        if not rows:
            return jsonify({"error": "Nessuna misurazione presente nella tabella"}), 404
        conv = [{"timestamp": _iso(r["timestamp"]), "upload": r["upload_mbps"], "download": r["download_mbps"]} for r in rows]
        current, previous = conv[0], (conv[1] if len(conv) > 1 else None)

        def tendenza(k):
            if not previous or current.get(k) is None or previous.get(k) is None:
                return "flat"
            a, b = current[k], previous[k]
            if b and abs(a - b) / abs(b) < 0.01:
                return "flat"
            return "up" if a > b else "down"

        try:
            eta = int((dt.datetime.now() - dt.datetime.fromisoformat(current["timestamp"])).total_seconds())
        except (TypeError, ValueError):
            eta = None
        out = {"current": current, "previous": previous,
               "trend": {"upload": tendenza("upload"), "download": tendenza("download")}, "age_seconds": eta}

        ore = request.args.get("hours", type=float)
        if ore and ore > 0:
            ore = max(0.25, min(ore, 24 * 366))
            n = request.args.get("buckets", default=32, type=int)
            dt_to = dt.datetime.now()
            dt_from = dt_to - dt.timedelta(hours=ore)
            serie = _rows(conn, dt_from, dt_to)
            out["history"] = {"hours": ore, "from": dt_from.isoformat(sep=" ", timespec="seconds"),
                              "to": dt_to.isoformat(sep=" ", timespec="seconds"), "samples": len(serie),
                              "buckets": bucket_series(serie, dt_from, dt_to, n)}
    return jsonify(out)


def _parse(value, fallback):
    if not value:
        return fallback
    try:
        return dt.datetime.fromisoformat(str(value).strip().replace("Z", "").replace("T", " "))
    except ValueError:
        return fallback


@bp.get("/query")
def query():
    if not _token_ok():
        return _unauthorized()
    cfg = current_app.config["ASTREO_CFG"]
    now = dt.datetime.now()
    end = _parse(request.args.get("to"), now)
    start = _parse(request.args.get("from"), now - dt.timedelta(days=1))
    if start > end:
        start, end = end, start
    with db.connect(cfg.database) as conn:
        return jsonify(_rows(conn, start, end))
