"""Controlli di altri dispositivi e servizi. Gira ogni minuto; ogni controllo ha il suo intervallo.

Stato effettivo per controllo (monitor_state "check:<id>"):
  DOWN     dopo `retries` fallimenti consecutivi;
  WARNING  riuscito ma con anomalia (certificato in scadenza, molti pacchetti persi);
  OK       altrimenti.
Avvisi: evento "Dispositivi e servizi" (regola e canali in Impostazioni > Notifiche); cambi di stato
anche come eventi sui grafici.
"""
from __future__ import annotations

import datetime as dt
import logging
from concurrent.futures import ThreadPoolExecutor

from sqlalchemy import true as sa_true, select

from .. import checks as checks_mod
from .. import db, events, i18n, models, notifier
from .. import settings as settings_mod
from ..config import Config
from .base import run

log = logging.getLogger("job.checks")


def due(c: dict, last: dict | None, now: dt.datetime) -> bool:
    if not last or not last.get("time"):
        return True
    return (now - dt.datetime.fromisoformat(last["time"])).total_seconds() >= c["interval_s"] - 15


def apply_result(c: dict, res: checks_mod.Result, last: dict | None, now: dt.datetime) -> dict:
    """Nuovo stato del controllo a partire dal risultato grezzo e dallo stato precedente."""
    prev_status = (last or {}).get("status")
    fails = 0 if res.ok else (last or {}).get("fails", 0) + 1
    if res.ok:
        status = "WARNING" if res.warning else "OK"
    elif fails >= c["retries"]:
        status = "DOWN"
    else:
        status = prev_status or "OK"           # fallimento isolato: non cambia lo stato
    since = (last or {}).get("since") if status == prev_status else now.isoformat(timespec="seconds")
    return {"time": now.isoformat(timespec="seconds"), "status": status, "fails": fails, "ok": res.ok,
            "latency_ms": res.latency_ms, "detail": res.detail, "warning": res.warning,
            "cert_days": round(res.cert_days, 1) if res.cert_days is not None else None, "since": since or now.isoformat()}


def main(cfg: Config, dry_run: bool) -> int:
    now = dt.datetime.now().replace(microsecond=0)
    with db.connect(cfg.database) as conn:
        C = models.checks
        items = db.rows(conn, select(C).where(C.c.enabled == sa_true()).order_by(C.c.sort_order, C.c.id))
        states = {c["id"]: db.state_get(conn, f"check:{c['id']}") for c in items}
        values = settings_mod.load(conn, cfg)
    todo = [c for c in items if dry_run or due(c, states[c["id"]], now)]
    if not todo:
        return 0
    with ThreadPoolExecutor(max_workers=min(16, len(todo))) as ex:
        results = dict(zip([c["id"] for c in todo], ex.map(checks_mod.run, todo)))
    if dry_run:
        for c in todo:
            r = results[c["id"]]
            log.info("%s (%s %s): %s %s %s", c["name"], c["kind"], c["target"], "OK" if r.ok else "KO", r.latency_ms, r.detail)
        return 0

    lang = i18n.lang_of(values)
    tr = i18n.translator(lang)
    rule = settings_mod.policy(values, "checks")
    with db.connect(cfg.database) as conn:
        conn.execute(models.check_results.insert(), [
            {"timestamp": now, "check_id": cid, "ok": r.ok, "latency_ms": r.latency_ms, "detail": (r.warning or r.detail)[:300]}
            for cid, r in results.items()])
        for c in todo:
            last = states[c["id"]]
            new = apply_result(c, results[c["id"]], last, now)
            db.state_set(conn, f"check:{c['id']}", new)
            prev = (last or {}).get("status")
            if prev and prev != new["status"]:
                log.info("%s: %s -> %s (%s)", c["name"], prev, new["status"], new["detail"])
                down = new["status"] == "DOWN"
                events.record(conn, "check", "alert" if down else "info",
                              f"{c['name']}: non raggiungibile" if down else f"{c['name']}: di nuovo raggiungibile",
                              new["warning"] or new["detail"], when=now)
            state = notifier.AlertState(conn, f"check:{c['id']}")
            should_notify, reason, previous = state.evaluate(new["status"], rule)
            if should_notify:
                where = c["target"] + (f":{c['port']}" if c.get("port") else "")
                if new["status"] == "OK":
                    subject = tr("{p0}: di nuovo raggiungibile", p0=c["name"])
                elif new["status"] == "DOWN":
                    subject = tr("{p0}: non raggiungibile", p0=c["name"])
                else:
                    subject = f"{c['name']}: WARNING"
                body = "\n".join(x for x in (
                    notifier.reason_line(reason, state, lang),
                    f"{c['kind'].upper()} {where}",
                    tr("Stato: {stato}", stato=new["status"]) + f" — {i18n.translate_stored(new['warning'] or new['detail'], lang)}",
                    tr("Stato precedente: {stato}", stato=previous or "n/d")) if x)
                if notifier.dispatch(conn, cfg, "checks", subject, body, detected_at=now):
                    state.mark_notified()
            state.save()
    return 0


def entrypoint() -> None:
    run("checks", "Controlli di altri dispositivi e servizi", main)


if __name__ == "__main__":
    entrypoint()
