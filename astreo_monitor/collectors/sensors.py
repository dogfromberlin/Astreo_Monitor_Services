"""Temperature hardware.

Si usa `sensors -j` (lm-sensors) per mantenere gli stessi nomi adapter/device
dello storico già presente nel DB (es. "ISA adapter" / "Package id 0").
Se lm-sensors non è disponibile si ripiega su psutil.
"""
from __future__ import annotations

import json
import logging
import shutil
import subprocess

import psutil

log = logging.getLogger(__name__)


def read() -> list[dict]:
    """Ritorna [{adapter, device, value, high, critical}]."""
    if shutil.which("sensors"):
        try:
            return _from_lm_sensors()
        except Exception as exc:  # noqa: BLE001
            log.warning("Lettura `sensors -j` fallita, uso psutil: %s", exc)
    return _from_psutil()


def _from_lm_sensors() -> list[dict]:
    res = subprocess.run(["sensors", "-j"], capture_output=True, text=True, timeout=10, check=False)
    if not res.stdout.strip():
        raise RuntimeError(res.stderr.strip() or "output vuoto")
    data = json.loads(res.stdout)
    out = []
    for chip, chip_data in data.items():
        adapter = chip_data.get("Adapter", chip)
        for device, values in chip_data.items():
            if device == "Adapter" or not isinstance(values, dict):
                continue
            entry = {"adapter": adapter, "device": device, "value": None, "high": None, "critical": None}
            for metric, val in values.items():
                if metric.endswith("_input"):
                    entry["value"] = float(val)
                elif metric.endswith("_max"):
                    entry["high"] = float(val)
                elif metric.endswith("_crit") and not metric.endswith("_crit_alarm"):
                    entry["critical"] = float(val)
            # Solo sensori di temperatura (i nomi lm-sensors iniziano con temp*)
            if entry["value"] is not None and any(m.startswith("temp") for m in values):
                out.append(entry)
    return out


def _from_psutil() -> list[dict]:
    out = []
    for chip, entries in (psutil.sensors_temperatures() or {}).items():
        for i, e in enumerate(entries):
            out.append({
                "adapter": chip,
                "device": e.label or f"temp{i + 1}",
                "value": e.current,
                "high": e.high,
                "critical": e.critical,
            })
    return out
