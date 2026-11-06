"""Panoramica (4.1): lo stato di tutto in una risposta sola, per la pagina iniziale della dashboard.

Raccoglie quello che i job hanno già salvato (stato dei servizi, server collegati, connessione,
backup, controlli, scadenze) e ne ricava:
  - una frase di stato ("Tutto funziona", "Tutto funziona · 1 cosa da controllare", ...);
  - l'elenco "Da controllare", in ordine di importanza, con l'azione suggerita;
  - i riquadri della pagina (server, servizi, connessione, backup, ultimi eventi).
Non esegue controlli nuovi: legge soltanto, quindi è veloce e sicura da chiamare spesso.
"""
from __future__ import annotations

import datetime as dt

from sqlalchemy import select, true

from . import db, events, hosts as hosts_mod, i18n, models, services_store
from . import settings as settings_mod
from .collectors import sensors, services, smart, system
from .integrations import docker as docker_mod
from .web import history

SEVERITY_ORDER = {"alert": 0, "warn": 1, "info": 2}
BACKUP_MAX_AGE_H = 36            # oltre, il backup "di stanotte" manca
EVENTS_SHOWN = 6


def _level(value, warn, alert) -> str | None:
    if value is None:
        return None
    return "alert" if value >= alert else "warn" if value >= warn else None


def _age_hours(iso: str | None, now: dt.datetime) -> float | None:
    if not iso:
        return None
    try:
        return (now - dt.datetime.fromisoformat(str(iso)[:19])).total_seconds() / 3600
    except ValueError:
        return None


def _local_host(cfg, row: dict, svc: list[dict], values: dict | None = None) -> dict:
    snap = system.snapshot(cfg.metrics.root_disk)
    temps = sensors.read()
    disks = [{"mountpoint": d["mountpoint"], "used_pct": d["used_pct"]} for d in snap.get("disks", [])]
    return {
        "id": row["id"], "name": row["name"] or snap["hostname"], "kind": "local", "status": "OK", "enabled": True,
        "os": row.get("os_info"), "agent_version": None, "last_seen": snap["time"],
        "uptime_s": snap["uptime"]["uptime_s"], "cpu_pct": round(snap["cpu_pct"], 1),
        "mem_pct": snap["memory"]["used_pct"], "disk_pct": snap["root_disk_pct"], "disks": disks,
        "temperature_max": max((t["value"] for t in temps), default=None),
        "services": [{"unit": s["unit"], "label": s["label"], "up": s["up"], "state": s["state"]} for s in svc],
        "notify_offline": True, "limits": hosts_mod.limits(row, cfg, values),
    }


def _remote_host(h: dict, cfg, values: dict | None = None) -> dict:
    snap = h.get("snapshot") or {}
    online = h["status"] == "OK"
    disks = [{"mountpoint": d.get("mountpoint"), "used_pct": d.get("used_pct")}
             for d in (snap.get("disks") or []) if d.get("used_pct") is not None]
    return {
        "id": h["id"], "name": h["name"], "kind": h["kind"], "status": h["status"], "enabled": bool(h["enabled"]),
        "os": h.get("os_info"), "agent_version": h.get("agent_version"), "last_seen": h.get("last_seen"),
        "uptime_s": snap.get("uptime_s") if online else None,
        "cpu_pct": snap.get("cpu_pct") if online else None,
        "mem_pct": snap.get("mem_used_pct") if online else None,
        "disk_pct": max((d["used_pct"] for d in disks), default=snap.get("disk_used_pct")) if online else None,
        "disks": disks if online else [],
        "temperature_max": snap.get("temperature_max") if online else None,
        "services": [{"unit": s["unit"], "label": s["label"], "up": bool(s["up"]), "state": s.get("state")}
                     for s in (h.get("services_state") or {}).get("services", [])] if online else [],
        "notify_offline": bool(h.get("notify_offline", True)), "limits": hosts_mod.limits(h, cfg, values),
        "health": h.get("health"), "containers": (h.get("containers") or {}).get("containers"),
        "allow_commands": bool(h.get("allow_commands")),
    }


def _connection(conn, now: dt.datetime) -> dict:
    last = db.state_get(conn, "connectivity:last") or {}
    inet = [s for s in last.get("samples") or [] if s.get("role") == "internet" and s.get("rtt_avg_ms") is not None]
    week = history.outages(conn, now - dt.timedelta(days=7), now)
    return {
        "status": last.get("status"), "text": last.get("text"), "time": last.get("time"),
        "latency_ms": round(sum(s["rtt_avg_ms"] for s in inet) / len(inet), 1) if inet else None,
        "availability_7d": week["availability"], "outages_7d": len(week["outages"]),
        "down_minutes_7d": week["down_minutes"],
        "speedtest": history.latest_speedtest(conn),
        "public_ip": db.state_get(conn, "publicip:current"),
    }


