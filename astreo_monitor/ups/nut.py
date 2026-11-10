"""Network UPS Tools (upsd, porta 3493): protocollo testuale, sola lettura (LIST UPS, LIST VAR)."""
from __future__ import annotations

import socket

from .base import Reading, UpsError, num

TIMEOUT = 8


def _session(host: str, port: int, lines: list[str]) -> list[list[str]]:
    """Invia i comandi e restituisce, per ognuno, le righe della risposta (fino a END LIST o a una riga sola)."""
    try:
        with socket.create_connection((host, port), timeout=TIMEOUT) as s:
            f = s.makefile("rwb", buffering=0)
            out = []
            for cmd in lines:
                f.write((cmd + "\n").encode())
                res = []
                while True:
                    raw = f.readline()
                    if not raw:
                        raise UpsError("connessione chiusa dal server NUT")
                    line = raw.decode("utf-8", "replace").rstrip("\r\n")
                    if line.startswith("ERR "):
                        raise UpsError(f"NUT: {line[4:]}")
                    res.append(line)
                    if not line.startswith("BEGIN LIST") and (line.startswith("END LIST") or not res[0].startswith("BEGIN LIST")):
                        break
                out.append(res)
            f.write(b"LOGOUT\n")
            return out
    except OSError as exc:
        raise UpsError(f"server NUT {host}:{port} non raggiungibile ({exc.__class__.__name__})") from None


def _unquote(s: str) -> str:
    s = s.strip()
    return s[1:-1].replace('\\"', '"') if len(s) >= 2 and s[0] == s[-1] == '"' else s


def discover(host: str, port: int = 3493) -> list[dict]:
    """UPS esposti da un server NUT: [{"name", "description"}]."""
    res = _session(host, port, ["LIST UPS"])[0]
    out = []
    for line in res:
        if line.startswith("UPS "):
            _, name, desc = line.split(" ", 2) if line.count(" ") >= 2 else (*line.split(" ", 1), "")
            out.append({"name": name, "description": _unquote(desc)})
    return out


FLAGS = {"RB": "replace", "OVER": "overload", "CHRG": "charging", "TRIM": "trim", "BOOST": "boost"}


def parse(vars_: dict) -> Reading:
    st = (vars_.get("ups.status") or "").split()
    status = ("low" if "LB" in st else "battery" if "OB" in st else "bypass" if "BYPASS" in st
              else "off" if "OFF" in st else "online" if "OL" in st else "unknown")
    return Reading(
        status=status, flags=[FLAGS[f] for f in st if f in FLAGS],
        charge=num(vars_.get("battery.charge")), runtime_s=num(vars_.get("battery.runtime")),
        load=num(vars_.get("ups.load")), input_v=num(vars_.get("input.voltage")),
        output_v=num(vars_.get("output.voltage")), battery_v=num(vars_.get("battery.voltage")),
        temperature=num(vars_.get("ups.temperature") or vars_.get("battery.temperature")),
        manufacturer=vars_.get("device.mfr") or vars_.get("ups.mfr"), model=vars_.get("device.model") or vars_.get("ups.model"),
        serial=vars_.get("device.serial") or vars_.get("ups.serial"), test_result=vars_.get("ups.test.result"), raw=vars_)


def read(dev: dict) -> Reading:
    name = dev.get("ups_name") or "ups"
    res = _session(dev["host"], int(dev.get("port") or 3493), [f"LIST VAR {name}"])[0]
    vars_ = {}
    for line in res:
        if line.startswith("VAR "):
            parts = line.split(" ", 3)
            if len(parts) == 4:
                vars_[parts[2]] = _unquote(parts[3])
    if not vars_:
        raise UpsError(f"nessun dato per l'UPS «{name}»")
    return parse(vars_)
