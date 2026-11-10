"""4.6: UPS. Un modello unico (Reading) e fonti intercambiabili ("backend") che lo riempiono.

Per aggiungere una fonte: un modulo con read(dev) -> Reading e, se serve, discover(host, port) -> [nomi UPS],
registrato in BACKENDS. Le marche si coprono soprattutto con NUT (centinaia di modelli: APC, Eaton, CyberPower,
Riello, Vertiv, Tripp Lite, Salicru…), poi apcupsd e SNMP (UPS-MIB standard).
"""
from __future__ import annotations

from .base import Reading, UpsError

__all__ = ["Reading", "UpsError", "backend", "BACKENDS", "DEFAULT_PORTS"]

BACKENDS = {}


def backend(name: str):
    if not BACKENDS:
        from . import apcupsd, nut, snmp
        BACKENDS.update({"nut": nut, "apcupsd": apcupsd, "snmp": snmp})
    if name not in BACKENDS:
        raise UpsError(f"Tipo di UPS sconosciuto: {name}")
    return BACKENDS[name]


DEFAULT_PORTS = {"nut": 3493, "apcupsd": 3551, "snmp": 161}
