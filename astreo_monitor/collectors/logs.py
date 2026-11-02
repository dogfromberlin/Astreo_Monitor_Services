"""Lettura del journal di systemd per i servizi monitorati e per Astreo Monitor.

Solo unit consentite (servizi monitorati e astreo-*), mai comandi arbitrari. L'utente dei servizi
deve poter leggere il journal di sistema: di norma è nel gruppo adm; altrimenti
`sudo usermod -aG systemd-journal <utente>` e un riavvio della dashboard.
"""
from __future__ import annotations

import datetime as dt
import json
import re
import subprocess

PRIORITIES = {"emerg": 0, "alert": 1, "crit": 2, "err": 3, "warning": 4, "notice": 5, "info": 6, "debug": 7}
SINCE = {"15m": "-15min", "1h": "-1h", "6h": "-6h", "24h": "-24h", "7d": "-7d"}
MAX_LINES = 2000


class LogError(Exception):
    pass


def _text(v) -> str:
    if isinstance(v, list):                          # messaggi binari: lista di byte
        try:
            return bytes(v).decode("utf-8", "replace")
        except (TypeError, ValueError):
            return ""
    return str(v or "")


def read(units: list[str], since: str = "1h", priority: str = "info", grep: str = "", lines: int = 500) -> list[dict]:
    if not units:
        return []
    args = ["journalctl", "--no-pager", "-o", "json", "--since", SINCE.get(since, "-1h"),
            "-p", str(PRIORITIES.get(priority, 6)), "-n", str(min(int(lines), MAX_LINES))]
    for u in units:
        args += ["-u", u]
    try:
        res = subprocess.run(args, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise LogError(f"journalctl non disponibile: {exc}") from exc
    if res.returncode != 0 and not res.stdout:
        msg = res.stderr.strip()
        if "No journal files were opened" in msg or "insufficient permissions" in msg.lower():
            raise LogError("permesso di leggere il journal mancante: aggiungi l'utente dei servizi al gruppo "
                           "systemd-journal (sudo usermod -aG systemd-journal UTENTE) e riavvia la dashboard")
        raise LogError(msg[:300] or "journalctl non riuscito")
    rx = re.compile(re.escape(grep), re.I) if grep else None
    out = []
    for line in res.stdout.splitlines():
        try:
            e = json.loads(line)
        except ValueError:
            continue
        msg = _text(e.get("MESSAGE"))
        if rx and not rx.search(msg):
            continue
        ts = int(e.get("__REALTIME_TIMESTAMP", "0")) / 1_000_000
        out.append({"time": dt.datetime.fromtimestamp(ts).isoformat(timespec="seconds"),
                    "unit": e.get("_SYSTEMD_UNIT") or e.get("UNIT") or "",
                    "ident": e.get("SYSLOG_IDENTIFIER", ""), "priority": int(e.get("PRIORITY", 6)),
                    "message": msg[:4000]})
    return out
