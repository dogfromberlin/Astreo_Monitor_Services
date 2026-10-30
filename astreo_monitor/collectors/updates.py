"""Aggiornamenti di sistema in sospeso e riavvio richiesto (Ubuntu/Debian, senza privilegi)."""
from __future__ import annotations

import datetime as dt
import os
import subprocess

REBOOT_FILE = "/var/run/reboot-required"


def pending() -> dict:
    """Pacchetti aggiornabili dalla cache di apt (aggiornata ogni giorno da apt-daily.timer)."""
    try:
        res = subprocess.run(["apt", "list", "--upgradable"], capture_output=True, text=True, timeout=120,
                             env={**os.environ, "LANG": "C", "LC_ALL": "C"})
        lines = [x for x in res.stdout.splitlines() if "/" in x and "[upgradable" in x]
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"error": str(exc), "total": 0, "security": []}
    security = []
    for line in lines:
        name, _, rest = line.partition("/")
        origin = rest.split(" ", 1)[0]
        if "-security" in origin:
            security.append(name)
    return {"total": len(lines), "security": sorted(security)}


def reboot() -> dict:
    if not os.path.exists(REBOOT_FILE):
        return {"required": False}
    since = dt.datetime.fromtimestamp(os.path.getmtime(REBOOT_FILE))
    pkgs = []
    try:
        with open(REBOOT_FILE + ".pkgs", encoding="utf-8") as f:
            pkgs = sorted({x.strip() for x in f if x.strip()})
    except OSError:
        pass
    return {"required": True, "since": since.isoformat(timespec="minutes"), "packages": pkgs}
