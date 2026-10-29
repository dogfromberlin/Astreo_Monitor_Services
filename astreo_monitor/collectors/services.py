"""Stato dei servizi systemd, limitato alla whitelist in configurazione."""
from __future__ import annotations

import subprocess

from ..config import ServiceDef


def statuses(services: list[ServiceDef]) -> list[dict]:
    """Stato di tutti i servizi con una sola chiamata a systemctl."""
    if not services:
        return []
    try:
        res = subprocess.run(
            ["systemctl", "is-active", *[s.unit for s in services]],
            capture_output=True, text=True, timeout=10, check=False,
        )
        states = res.stdout.split()
    except (OSError, subprocess.TimeoutExpired):
        states = []
    out = []
    for i, s in enumerate(services):
        state = states[i] if i < len(states) else "unknown"
        out.append({"key": s.key, "unit": s.unit, "label": s.label, "state": state, "up": state == "active"})
    return out


def detail(service: ServiceDef, lines: int = 30) -> str:
    """Output di `systemctl status` per un servizio della whitelist."""
    try:
        res = subprocess.run(
            ["systemctl", "status", service.unit, "--no-pager", "-l", "-n", str(lines)],
            capture_output=True, text=True, timeout=10, check=False,
        )
        return (res.stdout or res.stderr).strip()
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"Impossibile leggere lo stato di {service.unit}: {exc}"
