"""Dati per le integrazioni: formato Prometheus (/metrics) e JSON semplice per Home Assistant (/api/v1/status).

Entrambi gli endpoint richiedono il token per le integrazioni (Impostazioni > Moduli), inviato come
`Authorization: Bearer <token>`: nessun accesso alla dashboard, solo lettura.
"""
from __future__ import annotations

import datetime as dt
import re

from sqlalchemy import select

from . import __version__, db, models, services_store
from .collectors import sensors, services, system
from .web import history

LEVEL = {"OK": 0, "WARNING": 1, "ALERT": 2, "DOWN": 2}


def _ts(iso: str | None) -> float | None:
    try:
        return dt.datetime.fromisoformat(iso).timestamp() if iso else None
    except ValueError:
        return None


def status(conn, cfg, snap: dict | None = None) -> dict:
    """Valori correnti in forma piatta (facile da usare nei sensori REST di Home Assistant)."""
    snap = snap or system.snapshot(cfg.metrics.root_disk)
    temps = sensors.read()
    svc = services.statuses(services_store.monitored(conn, cfg))
    con = db.state_get(conn, "connectivity:last") or {}
    last = history.latest_speedtest(conn) or {}
    bk = db.state_get(conn, "backup:last") or {}
    health = db.state_get(conn, "health:last") or {}
    upd = health.get("updates") or {}
    C = models.checks
    checks = []
    for c in db.rows(conn, select(C.c.id, C.c.name, C.c.kind, C.c.target).where(C.c.enabled == models_true()).order_by(C.c.sort_order)):
        st = db.state_get(conn, f"check:{c['id']}") or {}
        checks.append({"name": c["name"], "kind": c["kind"], "status": st.get("status"), "latency_ms": st.get("latency_ms")})
    return {
        "version": __version__, "hostname": snap["hostname"], "time": dt.datetime.now().isoformat(timespec="seconds"),
        "uptime_s": snap["uptime"]["uptime_s"],
        "cpu_percent": round(snap["cpu_pct"], 1), "load1": snap["load"]["load1"],
        "memory_percent": snap["memory"]["used_pct"], "disk_percent": snap["root_disk_pct"],
        "temperature_max": max((t["value"] for t in temps), default=None),
        "services_total": len(svc), "services_down": [s["label"] for s in svc if not s["up"]],
        "connection": con.get("status"),
        "speedtest": {"status": last.get("status"), "download_mbps": last.get("download_mbps"),
                      "upload_mbps": last.get("upload_mbps"), "latency_ms": last.get("latency_ms"), "time": last.get("timestamp")},
        "backup": {"status": bk.get("status"), "time": bk.get("time")},
        "updates_security": len(upd.get("security", [])) if upd else None,
        "reboot_required": bool((upd.get("reboot") or {}).get("required")) if upd else None,
        "checks": checks,
    }


def models_true():
    from sqlalchemy import true
    return true()


def _label(v) -> str:
    return str(v).replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")


