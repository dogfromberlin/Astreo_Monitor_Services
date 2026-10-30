"""Riepilogo settimanale: ogni lunedì alle 08:00 (evento "Riepilogo settimanale").

Ultimi 7 giorni: disponibilità della connessione, speedtest, risorse del server,
avvisi inviati, backup, verifica del ripristino, dischi, aggiornamenti e scadenze.
"""
from __future__ import annotations

import datetime as dt
import logging

from .. import db, notifier
from ..config import Config
from ..web import history
from .base import run

log = logging.getLogger("job.weekly_summary")


def _f(v, d=0, suffix=""):
    return "n/d" if v is None else f"{float(v):.{d}f}{suffix}"


def build(conn, now: dt.datetime) -> tuple[str, str]:
    start = now - dt.timedelta(days=7)
    p = (db.ts(start), db.ts(now))
    lines = [f"Settimana dal {start:%d/%m} al {now:%d/%m/%Y}", ""]

    # --- connessione
    c = history.connectivity(conn, start, now)
    lines.append("CONNESSIONE")
    if c["samples"]:
        longest = max((o["minutes"] for o in c["outages"]), default=0)
        lines.append(f"- Disponibilità {c['availability']:.2f}% — interruzioni: {len(c['outages'])}"
                     + (f", in tutto {c['down_minutes']} min, la più lunga {longest} min" if c["outages"] else ""))
    s = db.query_one(conn, """
        SELECT COUNT(*) AS n, AVG(download_mbps) AS dl, MIN(download_mbps) AS dl_min, AVG(upload_mbps) AS ul,
               AVG(latency_ms) AS lat, SUM(CASE WHEN status IN ('WARNING','ALERT','DOWN') THEN 1 ELSE 0 END) AS bad
        FROM speedtest_results WHERE provider <> 'legacy'
          AND [timestamp] >= CONVERT(datetime2(0), %s, 126) AND [timestamp] < CONVERT(datetime2(0), %s, 126)""", p)
    if s and s["n"]:
        lines.append(f"- Speedtest ({s['n']} misure): download medio {_f(s['dl'])} Mbps (minimo {_f(s['dl_min'])}), "
                     f"upload medio {_f(s['ul'])} Mbps, latenza {_f(s['lat'])} ms; sotto soglia {s['bad']} volte")
    lines.append("")

    # --- server
    m = db.query_one(conn, """
        SELECT AVG(cpu_pct) AS cpu, MAX(cpu_pct) AS cpu_max, AVG(mem_used_pct) AS mem, MAX(disk_used_pct) AS disk
        FROM system_metrics WHERE [timestamp] >= CONVERT(datetime2(0), %s, 126) AND [timestamp] < CONVERT(datetime2(0), %s, 126)""", p)
    t = db.query_one(conn, """
        SELECT MAX(temperature) AS tmax, AVG(temperature) AS tavg FROM system_temperature
        WHERE [timestamp] >= CONVERT(datetime, %s, 126) AND [timestamp] < CONVERT(datetime, %s, 126)""", p)
    lines += ["SERVER",
              f"- CPU media {_f(m['cpu'], 1, '%')} (picco {_f(m['cpu_max'], 0, '%')}), RAM media {_f(m['mem'], 0, '%')}, "
              f"disco {_f(m['disk'], 0, '%')}",
              f"- Temperatura media {_f(t['tavg'], 0, ' °C')}, massima {_f(t['tmax'], 0, ' °C')}", ""]

    # --- avvisi
    a = db.query(conn, """
        SELECT source, COUNT(*) AS n FROM notification_log
        WHERE status = 'inviata' AND source NOT IN ('test', 'summary', 'riepilogo')
          AND [timestamp] >= CONVERT(datetime2(0), %s, 126) AND [timestamp] < CONVERT(datetime2(0), %s, 126)
        GROUP BY source ORDER BY n DESC""", p)
    from .. import settings as settings_mod
    lines.append("AVVISI INVIATI")
    lines += [f"- {settings_mod.SOURCES.get(r['source'], r['source'])}: {r['n']}" for r in a] or ["- nessuno"]
    lines.append("")

    # --- backup, dischi, aggiornamenti, scadenze
    bk = db.state_get(conn, "backup:last") or {}
    rt = db.state_get(conn, "restoretest:last") or {}
    health = db.state_get(conn, "health:last") or {}
    exp = db.state_get(conn, "expiry:last") or {}
    lines.append("SICUREZZA DEI DATI E MANUTENZIONE")
    if bk:
        lines.append(f"- Ultimo backup: {bk.get('status')} il {str(bk.get('time', ''))[:16].replace('T', ' ')}")
    if rt:
        lines.append(f"- Ultima verifica del ripristino: {rt.get('status')} il {str(rt.get('time', ''))[:10]}")
    for d in health.get("disks", []):
        lines.append(f"- Disco {d['device']}: {d.get('status')}, {d.get('temperature')} °C"
                     + (f", usura {d['wear_used_pct']}%" if d.get("wear_used_pct") is not None else "")
                     + (f" ({'; '.join(d['reasons'])})" if d.get("reasons") else ""))
    u = health.get("updates") or {}
    if u:
        lines.append(f"- Aggiornamenti: {u.get('total', 0)} in sospeso, {len(u.get('security', []))} di sicurezza"
                     + (", riavvio richiesto" if (u.get("reboot") or {}).get("required") else ""))
    for it in exp.get("items", []):
        if it.get("days") is not None:
            lines.append(f"- {it['name']}: scade tra {int(it['days'])} giorni")

    bad = (c["outages"] and len(c["outages"]) > 0) or bk.get("status") not in (None, "OK")
    subject = f"Riepilogo settimanale {now:%d/%m}" + (" — con anomalie" if bad else "")
    return subject, "\n".join(lines)


def main(cfg: Config, dry_run: bool) -> int:
    now = dt.datetime.now().replace(second=0, microsecond=0)
    with db.connect(cfg.database) as conn:
        subject, body = build(conn, now)
        if dry_run:
            print(subject, "\n", body, sep="")
            return 0
        notifier.dispatch(conn, cfg, "summary", subject, body, detected_at=now)
    log.info("Riepilogo settimanale inviato")
    return 0


def entrypoint() -> None:
    run("weekly_summary", "Invia il riepilogo settimanale", main)


if __name__ == "__main__":
    entrypoint()
