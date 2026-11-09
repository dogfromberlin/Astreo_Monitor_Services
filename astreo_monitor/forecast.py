"""4.4: previsione del disco pieno, dallo storico del disco di sistema di ogni server (system_metrics.disk_used_pct).

Metodo: medie orarie degli ultimi 14 giorni, retta dei minimi quadrati (occupazione in funzione del tempo).
La previsione vale solo se:
  - ci sono almeno 3 giorni di dati,
  - il disco cresce (più di 0,05 punti percentuali al giorno),
  - la crescita è regolare (R² ≥ 0,5) e distribuita nei giorni (nessun giorno vale più del 60% della crescita):
    una copia occasionale di file grandi non fa scattare nulla.
Il risultato si tiene in monitor_state per 30 minuti (forecast:<server>): è un calcolo su qualche migliaio di righe.
"""
from __future__ import annotations

import datetime as dt

from sqlalchemy import select

from . import db, models

WINDOW_DAYS = 14
MIN_DAYS = 3
MIN_SLOPE = 0.05          # punti percentuali al giorno
MIN_R2 = 0.5
MAX_STEP_SHARE = 0.6      # un solo giorno non può valere più del 60% della crescita totale
CACHE_MINUTES = 30
SHOW_DAYS = 60            # oltre, "stabile": niente numeri inutili


def fit(points: list[tuple[float, float]]) -> tuple[float, float, float] | None:
    """Retta y = a + b·x con R². x in giorni, y in percento."""
    n = len(points)
    if n < 3:
        return None
    mx = sum(p[0] for p in points) / n
    my = sum(p[1] for p in points) / n
    sxx = sum((p[0] - mx) ** 2 for p in points)
    if sxx == 0:
        return None
    sxy = sum((p[0] - mx) * (p[1] - my) for p in points)
    b = sxy / sxx
    a = my - b * mx
    ss_tot = sum((p[1] - my) ** 2 for p in points)
    ss_res = sum((p[1] - (a + b * p[0])) ** 2 for p in points)
    r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 0.0
    return a, b, r2


def compute(conn, host_id: int, now: dt.datetime) -> dict:
    M = models.system_metrics
    rows = db.rows(conn, select(M.c.timestamp, M.c.disk_used_pct)
                   .where(M.c.host_id == host_id, M.c.timestamp >= now - dt.timedelta(days=WINDOW_DAYS),
                          M.c.disk_used_pct.isnot(None)).order_by(M.c.timestamp))
    hours: dict[dt.datetime, list[float]] = {}
    for r in rows:
        t = db.as_datetime(r["timestamp"]).replace(minute=0, second=0, microsecond=0)
        hours.setdefault(t, []).append(float(r["disk_used_pct"]))
    if not hours:
        return {"status": "nodata"}
    first = min(hours)
    pts = [((t - first).total_seconds() / 86400, sum(v) / len(v)) for t, v in sorted(hours.items())]
    span = pts[-1][0] - pts[0][0]
    current = pts[-1][1]
    out = {"current": round(current, 1), "span_days": round(span, 1), "time": now.isoformat(timespec="seconds")}
    if span < MIN_DAYS:
        return {**out, "status": "learning"}                     # pochi giorni di storico
    f = fit(pts)
    if not f:
        return {**out, "status": "stable"}
    _a, slope, r2 = f
    out.update(slope_per_day=round(slope, 3), r2=round(r2, 2))
    if slope < MIN_SLOPE or r2 < MIN_R2:
        return {**out, "status": "stable"}
    # crescita concentrata in un salto (una copia di file grandi) e non distribuita nei giorni: niente previsione
    days_avg: dict[int, list[float]] = {}
    for x, y in pts:
        days_avg.setdefault(int(x), []).append(y)
    daily = [sum(v) / len(v) for _k, v in sorted(days_avg.items())]
    steps = [b2 - a2 for a2, b2 in zip(daily, daily[1:])]
    total = daily[-1] - daily[0]
    if total <= 0 or (steps and max(steps) > MAX_STEP_SHARE * total):
        return {**out, "status": "stable", "irregular": True}
    days = (100 - current) / slope
    out.update(status="growing", days_left=round(days, 1),
               full_at=(now + dt.timedelta(days=days)).date().isoformat())
    return out


def get(conn, host_id: int, now: dt.datetime | None = None, force: bool = False) -> dict:
    """Previsione del server, ricalcolata al massimo ogni CACHE_MINUTES."""
    now = now or dt.datetime.now().replace(microsecond=0)
    key = f"forecast:{host_id}"
    cached = db.state_get(conn, key)
    if cached and not force:
        try:
            if now - dt.datetime.fromisoformat(cached["time"]) < dt.timedelta(minutes=CACHE_MINUTES):
                return cached
        except (KeyError, ValueError):
            pass
    res = compute(conn, host_id, now)
    res.setdefault("time", now.isoformat(timespec="seconds"))
    db.state_set(conn, key, res)
    return res


def level(fc: dict, warn_days: float) -> str:
    """OK / WARNING (pieno entro warn_days) / ALERT (entro 3 giorni)."""
    if fc.get("status") != "growing":
        return "OK"
    d = fc["days_left"]
    return "ALERT" if d <= 3 else "WARNING" if d <= warn_days else "OK"
