"""Controlli di altri dispositivi e servizi: validazione, esecuzione, regola dei fallimenti consecutivi."""
import datetime as dt
import socket
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from astreo_monitor import checks
from astreo_monitor.jobs import checks as job


class Page(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        code = 503 if self.path == "/rotto" else 200
        self.send_response(code)
        self.end_headers()
        self.wfile.write("Benvenuto nel NAS".encode())


@pytest.fixture(scope="module")
def web():
    srv = HTTPServer(("127.0.0.1", 0), Page)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv.server_port
    srv.shutdown()


@pytest.mark.parametrize("data,error", [
    ({"name": "", "kind": "ping", "target": "nas"}, "Nome"),
    ({"name": "a", "kind": "ftp", "target": "nas"}, "Tipo"),
    ({"name": "a", "kind": "tcp", "target": "nas"}, "Porta"),
    ({"name": "a", "kind": "tcp", "target": "nas", "port": 70000}, "Porta"),
    ({"name": "a", "kind": "http", "target": "nas.lan"}, "http"),
    ({"name": "a", "kind": "ping", "target": "nas; rm -rf /"}, "Host"),
    ({"name": "a", "kind": "http", "target": "http://x", "expect_status": "abc"}, "Codici"),
    ({"name": "a", "kind": "ping", "target": "nas", "interval_s": 5}, "interval_s"),
])
def test_validazione(data, error):
    with pytest.raises(checks.CheckError, match=error):
        checks.validate(data)


def test_validazione_normalizza():
    c = checks.validate({"name": " NAS ", "kind": "TCP", "target": "nas.lan", "port": "445"})
    assert c["name"] == "NAS" and c["kind"] == "tcp" and c["port"] == 445 and c["retries"] == 2 and c["keyword"] is None


def test_porta_tcp():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    s.listen()
    port = s.getsockname()[1]
    assert checks.run({"kind": "tcp", "target": "127.0.0.1", "port": port}).ok
    s.close()
    r = checks.run({"kind": "tcp", "target": "127.0.0.1", "port": port, "timeout_s": 2})
    assert not r.ok and r.detail == "connessione rifiutata"


def test_pagina_web(web):
    base = f"http://127.0.0.1:{web}"
    assert checks.run({"kind": "http", "target": base, "keyword": "NAS"}).ok
    r = checks.run({"kind": "http", "target": base, "keyword": "router"})
    assert not r.ok and "non trovato" in r.detail
    r = checks.run({"kind": "http", "target": f"{base}/rotto"})
    assert not r.ok and r.detail.startswith("HTTP 503")
    assert checks.run({"kind": "http", "target": f"{base}/rotto", "expect_status": "500-599"}).ok


def test_fallimenti_consecutivi():
    c = {"retries": 2}
    t = dt.datetime(2026, 11, 1, 10, 0)
    ok, ko = checks.Result(True, 5.0, "ok"), checks.Result(False, None, "giù")
    s1 = job.apply_result(c, ok, None, t)
    s2 = job.apply_result(c, ko, s1, t)                 # primo fallimento: resta OK
    s3 = job.apply_result(c, ko, s2, t)                 # secondo: DOWN
    s4 = job.apply_result(c, ok, s3, t)
    assert [s["status"] for s in (s1, s2, s3, s4)] == ["OK", "OK", "DOWN", "OK"]
    assert s4["fails"] == 0
    assert job.apply_result(c, checks.Result(True, 1.0, "ok", warning="certificato in scadenza tra 3 giorni"), s4, t)["status"] == "WARNING"


def test_intervallo():
    now = dt.datetime(2026, 11, 1, 10, 0)
    c = {"interval_s": 300}
    assert job.due(c, None, now)
    assert not job.due(c, {"time": (now - dt.timedelta(seconds=120)).isoformat()}, now)
    assert job.due(c, {"time": (now - dt.timedelta(seconds=290)).isoformat()}, now)
