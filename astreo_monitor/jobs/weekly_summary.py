"""Riepilogo settimanale: ogni lunedì alle 08:00 (evento "Riepilogo settimanale").

Ultimi 7 giorni: disponibilità della connessione, speedtest, risorse del server,
avvisi inviati, backup, verifica del ripristino, dischi, aggiornamenti e scadenze.
"""
from __future__ import annotations

import datetime as dt
import logging

from sqlalchemy import true as sa_true, case, func, select

from .. import db, models, notifier
from ..config import Config
from ..web import history
from .base import run

log = logging.getLogger("job.weekly_summary")


def _f(v, d=0, suffix=""):
    return "n/d" if v is None else f"{float(v):.{d}f}{suffix}"


def per_host(conn, start: dt.datetime, now: dt.datetime, tr) -> list[str]:
    """Disponibilità (dati ricevuti), riavvii, servizi fermi, picchi e manutenzione di ogni server collegato."""
    H, M, E = models.hosts, models.system_metrics, models.events
    out = []
    expected = max(1, int((now - start).total_seconds() // 300))      # un invio ogni 5 minuti
    for h in db.rows(conn, select(H.c.id, H.c.name, H.c.kind).where(H.c.id != 1, H.c.enabled == sa_true()).order_by(H.c.sort_order, H.c.id)):
        m = db.one(conn, select(func.count().label("n"), func.max(M.c.cpu_pct).label("cpu"), func.max(M.c.mem_used_pct).label("mem"),
                                func.max(M.c.disk_used_pct).label("disk"))
                   .where(M.c.host_id == h["id"], M.c.timestamp >= start, M.c.timestamp < now)) or {}
        ev = {r["kind"]: r["n"] for r in db.rows(conn, select(E.c.kind, func.count().label("n"))
                                                  .where(E.c.host_id == h["id"], E.c.timestamp >= start, E.c.timestamp < now)
                                                  .group_by(E.c.kind))}
        stops = db.scalar(conn, select(func.count()).select_from(E).where(
            E.c.host_id == h["id"], E.c.kind == "service", E.c.severity == "alert", E.c.timestamp >= start, E.c.timestamp < now)) or 0
        out += ["", tr("SERVER {nome}", nome=h["name"].upper())]
        n = m.get("n") or 0
        out.append(tr("- Dati ricevuti: {pct}% del tempo", pct=f"{min(100, 100 * n / expected):.1f}"))
        out.append(tr("- Riavvii: {r} · servizi fermati: {s}", r=ev.get("boot", 0), s=stops))
        if n:
            out.append(tr("- Picchi: CPU {cpu}% · memoria {mem}% · disco {disco}%", cpu=f"{m['cpu'] or 0:.0f}",
                          mem=f"{m['mem'] or 0:.0f}", disco=f"{m['disk'] or 0:.0f}"))
        u = ((db.state_get(conn, f"host:{h['id']}:health") or {}).get("updates")) or {}
        if u:
            out.append(tr("- Aggiornamenti: {tot} in sospeso, {sic} di sicurezza", tot=u.get("total", 0), sic=u.get("security_count", 0))
                       + (tr(", riavvio richiesto") if (u.get("reboot") or {}).get("required") else ""))
    return out


def build(conn, now: dt.datetime, values: dict | None = None) -> tuple[str, str]:
    from .. import i18n
    from .. import settings as settings_mod
    lang = i18n.lang_of(values or {})
    tr = i18n.translator(lang)
    start = now - dt.timedelta(days=7)
    lines = [tr("Settimana dal {inizio} al {fine}", inizio=f"{start:%d/%m}", fine=f"{now:%d/%m/%Y}"), ""]

    # --- connessione
    c = history.connectivity(conn, start, now)
    lines.append(tr("CONNESSIONE"))
    if c["samples"]:
        longest = max((o["minutes"] for o in c["outages"]), default=0)
        lines.append(tr("- Disponibilità {pct}% — interruzioni: {n}", pct=f"{c['availability']:.2f}", n=len(c["outages"]))
                     + (tr(", in tutto {tot} min, la più lunga {max} min", tot=c["down_minutes"], max=longest) if c["outages"] else ""))
    S = models.speedtest_results
    bad = func.sum(case((S.c.status.in_(("WARNING", "ALERT", "DOWN")), 1), else_=0))
    s = db.one(conn, select(func.count().label("n"), func.avg(S.c.download_mbps).label("dl"),
                            func.min(S.c.download_mbps).label("dl_min"), func.avg(S.c.upload_mbps).label("ul"),
                            func.avg(S.c.latency_ms).label("lat"), bad.label("bad"))
               .where(S.c.provider != "legacy", S.c.timestamp >= start, S.c.timestamp < now))
    if s and s["n"]:
        lines.append(tr("- Speedtest ({n} misure): download medio {dl} Mbps (minimo {dlmin}), upload medio {ul} Mbps, "
                        "latenza {lat} ms; sotto soglia {bad} volte", n=s["n"], dl=_f(s["dl"]), dlmin=_f(s["dl_min"]),
                        ul=_f(s["ul"]), lat=_f(s["lat"]), bad=s["bad"]))
    lines.append("")

    # --- server
    M, T = models.system_metrics, models.system_temperature
    m = db.one(conn, select(func.avg(M.c.cpu_pct).label("cpu"), func.max(M.c.cpu_pct).label("cpu_max"),
                            func.avg(M.c.mem_used_pct).label("mem"), func.max(M.c.disk_used_pct).label("disk"))
               .where(M.c.timestamp >= start, M.c.timestamp < now, M.c.host_id == 1))
    t = db.one(conn, select(func.max(T.c.temperature).label("tmax"), func.avg(T.c.temperature).label("tavg"))
               .where(T.c.timestamp >= start, T.c.timestamp < now, T.c.host_id == 1))
    lines += ["SERVER",
              tr("- CPU media {cpu} (picco {picco}), RAM media {ram}, disco {disco}", cpu=_f(m["cpu"], 1, "%"),
                 picco=_f(m["cpu_max"], 0, "%"), ram=_f(m["mem"], 0, "%"), disco=_f(m["disk"], 0, "%")),
              tr("- Temperatura media {media}, massima {max}", media=_f(t["tavg"], 0, " °C"), max=_f(t["tmax"], 0, " °C")), ""]

    # --- avvisi
    L = models.notification_log
    a = db.rows(conn, select(L.c.source, func.count().label("n"))
                .where(L.c.status == "inviata", L.c.source.notin_(("test", "summary", "riepilogo")),
                       L.c.timestamp >= start, L.c.timestamp < now)
                .group_by(L.c.source).order_by(func.count().desc()))
    lines.append(tr("AVVISI INVIATI"))
    lines += [f"- {tr(settings_mod.SOURCES.get(r['source'], r['source']))}: {r['n']}" for r in a] or [tr("- nessuno")]
    lines.append("")

    # --- dispositivi e servizi
    Ck, Cr = models.checks, models.check_results
    rows = db.rows(conn, select(Ck.c.name, func.count(Cr.c.id).label("n"),
                                func.sum(case((Cr.c.ok == sa_true(), 1), else_=0)).label("ok"))
                   .select_from(Ck.join(Cr, Cr.c.check_id == Ck.c.id))
                   .where(Cr.c.timestamp >= start, Cr.c.timestamp < now)
                   .group_by(Ck.c.name).order_by(Ck.c.name))
    if rows:
        lines.append(tr("DISPOSITIVI E SERVIZI"))
        lines += [tr("- {nome}: disponibilità {pct}%", nome=r["name"], pct=f"{100 * (r['ok'] or 0) / r['n']:.2f}") for r in rows]
        lines.append("")

    # --- backup, dischi, aggiornamenti, scadenze
    bk = db.state_get(conn, "backup:last") or {}
    rt = db.state_get(conn, "restoretest:last") or {}
    health = db.state_get(conn, "health:last") or {}
    exp = db.state_get(conn, "expiry:last") or {}
    lines.append(tr("SICUREZZA DEI DATI E MANUTENZIONE"))
    if bk:
        lines.append(tr("- Ultimo backup: {stato} il {quando}", stato=bk.get("status"), quando=str(bk.get("time", ""))[:16].replace("T", " ")))
    if rt:
        lines.append(tr("- Ultima verifica del ripristino: {stato} il {quando}", stato=rt.get("status"), quando=str(rt.get("time", ""))[:10]))
    for d in health.get("disks", []):
        lines.append(tr("- Disco {disco}: {stato}, {t} °C", disco=d["device"], stato=d.get("status"), t=d.get("temperature"))
                     + (tr(", usura {p0}%", p0=d["wear_used_pct"]) if d.get("wear_used_pct") is not None else "")
                     + (f" ({'; '.join(i18n.translate_stored(r, lang) for r in d['reasons'])})" if d.get("reasons") else ""))
    u = health.get("updates") or {}
    if u:
        lines.append(tr("- Aggiornamenti: {tot} in sospeso, {sic} di sicurezza", tot=u.get("total", 0), sic=len(u.get("security", [])))
                     + (tr(", riavvio richiesto") if (u.get("reboot") or {}).get("required") else ""))
    for it in exp.get("items", []):
        if it.get("days") is not None:
            lines.append(tr("- {nome}: scade tra {giorni} giorni", nome=i18n.translate_stored(it["name"], lang), giorni=int(it["days"])))

    # --- 4.6: blackout della settimana (dagli eventi UPS)
    E = models.events
    bos = db.rows(conn, select(E.c.timestamp, E.c.title).where(E.c.kind == "ups", E.c.timestamp >= start, E.c.timestamp < now,
                                                                 E.c.title.like("Corrente tornata%")).order_by(E.c.timestamp))
    if bos:
        lines += ["", tr("UPS: {n} blackout", n=len(bos))] + [f"- {db.as_datetime(b['timestamp']):%d/%m %H:%M} {b['title']}" for b in bos[:10]]

    # --- 4.2: una sezione per ogni server collegato
    lines += per_host(conn, start, now, tr)

    bad = (c["outages"] and len(c["outages"]) > 0) or bk.get("status") not in (None, "OK")
    subject = tr("Riepilogo settimanale {data}", data=f"{now:%d/%m}") + (tr(" — con anomalie") if bad else "")
    return subject, "\n".join(lines)


def main(cfg: Config, dry_run: bool) -> int:
    now = dt.datetime.now().replace(second=0, microsecond=0)
    with db.connect(cfg.database) as conn:
        from .. import settings as settings_mod
        subject, body = build(conn, now, settings_mod.load(conn, cfg))
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
