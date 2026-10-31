"""Modulo Pi-hole (API v6): statistiche e stato del blocco.

L'API v6 richiede una sessione: POST /api/auth con la password (si consiglia una
"password per le app", creata in Impostazioni > Interfaccia web/API di Pi-hole),
poi l'header X-FTL-SID. Pi-hole limita le sessioni contemporanee: ogni sessione
viene riusata finché valida e chiusa (DELETE /api/auth) alla fine dei job.
"""
from __future__ import annotations

import shutil
import threading
import time

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)   # Pi-hole in https usa un certificato suo

TIMEOUT = 8


def detect(url: str) -> tuple[bool, str]:
    try:
        r = requests.get(f"{url.rstrip('/')}/api/info/version", timeout=TIMEOUT, verify=False)
        data = r.json()
        if r.ok or (isinstance(data, dict) and "error" in data):
            return True, "Pi-hole v6"
    except (requests.RequestException, ValueError):
        pass
    if shutil.which("pihole"):
        return False, f"Pi-hole installato ma l'API non risponde su {url}"
    return False, "Pi-hole non installato"


class PiholeError(Exception):
    pass


class Client:
    _lock = threading.Lock()
    _sessions: dict[tuple, tuple[str, float]] = {}       # (url, password) -> (sid, scadenza)

    def __init__(self, url: str, password: str):
        self.url = url.rstrip("/")
        self.password = password

    def _sid(self, fresh: bool = False) -> str:
        key = (self.url, self.password)
        with self._lock:
            sid, until = self._sessions.get(key, ("", 0))
            if sid and not fresh and until > time.time() + 30:
                return sid
            if not self.password:
                raise PiholeError("password per le app non impostata (Impostazioni → Moduli)")
            r = requests.post(f"{self.url}/api/auth", json={"password": self.password}, timeout=TIMEOUT, verify=False)
            data = r.json() if r.content else {}
            session = data.get("session") or {}
            if not session.get("valid"):
                msg = (data.get("error") or {}).get("message") or session.get("message") or f"HTTP {r.status_code}"
                raise PiholeError(f"accesso negato: {msg}")
            sid = session.get("sid") or ""
            self._sessions[key] = (sid, time.time() + float(session.get("validity", 300)))
            return sid

    def get(self, path: str) -> dict:
        for attempt in (0, 1):
            sid = self._sid(fresh=attempt == 1)
            r = requests.get(f"{self.url}/api/{path}", headers={"X-FTL-SID": sid} if sid else {},
                             timeout=TIMEOUT, verify=False)
            if r.status_code == 401 and attempt == 0:
                continue                                  # sessione scaduta: ne apro una nuova
            if not r.ok:
                raise PiholeError(f"/api/{path}: HTTP {r.status_code}")
            return r.json()
        raise PiholeError("sessione non valida")

    def logout(self) -> None:
        key = (self.url, self.password)
        with self._lock:
            sid, _ = self._sessions.pop(key, ("", 0))
        if sid:
            try:
                requests.delete(f"{self.url}/api/auth", headers={"X-FTL-SID": sid}, timeout=TIMEOUT, verify=False)
            except requests.RequestException:
                pass

    def overview(self) -> dict:
        s = self.get("stats/summary")
        b = self.get("dns/blocking")
        q, cl, gr = s.get("queries") or {}, s.get("clients") or {}, s.get("gravity") or {}
        return {
            "blocking": b.get("blocking"),                        # enabled | disabled | failed | unknown
            "blocking_timer": b.get("timer"),
            "queries_total": q.get("total"), "queries_blocked": q.get("blocked"),
            "percent_blocked": q.get("percent_blocked"), "unique_domains": q.get("unique_domains"),
            "forwarded": q.get("forwarded"), "cached": q.get("cached"),
            "clients_active": cl.get("active"), "clients_total": cl.get("total"),
            "domains_blocked": gr.get("domains_being_blocked"), "gravity_updated": gr.get("last_update"),
        }


def evaluate(ov: dict | None, error: str | None) -> tuple[str, str]:
    if error:
        return "ALERT", f"Pi-hole non risponde: {error}"
    if ov.get("blocking") != "enabled":
        return "WARNING", f"Blocco della pubblicità: {ov.get('blocking')}"
    return "OK", f"Blocco attivo, {ov.get('percent_blocked') or 0:.1f}% delle richieste bloccate"
