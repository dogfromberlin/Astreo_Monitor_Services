"""Modello unico di una lettura UPS, uguale per tutte le fonti."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field


class UpsError(Exception):
    pass


# stato normalizzato: online (da rete), battery (blackout), low (batteria scarica), bypass, off, unknown
@dataclass
class Reading:
    status: str = "unknown"
    flags: list[str] = field(default_factory=list)        # replace (batteria da sostituire), overload, charging, trim, boost
    charge: float | None = None                           # %
    runtime_s: float | None = None                        # autonomia residua
    load: float | None = None                             # %
    input_v: float | None = None
    output_v: float | None = None
    battery_v: float | None = None
    temperature: float | None = None
    manufacturer: str | None = None
    model: str | None = None
    serial: str | None = None
    test_result: str | None = None
    raw: dict = field(default_factory=dict)               # valori originali, per il dettaglio

    def to_dict(self) -> dict:
        d = asdict(self)
        d["raw"] = {k: v for k, v in list(self.raw.items())[:80]}
        return d


def num(v) -> float | None:
    try:
        return round(float(str(v).split()[0]), 2)
    except (TypeError, ValueError, IndexError):
        return None
