"""Server collegati: ogni minuto controlla chi non invia dati e valuta gli allarmi degli agenti.

Per ciascun agente: non raggiungibile (nessun invio da `hosts.offline_minutes`), disco e
temperatura con le soglie del centrale, servizi fermi. Gli avvisi usano le regole e i canali di
sempre; l'oggetto inizia con il nome del server.
"""
from __future__ import annotations

import datetime as dt
import logging

from .. import db, events, hosts, i18n, notifier
from .. import settings as settings_mod
from ..config import Config
from .base import run

log = logging.getLogger("job.hosts")


def level(value, warning, alert) -> str:
    if value is None:
        return "OK"
    return "ALERT" if value >= alert else "WARNING" if value >= warning else "OK"


def main(cfg: Config, dry_run: bool) -> int:
    now = dt.datetime.now().replace(microsecond=0)
    with db.connect(cfg.database) as conn:
        values = settings_mod.load(conn, cfg)
        mins = int(values["hosts.offline_minutes"])
        lang = i18n.lang_of(values)
        tr = i18n.translator(lang)
        for h in hosts.listing(conn, mins):
            if h["id"] == hosts.LOCAL_ID or not h["enabled"] or h["status"] == "WAITING":
                continue
            name = h["name"]
            checks = []
            # --- raggiungibile
            online = h["status"] != "DOWN"
            st_on = "OK" if online else "DOWN"
            last = h["last_seen"][11:16] if h["last_seen"] else "–"
            checks.append(("online", "hosts", st_on,
                           tr("{p0}: di nuovo raggiungibile", p0=name) if online else tr("{p0}: non raggiungibile", p0=name),
                           tr("Ultimo invio dei dati alle {p0}.", p0=last)))
            snap = h["snapshot"] or {}
            lim = hosts.limits(h, cfg)                                  # 4.2: soglie del server
            if online and snap:
                disks = [x for x in (snap.get("disks") or []) if x.get("used_pct") is not None]
                worst = max(disks, key=lambda x: x["used_pct"]) if disks else {"mountpoint": "/", "used_pct": snap.get("disk_used_pct")}
                d = worst["used_pct"]
                st = level(d, lim["disk_warning"], lim["disk_alert"])
                checks.append(("disk", "disk", st, f"[{name}] " + (tr("Allarme {nome} rientrato", nome=tr("Disco").lower()) if st == "OK" else f"{tr('Disco')}: {st}"),
                               tr("Disco {disco} occupato al {pct}%", disco=worst["mountpoint"], pct=round(d or 0))))
                tmax = snap.get("temperature_max")
                if tmax is not None:
                    st = level(tmax, lim["temp_warning"], lim["temp_alert"])
                    checks.append(("temperature", "temperature", st,
                                   f"[{name}] " + (tr("Allarme {nome} rientrato", nome=tr("Temperatura").lower()) if st == "OK" else f"{tr('Temperatura')}: {st}"),
                                   tr("Temperatura massima {t} °C ({sensore})", t=f"{tmax:.1f}", sensore=name)))
                for s in (h["services_state"] or {}).get("services", []):
                    st = "OK" if s["up"] else "ALERT"
                    checks.append((f"service:{s['unit']}", "services", st,
                                   f"[{name}] " + (tr("Servizio {nome} di nuovo attivo", nome=s["label"]) if s["up"]
                                                   else tr("Servizio {nome} fermo ({stato})", nome=s["label"], stato=s["state"])),
                                   tr("Servizio: {nome} ({unit})", nome=s["label"], unit=s["unit"])))
            for key, source, status, subject, text in checks:
                state = notifier.AlertState(conn, f"host:{h['id']}:{key}")
                prev = state.status
                should, reason, previous = state.evaluate(status, settings_mod.policy(values, source))
                if key == "online" and prev and prev != status:
                    events.record(conn, "host", "alert" if status == "DOWN" else "info",
                                  f"{name}: non raggiungibile" if status == "DOWN" else f"{name}: di nuovo raggiungibile",
                                  text, when=now, host_id=h["id"])
                if key == "online" and not h.get("notify_offline", True):
                    should = False                                       # 4.2: server che si spegne volutamente
                if should and not dry_run:
                    body = "\n".join(x for x in (notifier.reason_line(reason, state, lang), text,
                                                 tr("Stato precedente: {stato}", stato=previous or "n/d")) if x)
                    if notifier.dispatch(conn, cfg, source, subject, body, detected_at=now):
                        state.mark_notified()
                if not dry_run:
                    state.save()
    return 0


def entrypoint() -> None:
    run("hosts", "Controllo dei server collegati", main)


if __name__ == "__main__":
    entrypoint()
