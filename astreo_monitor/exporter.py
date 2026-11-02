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

    def metric(name: str, help_: str, values: list[tuple[dict, float | None]], kind: str = "gauge"):
        vals = [(lbl, v) for lbl, v in values if v is not None]
        if not vals:
            return
        out.append(f"# HELP astreo_{name} {help_}")
        out.append(f"# TYPE astreo_{name} {kind}")
        for lbl, v in vals:
            labels = ",".join(f'{k}="{_label(x)}"' for k, x in lbl.items())
            out.append(f"astreo_{name}{{{labels}}} {float(v):g}" if labels else f"astreo_{name} {float(v):g}")

    snap = system.snapshot(cfg.metrics.root_disk)
    s = status(conn, cfg, snap)
    metric("info", "Versione di Astreo Monitor", [({"version": __version__, "hostname": s["hostname"]}, 1)])
    metric("uptime_seconds", "Secondi dall'avvio del server", [({}, s["uptime_s"])])
    metric("cpu_percent", "Uso della CPU", [({}, s["cpu_percent"])])
    metric("load1", "Load average a 1 minuto", [({}, snap["load"]["load1"])])
    metric("load5", "Load average a 5 minuti", [({}, snap["load"]["load5"])])
    metric("memory_used_percent", "Memoria usata", [({}, s["memory_percent"])])
    metric("disk_used_percent", "Disco radice usato", [({}, s["disk_percent"])])
    metric("temperature_celsius", "Temperature dei sensori",
           [({"sensor": f"{t['adapter']} - {t['device']}"}, t["value"]) for t in sensors.read()])
    metric("service_up", "Servizio systemd attivo (1) o fermo (0)",
           [({"unit": x["unit"], "label": x["label"]}, 1 if x["up"] else 0)
            for x in services.statuses(services_store.monitored(conn, cfg))])
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
    return "\n".join(out) + "\n"


def valid_metric_text(text: str) -> bool:
    """Controllo minimo del formato (usato nei test)."""
    rx = re.compile(r'^astreo_[a-z0-9_]+(\{([a-z_]+="[^"]*",?)*\})? -?[0-9.e+-]+$')
    return all(line.startswith("#") or rx.match(line) for line in text.strip().splitlines())
