"""Server collegati (4.0): il centrale è l'host 1, gli altri inviano i dati con un agente.

Ogni agente ha un token (nel database solo il suo sha256) e può solo scrivere i propri dati:
metriche, temperature, stato dei servizi e riavvii. Riceve in risposta l'elenco dei servizi da
controllare per sé, nient'altro.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import math
import re
import secrets

from sqlalchemy import delete, func, select, update

from . import db, events, models

LOCAL_ID = 1
KINDS = ("linux", "windows")
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._\-]{0,63}$")
MAX_ITEMS = 500
H = models.hosts


class HostError(ValueError):
    """Dati non validi (messaggio per l'utente o per l'agente)."""


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def new_token() -> str:
    return "agt_" + secrets.token_urlsafe(32)


def clean_services(text: str) -> str:
    units = [u.strip() for u in re.split(r"[,\n]", text or "") if u.strip()]
    for u in units:
        if not re.match(r"^[A-Za-z0-9@._:\-\\$ ]{1,120}$", u):
            raise HostError(f"Nome di servizio non valido: {u}")
    if len(units) > 60:
        raise HostError("Al massimo 60 servizi per server")
    return ",".join(dict.fromkeys(units))


def create(conn, name: str, kind: str, services: str = "") -> tuple[int, str]:
    name = (name or "").strip()
    if not NAME_RE.match(name):
        raise HostError("Nome non valido: lettere, numeri, spazi, punto, trattino (massimo 64)")
    if kind not in KINDS:
        raise HostError("Sistema non valido: linux o windows")
    if db.scalar(conn, select(func.count()).select_from(H).where(func.lower(H.c.name) == name.lower())):
        raise HostError(f"Esiste già un server chiamato {name}")
    token = new_token()
    top = db.scalar(conn, select(func.coalesce(func.max(H.c.sort_order), 0))) or 0
    hid = conn.execute(H.insert().values(name=name, kind=kind, token_hash=token_hash(token), services=clean_services(services),
                                         enabled=True, sort_order=top + 10, created_at=db.now())).inserted_primary_key[0]
    return int(hid), token


def regenerate(conn, hid: int) -> str:
    token = new_token()
    if hid == LOCAL_ID or not conn.execute(update(H).where(H.c.id == hid).values(token_hash=token_hash(token), enabled=True)).rowcount:
        raise HostError("Server inesistente")
    return token


def by_token(conn, token: str) -> dict | None:
    if not token or len(token) > 200:
        return None
    return db.one(conn, select(H).where(H.c.token_hash == token_hash(token), H.c.enabled == models_true(), H.c.id != LOCAL_ID))


def models_true():
    from sqlalchemy import true
    return true()


def remove(conn, hid: int) -> None:
    if hid == LOCAL_ID:
        raise HostError("Il server centrale non si può eliminare")
    for t in (models.system_metrics, models.system_temperature, models.events):
        conn.execute(delete(t).where(t.c.host_id == hid))
    S = models.monitor_state
    conn.execute(delete(S).where(S.c.key.like(f"host:{hid}:%") | S.c.key.like(f"alert:host:{hid}:%")))
    if not conn.execute(delete(H).where(H.c.id == hid)).rowcount:
        raise HostError("Server inesistente")


def listing(conn, offline_minutes: int) -> list[dict]:
    now = dt.datetime.now()
    out = []
    for h in db.rows(conn, select(H).order_by(H.c.sort_order, H.c.id)):
        h = {k: v for k, v in h.items() if k != "token_hash"}
        if h["id"] == LOCAL_ID:
            h["status"] = "OK"
        else:
            seen = db.as_datetime(h["last_seen"]) if h["last_seen"] else None
            h["status"] = ("DISABLED" if not h["enabled"] else "WAITING" if not seen
                           else "DOWN" if (now - seen).total_seconds() > offline_minutes * 60 else "OK")
        h["snapshot"] = db.state_get(conn, f"host:{h['id']}:snapshot")
        h["services_state"] = db.state_get(conn, f"host:{h['id']}:services")
        for k in ("created_at", "last_seen"):
            h[k] = db.as_datetime(h[k]).isoformat(timespec="seconds") if h[k] else None
        out.append(h)
    return out


# ----------------------------------------------------------------------------- ricezione
def _num(v, lo: float, hi: float):
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        raise HostError("valore numerico non valido") from None
    if math.isnan(f) or not lo <= f <= hi:
        raise HostError("valore fuori intervallo")
    return f


def _time(v, now: dt.datetime, max_age_days: int = 2) -> dt.datetime:
    try:
        t = dt.datetime.fromisoformat(str(v)[:19])
    except ValueError:
        raise HostError("ora non valida") from None
    if t > now + dt.timedelta(minutes=10) or t < now - dt.timedelta(days=max_age_days):
        raise HostError("ora fuori intervallo (orologio dell'agente da controllare)")
    return t.replace(microsecond=0)


def _txt(v, n: int) -> str:
    return str(v or "")[:n]


def _disks(v) -> list[dict]:
    """4.0.1: tutti i dischi fissi dell'agente (Linux: punti di montaggio, Windows: unità)."""
    if v is None:
        return []
    if not isinstance(v, list) or len(v) > 32:
        raise HostError("dischi non validi")
    out = []
    for d in v:
        if not isinstance(d, dict):
            raise HostError("disco non valido")
        out.append({"mountpoint": _txt(d.get("mountpoint"), 120), "device": _txt(d.get("device"), 120),
                    "fstype": _txt(d.get("fstype"), 20), "label": _txt(d.get("label"), 60),
                    "total_mb": _num(d.get("total_mb"), 0, 1e12), "used_mb": _num(d.get("used_mb"), 0, 1e12),
                    "free_mb": _num(d.get("free_mb"), 0, 1e12), "used_pct": _num(d.get("used_pct"), 0, 100)})
    return out


