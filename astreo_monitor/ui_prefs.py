"""Preferenze dell'interfaccia di ogni utente della dashboard (4.1): tema, e dalla 4.1 anche l'ordine delle card.

Salvate nella tabella monitor_state con la chiave ui:prefs:<utente>: nessuna migrazione del database.
Valgono per l'utente, quindi sono le stesse dal computer e dal telefono; il browser ne tiene una copia
locale solo per mostrare subito il tema giusto all'apertura della pagina.
"""
from __future__ import annotations

import hashlib

from . import db

THEMES = ("system", "light", "dark")
DEFAULTS = {"theme": "system"}


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
