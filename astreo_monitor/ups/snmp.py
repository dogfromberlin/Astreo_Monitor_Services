"""SNMP v2c per gli UPS con scheda di rete: UPS-MIB standard (RFC 1628), con ripiego sulla PowerNet-MIB di APC.

Client SNMP minimo in Python (solo GET, nessuna libreria in più): codifica e decodifica BER dei pochi tipi necessari.
"""
from __future__ import annotations

import random
import socket

from .base import Reading, UpsError

TIMEOUT = 3

# --------------------------------------------------------------------------- BER minimo
def _len(n: int) -> bytes:
    if n < 0x80:
        return bytes([n])
    b = n.to_bytes((n.bit_length() + 7) // 8, "big")
    return bytes([0x80 | len(b)]) + b


def _tlv(tag: int, val: bytes) -> bytes:
    return bytes([tag]) + _len(len(val)) + val


def _int(v: int) -> bytes:
    return _tlv(0x02, v.to_bytes(max(1, (v.bit_length() + 8) // 8), "big", signed=True))


def _oid(oid: str) -> bytes:
    p = [int(x) for x in oid.strip(".").split(".")]
    out = bytes([40 * p[0] + p[1]])
    for n in p[2:]:
        chunk = [n & 0x7F]
        n >>= 7
        while n:
            chunk.insert(0, 0x80 | (n & 0x7F))
            n >>= 7
        out += bytes(chunk)
    return _tlv(0x06, out)


def _parse(data: bytes, i: int = 0):
    tag = data[i]
    n = data[i + 1]
    j = i + 2
    if n & 0x80:
        k = n & 0x7F
        n = int.from_bytes(data[j:j + k], "big")
        j += k
    return tag, data[j:j + n], j + n


def _children(data: bytes) -> list:
    out, i = [], 0
    while i < len(data):
        tag, val, i = _parse(data, i)
        out.append((tag, val))
    return out


def _decode_oid(b: bytes) -> str:
    parts = [b[0] // 40, b[0] % 40]
    n = 0
    for x in b[1:]:
        n = (n << 7) | (x & 0x7F)
        if not x & 0x80:
            parts.append(n)
            n = 0
    return ".".join(map(str, parts))


def _value(tag: int, val: bytes):
    if tag in (0x02, 0x41, 0x42, 0x43, 0x46):          # Integer, Counter32, Gauge32, TimeTicks, Counter64
        return int.from_bytes(val, "big", signed=(tag == 0x02))
    if tag == 0x04:
        return val.decode("utf-8", "replace").strip("\x00 ").strip()
    if tag == 0x06:
        return _decode_oid(val)
    return None                                            # NULL, noSuchObject, noSuchInstance, endOfMibView


def get(host: str, community: str, oids: list[str], port: int = 161, timeout: float = TIMEOUT) -> dict:
    rid = random.randint(1, 2 ** 30)
    vbs = b"".join(_tlv(0x30, _oid(o) + _tlv(0x05, b"")) for o in oids)
    pdu = _tlv(0xA0, _int(rid) + _int(0) + _int(0) + _tlv(0x30, vbs))
    msg = _tlv(0x30, _int(1) + _tlv(0x04, community.encode()) + pdu)
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.settimeout(timeout)
            s.sendto(msg, (host, port))
            data, _ = s.recvfrom(65535)
    except socket.timeout:
        raise UpsError(f"SNMP {host}:{port}: nessuna risposta (indirizzo, porta o community?)") from None
    except OSError as exc:
        raise UpsError(f"SNMP {host}:{port}: {exc.__class__.__name__}") from None
    try:
        _t, body, _ = _parse(data)
        items = _children(body)                           # versione, community, PDU
        _t, pdu_b = items[2]
        p = _children(pdu_b)
        if p[1][0] == 0x02 and _value(*p[1]):
            raise UpsError(f"SNMP: errore {_value(*p[1])} dall'UPS")
        out = {}
        for _t, vb in _children(p[3][1]):
            (_to, ob), (tv, vv) = _children(vb)
            out[_decode_oid(ob)] = _value(tv, vv)
        return out
    except (IndexError, ValueError) as exc:
        raise UpsError(f"SNMP: risposta non leggibile ({exc.__class__.__name__})") from None


# --------------------------------------------------------------------------- UPS-MIB e PowerNet (APC)
U = "1.3.6.1.2.1.33.1."
UPS_MIB = {"mfr": U + "1.1.0", "model": U + "1.2.0", "bstatus": U + "2.1.0", "minutes": U + "2.3.0", "charge": U + "2.4.0",
           "bvolt": U + "2.5.0", "temp": U + "2.7.0", "in_v": U + "3.3.1.3.1", "source": U + "4.1.0", "out_v": U + "4.4.1.2.1",
           "load": U + "4.4.1.5.1", "alarms": U + "6.1.0"}
A = "1.3.6.1.4.1.318.1.1.1."
APC = {"model": A + "1.1.1.0", "serial": A + "1.2.3.0", "status": A + "4.1.1.0", "charge": A + "2.2.1.0", "temp": A + "2.2.2.0",
       "runtime": A + "2.2.3.0", "replace": A + "2.2.4.0", "in_v": A + "3.2.1.0", "out_v": A + "4.2.1.0", "load": A + "4.2.3.0"}


def _from_ups_mib(v: dict) -> Reading:
    src, bst = v.get("source"), v.get("bstatus")
    status = ("low" if bst in (3, 4) and src == 5 else "battery" if src == 5 else "bypass" if src == 4
              else "off" if src == 2 else "online" if src in (3, 6, 7) else "unknown")
    flags = (["overload"] if (v.get("load") or 0) > 100 else []) + (["boost"] if src == 6 else []) + (["trim"] if src == 7 else [])
    return Reading(status=status, flags=flags, charge=v.get("charge"),
                   runtime_s=v["minutes"] * 60 if isinstance(v.get("minutes"), int) else None, load=v.get("load"),
                   input_v=v.get("in_v"), output_v=v.get("out_v"),
                   battery_v=v["bvolt"] / 10 if isinstance(v.get("bvolt"), int) else None, temperature=v.get("temp"),
                   manufacturer=v.get("mfr") or None, model=v.get("model") or None, raw={k: v[k] for k in v if v[k] is not None})


def _from_apc(v: dict) -> Reading:
    st = v.get("status")
    status = {2: "online", 3: "battery", 4: "online", 6: "bypass", 7: "off", 8: "off", 12: "online"}.get(st, "unknown")
    if status == "battery" and (v.get("charge") or 100) <= 10:
        status = "low"
    return Reading(status=status, flags=(["replace"] if v.get("replace") == 2 else []), charge=v.get("charge"),
                   runtime_s=v["runtime"] / 100 if isinstance(v.get("runtime"), int) else None, load=v.get("load"),
                   input_v=v.get("in_v"), output_v=v.get("out_v"), temperature=v.get("temp"), manufacturer="APC",
                   model=v.get("model") or None, serial=v.get("serial") or None, raw={k: v[k] for k in v if v[k] is not None})


def _query(host, community, port, table):
    res = get(host, community, list(table.values()), port)
    inv = {oid: k for k, oid in table.items()}
    return {inv[o]: val for o, val in res.items() if o in inv}


def read(dev: dict) -> Reading:
    host, port, com = dev["host"], int(dev.get("port") or 161), dev.get("community") or "public"
    v = _query(host, com, port, UPS_MIB)
    if v.get("source") is not None or v.get("charge") is not None:
        return _from_ups_mib(v)
    v = _query(host, com, port, APC)
    if v.get("status") is not None:
        return _from_apc(v)
    raise UpsError("l'apparecchio risponde a SNMP ma non espone dati UPS (UPS-MIB o PowerNet)")


def discover(host: str, port: int = 161, community: str = "public") -> list[dict]:
    r = read({"host": host, "port": port, "community": community})
    return [{"name": "snmp", "description": " ".join(x for x in (r.manufacturer, r.model) if x)}]
