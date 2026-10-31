"""Eventi da mostrare sui grafici.

Due fonti:
  - tabella events: riavvii, servizi e container fermati/ripartiti, Pi-hole (scritti dai job);
  - eventi ricavati da tabelle esistenti, quindi disponibili anche per il passato:
    interruzioni della connessione, cambi di IP pubblico, speedtest sotto soglia, avvisi inviati.
"""
from __future__ import annotations

import datetime as dt
import logging
import subprocess

from . import db

log = logging.getLogger(__name__)

KINDS = {
    "reboot": "Riavvio del server",
    "outage": "Interruzione della connessione",
    "ip": "Cambio di IP pubblico",
    "service": "Servizio",
    "container": "Container",
    "pihole": "Pi-hole",
    "speedtest": "Speedtest sotto soglia",
    "alert": "Avviso inviato",
}


def record(conn, kind: str, severity: str, title: str, detail: str = "", ref: str | None = None,
           when: dt.datetime | None = None) -> bool:
    """Registra un evento. Con ref, un evento già presente non viene duplicato."""
    if ref and db.query_one(conn, "SELECT 1 AS x FROM events WHERE ref = %s", (ref,)):
        return False
    db.execute(conn, "INSERT INTO events ([timestamp], kind, severity, title, detail, ref) "
                     "VALUES (CONVERT(datetime2(0), %s, 126), %s, %s, %s, %s, %s)",
               (db.ts(when or dt.datetime.now()), kind, severity, title[:200], (detail or "")[:400] or None, ref))
    return True


def backfill_reboots(conn) -> int:
    """Importa i riavvii registrati dal sistema (last -x -F reboot). Idempotente."""
    try:
        out = subprocess.run(["last", "-x", "-F", "reboot"], capture_output=True, text=True, timeout=15,
                             env={"LC_ALL": "C", "LANG": "C", "PATH": "/usr/bin:/bin"}).stdout
    except (OSError, subprocess.TimeoutExpired):
        return 0
    n = 0
    for line in out.splitlines():
        parts = line.split()
        if len(parts) < 9 or parts[0] != "reboot":
            continue
        try:   # reboot system boot 6.8.0-147-generic Mon Oct 19 18:00:34 2026 still running
            when = dt.datetime.strptime(" ".join(parts[5:9]), "%b %d %H:%M:%S %Y")
        except ValueError:
            continue
        if record(conn, "reboot", "info", "Riavvio del server", f"kernel {parts[3]}", f"reboot:{when:%Y%m%d%H%M}", when):
            n += 1
    return n


def list_events(conn, start: dt.datetime, end: dt.datetime, outages: list[dict] | None = None) -> list[dict]:
    p = (db.ts(start), db.ts(end))
    rng = "[timestamp] >= CONVERT(datetime2(0), %s, 126) AND [timestamp] < CONVERT(datetime2(0), %s, 126)"
    out = []
    for r in db.query(conn, f"SELECT [timestamp], kind, severity, title, detail FROM events WHERE {rng}", p):
        out.append({"time": db.as_datetime(r["timestamp"]), "kind": r["kind"], "severity": r["severity"],
                    "title": r["title"], "detail": r["detail"] or ""})
    for o in outages or []:
        out.append({"time": dt.datetime.fromisoformat(o["start"]), "kind": "outage", "severity": "alert",
                    "title": f"Interruzione della connessione ({o['minutes']} min)",
                    "detail": f"dalle {o['start'][11:16]} alle {o['end'][11:16]}"})
    for r in db.query(conn, f"SELECT [timestamp], ip, previous_ip FROM public_ip_history WHERE previous_ip IS NOT NULL AND {rng}", p):
        out.append({"time": db.as_datetime(r["timestamp"]), "kind": "ip", "severity": "info",
                    "title": "Cambio di IP pubblico", "detail": f"{r['previous_ip']} → {r['ip']}"})
    for r in db.query(conn, f"SELECT [timestamp], status, download_mbps, upload_mbps FROM speedtest_results "
                            f"WHERE status IN ('WARNING', 'ALERT', 'DOWN') AND {rng}", p):
        out.append({"time": db.as_datetime(r["timestamp"]), "kind": "speedtest",
                    "severity": "warning" if r["status"] == "WARNING" else "alert",
                    "title": f"Speedtest {r['status']}",
                    "detail": f"↓ {r['download_mbps'] or 0:.0f} ↑ {r['upload_mbps'] or 0:.0f} Mbps"})
    # avvisi inviati, esclusi quelli che hanno già un evento proprio (servizi, container, interruzioni, IP, speedtest)
    for r in db.query(conn, f"SELECT [timestamp], source, subject FROM notification_log "
                            f"WHERE status = 'inviata' AND source NOT IN ('test', 'summary', 'riepilogo', 'services', "
                            f"'docker', 'pihole', 'connectivity', 'publicip', 'speedtest') AND {rng}", p):
        out.append({"time": db.as_datetime(r["timestamp"]), "kind": "alert", "severity": "warning",
                    "title": r["subject"], "detail": r["source"]})
    out.sort(key=lambda e: e["time"])
    for e in out:
        e["time"] = e["time"].isoformat(timespec="seconds")
    return out
