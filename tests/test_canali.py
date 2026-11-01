"""Nuovi canali di notifica (ntfy, Gotify, Discord, webhook) contro un server HTTP di prova."""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from astreo_monitor import notifier

RECEIVED = []


class Fake(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        RECEIVED.append({"path": self.path, "headers": dict(self.headers), "json": json.loads(body or b"{}")})
        code = 401 if self.path.startswith("/negato") else (204 if "discord" in self.path else 200)
        self.send_response(code)
        self.end_headers()
        if code == 401:
            self.wfile.write(b"token non valido")


@pytest.fixture(scope="module")
def url():
    srv = HTTPServer(("127.0.0.1", 0), Fake)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}"
    srv.shutdown()


def test_ntfy(url):
    RECEIVED.clear()
    ok, err = notifier.send_ntfy(url, "astreo-prova", "tk_segreto", "Servizio nginx fermo (failed)", "Dettaglio è qui")
    r = RECEIVED[-1]
    assert ok and err == ""
    assert r["json"]["topic"] == "astreo-prova" and r["json"]["title"] == "[Astreo] Servizio nginx fermo (failed)"
    assert r["json"]["priority"] == 4 and r["headers"]["Authorization"] == "Bearer tk_segreto"


def test_gotify(url):
    RECEIVED.clear()
    ok, _ = notifier.send_gotify(url, "AppTok", "Backup database FALLITO", "x")
    r = RECEIVED[-1]
    assert ok and r["path"] == "/message" and r["headers"]["X-Gotify-Key"] == "AppTok" and r["json"]["priority"] == 8


def test_discord(url):
    RECEIVED.clear()
    ok, _ = notifier.send_discord(f"{url}/api/webhooks/1/discord", "Prova", "y" * 3000)
    r = RECEIVED[-1]
    assert ok and r["json"]["content"].startswith("**[Astreo] Prova**") and len(r["json"]["content"]) <= 2000


def test_webhook_e_segreti_nascosti(url):
    RECEIVED.clear()
    ok, _ = notifier.send_webhook(f"{url}/hook", "s3greto", "disk", "Disco: WARNING", "corpo")
    r = RECEIVED[-1]
    assert ok and r["json"]["source"] == "disk" and r["json"]["subject"] == "Disco: WARNING" and "host" in r["json"]
    assert r["headers"]["Authorization"] == "Bearer s3greto"
    ok, err = notifier.send_webhook(f"{url}/negato?token=s3greto", "s3greto", "disk", "x", "y")
    assert not ok and "401" in err and "s3greto" not in err


def test_canali_non_configurati():
    assert notifier.send_ntfy("", "", "", "a", "b")[0] is False
    assert notifier.send_gotify("https://x", "", "a", "b")[0] is False
    assert notifier.send_discord("", "a", "b")[0] is False
    assert notifier.send_webhook("", "", "s", "a", "b")[0] is False
