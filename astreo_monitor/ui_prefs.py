"""Preferenze dell'interfaccia di ogni utente della dashboard (4.1): tema e disposizione delle card (Personalizza).

Salvate nella tabella monitor_state con la chiave ui:prefs:<utente>: nessuna migrazione del database.
Valgono per l'utente, quindi sono le stesse dal computer e dal telefono; il browser ne tiene una copia
locale solo per mostrare subito il tema giusto all'apertura della pagina.
"""
from __future__ import annotations

import hashlib
import re

from . import db

THEMES = ("system", "light", "dark")
# sezioni della dashboard con le card riorganizzabili (Personalizza)
LAYOUT_SECTIONS = ("ov-kpis", "ov-hosts", "ov-bottom", "srv-detail")
CARD_RE = re.compile(r"^[a-z0-9:_-]{1,64}$")
MAX_CARDS = 60
DEFAULTS = {"theme": "system", "layout": {}}


def _cards(v) -> list[str]:
    if not isinstance(v, list) or len(v) > MAX_CARDS or not all(isinstance(x, str) and CARD_RE.match(x) for x in v):
        raise ValueError("Elenco di card non valido")
    return list(dict.fromkeys(v))


def _layout(v) -> dict:
    if not isinstance(v, dict):
        raise ValueError("Disposizione non valida")
    out = {}
    for sec, conf in v.items():
        if sec not in LAYOUT_SECTIONS or not isinstance(conf, dict) or set(conf) - {"order", "hidden"}:
            raise ValueError(f"Sezione non valida: {sec}")
        out[sec] = {"order": _cards(conf.get("order", [])), "hidden": _cards(conf.get("hidden", []))}
    return out


def _key(user: str) -> str:
    user = (user or "admin").strip()
    if len(user) > 40:                      # la chiave di monitor_state è lunga al massimo 64 caratteri
        user = hashlib.sha256(user.encode()).hexdigest()[:40]
    return f"ui:prefs:{user}"


def validate(data) -> dict:
    """Solo le chiavi note, con valori ammessi; le altre sono un errore (niente dati arbitrari nel DB)."""
    if not isinstance(data, dict) or not data:
        raise ValueError("Preferenze non valide")
    out = {}
    for k, v in data.items():
        if k == "theme":
            if v not in THEMES:
                raise ValueError("Tema non valido")
            out[k] = v
        elif k == "layout":
            out[k] = _layout(v)
        else:
            raise ValueError(f"Preferenza sconosciuta: {k}")
    return out


def load(conn, user: str) -> dict:
    stored = db.state_get(conn, _key(user)) or {}
    return {**DEFAULTS, **{k: v for k, v in stored.items() if k in DEFAULTS}}


def save(conn, user: str, changes: dict) -> dict:
    prefs = {**load(conn, user), **changes}
    db.state_set(conn, _key(user), prefs)
    return prefs
