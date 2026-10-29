"""Controllo delle unit di Astreo Monitor (solo quelle, mai altri servizi).

Richiede la regola polkit deploy/polkit/50-astreo-monitor.rules, che consente
all'utente <utente> start/stop/restart delle sole unit elencate qui.
"""
from __future__ import annotations

import datetime as dt
import subprocess

CONTROLLABLE = {
    "astreo-speedtest.service", "astreo-speedtest.timer",
    "astreo-metrics.service", "astreo-publicip.service",
    "astreo-backup.service", "astreo-maintenance.service",
}
VERBS = {"start", "stop", "restart"}


class UnitControlError(Exception):
    pass


def control(unit: str, verb: str) -> None:
    if unit not in CONTROLLABLE or verb not in VERBS:
        raise UnitControlError(f"Operazione non consentita: {verb} {unit}")
    args = ["systemctl", "--no-ask-password"]
    if unit.endswith(".service") and verb == "start":
        args.append("--no-block")  # i job durano decine di secondi: non blocco la richiesta web
    res = subprocess.run([*args, verb, unit], capture_output=True, text=True, timeout=20, check=False)
    if res.returncode != 0:
        msg = (res.stderr or res.stdout).strip()
        if "Interactive authentication required" in msg or "Access denied" in msg:
            msg += " — manca la regola polkit (vedi docs/impostazioni.md)"
        raise UnitControlError(msg)


def _usec_to_iso(value: str) -> str | None:
    try:
        n = int(value)
    except (TypeError, ValueError):
        return None
    if n <= 0:
        return None
    return dt.datetime.fromtimestamp(n / 1_000_000).isoformat(timespec="seconds")


def info(unit: str) -> dict:
    props = ["ActiveState", "SubState", "UnitFileState", "NextElapseUSecRealtime", "LastTriggerUSec",
             "ExecMainStartTimestamp", "Result"]
    try:
        res = subprocess.run(["systemctl", "show", unit, "--timestamp=unix", "-p", ",".join(props)],
                             capture_output=True, text=True, timeout=10, check=False)
        data = dict(line.split("=", 1) for line in res.stdout.splitlines() if "=" in line)
    except (OSError, subprocess.TimeoutExpired):
        data = {}

    def ts(key):
        v = data.get(key, "")
        if v.startswith("@"):
            try:
                return dt.datetime.fromtimestamp(int(v[1:])).isoformat(timespec="seconds")
            except ValueError:
                return None
        return _usec_to_iso(v)

    return {
        "unit": unit,
        "active": data.get("ActiveState", "unknown"),
        "sub": data.get("SubState", ""),
        "enabled": data.get("UnitFileState", ""),
        "next_run": ts("NextElapseUSecRealtime"),
        "last_trigger": ts("LastTriggerUSec"),
        "last_start": ts("ExecMainStartTimestamp"),
        "result": data.get("Result", ""),
    }
