"""4.6: ricerca automatica degli UPS sulla rete di casa: server NUT (3493), apcupsd (3551) e UPS con scheda SNMP (161).

Scansiona la sottorete /24 del centrale (dalla rotta predefinita) più il centrale stesso, con tempi brevi e in
parallelo: in genere 5-10 secondi. Per ogni server trovato elenca gli UPS che espone.
"""
from __future__ import annotations

import ipaddress
import socket
from concurrent.futures import ThreadPoolExecutor

from . import UpsError, backend

CONNECT_TIMEOUT = 0.35
WORKERS = 64
PORTS = (("nut", 3493), ("apcupsd", 3551))
SNMP_PORT = 161


def local_network() -> ipaddress.IPv4Network | None:
    """Sottorete /24 dell'indirizzo con cui il centrale esce verso Internet (nessun pacchetto inviato davvero)."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("192.0.2.1", 9))
            ip = s.getsockname()[0]
        return ipaddress.IPv4Network(f"{ip}/24", strict=False)
    except OSError:
        return None


def _tcp_open(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=CONNECT_TIMEOUT):
            return True
    except OSError:
        return False


def _probe(host: str, community: str) -> list[dict]:
    found = []
    for name, port in PORTS:
        if _tcp_open(host, port):
            try:
                for u in backend(name).discover(host, port):
                    found.append({"backend": name, "host": host, "port": port, "ups_name": u["name"] if name == "nut" else None,
                                  "description": u.get("description") or ""})
            except UpsError as exc:
                found.append({"backend": name, "host": host, "port": port, "ups_name": None, "description": "", "error": str(exc)})
    try:
        from . import snmp
        res = snmp.get(host, community, [snmp.UPS_MIB["model"], snmp.APC["model"]], SNMP_PORT, timeout=0.6)
        model = next((v for v in res.values() if v), None)
        if model:
            found.append({"backend": "snmp", "host": host, "port": SNMP_PORT, "ups_name": None, "description": str(model)})
    except UpsError:
        pass
    return found


def scan(community: str = "public", network: ipaddress.IPv4Network | None = None) -> dict:
    net = network or local_network()
    hosts = ["127.0.0.1"] + ([str(h) for h in net.hosts()] if net else [])
    out = []
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        for res in pool.map(lambda h: _probe(h, community), hosts):
            out.extend(res)
    return {"network": str(net) if net else None, "found": out}
