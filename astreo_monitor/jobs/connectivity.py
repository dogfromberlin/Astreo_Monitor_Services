"""Controllo continuo della connessione: ping ogni minuto verso router e Internet.

Per ogni destinazione 5 ping a 0,2 s di distanza (circa 1-2 secondi in tutto).
Stato:
  DOWN    nessuna destinazione Internet risponde (interruzione);
  WARNING perdita di pacchetti o latenza oltre le soglie;
  OK      altrimenti.
L'avviso di ripristino riporta la durata dell'interruzione. Durante un'interruzione
gli avvisi non possono partire: per questo conta soprattutto quello di ripristino
(e, a server spento o isolato, l'heartbeat esterno).
"""
from __future__ import annotations

import datetime as dt
import logging
import os
import re
import subprocess
from concurrent.futures import ThreadPoolExecutor

from .. import db, i18n, models, notifier
from .. import settings as settings_mod
from ..config import Config
from .base import run

log = logging.getLogger("job.connectivity")

STATS_RE = re.compile(r"(\d+) packets transmitted, (\d+) (?:packets )?received")
RTT_RE = re.compile(r"= [\d.]+/([\d.]+)/([\d.]+)/")


def default_gateway() -> str | None:
    try:
        out = subprocess.run(["ip", "route", "show", "default"], capture_output=True, text=True, timeout=5).stdout
        m = re.search(r"default via (\S+)", out)
        return m.group(1) if m else None
    except (OSError, subprocess.TimeoutExpired):
        return None


def ping(target: str, count: int = 5) -> dict:
    try:
        # LC_ALL=C: ping è tradotto (es. "pacchetti trasmessi") e la lettura del risultato richiede l'inglese
        res = subprocess.run(["ping", "-n", "-q", "-c", str(count), "-i", "0.2", "-W", "1", target],
                             capture_output=True, text=True, timeout=count + 5,
                             env={**os.environ, "LC_ALL": "C", "LANG": "C"})
        out = res.stdout
    except (OSError, subprocess.TimeoutExpired) as exc:
        log.warning("ping %s non eseguito: %s", target, exc)
        out = ""
    m = STATS_RE.search(out)
    sent, received = (int(m.group(1)), int(m.group(2))) if m else (count, 0)
    r = RTT_RE.search(out)
    return {"target": target, "sent": sent, "received": received,
            "loss_pct": round((sent - received) / sent * 100, 1) if sent else 100.0,
            "rtt_avg_ms": float(r.group(1)) if r else None, "rtt_max_ms": float(r.group(2)) if r else None}


def resolve_targets(values: dict) -> list[tuple[str, str]]:
    out = []
    for t in [x.strip() for x in values["connectivity.targets"].split(",") if x.strip()]:
        if t.lower() == "gateway":
            gw = default_gateway()
            if gw:
                out.append((gw, "gateway"))
            else:
                log.warning("Gateway predefinito non trovato")
        else:
            out.append((t, "internet"))
    return out


def classify(samples: list[dict], values: dict) -> tuple[str, str]:
    internet = [s for s in samples if s["role"] == "internet"]
    gateway = [s for s in samples if s["role"] == "gateway"]
    if internet and all(s["received"] == 0 for s in internet):
        if gateway and all(s["received"] == 0 for s in gateway):
            return "DOWN", "Né il router né Internet rispondono: problema di rete locale o del router."
        return "DOWN", "Il router risponde ma Internet no: interruzione della linea o del provider."
    worst_loss = max((s["loss_pct"] for s in internet), default=0)
    rtts = [s["rtt_avg_ms"] for s in internet if s["rtt_avg_ms"] is not None]
    avg_rtt = sum(rtts) / len(rtts) if rtts else 0
    if worst_loss >= values["connectivity.loss_warning"]:
        return "WARNING", f"Perdita di pacchetti fino al {worst_loss:g}% (soglia {values['connectivity.loss_warning']:g}%)."
    if avg_rtt >= values["connectivity.rtt_warning"]:
        return "WARNING", f"Latenza media {avg_rtt:.0f} ms (soglia {values['connectivity.rtt_warning']:g} ms)."
    return "OK", f"Latenza media {avg_rtt:.0f} ms, nessuna perdita significativa."


