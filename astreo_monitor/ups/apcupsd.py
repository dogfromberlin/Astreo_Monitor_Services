"""apcupsd NIS (porta 3551): richiesta "status" con lunghezza in testa, risposta a record "CHIAVE : valore"."""
from __future__ import annotations

import socket
import struct

from .base import Reading, UpsError, num

TIMEOUT = 8


def _status(host: str, port: int) -> dict:
    try:
        with socket.create_connection((host, port), timeout=TIMEOUT) as s:
            s.sendall(struct.pack(">H", 6) + b"status")
            data, out = b"", {}
            while True:
                hdr = s.recv(2)
                while len(hdr) < 2:
                    more = s.recv(2 - len(hdr))
                    if not more:
                        raise UpsError("risposta di apcupsd interrotta")
                    hdr += more
                n = struct.unpack(">H", hdr)[0]
                if n == 0:
                    break
                data = b""
                while len(data) < n:
                    chunk = s.recv(n - len(data))
                    if not chunk:
                        raise UpsError("risposta di apcupsd interrotta")
                    data += chunk
                line = data.decode("utf-8", "replace")
                if ":" in line:
                    k, v = line.split(":", 1)
                    out[k.strip()] = v.strip()
            return out
    except OSError as exc:
        raise UpsError(f"apcupsd {host}:{port} non raggiungibile ({exc.__class__.__name__})") from None


def parse(d: dict) -> Reading:
    st = (d.get("STATUS") or "").upper().split()
    status = ("low" if "LOWBATT" in st else "battery" if "ONBATT" in st else "unknown" if "COMMLOST" in st
              else "off" if "SHUTTING" in st else "online" if "ONLINE" in st else "unknown")
    flags = (["replace"] if "REPLACEBATT" in st else []) + (["overload"] if "OVERLOAD" in st else []) \
        + (["boost"] if "BOOST" in st else []) + (["trim"] if "TRIM" in st else [])
    tl = num(d.get("TIMELEFT"))
    return Reading(status=status, flags=flags, charge=num(d.get("BCHARGE")), runtime_s=tl * 60 if tl is not None else None,
                   load=num(d.get("LOADPCT")), input_v=num(d.get("LINEV")), output_v=num(d.get("OUTPUTV")),
                   battery_v=num(d.get("BATTV")), temperature=num(d.get("ITEMP")), manufacturer="APC",
                   model=d.get("MODEL"), serial=d.get("SERIALNO"), test_result=d.get("SELFTEST"), raw=d)


def read(dev: dict) -> Reading:
    d = _status(dev["host"], int(dev.get("port") or 3551))
    if not d:
        raise UpsError("apcupsd non ha restituito dati")
    return parse(d)


def discover(host: str, port: int = 3551) -> list[dict]:
    d = _status(host, port)
    return [{"name": d.get("UPSNAME") or "apcupsd", "description": d.get("MODEL") or ""}]
