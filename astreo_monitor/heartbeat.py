"""Heartbeat verso un servizio esterno (es. healthchecks.io).

Astreo non può avvisarti se è spento o isolato: lo fa il servizio esterno,
quando smette di ricevere i ping. Il job delle metriche (ogni 5 minuti) chiama
l'URL configurato; in caso di errore chiama <URL>/fail, così il servizio esterno
distingue "Astreo spento" da "Astreo acceso ma con un problema".
"""
from __future__ import annotations

import datetime as dt
import logging

import requests

from . import __version__, db

log = logging.getLogger(__name__)
HEADERS = {"User-Agent": f"astreo-monitor/{__version__}"}


def ping(conn, values: dict, ok: bool = True, message: str = "") -> tuple[bool, str]:
    """Invia il ping (o /fail). Non solleva eccezioni. Registra l'esito in monitor_state."""
    if not values.get("heartbeat.enabled") or not values.get("heartbeat.url"):
        return False, "heartbeat non configurato"
    url = values["heartbeat.url"].rstrip("/") + ("" if ok else "/fail")
    try:
        r = requests.post(url, data=(message or "ok").encode()[:10000], headers=HEADERS, timeout=10)
        result = (r.ok, "" if r.ok else f"HTTP {r.status_code}")
    except requests.RequestException as exc:
        result = (False, str(exc).split("(")[0][:200])
    try:
        db.state_set(conn, "heartbeat:last", {"ok": result[0], "error": result[1], "signal": "ok" if ok else "fail",
                                              "time": dt.datetime.now().isoformat(timespec="seconds")})
    except Exception:  # noqa: BLE001
        pass
    if not result[0]:
        log.warning("Heartbeat non inviato: %s", result[1])
    return result