def describe(samples: list[dict], lang: str = "it") -> str:
    _ = i18n.translator(lang)
    return "\n".join(
        f"- {s['target']} ({'router' if s['role'] == 'gateway' else 'Internet'}): "
        + _("{ok}/{tot} risposte", ok=s["received"], tot=s["sent"]) + ", "
        + (f"{s['rtt_avg_ms']:.1f} ms" if s["rtt_avg_ms"] is not None else _("nessuna risposta"))
        for s in samples)


def fmt_duration(delta: dt.timedelta) -> str:
    m = max(1, round(delta.total_seconds() / 60))
    return f"{m} min" if m < 60 else f"{m // 60} h {m % 60} min"


def main(cfg: Config, dry_run: bool) -> int:
    now = dt.datetime.now().replace(second=0, microsecond=0)
    if dry_run:
        values = None
        try:
            with db.connect(cfg.database) as conn:
                values = settings_mod.load(conn, cfg)
        except db.DatabaseError:
            pass
        values = values or {k: sp.default for k, sp in settings_mod.build_spec(cfg).items()}
    else:
        with db.connect(cfg.database) as conn:
            values = settings_mod.load(conn, cfg)
            if not values["connectivity.enabled"]:
                log.info("Controllo continuo disattivato dalle Impostazioni")
                return 0

    targets = resolve_targets(values)
    with ThreadPoolExecutor(max_workers=max(1, len(targets))) as ex:
        results = list(ex.map(lambda t: {**ping(t[0]), "role": t[1]}, targets))
    status, text = classify(results, values)
    # gira ogni minuto: nel journal solo i cambi di stato (dettagli con --verbose o --dry-run)
    detail = log.info if dry_run else log.debug
    detail("%s - %s", status, text)
    for s in results:
        detail("  %s %s: %d/%d, rtt %s ms", s["role"], s["target"], s["received"], s["sent"], s["rtt_avg_ms"])
    if dry_run:
        return 0

    with db.connect(cfg.database) as conn:
        conn.execute(models.connectivity_samples.insert(),
                     [{"timestamp": now, "target": s["target"], "role": s["role"], "sent": s["sent"],
                       "received": s["received"], "loss_pct": s["loss_pct"], "rtt_avg_ms": s["rtt_avg_ms"],
                       "rtt_max_ms": s["rtt_max_ms"]} for s in results])
        state = notifier.AlertState(conn, "connectivity")
        since = state.anomaly_since
        should_notify, reason, previous = state.evaluate(status, settings_mod.policy(values, "connectivity"))
        if previous != status:
            log.info("Connessione: %s -> %s. %s", previous or "n/d", status, text)
        db.state_set(conn, "connectivity:last", {"time": now.isoformat(timespec="seconds"), "status": status,
                                                 "text": text, "samples": results})
        if should_notify:
            lang = i18n.lang_of(values)
            _ = i18n.translator(lang)
            if status == "OK":
                real_now = dt.datetime.now()
                subject = _("Connessione ripristinata dopo {durata}", durata=fmt_duration(real_now - since)) if since \
                    else _("Connessione ripristinata")
                body = (_("La connessione è tornata regolare alle {ora}.", ora=f"{now:%H:%M}") + "\n"
                        + (_("Situazione anomala ({stato}) dalle {inizio}, durata {durata}.", stato=previous,
                             inizio=f"{since:%H:%M %d/%m}", durata=fmt_duration(real_now - since)) + "\n" if since else "")
                        + "\n" + describe(results, lang))
            else:
                subject = _("Connessione assente") if status == "DOWN" else _("Connessione degradata")
                intro = notifier.reason_line(reason, state, lang)
                body = "\n".join(x for x in (intro, i18n.translate_stored(text, lang), "", describe(results, lang)) if x is not None)
            if notifier.dispatch(conn, cfg, "connectivity", subject, body, detected_at=now):
                state.mark_notified()
        state.save()
    return 0


def entrypoint() -> None:
    run("connectivity", "Ping continuo verso router e Internet", main)


if __name__ == "__main__":
    entrypoint()
