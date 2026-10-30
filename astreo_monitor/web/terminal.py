"""Terminale web: sblocco con password separata e verifica per nginx.

Architettura:
  browser --HTTPS--> nginx :5443 --/terminal/--> ttyd (127.0.0.1:7681) -> bash come <utente>
                         \\-- auth_request --> /api/v1/terminal/check (questa app)

Il terminale si apre solo se TUTTE queste condizioni sono vere:
  - connessione HTTPS (tramite nginx), mai HTTP in chiaro;
  - login della dashboard (Basic Auth) valido;
  - sblocco con la password del terminale, separata, con sessione che scade dopo
    `session_minutes` di inattività (si rinnova finché scrivi nel terminale);
  - indirizzo del client in [terminal] allowed_networks (LAN/VPN).
I tentativi di sblocco errati sono limitati (5 ogni 15 minuti per IP) e ogni
sblocco, blocco o rifiuto è registrato nel journal.
"""
from __future__ import annotations

import ipaddress
import logging
import secrets
import time

from flask import Blueprint, abort, current_app, jsonify, request, session
from werkzeug.security import check_password_hash

log = logging.getLogger("web.terminal")
bp = Blueprint("terminal", __name__, url_prefix="/api/v1/terminal")

MAX_FAILURES = 5
FAILURE_WINDOW = 15 * 60
_failures: dict[str, list[float]] = {}
# Sessioni attive lato server: chiuderle (Blocca, chiusura della scheda, scadenza)
# le invalida subito, anche se il browser conservasse ancora il cookie.
_sessions: dict[str, dict] = {}


def _tcfg():
    return current_app.config["ASTREO_CFG"].terminal


def _client_ip() -> str:
    return request.remote_addr or ""


def _ip_allowed(nets: list[str]) -> bool:
    try:
        ip = ipaddress.ip_address(_client_ip())
    except ValueError:
        return False
    for n in nets:
        try:
            if ip in ipaddress.ip_network(n, strict=False):
                return True
        except ValueError:
            continue
    return False


def _unlocked_until() -> float:
    sid = session.get("term_id")
    info = _sessions.get(sid) if sid else None
    if not info:
        return 0
    if info["until"] <= time.time() or info["ip"] != _client_ip():
        _sessions.pop(sid, None)
        return 0
    return info["until"]


def _status() -> dict:
    t = _tcfg()
    https = request.scheme == "https"
    st = {
        "enabled": bool(t and t.enabled and t.password_hash),
        "https": https,
        "ip_allowed": bool(t) and _ip_allowed(t.allowed_networks),
        "client_ip": _client_ip(),
        "session_minutes": t.session_minutes if t else 0,
        "unlocked_until": None,
    }
    until = _unlocked_until()
    if until and st["enabled"] and https and st["ip_allowed"]:
        st["unlocked_until"] = int(until)
    return st


@bp.get("/status")
def status():
    return jsonify(_status())


@bp.post("/unlock")
def unlock():
    t = _tcfg()
    st = _status()
    if not st["enabled"]:
        abort(403, description="Terminale non abilitato ([terminal] enabled e password_hash nel config)")
    if not st["https"]:
        abort(403, description="Il terminale è disponibile solo tramite HTTPS")
    if not st["ip_allowed"]:
        log.warning("Terminale: sblocco rifiutato, indirizzo %s non ammesso", _client_ip())
        abort(403, description=f"Indirizzo {_client_ip()} non ammesso per il terminale")

    ip = _client_ip()
    now = time.time()
    recent = [x for x in _failures.get(ip, []) if now - x < FAILURE_WINDOW]
    _failures[ip] = recent
    if len(recent) >= MAX_FAILURES:
        log.warning("Terminale: troppi tentativi da %s, sblocco bloccato", ip)
        abort(429, description="Troppi tentativi errati: riprova tra 15 minuti")

    data = request.get_json(silent=True) or {}
    if not check_password_hash(t.password_hash, str(data.get("password", ""))):
        recent.append(now)
        log.warning("Terminale: password errata da %s (%d/%d)", ip, len(recent), MAX_FAILURES)
        abort(401, description="Password del terminale errata")

    _failures.pop(ip, None)
    old = session.get("term_id")
    if old:
        _sessions.pop(old, None)
    session.clear()
    sid = secrets.token_hex(12)
    session["term_id"] = sid          # cookie di sessione del browser: sparisce alla chiusura del browser
    _sessions[sid] = {"until": now + t.session_minutes * 60, "ip": ip}
    log.warning("Terminale: SBLOCCATO da %s, scade dopo %d minuti di inattività (sessione %s)", ip, t.session_minutes, sid[:8])
    return jsonify(_status())


@bp.post("/touch")
def touch():
    """Rinnova la sessione: chiamato dalla pagina mentre stai usando il terminale."""
    t = _tcfg()
    st = _status()
    if not st["unlocked_until"]:
        abort(401, description="Sessione del terminale scaduta")
    _sessions[session["term_id"]]["until"] = time.time() + t.session_minutes * 60
    return jsonify(_status())


@bp.post("/lock")
def lock():
    sid = session.get("term_id")
    if sid and _sessions.pop(sid, None):
        log.warning("Terminale: chiuso da %s (sessione %s)", _client_ip(), sid[:8])
    session.clear()
    return jsonify(_status())


@bp.get("/check")
def check():
    """Chiamato da nginx (auth_request) prima di ogni accesso a /terminal/."""
    st = _status()
    if st["unlocked_until"]:
        return "", 204
    log.warning("Terminale: accesso negato a %s (https=%s, ip ammesso=%s, sbloccato=%s)",
                _client_ip(), st["https"], st["ip_allowed"], bool(_unlocked_until()))
    return "", 401
