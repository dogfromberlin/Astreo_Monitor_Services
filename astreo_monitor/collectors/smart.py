"""Lettura dei dati SMART raccolti da deploy/bin/astreo-smart-collect (come root)."""
from __future__ import annotations

import datetime as dt
import glob
import json
import os

SMART_DIR = "/var/lib/astreo-monitor/smart"

# Attributi ATA: id -> chiave
ATA = {5: "reallocated", 197: "pending", 198: "uncorrectable", 194: "temperature", 9: "power_on_hours"}
# Attributi di vita residua degli SSD SATA (il valore normalizzato è la % RESIDUA)
LIFE_ATTRS = {177, 202, 231, 233, 169}


def read_disks(path: str = SMART_DIR) -> list[dict]:
    disks = []
    for f in sorted(glob.glob(os.path.join(path, "*.json"))):
        try:
            with open(f, encoding="utf-8") as fh:
                d = json.load(fh)
        except (OSError, ValueError) as exc:
            disks.append({"device": os.path.basename(f)[:-5], "error": f"file non leggibile: {exc}"})
            continue
        disks.append(parse(d, os.path.basename(f)[:-5], dt.datetime.fromtimestamp(os.path.getmtime(f))))
    return disks


def parse(d: dict, name: str, read_at: dt.datetime) -> dict:
    out = {
        "device": name,
        "model": d.get("model_name") or d.get("model_family") or "",
        "serial": d.get("serial_number", ""),
        "capacity_gb": round((d.get("user_capacity") or {}).get("bytes", 0) / 1e9),
        "passed": (d.get("smart_status") or {}).get("passed"),
        "temperature": (d.get("temperature") or {}).get("current"),
        "power_on_hours": (d.get("power_on_time") or {}).get("hours"),
        "reallocated": 0, "pending": 0, "uncorrectable": 0, "media_errors": 0,
        "wear_used_pct": None,
        "read_at": read_at.isoformat(timespec="minutes"),
        "messages": [m.get("string") for m in (d.get("smartctl") or {}).get("messages", []) if m.get("severity") == "error"],
    }
    for a in (d.get("ata_smart_attributes") or {}).get("table", []):
        aid = a.get("id")
        raw = (a.get("raw") or {}).get("value")
        if aid in (5, 197, 198) and raw is not None:
            out[ATA[aid]] = int(raw)
        if aid in LIFE_ATTRS and a.get("value") is not None and out["wear_used_pct"] is None:
            out["wear_used_pct"] = max(0, 100 - int(a["value"]))
    nvme = d.get("nvme_smart_health_information_log")
    if nvme:
        out["wear_used_pct"] = nvme.get("percentage_used")
        out["media_errors"] = nvme.get("media_errors", 0)
        out["temperature"] = out["temperature"] or nvme.get("temperature")
    return out


def evaluate(disk: dict, temp_warning: float, wear_warning: float) -> tuple[str, list[str]]:
    """Stato del disco e motivi."""
    if disk.get("error"):
        return "UNKNOWN", [disk["error"]]
    alert, warn = [], []
    if disk.get("passed") is False:
        alert.append("autodiagnosi SMART FALLITA: il disco prevede un guasto")
    if disk.get("pending"):
        alert.append(f"{disk['pending']} settori in attesa di riallocazione")
    if disk.get("uncorrectable"):
        alert.append(f"{disk['uncorrectable']} settori non correggibili")
    if disk.get("media_errors"):
        alert.append(f"{disk['media_errors']} errori del supporto (NVMe)")
    if disk.get("reallocated"):
        warn.append(f"{disk['reallocated']} settori riallocati")
    if disk.get("wear_used_pct") is not None and disk["wear_used_pct"] >= wear_warning:
        warn.append(f"usura SSD al {disk['wear_used_pct']}%")
    if disk.get("temperature") is not None and disk["temperature"] >= temp_warning:
        warn.append(f"temperatura {disk['temperature']} °C")
    if alert:
        return "ALERT", alert + warn
    if warn:
        return "WARNING", warn
    return "OK", []
