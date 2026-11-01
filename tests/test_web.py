"""Dashboard: autenticazione, protezioni, endpoint pubblici, terminale (senza database)."""
from unittest import mock

import pytest

from astreo_monitor import db
from astreo_monitor.web import app as webapp

AUTH = {"Authorization": "Basic YWRtaW46cHJvdmE="}      # admin:prova


@pytest.fixture()
def client(cfg):
    with mock.patch.object(db, "connect", side_effect=db.DatabaseError("db di prova assente")):
        app = webapp.create_app(cfg)
        app.testing = True
        yield app.test_client()


def test_login_richiesto(client):
    assert client.get("/").status_code == 401
    assert client.get("/api/v1/system").status_code == 401
    assert client.get("/api/v1/system", headers={"Authorization": "Basic YWRtaW46c2JhZ2xpYXRh"}).status_code == 401


def test_pagine_pubbliche(client):
    assert client.get("/manifest.webmanifest").status_code == 200
    assert client.get("/favicon.ico").status_code == 200
    with mock.patch.object(db, "ping", return_value=False):
        h = client.get("/api/v1/health").get_json()
    assert h["status"] == "ok" and h["database"] is False


def test_dashboard_e_versione(client):
    from astreo_monitor import __version__
    r = client.get("/", headers=AUTH)
    assert r.status_code == 200 and f'data-version="{__version__}"'.encode() in r.data


def test_protezione_csrf(client):
    assert client.put("/api/v1/settings", data="x=1", headers=AUTH).status_code == 415
    r = client.put("/api/v1/settings", json={}, headers={**AUTH, "Origin": "http://altro-sito.example"})
    assert r.status_code == 403


def test_database_assente_risponde_503(client):
    assert client.get("/api/v1/services", headers=AUTH).status_code == 503


def test_terminale_solo_https(client):
    st = client.get("/api/v1/terminal/status", headers=AUTH).get_json()
    assert st["https"] is False and st["unlocked_until"] is None
    assert client.get("/api/v1/terminal/check", headers=AUTH).status_code == 401   # non sbloccato


def test_netpulse_richiede_token(client):
    assert client.get("/api/netpulse/latest").status_code == 401


# ----------------------------------------------------------------------- traduzioni
def test_catalogo_inglese_completo():
    """Ogni testo dell'interfaccia (pagine e script) deve avere la traduzione inglese, con gli stessi segnaposto."""
    import glob
    import json
    import os
    import re
    root = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "astreo_monitor")
    cat = json.load(open(os.path.join(root, "i18n", "en.json"), encoding="utf-8"))
    keys = set()
    for f in glob.glob(os.path.join(root, "web", "templates", "*.html")):
        keys |= {m.replace('\\"', '"') for m in re.findall(r'\{\{ _\("((?:[^"\\]|\\.)*)"\) \}\}', open(f, encoding="utf-8").read())}
    for f in glob.glob(os.path.join(root, "web", "static", "js", "*.js")):
        keys |= {m.replace('\\"', '"') for m in re.findall(r'(?<![\w.$])t\("((?:[^"\\]|\\.)*)"', open(f, encoding="utf-8").read())}
    missing = sorted(k for k in keys if k not in cat)          # anche i testi uguali nelle due lingue stanno nel catalogo
    assert not missing, f"testi senza traduzione inglese: {missing[:10]}"
    for k, v in cat.items():
        assert set(re.findall(r"\{\w+\}", k)) == set(re.findall(r"\{\w+\}", v)), f"segnaposto diversi: {k}"


def test_pagina_in_inglese(cfg):
    import contextlib
    with mock.patch.object(db, "connect", return_value=contextlib.nullcontext(None)), \
         mock.patch("astreo_monitor.schema.check", return_value=[]), \
         mock.patch("astreo_monitor.settings.load", return_value={"ui.language": "en"}):
        app = webapp.create_app(cfg)
        app.testing = True
        html = app.test_client().get("/", headers=AUTH).get_data(as_text=True)
    assert 'lang="en"' in html and 'aria-label="Real-time resources"' in html and '<h2>Processes</h2>' in html


# ----------------------------------------------------------------------- utente in sola lettura
VIEWER = {"Authorization": "Basic ZmFtaWdsaWE6c29sb2xldHR1cmE="}    # famiglia:sololettura


@pytest.fixture()
def viewer_client(cfg):
    import dataclasses
    from werkzeug.security import generate_password_hash
    web = dataclasses.replace(cfg.web, viewer_username="famiglia", viewer_password_hash=generate_password_hash("sololettura"))
    with mock.patch.object(db, "connect", side_effect=db.DatabaseError("db di prova assente")):
        app = webapp.create_app(dataclasses.replace(cfg, web=web))
        app.testing = True
        yield app.test_client()


def test_sola_lettura(viewer_client):
    c = viewer_client
    html = c.get("/", headers=VIEWER).get_data(as_text=True)
    assert 'data-role="viewer"' in html
    assert c.get("/api/v1/system", headers=VIEWER).status_code == 200
    for path in ("/api/v1/settings", "/api/v1/processes", "/api/v1/notify/log", "/api/v1/services/nginx.service",
                 "/api/v1/terminal/status"):
        assert c.get(path, headers=VIEWER).status_code == 403, path
    assert c.put("/api/v1/settings", json={}, headers=VIEWER).status_code == 403
    assert c.post("/api/v1/speedtest/run", json={}, headers=VIEWER).status_code == 403
    assert c.get("/api/v1/settings", headers=AUTH).status_code != 403        # l'amministratore sì
    assert 'data-role="admin"' in c.get("/", headers=AUTH).get_data(as_text=True)