def metrics(conn, cfg) -> str:
    """Testo nel formato di esposizione di Prometheus."""
    out: list[str] = []

    series: dict[str, tuple[str, str, list[str]]] = {}
    central = ""                                       # 4.2: etichetta host su tutte le metriche

    def metric(name: str, help_: str, values: list[tuple[dict, float | None]], kind: str = "gauge", host: str | None = None):
        vals = [(lbl, v) for lbl, v in values if v is not None]
        if not vals:
            return
        h, k, lines = series.setdefault(name, (help_, kind, []))
        for lbl, v in vals:
            labels = ",".join(f'{k2}="{_label(x)}"' for k2, x in {"host": host or central, **lbl}.items())
            lines.append(f"astreo_{name}{{{labels}}} {float(v):g}")

    snap = system.snapshot(cfg.metrics.root_disk)
    s = status(conn, cfg, snap)
    from . import hosts as hosts_mod
    from . import settings as settings_mod
    values = settings_mod.load(conn, cfg)
    host_list = hosts_mod.listing(conn, int(values["hosts.offline_minutes"]))
    central = next((h["name"] for h in host_list if h["id"] == hosts_mod.LOCAL_ID and h.get("name")), s["hostname"])
    metric("info", "Versione di Astreo Monitor", [({"version": __version__, "hostname": s["hostname"]}, 1)])
    metric("host_up", "Server raggiungibile (1) o no (0)", [({"kind": "local"}, 1)])
    metric("uptime_seconds", "Secondi dall'avvio del server", [({}, s["uptime_s"])])
    metric("cpu_percent", "Uso della CPU", [({}, s["cpu_percent"])])
    metric("load1", "Load average a 1 minuto", [({}, snap["load"]["load1"])])
    metric("load5", "Load average a 5 minuti", [({}, snap["load"]["load5"])])
    metric("memory_used_percent", "Memoria usata", [({}, s["memory_percent"])])
    metric("disk_used_percent", "Disco radice usato", [({}, s["disk_percent"])])
    metric("temperature_celsius", "Temperature dei sensori",
           [({"sensor": f"{t['adapter']} - {t['device']}"}, t["value"]) for t in sensors.read()])
    metric("service_up", "Servizio attivo (1) o fermo (0)",
           [({"unit": x["unit"], "label": x["label"]}, 1 if x["up"] else 0)
            for x in services.statuses(services_store.monitored(conn, cfg))])
    # 4.2: i server collegati, con le stesse metriche e la loro etichetta host
    for h in host_list:
        if h["id"] == hosts_mod.LOCAL_ID or not h["enabled"]:
            continue
        name, snap_h, up = h["name"], h.get("snapshot") or {}, h["status"] == "OK"
        metric("host_up", "Server raggiungibile (1) o no (0)", [({"kind": h["kind"]}, 1 if up else 0)], host=name)
        if not up:
            continue
        metric("uptime_seconds", "", [({}, snap_h.get("uptime_s"))], host=name)
        metric("cpu_percent", "", [({}, snap_h.get("cpu_pct"))], host=name)
        metric("load1", "", [({}, snap_h.get("load1"))], host=name)
        metric("load5", "", [({}, snap_h.get("load5"))], host=name)
        metric("memory_used_percent", "", [({}, snap_h.get("mem_used_pct"))], host=name)
        metric("disk_used_percent", "", [({}, snap_h.get("disk_used_pct"))], host=name)
        metric("temperature_celsius", "", [({"sensor": "max"}, snap_h.get("temperature_max"))], host=name)
        metric("service_up", "", [({"unit": x["unit"], "label": x["label"]}, 1 if x["up"] else 0)
                                  for x in (h.get("services_state") or {}).get("services", [])], host=name)
        upd = (h.get("health") or {}).get("updates") or {}
        metric("updates_security_pending", "", [({}, upd.get("security_count"))], host=name)
        metric("reboot_required", "", [({}, None if not upd else int(bool((upd.get("reboot") or {}).get("required"))))], host=name)
    # 4.6: UPS (etichetta ups con il nome)
    from .ups import store as ups_store
    for u in ups_store.listing(conn):
        r = ((u.get("last") or {}).get("reading")) or {}
        if not u["enabled"] or not r:
            continue
        lbl = {"ups": u["name"]}
        metric("ups_on_battery", "UPS a batteria (1) o dalla rete (0)", [(lbl, 1 if r.get("status") in ("battery", "low") else 0)])
        metric("ups_battery_charge_percent", "Carica della batteria dell'UPS", [(lbl, r.get("charge"))])
        metric("ups_runtime_seconds", "Autonomia residua dell'UPS", [(lbl, r.get("runtime_s"))])
        metric("ups_load_percent", "Carico dell'UPS", [(lbl, r.get("load"))])
        metric("ups_input_voltage", "Tensione in ingresso dell'UPS", [(lbl, r.get("input_v"))])
    con = db.state_get(conn, "connectivity:last") or {}
    metric("connectivity_status", "Connessione: 0 OK, 1 WARNING, 2 DOWN", [({}, LEVEL.get(con.get("status")))])
    for key, name, help_ in (("rtt_avg_ms", "connectivity_rtt_ms", "Latenza media del ping"),
                             ("loss_pct", "connectivity_loss_percent", "Pacchetti persi")):
        metric(name, help_, [({"target": x["target"], "role": x["role"]}, x.get(key)) for x in con.get("samples", [])])
    sp = s["speedtest"]
    metric("speedtest_download_mbps", "Ultimo speedtest: download", [({}, sp["download_mbps"])])
    metric("speedtest_upload_mbps", "Ultimo speedtest: upload", [({}, sp["upload_mbps"])])
    metric("speedtest_latency_ms", "Ultimo speedtest: latenza", [({}, sp["latency_ms"])])
    metric("speedtest_timestamp_seconds", "Ora dell'ultimo speedtest", [({}, _ts(sp["time"]))])
    bk = db.state_get(conn, "backup:last") or {}
    metric("backup_ok", "Ultimo backup riuscito (1) o no (0)", [({}, None if not bk else 1 if bk.get("status") == "OK" else 0)])
    metric("backup_timestamp_seconds", "Ora dell'ultimo backup", [({}, _ts(bk.get("time")))])
    health = db.state_get(conn, "health:last") or {}
    metric("disk_smart_status", "Dischi: 0 OK, 1 WARNING, 2 ALERT",
           [({"device": d["device"]}, LEVEL.get(d.get("status"))) for d in health.get("disks", [])])
    metric("updates_security_pending", "Aggiornamenti di sicurezza in sospeso", [({}, s["updates_security"])])
    metric("reboot_required", "Riavvio richiesto", [({}, None if s["reboot_required"] is None else int(s["reboot_required"]))])
    exp = db.state_get(conn, "expiry:last") or {}
    metric("expiry_days", "Giorni alla scadenza", [({"name": it["name"]}, it.get("days")) for it in exp.get("items", [])])
    metric("check_up", "Controllo raggiungibile (1) o DOWN (0)",
           [({"name": c["name"], "kind": c["kind"]}, None if c["status"] is None else 0 if c["status"] == "DOWN" else 1)
            for c in s["checks"]])
    metric("check_latency_ms", "Latenza dell'ultimo controllo",
           [({"name": c["name"], "kind": c["kind"]}, c["latency_ms"]) for c in s["checks"]])
    for name, (help_, kind, lines) in series.items():
        out.append(f"# HELP astreo_{name} {help_}")
        out.append(f"# TYPE astreo_{name} {kind}")
        out.extend(lines)
    return "\n".join(out) + "\n"


def valid_metric_text(text: str) -> bool:
    """Controllo minimo del formato (usato nei test)."""
    rx = re.compile(r'^astreo_[a-z0-9_]+(\{([a-z_]+="[^"]*",?)*\})? -?[0-9.e+-]+$')
    return all(line.startswith("#") or rx.match(line) for line in text.strip().splitlines())
