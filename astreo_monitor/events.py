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

from sqlalchemy import and_, select

from . import db, models

log = logging.getLogger(__name__)

KINDS = {
    "reboot": "Riavvio del server",
    "outage": "Interruzione della connessione",
    "ip": "Cambio di IP pubblico",
    "service": "Servizio",
    "container": "Container",
    "pihole": "Pi-hole",
    "check": "Dispositivi e servizi",
    "host": "Server collegati",
    "ups": "UPS e alimentazione",
    "speedtest": "Speedtest sotto soglia",
    "alert": "Avviso inviato",
}


def translate(text: str, lang: str) -> str:
    """Traduce un testo salvato in italiano (vedi i18n.translate_stored)."""
    from . import i18n
    return i18n.translate_stored(text, lang)


def record(conn, kind: str, severity: str, title: str, detail: str = "", ref: str | None = None,
           when: dt.datetime | None = None, host_id: int = 1) -> bool:
    """Registra un evento. Con ref, un evento già presente non viene duplicato."""
    E = models.events
    if ref and db.one(conn, select(E.c.id).where(E.c.ref == ref)):
        return False
    conn.execute(E.insert().values(timestamp=(when or dt.datetime.now()).replace(microsecond=0), kind=kind,
                                   severity=severity, title=title[:200], detail=(detail or "")[:400] or None, ref=ref,
                                   host_id=host_id))
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


def list_events(conn, start: dt.datetime, end: dt.datetime, outages: list[dict] | None = None, lang: str = "it",
                host_id: int = 1) -> list[dict]:
    from . import i18n
    _ = i18n.translator(lang)
    E, IP, S, N = models.events, models.public_ip_history, models.speedtest_results, models.notification_log

    def rng(t):
        return and_(t.c.timestamp >= start, t.c.timestamp < end)

    out = []
    for r in db.rows(conn, select(E.c.timestamp, E.c.kind, E.c.severity, E.c.title, E.c.detail)
                     .where(rng(E), E.c.host_id == host_id)):
        out.append({"time": db.as_datetime(r["timestamp"]), "kind": r["kind"], "severity": r["severity"],
                    "title": translate(r["title"], lang), "detail": translate(r["detail"] or "", lang)})
    if host_id != 1:                  # connessione, IP, speedtest e avvisi sono del solo server centrale
        out.sort(key=lambda e: e["time"])
        for e in out:
            e["time"] = e["time"].isoformat(timespec="seconds")
        return out
    for o in outages or []:
        out.append({"time": dt.datetime.fromisoformat(o["start"]), "kind": "outage", "severity": "alert",
                    "title": _("Interruzione della connessione ({p0} min)", p0=o["minutes"]),
                    "detail": _("dalle {p0} alle {p1}", p0=o["start"][11:16], p1=o["end"][11:16])})
    for r in db.rows(conn, select(IP.c.timestamp, IP.c.ip, IP.c.previous_ip).where(IP.c.previous_ip.isnot(None), rng(IP))):
        out.append({"time": db.as_datetime(r["timestamp"]), "kind": "ip", "severity": "info",
                    "title": _("Cambio di IP pubblico"), "detail": f"{r['previous_ip']} → {r['ip']}"})
    for r in db.rows(conn, select(S.c.timestamp, S.c.status, S.c.download_mbps, S.c.upload_mbps)
                     .where(S.c.status.in_(("WARNING", "ALERT", "DOWN")), rng(S))):
        out.append({"time": db.as_datetime(r["timestamp"]), "kind": "speedtest",
                    "severity": "warning" if r["status"] == "WARNING" else "alert",
                    "title": f"Speedtest {r['status']}",
                    "detail": f"↓ {r['download_mbps'] or 0:.0f} ↑ {r['upload_mbps'] or 0:.0f} Mbps"})
    # avvisi inviati, esclusi quelli che hanno già un evento proprio (servizi, container, interruzioni, IP, speedtest)
    escluse = ("test", "summary", "riepilogo", "services", "docker", "pihole", "connectivity", "publicip", "speedtest")
    for r in db.rows(conn, select(N.c.timestamp, N.c.source, N.c.subject)
                     .where(N.c.status == "inviata", N.c.source.notin_(escluse), rng(N))):
        out.append({"time": db.as_datetime(r["timestamp"]), "kind": "alert", "severity": "warning",
                    "title": r["subject"], "detail": r["source"]})
    out.sort(key=lambda e: e["time"])
    for e in out:
        e["time"] = e["time"].isoformat(timespec="seconds")
    return out