def _backup(conn, values: dict | None = None) -> dict:
    bk = db.state_get(conn, "backup:last") or {}
    rt = db.state_get(conn, "restoretest:last") or {}
    dests = bk.get("destinations") or []
    values = values or {}
    external = settings_mod.external_backup(values)
    external_ok = bk.get("status") == "OK" and bool(bk.get("release") or any(d.get("ok") for d in dests if isinstance(d, dict)))
    # 4.2: avviso "nessun backup": nessuna copia fuori dal server, oppure configurata ma senza ancora un backup riuscito
    warning = None if values.get("backup.no_backup_dismissed") else "none" if not external else None if external_ok else "pending"
    return {
        "external": external, "external_ok": external_ok, "warning": warning,
        "status": bk.get("status"), "time": bk.get("time"), "databases": len(bk.get("databases") or []),
        "errors": bk.get("errors") or [], "destinations": len(dests) if isinstance(dests, list) else 0,
        "github": bool(bk.get("release")),
        "restore_test": {"status": rt.get("status"), "time": rt.get("time")} if rt else None,
    }


def _todo(conn, cfg, hosts: list[dict], conn_info: dict, backup: dict, now: dt.datetime, lang: str,
          values: dict | None = None) -> list[dict]:
    values = values or {}
    load_alerts = bool(values.get("load.alerts_enabled"))
    _ = i18n.translator(lang)
    items: list[dict] = []

    def add(severity, key, title, detail="", since=None, host=None, action=None):
        items.append({"severity": severity, "key": key, "title": title, "detail": detail, "since": since,
                      "host": host, "action": action})

    for h in hosts:
        if not h["enabled"]:
            continue
        if h["status"] == "DOWN":
            seen = (h["last_seen"] or "")[11:16] or "–"
            if not h["notify_offline"]:                           # 4.2: spento volutamente, nessun allarme
                add("info", f"host:{h['id']}", _("{p0} spento o non raggiungibile", p0=h["name"]),
                    _("ultimo invio dei dati alle {p0}", p0=seen) + " · " + _("avviso disattivato per questo server"),
                    since=h["last_seen"], host=h["id"], action={"kind": "host", "host": h["id"]})
                continue
            add("alert", f"host:{h['id']}", _("{p0} non raggiungibile", p0=h["name"]),
                _("ultimo invio dei dati alle {p0}", p0=seen), since=h["last_seen"], host=h["id"],
                action={"kind": "host", "host": h["id"]})
            continue
        if h["status"] == "WAITING":
            add("info", f"host:{h['id']}", _("{p0}: in attesa del primo invio dei dati", p0=h["name"]),
                _("installa l'agente con il comando indicato nelle impostazioni"), host=h["id"],
                action={"kind": "view", "view": "impostazioni"})
            continue
        for s in h["services"]:
            if not s["up"]:
                add("alert", f"service:{h['id']}:{s['unit']}", f"{h['name']} · " + _("servizio {p0} fermo", p0=s["label"]),
                    _("stato: {p0}", p0=s["state"] or "–") + " · " + _("se non serve più, toglilo dai servizi controllati"),
                    host=h["id"], action={"kind": "unmonitor", "host": h["id"], "unit": s["unit"], "label": s["label"]})
        worst = max(h["disks"], key=lambda d: d["used_pct"]) if h["disks"] else None
        m = h["limits"]
        lvl = _level(worst["used_pct"] if worst else h["disk_pct"], m["disk_warning"], m["disk_alert"])
        if lvl:
            add(lvl, f"disk:{h['id']}", f"{h['name']} · " + _("disco {p0} occupato al {p1}%",
                                                               p0=worst["mountpoint"] if worst else "/",
                                                               p1=round(worst["used_pct"] if worst else h["disk_pct"])),
                _("libera spazio o amplia il disco"), host=h["id"], action={"kind": "host", "host": h["id"]})
        if load_alerts:                                           # 4.2: CPU e memoria, se attivati
            for key, val, w, a, txt in (("cpu", h["cpu_pct"], m["cpu_warning"], m["cpu_alert"], _("CPU al {p0}%", p0=round(h["cpu_pct"] or 0))),
                                        ("mem", h["mem_pct"], m["mem_warning"], m["mem_alert"], _("memoria al {p0}%", p0=round(h["mem_pct"] or 0)))):
                lv = _level(val, w, a)
                if lv:
                    add(lv, f"{key}:{h['id']}", f"{h['name']} · {txt}", _("misura attuale; l'avviso parte se dura oltre l'attesa impostata"),
                        host=h["id"], action={"kind": "host", "host": h["id"]})
        # 4.2: dischi, aggiornamenti e container dei server collegati (dati inviati dagli agenti)
        hl = h.get("health") or {}
        for d in hl.get("disks", []):
            st, why = smart.evaluate(d, values.get("smart.temp_warning", 55), values.get("smart.wear_warning", 80))
            if st in ("WARNING", "ALERT"):
                add("alert" if st == "ALERT" else "warn", f"smart:{h['id']}:{d['device']}",
                    f"{h['name']} · " + _("disco {p0}", p0=f"{d['device']} {d.get('model') or ''}".strip()),
                    "; ".join(i18n.translate_stored(r, lang) for r in why), host=h["id"], action={"kind": "host", "host": h["id"]})
        upd = hl.get("updates") or {}
        if upd.get("security_count"):
            add("info", f"updates:{h['id']}", f"{h['name']} · " + _("{p0} aggiornamenti di sicurezza da installare", p0=upd["security_count"]),
                "", host=h["id"], action={"kind": "host", "host": h["id"]})
        if (upd.get("reboot") or {}).get("required"):
            add("info", f"reboot:{h['id']}", f"{h['name']} · " + _("riavvio richiesto"), "", host=h["id"], action={"kind": "host", "host": h["id"]})
        for c in h.get("containers") or []:
            st = docker_mod.evaluate(c)
            if st != "OK":
                add("alert" if st == "ALERT" else "warn", f"docker:{h['id']}:{c['name']}",
                    f"{h['name']} · " + _("container {p0}: {p1}", p0=c["name"], p1=c["state"]), c.get("status") or "",
                    host=h["id"], action={"kind": "host", "host": h["id"]})
        lvl = _level(h["temperature_max"], m["temp_warning"], m["temp_alert"])
        if lvl:
            add(lvl, f"temp:{h['id']}", f"{h['name']} · " + _("temperatura {p0} °C", p0=round(h["temperature_max"])),
                _("controlla ventole e aerazione"), host=h["id"], action={"kind": "host", "host": h["id"]})

    st = conn_info.get("status")
    if st == "DOWN":
        add("alert", "connection", _("Connessione Internet assente"), i18n.translate_stored(conn_info.get("text") or "", lang),
            since=conn_info.get("time"), action={"kind": "view", "view": "connessione"})
    elif st == "WARNING":
        add("warn", "connection", _("Connessione Internet degradata"), i18n.translate_stored(conn_info.get("text") or "", lang),
            since=conn_info.get("time"), action={"kind": "view", "view": "connessione"})

    if backup["status"] == "ALERT":
        add("alert", "backup", _("Ultimo backup non riuscito"), "; ".join(str(e) for e in backup["errors"][:2]),
            since=backup["time"], action={"kind": "view", "view": "impostazioni"})
    elif backup["status"] and (_age_hours(backup["time"], now) or 0) > BACKUP_MAX_AGE_H:
        add("warn", "backup", _("Nessun backup nelle ultime {p0} ore", p0=BACKUP_MAX_AGE_H),
            _("controlla il timer astreo-backup"), since=backup["time"], action={"kind": "view", "view": "impostazioni"})
    if backup.get("warning") == "none":
        add("warn", "nobackup", _("Nessun backup fuori dal server"),
            _("la copia locale non protegge da un guasto del disco: configura GitHub o una destinazione rclone"),
            action={"kind": "nobackup"})
    elif backup.get("warning") == "pending":
        add("info", "nobackup", _("Backup configurato: in attesa del primo backup riuscito fuori dal server"), "",
            action={"kind": "nobackup"})
    rt = backup.get("restore_test") or {}
    if rt.get("status") in ("ALERT", "DOWN"):
        add("alert", "restoretest", _("Prova di ripristino del backup non riuscita"), "", since=rt.get("time"),
            action={"kind": "view", "view": "impostazioni"})

    C = models.checks
    for c in db.rows(conn, select(C.c.id, C.c.name, C.c.kind, C.c.target).where(C.c.enabled == true()).order_by(C.c.sort_order, C.c.id)):
        s = db.state_get(conn, f"check:{c['id']}") or {}
        if s.get("status") in ("DOWN", "WARNING"):
            add("alert" if s["status"] == "DOWN" else "warn", f"check:{c['id']}",
                _("{p0} non risponde", p0=c["name"]) if s["status"] == "DOWN" else _("{p0}: risposta con avviso", p0=c["name"]),
                i18n.translate_stored(str(s.get("warning") or s.get("detail") or ""), lang), since=s.get("since"),
                action={"kind": "check", "check": c["id"]})

    for it in (db.state_get(conn, "expiry:last") or {}).get("items", []):
        if it.get("status") in ("WARNING", "ALERT"):
            days = it.get("days")
            add("alert" if it["status"] == "ALERT" else "warn", f"expiry:{it.get('key')}",
                _("{p0} scade tra {p1} giorni", p0=i18n.translate_stored(it.get("name", ""), lang), p1=max(0, int(days or 0))),
                (it.get("expires") or "")[:10], action={"kind": "help", "page": "health#scadenze"})

    health = db.state_get(conn, "health:last") or {}
    upd = health.get("updates") or {}
    sec = len(upd.get("security") or [])
    if sec:
        add("info", "updates", _("{p0} aggiornamenti di sicurezza da installare", p0=sec), "", action={"kind": "host", "host": hosts_mod.LOCAL_ID})
    if (upd.get("reboot") or {}).get("required"):
        add("info", "reboot", _("Il server centrale va riavviato per completare gli aggiornamenti"), "",
            action={"kind": "host", "host": hosts_mod.LOCAL_ID})

    items.sort(key=lambda x: SEVERITY_ORDER[x["severity"]])
    return items