def ingest(conn, host: dict, payload: dict) -> dict:
    """Registra un pacchetto dell'agente. Ritorna la risposta per l'agente."""
    if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
        raise HostError("formato non valido")
    items = payload["items"]
    if len(items) > MAX_ITEMS:
        raise HostError(f"al massimo {MAX_ITEMS} elementi per invio")
    now = dt.datetime.now()
    agent = payload.get("agent") or {}
    metrics, temps, latest, rejected = [], [], None, []
    for it in items:
        try:
            latest = _item(conn, host, it, now, metrics, temps, latest)
        except HostError as exc:                  # si scarta solo l'elemento non valido, non tutto l'invio
            rejected.append(f"{str(it.get('type') if isinstance(it, dict) else '?')[:20]}: {exc}")
    return _finish(conn, host, agent, items, metrics, temps, latest, rejected, now)


def _item(conn, host: dict, it, now: dt.datetime, metrics: list, temps: list, latest: dict | None) -> dict | None:
    hid = host["id"]
    if not isinstance(it, dict):
        raise HostError("elemento non valido")
    kind, t = it.get("type"), _time(it.get("time"), now)
    if kind == "metrics":
        row = {"timestamp": t, "host_id": hid, "source": "agent",
               "cpu_pct": _num(it.get("cpu_pct"), 0, 100), "load1": _num(it.get("load1"), 0, 10000),
               "load5": _num(it.get("load5"), 0, 10000), "load15": _num(it.get("load15"), 0, 10000),
               "mem_used_pct": _num(it.get("mem_used_pct"), 0, 100), "swap_used_pct": _num(it.get("swap_used_pct"), 0, 100),
               "disk_used_pct": _num(it.get("disk_used_pct"), 0, 100)}
        mb = _num(it.get("mem_used_mb"), 0, 1e9)
        row["mem_used_mb"] = int(mb) if mb is not None else None
        metrics.append(row)
        if latest is None or t >= latest["time"]:
            latest = {**{k: v for k, v in row.items() if k not in ("timestamp", "host_id", "source")}, "time": t,
                      "uptime_s": _num(it.get("uptime_s"), 0, 1e10), "mem_total_mb": _num(it.get("mem_total_mb"), 0, 1e9),
                      "disks": _disks(it.get("disks"))}
    elif kind == "temperatures":
        sensors = it.get("sensors") or []
        if not isinstance(sensors, list) or len(sensors) > 64:
            raise HostError("sensori non validi")
        for s in sensors:
            temps.append({"timestamp": t, "host_id": hid, "adapter": _txt(s.get("adapter"), 255),
                          "device": _txt(s.get("device"), 255), "temperature": _num(s.get("value"), -50, 200)})
    elif kind == "services":
        svc = it.get("services") or []
        if not isinstance(svc, list) or len(svc) > 60:
            raise HostError("servizi non validi")
        current = [{"unit": _txt(s.get("unit"), 120), "label": _txt(s.get("label") or s.get("unit"), 100),
                    "up": bool(s.get("up")), "state": _txt(s.get("state"), 40)} for s in svc]
        _services(conn, host, current, t)
    elif kind == "boot":
        bt = _time(it.get("boot_time"), now, max_age_days=30)
        events.record(conn, "boot", "info", "Riavvio del server", "", ref=f"boot:{hid}:{bt.isoformat()}",
                      when=bt, host_id=hid)
    else:
        raise HostError(f"tipo sconosciuto: {_txt(kind, 20)}")
    return latest


def _finish(conn, host, agent, items, metrics, temps, latest, rejected, now) -> dict:
    hid = host["id"]
    if metrics:
        conn.execute(models.system_metrics.insert(), metrics)
    if temps:
        conn.execute(models.system_temperature.insert(), temps)
    if latest:
        latest["time"] = latest["time"].isoformat(timespec="seconds")
        latest["temperature_max"] = max((x["temperature"] for x in temps if x["temperature"] is not None), default=None)
        prev = db.state_get(conn, f"host:{hid}:snapshot") or {}
        if latest["temperature_max"] is None:
            latest["temperature_max"] = prev.get("temperature_max")
        db.state_set(conn, f"host:{hid}:snapshot", latest)
    vals = {"last_seen": now.replace(microsecond=0)}
    if agent.get("version"):                  # la prova di collegamento non li invia: non si cancellano
        vals["agent_version"] = _txt(agent["version"], 32)
    if agent.get("os"):
        vals["os_info"] = _txt(agent["os"], 200)
    conn.execute(update(H).where(H.c.id == hid).values(**vals))
    return {"ok": True, "accepted": len(items) - len(rejected), "rejected": rejected[:20],
            "services": [u for u in (host.get("services") or "").split(",") if u]}


def _services(conn, host: dict, current: list[dict], t: dt.datetime) -> None:
    """Stato dei servizi dell'agente; un evento a ogni cambio (fermo / ripartito)."""
    hid = host["id"]
    prev = {s["unit"]: s for s in (db.state_get(conn, f"host:{hid}:services") or {}).get("services", [])}
    for s in current:
        p = prev.get(s["unit"])
        if p is not None and p["up"] != s["up"]:
            events.record(conn, "service", "info" if s["up"] else "alert",
                          f"Servizio {s['label']} ripartito" if s["up"] else f"Servizio {s['label']} fermo",
                          s["state"], when=t, host_id=hid)
    db.state_set(conn, f"host:{hid}:services", {"time": t.isoformat(timespec="seconds"), "services": current})
