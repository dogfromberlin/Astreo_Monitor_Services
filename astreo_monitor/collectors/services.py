"""Servizi systemd: catalogo completo, stato dei servizi monitorati, dettaglio."""
from __future__ import annotations

import re
import subprocess

UNIT_RE = re.compile(r"^[A-Za-z0-9@._:\\-]+\.service$")


def valid_unit(unit: str) -> bool:
    return bool(UNIT_RE.match(unit or "")) and len(unit) <= 255


def catalog() -> list[dict]:
    """Tutti i servizi noti a systemd (caricati o installati)."""
    units: dict[str, dict] = {}
    try:
        res = subprocess.run(
            ["systemctl", "list-units", "--type=service", "--all", "--no-legend", "--plain", "--no-pager"],
            capture_output=True, text=True, timeout=15, check=False,
        )
        for line in res.stdout.splitlines():
            parts = line.split(None, 4)
            if len(parts) >= 4 and parts[0].endswith(".service"):
                units[parts[0]] = {"unit": parts[0], "load": parts[1], "active": parts[2], "sub": parts[3],
                                   "description": parts[4] if len(parts) > 4 else ""}
        res = subprocess.run(
            ["systemctl", "list-unit-files", "--type=service", "--no-legend", "--plain", "--no-pager"],
            capture_output=True, text=True, timeout=15, check=False,
        )
        for line in res.stdout.splitlines():
            parts = line.split()
            if parts and parts[0].endswith(".service") and "@." not in parts[0] and parts[0] not in units:
                units[parts[0]] = {"unit": parts[0], "load": "not-loaded", "active": "inactive",
                                   "sub": parts[1] if len(parts) > 1 else "", "description": ""}
    except (OSError, subprocess.TimeoutExpired):
        pass
    return sorted(units.values(), key=lambda u: (u["active"] != "active", u["unit"].lower()))


def states(units: list[str]) -> dict[str, str]:
    """Stato (active/inactive/failed/...) di più unit con una sola chiamata."""
    if not units:
        return {}
    try:
        res = subprocess.run(["systemctl", "is-active", *units], capture_output=True, text=True, timeout=10, check=False)
        values = res.stdout.split()
    except (OSError, subprocess.TimeoutExpired):
        values = []
    return {u: (values[i] if i < len(values) else "unknown") for i, u in enumerate(units)}


def statuses(rows: list[dict]) -> list[dict]:
    """rows: servizi monitorati dal DB (unit, label, ...). Aggiunge lo stato corrente."""
    st = states([r["unit"] for r in rows])
    out = []
    for r in rows:
        state = st.get(r["unit"], "unknown")
        out.append({"key": r["unit"], "unit": r["unit"], "label": r["label"], "state": state, "up": state == "active",
                    "notify": bool(r.get("notify")), "ondemand": bool(r.get("ondemand"))})
    return out


def detail(unit: str, lines: int = 30) -> str:
    try:
        res = subprocess.run(
            ["systemctl", "status", unit, "--no-pager", "-l", "-n", str(lines)],
            capture_output=True, text=True, timeout=10, check=False,
        )
        return (res.stdout or res.stderr).strip()
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"Impossibile leggere lo stato di {unit}: {exc}"
