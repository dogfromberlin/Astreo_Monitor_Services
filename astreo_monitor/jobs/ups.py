"""4.6: controllo degli UPS (ogni minuto). Legge ogni UPS dalla sua fonte (NUT, apcupsd, SNMP), salva lo storico e
manda gli avvisi: blackout, batteria scarica, corrente tornata (con la durata), batteria da sostituire, sovraccarico,
UPS non raggiungibile. Nessuno spegnimento automatico: Astreo osserva e avvisa soltanto.
"""
from __future__ import annotations

import datetime as dt
import logging

from sqlalchemy import insert, select

from .. import db, events, i18n, models, notifier, ups
from .. import settings as settings_mod
from ..config import Config
from ..ups import store
from .base import run

log = logging.getLogger("job.ups")
COMM_TRIES = 3            # letture fallite di fila prima di dire "non raggiungibile" (cadute di rete brevi)


def read_all(devs: list[dict]) -> list[tuple[dict, ups.Reading | None, str]]:
    out = []
    for d in devs:
        try:
            out.append((d, ups.backend(d["backend"]).read(d), ""))
        except ups.UpsError as exc:
            out.append((d, None, str(exc)))
        except Exception as exc:  # noqa: BLE001 - una fonte difettosa non ferma le altre
            log.exception("Lettura dell'UPS %s non riuscita", d["name"])
            out.append((d, None, f"errore: {exc.__class__.__name__}"))
    return out


def _mins(seconds: float | None) -> str:
    return "–" if seconds is None else f"{round(seconds / 60)} min"


def main(cfg: Config, dry_run: bool) -> int:
    now = dt.datetime.now().replace(microsecond=0)
    with db.connect(cfg.database) as conn:
        devs = db.rows(conn, select(models.ups_devices).where(models.ups_devices.c.enabled == True))  # noqa: E712
    if not devs:
        return 0
    results = read_all(devs)                       # letture fuori dalle transazioni (rete)
    if dry_run:
        for d, r, err in results:
            log.info("%s: %s", d["name"], err or f"{r.status} {r.charge}% {r.load}%")
        return 0
    with db.connect(cfg.database) as conn:
        values = settings_mod.load(conn, cfg)
        lang = i18n.lang_of(values)
        _ = i18n.translator(lang)
        rule = settings_mod.policy(values, "ups")
        for d, r, err in results:
            uid, name = d["id"], d["name"]
            prev = db.state_get(conn, f"ups:{uid}:last") or {}
            fails = (prev.get("fails", 0) + 1) if r is None else 0
            last = {"time": now.isoformat(timespec="seconds"), "error": err or None, "fails": fails,
                    "reading": r.to_dict() if r else prev.get("reading"),
                    "read_at": now.isoformat(timespec="seconds") if r else prev.get("read_at")}
            if r:
                conn.execute(insert(models.ups_samples).values(ups_id=uid, timestamp=now, status=r.status, charge=r.charge,
                                                               runtime_s=r.runtime_s, load=r.load, input_v=r.input_v,
                                                               output_v=r.output_v))
                # inizio e fine del blackout, con la durata
                bo = db.state_get(conn, f"ups:{uid}:blackout")
                if r.status in ("battery", "low") and not bo:
                    db.state_set(conn, f"ups:{uid}:blackout", {"since": now.isoformat(timespec="seconds")})
                    events.record(conn, "ups", "alert", f"Blackout: UPS {name} a batteria",
                                  f"carica {r.charge}%, autonomia {_mins(r.runtime_s)}", when=now)
                elif r.status not in ("battery", "low") and bo:
                    mins = round((now - dt.datetime.fromisoformat(bo["since"])).total_seconds() / 60)
                    db.state_set(conn, f"ups:{uid}:blackout", None)
                    last["last_blackout"] = {"since": bo["since"], "minutes": mins}
                    events.record(conn, "ups", "info", f"Corrente tornata: UPS {name} (blackout di {mins} min)",
                                  f"carica {r.charge}%", when=now)
            elif prev.get("last_blackout"):
                last["last_blackout"] = prev["last_blackout"]
            if r and "last_blackout" not in last and prev.get("last_blackout"):
                last["last_blackout"] = prev["last_blackout"]
            db.state_set(conn, f"ups:{uid}:last", last)

            # avvisi (evento "UPS e alimentazione"); ogni condizione ha il suo stato
            checks = [("comm", "WARNING" if fails >= COMM_TRIES else "OK",
                       _("UPS {p0} non raggiungibile: {p1}", p0=name, p1=err) if fails >= COMM_TRIES else _("UPS {p0} di nuovo raggiungibile", p0=name))]
            if r:
                detail = _("Carica {c}% · autonomia {a} · carico {l}%", c=r.charge if r.charge is not None else "–",
                           a=_mins(r.runtime_s), l=r.load if r.load is not None else "–")
                bo = db.state_get(conn, f"ups:{uid}:blackout")
                if r.status in ("battery", "low"):
                    checks.append(("power", "ALERT", _("Blackout: l'UPS {p0} è a batteria", p0=name) + "\n" + detail))
                else:
                    back = last.get("last_blackout") if last.get("last_blackout", {}).get("since", "") >= (now - dt.timedelta(minutes=3)).isoformat() else None
                    checks.append(("power", "OK", (_("Corrente tornata dopo {p0} min", p0=back["minutes"]) if back
                                                   else _("UPS {p0} alimentato dalla rete", p0=name)) + "\n" + detail))
                checks.append(("low", "ALERT" if r.status == "low" else "OK",
                               (_("Batteria scarica: l'UPS {p0} sta per esaurirsi", p0=name) if r.status == "low"
                                else _("Batteria dell'UPS {p0} di nuovo sopra la soglia", p0=name)) + "\n" + detail))
                checks.append(("replace", "WARNING" if "replace" in r.flags else "OK",
                               _("L'UPS {p0} segnala la batteria da sostituire", p0=name) if "replace" in r.flags
                               else _("Batteria dell'UPS {p0} a posto", p0=name)))
                checks.append(("overload", "WARNING" if "overload" in r.flags else "OK",
                               _("UPS {p0} in sovraccarico: carico {l}%", p0=name, l=r.load) if "overload" in r.flags
                               else _("Sovraccarico dell'UPS {p0} rientrato", p0=name)))
            for key, status, text in checks:
                state = notifier.AlertState(conn, f"ups:{uid}:{key}")
                notify, reason, previous = state.evaluate(status, rule)
                if notify:
                    title = text.split("\n")[0]
                    body = "\n".join(x for x in (notifier.reason_line(reason, state, lang), text,
                                                 _("Stato precedente: {stato}", stato=previous or "n/d")) if x)
                    if notifier.dispatch(conn, cfg, "ups", title, body):
                        state.mark_notified()
                state.save()
        if now.minute == 0:
            store.prune(conn, now)
    return 0


def entrypoint() -> None:
    run("ups", "Legge gli UPS e avvisa di blackout, batteria scarica e corrente tornata", main)


if __name__ == "__main__":
    entrypoint()
