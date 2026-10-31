"""Moduli opzionali: si attivano da soli se il servizio è presente sul server.

Ogni modulo espone detect() -> (presente, motivo). La dashboard mostra la sezione
solo se il modulo è presente E la sua visibilità (ui.<chiave>) è attiva.
Per aggiungere un modulo: un file qui con detect() e i dati, una voce in MODULES.
"""
from __future__ import annotations

from . import docker, pihole

MODULES = {
    "docker": {"label": "Docker", "detect": lambda values: docker.detect()},
    "pihole": {"label": "Pi-hole", "detect": lambda values: pihole.detect(values["pihole.url"])},
}


def status(values: dict) -> list[dict]:
    out = []
    for key, m in MODULES.items():
        present, reason = m["detect"](values)
        out.append({"key": key, "label": m["label"], "available": present, "reason": reason,
                    "visible": bool(values.get(f"ui.{key}", True))})
    return out
