"""4.4: accensione di un server con Wake-on-LAN ("pacchetto magico" UDP: 6 byte 0xFF + 16 volte il MAC).

Il centrale lo invia in broadcast sulla rete di casa (porte 9 e 7), sia all'indirizzo generale 255.255.255.255 sia al
broadcast della sottorete del server (es. 192.168.10.255, ricavato dal suo ultimo indirizzo IP con maschera /24) o a
quello scelto nelle impostazioni del server.
"""
from __future__ import annotations

import ipaddress
import re
import socket

MAC_RE = re.compile(r"^([0-9A-Fa-f]{2})[:-]?([0-9A-Fa-f]{2})[:-]?([0-9A-Fa-f]{2})[:-]?([0-9A-Fa-f]{2})[:-]?([0-9A-Fa-f]{2})[:-]?([0-9A-Fa-f]{2})$")
PORTS = (9, 7)


class WolError(Exception):
    pass


def normalize(mac: str | None) -> str | None:
    """"00-11-22-AA-BB-CC" / "0011.22aa.bbcc" / "001122aabbcc" → "00:11:22:aa:bb:cc"; None se non valido."""
    m = MAC_RE.match((mac or "").strip().replace(".", ""))
    if not m:
        return None
    norm = ":".join(g.lower() for g in m.groups())
    return None if norm in ("00:00:00:00:00:00", "ff:ff:ff:ff:ff:ff") else norm


def packet(mac: str) -> bytes:
    norm = normalize(mac)
    if not norm:
        raise WolError("Indirizzo MAC non valido")
    return b"\xff" * 6 + bytes.fromhex(norm.replace(":", "")) * 16


def targets(ip: str | None, broadcast: str | None) -> list[str]:
    out = []
    if broadcast:
        try:
            out.append(str(ipaddress.IPv4Address(broadcast.strip())))
        except ValueError:
            raise WolError("Indirizzo di broadcast non valido") from None
    elif ip:
        try:
            out.append(str(ipaddress.IPv4Network(f"{ip}/24", strict=False).broadcast_address))
        except ValueError:
            pass
    out.append("255.255.255.255")
    return list(dict.fromkeys(out))


def send(mac: str, ip: str | None = None, broadcast: str | None = None) -> list[str]:
    """Invia il pacchetto 3 volte a ogni destinazione. Ritorna le destinazioni usate."""
    data = packet(mac)
    dests = targets(ip, broadcast)
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        for _ in range(3):
            for d in dests:
                for port in PORTS:
                    s.sendto(data, (d, port))
    return dests
