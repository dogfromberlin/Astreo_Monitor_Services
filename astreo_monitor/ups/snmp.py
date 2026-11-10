"""SNMP: arriva nella tappa successiva (UPS con scheda di rete, UPS-MIB standard)."""
from __future__ import annotations

from .base import Reading, UpsError


def read(dev: dict) -> Reading:
    raise UpsError("UPS via SNMP: disponibile da una prossima versione")


def discover(host: str, port: int = 161) -> list[dict]:
    raise UpsError("UPS via SNMP: disponibile da una prossima versione")
