"""4.4: "silenzia per un po'". Durante un silenzio gli avvisi non partono, ma tutto viene registrato.

Un silenzio riguarda:
  - all      tutto
  - host     un server (host_id), con tutto ciò che lo riguarda
  - source   un tipo di evento (es. connectivity, checks, backup)
  - service  un servizio di un server (host_id + unit)
Allo scadere, se il problema c'è ancora, l'avviso parte normalmente (rispettando "Avvisa dopo"): lo gestisce
notifier.AlertState.evaluate, che tiene l'avviso "in attesa" finché il silenzio dura.

I silenzi stanno in monitor_state (chiave "silences"): nessuna migrazione del database.
"""
from __future__ import annotations

import datetime as dt
import secrets

from . import db

KEY = "silences"
SCOPES = ("all", "host", "source", "service")
MAX_MINUTES = 7 * 24 * 60


class SilenceError(Exception):
    pass


def _now() -> dt.datetime:
    return dt.datetime.now().replace(microsecond=0)


def active(conn, now: dt.datetime | None = None) -> list[dict]:
    now = now or _now()
    return [s for s in (db.state_get(conn, KEY) or []) if dt.datetime.fromisoformat(s["until"]) > now]


def add(conn, scope: str, *, host_id: int | None = None, source: str | None = None, unit: str | None = None,
        minutes: int | None = None, until: str | None = None, by: str = "", label: str = "",
        now: dt.datetime | None = None) -> dict:
    now = now or _now()
    if scope not in SCOPES:
        raise SilenceError("Tipo di silenzio non valido")
    if scope in ("host", "service") and not host_id:
        raise SilenceError("Server mancante")
    if scope == "service" and not unit:
        raise SilenceError("Servizio mancante")
    if scope == "source" and not source:
        raise SilenceError("Tipo di evento mancante")
    if until:
        try:
            end = dt.datetime.fromisoformat(str(until)[:19])
        except ValueError:
            raise SilenceError("Orario non valido") from None
    else:
        try:
            m = int(minutes or 0)
        except (TypeError, ValueError):
            raise SilenceError("Durata non valida") from None
        end = now + dt.timedelta(minutes=m)
    if not now < end <= now + dt.timedelta(minutes=MAX_MINUTES):
        raise SilenceError("Durata non valida: da pochi minuti a 7 giorni")
    item = {"id": secrets.token_hex(4), "scope": scope, "host_id": int(host_id) if host_id else None,
            "source": source if scope == "source" else None, "unit": unit if scope == "service" else None,
            "until": end.isoformat(timespec="seconds"), "by": by[:40], "label": label[:120],
            "created": now.isoformat(timespec="seconds")}
    # un nuovo silenzio sullo stesso oggetto sostituisce il precedente
    same = lambda s: all(s.get(k) == item[k] for k in ("scope", "host_id", "source", "unit"))  # noqa: E731
    db.state_set(conn, KEY, [s for s in active(conn, now) if not same(s)] + [item])
    return item


def remove(conn, sid: str) -> bool:
    lst = db.state_get(conn, KEY) or []
    keep = [s for s in lst if s["id"] != sid]
    db.state_set(conn, KEY, keep)
    return len(keep) != len(lst)


def parse_key(key: str) -> tuple[int, str | None]:
    """Server e servizio di uno stato d'allarme (alert:host:2:service:Spooler, alert:service:nginx.service, …)."""
    k = key.removeprefix("alert:")
    host = 1
    if k.startswith("host:"):
        _, h, k = k.split(":", 2)
        host = int(h)
    unit = k.split(":", 1)[1] if k.startswith("service:") else None
    return host, unit


def match(conn, alert_key: str, source: str | None, now: dt.datetime | None = None) -> dict | None:
    """Il silenzio attivo che copre questo allarme, se c'è."""
    sil = active(conn, now)
    if not sil:
        return None
    host, unit = parse_key(alert_key)
    for s in sil:
        if s["scope"] == "all" \
                or (s["scope"] == "host" and s["host_id"] == host) \
                or (s["scope"] == "source" and source and s["source"] == source) \
                or (s["scope"] == "service" and s["host_id"] == host and unit and s["unit"] and s["unit"].lower() == unit.lower()):
            return s
    return None


def for_item(sil: list[dict], host: int | None, source: str | None, unit: str | None) -> dict | None:
    """Per la dashboard: il silenzio che copre una voce di "Da controllare"."""
    for s in sil:
        if s["scope"] == "all" or (s["scope"] == "host" and host and s["host_id"] == host) \
                or (s["scope"] == "source" and source and s["source"] == source) \
                or (s["scope"] == "service" and host and s["host_id"] == host and unit and (s["unit"] or "").lower() == unit.lower()):
            return s
    return None
