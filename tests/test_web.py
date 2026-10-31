"""Dashboard: autenticazione, protezioni, endpoint pubblici, terminale (senza database)."""
from unittest import mock

import pytest

from astreo_monitor import db
from astreo_monitor.web import app as webapp

AUTH = {"Authorization": "Basic bWFyY286cHJvdmE="}      # <utente>:prova


@pytest.fixture()
def client(cfg):
    with mock.patch.object(db, "connect", side_effect=db.DatabaseError("db di prova assente")):
        app = webapp.create_app(cfg)
        app.testing = True
        yield app.test_client()


def test_login_richiesto(client):
    assert client.get("/").status_code == 401
    assert client.get("/api/v1/system").status_code == 401
    assert client.get("/api/v1/system", headers={"Authorization": "Basic bWFyY286c2JhZ2xpYXRh"}).status_code == 401


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
