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
from ..collectors import smart
from ..integrations import docker as docker_mod
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
            lim = hosts.limits(h, cfg, values)                          # 4.2: soglie del server
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
                if values["load.alerts_enabled"]:                       # 4.2: CPU e memoria, se attivati
                    for key, field, w, a2, label in (("cpu", "cpu_pct", "cpu_warning", "cpu_alert", "CPU"),
                                                     ("memory", "mem_used_pct", "mem_warning", "mem_alert", "Memoria")):
                        v = snap.get(field)
                        if v is None:
                            continue
                        st = level(v, lim[w], lim[a2])
                        checks.append((key, key, st, f"[{name}] " + (tr("Allarme {nome} rientrato", nome=tr(label).lower()) if st == "OK" else f"{tr(label)}: {st}"),
                                       tr("{nome} al {pct}%", nome=tr(label), pct=round(v)) + " · "
                                       + tr("Soglie: warning {w}%, alert {a}%", w=lim[w], a=lim[a2])))
                for s in (h["services_state"] or {}).get("services", []):
                    if s.get("status") in ("pending", "unseen", "missing", "rest") or s.get("ondemand") and not s["up"]:
                        continue                                  # 4.3: discontinui, in attesa, inesistenti: niente avvisi
                    st = "OK" if s["up"] else "ALERT"
                    checks.append((f"service:{s['unit']}", "services", st,
                                   f"[{name}] " + (tr("Servizio {nome} di nuovo attivo", nome=s["label"]) if s["up"]
                                                   else tr("Servizio {nome} fermo ({stato})", nome=s["label"], stato=s["state"])),
                                   tr("Servizio: {nome} ({unit})", nome=s["label"], unit=s["unit"])))
            if online:                                                   # 4.2: dischi, aggiornamenti e Docker dagli agenti
                health = h.get("health") or {}
                for d in health.get("disks", []):
                    st, why = smart.evaluate(d, values["smart.temp_warning"], values["smart.wear_warning"])
                    if st == "UNKNOWN":
                        continue
                    label = f"{d['device']} {d.get('model') or ''}".strip()
                    checks.append((f"smart:{d['device']}", "smart", st,
                                   f"[{name}] " + (tr("Disco {p0}: di nuovo regolare", p0=label) if st == "OK" else tr("Disco {p0}: {p1}", p0=label, p1=st)),
                                   "; ".join(i18n.translate_stored(r, lang) for r in why) or tr("Salute del disco regolare")))
                upd = health.get("updates")
                if upd and not upd.get("error"):
                    sec, rb = upd.get("security_count", 0), upd.get("reboot", {}).get("required")
                    st = "WARNING" if sec or rb else "OK"
                    parts = ([tr("{p0} aggiornamenti di sicurezza da installare", p0=sec)] if sec else []) + \
                            ([tr("riavvio richiesto")] if rb else [])
                    checks.append(("updates", "updates", st,
                                   f"[{name}] " + (tr("Aggiornamenti installati") if st == "OK" else tr("Aggiornamenti in sospeso")),
                                   "; ".join(parts) or tr("{p0} aggiornamenti disponibili", p0=upd.get("total", 0))))
                for c in (h.get("containers") or {}).get("containers", []):
                    st = docker_mod.evaluate(c)
                    checks.append((f"docker:{c['name']}", "docker", st,
                                   f"[{name}] " + (tr("Container {p0} di nuovo regolare", p0=c["name"]) if st == "OK"
                                                   else tr("Container {p0}: {p1}", p0=c["name"], p1=c["state"])),
                                   f"{c['image']} · {c['status']}"))
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