def _events(conn, hosts: list[dict], now: dt.datetime, lang: str) -> list[dict]:
    start = now - dt.timedelta(hours=24)
    out = []
    for h in hosts:
        outages = history.outages(conn, start, now)["outages"] if h["id"] == hosts_mod.LOCAL_ID else []
        for e in events.list_events(conn, start, now, outages, lang, host_id=h["id"]):
            out.append({**e, "host": h["name"], "host_id": h["id"]})
    out.sort(key=lambda e: e["time"], reverse=True)
    return out[:EVENTS_SHOWN]


def build(conn, cfg, lang: str, offline_minutes: int) -> dict:
    lang = i18n.normalize(lang)
    _ = i18n.translator(lang)
    now = dt.datetime.now()
    rows = hosts_mod.listing(conn, offline_minutes)
    local_svc = services.statuses(services_store.monitored(conn, cfg))
    values = settings_mod.load(conn, cfg)
    hosts = [_local_host(cfg, r, local_svc, values) if r["id"] == hosts_mod.LOCAL_ID else _remote_host(r, cfg, values) for r in rows]
    if not any(h["id"] == hosts_mod.LOCAL_ID for h in hosts):           # tabella hosts vuota (installazione vecchia)
        hosts.insert(0, _local_host(cfg, {"id": hosts_mod.LOCAL_ID, "name": None}, local_svc, values))

    active = [h for h in hosts if h["enabled"] and (h["status"] != "DOWN" or h["notify_offline"])]
    reachable = [h for h in active if h["status"] == "OK"]
    svc = [s for h in reachable for s in h["services"]]
    conn_info = _connection(conn, now)
    backup = _backup(conn, values)
    todo = _todo(conn, cfg, hosts, conn_info, backup, now, lang, values)

    worst = todo[0]["severity"] if todo else "ok"
    n_check = sum(1 for x in todo if x["severity"] in ("alert", "warn"))
    if worst == "alert":
        headline = _("Attenzione · {p0} cose da controllare", p0=n_check) if n_check > 1 else _("Attenzione · 1 cosa da controllare")
    elif n_check:
        headline = _("Tutto funziona · {p0} cose da controllare", p0=n_check) if n_check > 1 else _("Tutto funziona · 1 cosa da controllare")
    else:
        headline = _("Tutto funziona")
    parts = [_("{p0} server su {p1} raggiungibili", p0=len(reachable), p1=len(active)) if len(active) > 1
             else _("server raggiungibile"),
             _("{p0} servizi su {p1} attivi", p0=sum(1 for s in svc if s["up"]), p1=len(svc))]
    if conn_info["status"]:
        parts.append({"OK": _("connessione regolare"), "WARNING": _("connessione degradata"),
                      "DOWN": _("connessione assente")}.get(conn_info["status"], conn_info["status"]))
    if backup["status"]:
        parts.append(_("ultimo backup riuscito") if backup["status"] == "OK" else _("ultimo backup non riuscito"))
    checks_total = len(active) + len(svc) + 2
    return {
        "time": now.isoformat(timespec="seconds"),
        "status": {"level": "ok" if worst in ("ok", "info") else worst, "headline": headline, "summary": " · ".join(parts),
                   "ok_pct": round(100 * max(0, checks_total - n_check) / checks_total)},
        "hosts": hosts,
        "services": {"total": len(svc), "up": sum(1 for s in svc if s["up"]),
                     "down": [{"host": h["name"], "host_id": h["id"], "label": s["label"]}
                              for h in reachable for s in h["services"] if not s["up"]]},
        "connection": conn_info,
        "backup": backup,
        "todo": todo,
        "events": _events(conn, active or hosts[:1], now, lang),
    }
