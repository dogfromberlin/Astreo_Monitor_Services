"""Controlli di altri dispositivi e servizi: ping, porta TCP, pagina web.

Ogni controllo produce un risultato grezzo (riuscito o no, latenza, dettaglio). Lo stato mostrato e
usato per gli avvisi tiene conto dei fallimenti consecutivi (`retries`): un solo ping perso non è un
guasto. Il job che li esegue è astreo_monitor.jobs.checks (ogni minuto, ciascuno col suo intervallo).
"""
from __future__ import annotations

import datetime as dt
import re
import socket
import time
from dataclasses import dataclass

import requests
import urllib3

from . import __version__

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)   # con verify_tls = false
KINDS = ("ping", "tcp", "http")


class CheckError(ValueError):
    """Definizione di un controllo non valida (messaggio per l'utente)."""


@dataclass
class Result:
    ok: bool
    latency_ms: float | None
    detail: str
    warning: str = ""            # riuscito ma con un'anomalia (es. certificato in scadenza)
    cert_days: float | None = None


def validate(c: dict) -> dict:
    """Controlla e normalizza la definizione di un controllo (dalla dashboard). Solleva ValueError."""
    out = {}
    name = str(c.get("name", "")).strip()
    if not name or len(name) > 100:
        raise CheckError("Nome mancante o troppo lungo")
    kind = str(c.get("kind", "")).strip().lower()
    if kind not in KINDS:
        raise CheckError("Tipo non valido: ping, tcp o http")
    target = str(c.get("target", "")).strip()
    if kind == "http":
        if not re.match(r"^https?://[^\s/]+", target):
            raise CheckError("Indirizzo non valido: deve iniziare con http:// o https://")
    elif not re.match(r"^[A-Za-z0-9.\-:\[\]]+$", target) or len(target) > 253:
        raise CheckError("Host non valido: nome o indirizzo IP, senza http:// né spazi")
    port = c.get("port")
    if kind == "tcp":
        try:
            port = int(port)
        except (TypeError, ValueError):
            raise CheckError("Porta mancante") from None
        if not 1 <= port <= 65535:
            raise CheckError("Porta non valida (1-65535)")
    else:
        port = None
    expect = str(c.get("expect_status") or "").strip() or None
    if expect and not re.match(r"^\d{3}(-\d{3})?(,\d{3}(-\d{3})?)*$", expect.replace(" ", "")):
        raise CheckError("Codici di risposta attesi non validi (es. 200-399 oppure 200,204)")

    def num(key, default, lo, hi):
        try:
            v = int(c.get(key, default))
        except (TypeError, ValueError):
            raise CheckError(f"{key}: numero non valido") from None
        if not lo <= v <= hi:
            raise CheckError(f"{key}: da {lo} a {hi}")
        return v

    out.update(name=name, kind=kind, target=target, port=port,
               interval_s=num("interval_s", 60, 30, 86400), timeout_s=num("timeout_s", 10, 1, 60),
               retries=num("retries", 2, 1, 10), cert_warning_days=num("cert_warning_days", 14, 0, 365),
               expect_status=expect.replace(" ", "") if expect else None,
               keyword=(str(c.get("keyword") or "").strip()[:200] or None) if kind == "http" else None,
               verify_tls=bool(c.get("verify_tls", True)), enabled=bool(c.get("enabled", True)))
    return out


def _status_ok(code: int, expect: str | None) -> bool:
    if not expect:
        return 200 <= code < 400
    for part in expect.split(","):
        lo, _, hi = part.partition("-")
        if int(lo) <= code <= int(hi or lo):
            return True
    return False


def _cert_days(host: str, port: int) -> float | None:
    from .jobs.expiry import cert_expiry          # legge il certificato presentato, anche se non valido
    try:
        end = cert_expiry(f"{host}:{port}")
    except Exception:  # noqa: BLE001
        return None
    return (end - dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)).total_seconds() / 86400


def run(c: dict) -> Result:
    kind, target, timeout = c["kind"], c["target"], int(c.get("timeout_s") or 10)
    if kind == "ping":
        from .jobs.connectivity import ping
        r = ping(target, count=3)
        if r["received"] == 0:
            return Result(False, None, f"nessuna risposta su {r['sent']}")
        return Result(True, r["rtt_avg_ms"], f"{r['received']}/{r['sent']} risposte",
                      warning=f"{r['loss_pct']:g}% di pacchetti persi" if r["loss_pct"] >= 50 else "")
    if kind == "tcp":
        t0 = time.perf_counter()
        try:
            with socket.create_connection((target, int(c["port"])), timeout=timeout):
                pass
        except ConnectionRefusedError:
            return Result(False, None, "connessione rifiutata")
        except (socket.timeout, TimeoutError):
            return Result(False, None, f"nessuna risposta entro {timeout} s")
        except socket.gaierror:
            return Result(False, None, "nome non risolto")
        except OSError as exc:
            msg = {113: "host irraggiungibile", 101: "rete irraggiungibile"}.get(exc.errno)
            return Result(False, None, msg or (exc.strerror or str(exc))[:200])
        return Result(True, round((time.perf_counter() - t0) * 1000, 1), f"porta {c['port']} aperta")
    # http
    t0 = time.perf_counter()
    try:
        r = requests.get(target, timeout=timeout, verify=bool(c.get("verify_tls", True)), allow_redirects=True,
                         headers={"User-Agent": f"astreo-monitor/{__version__}"}, stream=bool(not c.get("keyword")))
        latency = round((time.perf_counter() - t0) * 1000, 1)
    except requests.exceptions.SSLError:
        return Result(False, None, "certificato non valido")
    except (requests.exceptions.ConnectTimeout, requests.exceptions.ReadTimeout):
        return Result(False, None, f"nessuna risposta entro {timeout} s")
    except requests.exceptions.ConnectionError:
        return Result(False, None, "connessione non riuscita")
    except requests.RequestException as exc:
        return Result(False, None, str(exc)[:200])
    if not _status_ok(r.status_code, c.get("expect_status")):
        return Result(False, latency, f"HTTP {r.status_code} (attesi {c.get('expect_status') or '200-399'})")
    if c.get("keyword") and c["keyword"] not in r.text:
        return Result(False, latency, f"HTTP {r.status_code}, testo «{c['keyword']}» non trovato")
    res = Result(True, latency, f"HTTP {r.status_code}")
    if target.startswith("https://") and c.get("cert_warning_days", 14):
        from urllib.parse import urlsplit
        u = urlsplit(target)
        days = _cert_days(u.hostname, u.port or 443)
        res.cert_days = days
        if days is not None and days < int(c.get("cert_warning_days", 14)):
            res.warning = f"certificato in scadenza tra {max(0, int(days))} giorni"
    return res
