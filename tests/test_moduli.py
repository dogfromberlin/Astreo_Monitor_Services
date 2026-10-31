"""Moduli opzionali (Docker, Pi-hole) ed eventi."""
import datetime as dt
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from unittest import mock

import pytest

from astreo_monitor import events
from astreo_monitor.integrations import docker, pihole


# ------------------------------------------------------------------ Pi-hole v6
class FakePihole(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, obj):
        b = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        if self.headers.get("X-FTL-SID") != "sid1":
            return self._send(401, {"error": {"key": "unauthorized", "message": "Unauthorized"}})
        if self.path == "/api/stats/summary":
            return self._send(200, {"queries": {"total": 100, "blocked": 20, "percent_blocked": 20.0},
                                    "clients": {"active": 3}, "gravity": {"domains_being_blocked": 1000, "last_update": 0}})
        if self.path == "/api/dns/blocking":
            return self._send(200, {"blocking": "disabled", "timer": None})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        ok = body.get("password") == "giusta"
        self._send(200 if ok else 401, {"session": {"valid": ok, "sid": "sid1" if ok else None, "validity": 300,
                                                    "message": "ok" if ok else "password incorrect"}})

    def do_DELETE(self):
        self._send(204, {})


@pytest.fixture(scope="module")
def pihole_url():
    srv = HTTPServer(("127.0.0.1", 0), FakePihole)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}"
    srv.shutdown()


def test_pihole_rilevato_anche_senza_login(pihole_url):
    assert pihole.detect(pihole_url)[0] is True
    assert pihole.detect("http://127.0.0.1:9")[0] is False


def test_pihole_statistiche_e_stato(pihole_url):
    c = pihole.Client(pihole_url, "giusta")
    ov = c.overview()
    c.logout()
    assert ov["queries_total"] == 100 and ov["blocking"] == "disabled"
    assert pihole.evaluate(ov, None)[0] == "WARNING"        # blocco disattivato
    assert pihole.evaluate(None, "timeout")[0] == "ALERT"


def test_pihole_password_errata(pihole_url):
    with pytest.raises(pihole.PiholeError):
        pihole.Client(pihole_url, "sbagliata").overview()


# ------------------------------------------------------------------ Docker
def test_docker_assente():
    with mock.patch.object(docker.shutil, "which", return_value=None):
        assert docker.detect() == (False, "Docker non installato")


@pytest.mark.parametrize("state,policy,expected", [
    ("running", "unless-stopped", "OK"), ("exited", "unless-stopped", "ALERT"),
    ("exited", "no", "OK"), ("restarting", "always", "ALERT"),
])
def test_docker_valutazione(state, policy, expected):
    assert docker.evaluate({"state": state, "restart_policy": policy, "health": None}) == expected


# ------------------------------------------------------------------ eventi
def test_riavvii_da_last():
    out = ("reboot   system boot  6.8.0-147-generic Mon Oct 19 18:00:34 2026   still running\n"
           "reboot   system boot  6.8.0-139-generic Fri Sep 11 23:13:02 2026 - Mon Oct 19 17:59:40 2026 (37+18:46)\n")
    saved = []
    with mock.patch.object(events.subprocess, "run", return_value=mock.Mock(stdout=out)), \
         mock.patch.object(events, "record", side_effect=lambda *a, **k: saved.append((a, k)) or True):
        assert events.backfill_reboots(None) == 2
    assert saved[0][0][6] == dt.datetime(2026, 10, 19, 18, 0, 34)          # data e ora del riavvio
    assert saved[0][0][5] == "reboot:202610191800"                       # chiave anti-duplicati
