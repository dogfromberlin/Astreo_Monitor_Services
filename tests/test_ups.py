"""4.6: UPS (NUT, apcupsd), job con gli avvisi di blackout e corrente tornata, API."""
import base64
import dataclasses
import socketserver
import struct
import threading
from unittest import mock

import pytest
from sqlalchemy import delete, select

from astreo_monitor import db, migrate, models, notifier, ups
from astreo_monitor.ups import apcupsd, nut, store

import fake_nut  # noqa: E402 - tests/fake_nut.py


@pytest.fixture(scope="module")
def nut_server():
    srv = fake_nut.start(34931)
    yield fake_nut
    srv.shutdown()


def test_nut_lettura_e_ricerca(nut_server):
    assert nut.discover("127.0.0.1", 34931) == [{"name": "eaton", "description": "Eaton Ellipse"}]
    r = nut.read({"host": "127.0.0.1", "port": 34931, "ups_name": "eaton"})
    assert r.status == "battery" and r.charge == 87 and r.runtime_s == 1260 and r.model == "Ellipse PRO 650"
    with pytest.raises(ups.UpsError):
        nut.read({"host": "127.0.0.1", "port": 34931, "ups_name": "altro"})
    with pytest.raises(ups.UpsError):
        nut.read({"host": "127.0.0.1", "port": 1, "ups_name": "eaton"})


def test_stati_normalizzati():
    assert nut.parse({"ups.status": "OL CHRG", "battery.charge": "100"}).status == "online"
    low = nut.parse({"ups.status": "OB LB RB"})
    assert low.status == "low" and "replace" in low.flags
    a = apcupsd.parse({"STATUS": "ONBATT", "BCHARGE": "64.0 Percent", "TIMELEFT": "12.5 Minutes", "LOADPCT": "30.0 Percent"})
    assert a.status == "battery" and a.charge == 64 and a.runtime_s == 750 and a.load == 30


def test_apcupsd_protocollo():
    class H(socketserver.BaseRequestHandler):
        def handle(self):
            self.request.recv(8)
            for line in ("STATUS   : ONLINE", "BCHARGE  : 100.0 Percent", "MODEL    : Back-UPS 700", "UPSNAME  : studio"):
                b = (line + "\n").encode()
                self.request.sendall(struct.pack(">H", len(b)) + b)
            self.request.sendall(struct.pack(">H", 0))
    srv = socketserver.TCPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.handle_request, daemon=True).start()
    r = apcupsd.read({"host": "127.0.0.1", "port": srv.server_address[1]})
    assert r.status == "online" and r.charge == 100 and r.model == "Back-UPS 700"
    srv.server_close()


@pytest.fixture()
def env(cfg, tmp_path):
    dbc = dataclasses.replace(cfg.database, engine="sqlite", path=str(tmp_path / "t.db"))
    c = dataclasses.replace(cfg, database=dbc)
    migrate.run(c, None, None, out=lambda *_: None)
    with db.connect(dbc) as conn:
        for t in (models.ups_devices, models.ups_samples, models.monitor_state, models.events):
            conn.execute(delete(t))
    yield c
    db._engines.clear()


def test_blackout_e_corrente_tornata(env, nut_server):
    from astreo_monitor.jobs import ups as job
    with db.connect(env.database) as conn:
        uid = store.create(conn, {"name": "Studio", "backend": "nut", "host": "127.0.0.1", "port": 34931, "ups_name": "eaton"})
    sent = []
    with mock.patch.object(notifier, "dispatch", side_effect=lambda conn, cfg, src, subj, body, **k: sent.append(subj) or True):
        nut_server.VARS["ups.status"] = "OL"
        job.main(env, False)
        nut_server.VARS["ups.status"] = "OB DISCHRG"
        job.main(env, False)
        assert any("batteria" in s for s in sent)                       # blackout avvisato subito
        nut_server.VARS["ups.status"] = "OL CHRG"
        job.main(env, False)
    assert any("Corrente tornata" in s or "rete" in s for s in sent[-2:])
    with db.connect(env.database) as conn:
        assert db.scalar(conn, select(models.ups_samples.c.id).limit(1)) is not None
        titles = [e["title"] for e in db.rows(conn, select(models.events.c.title).where(models.events.c.kind == "ups"))]
        last = db.state_get(conn, f"ups:{uid}:last")
    assert any(t.startswith("Blackout") for t in titles) and any(t.startswith("Corrente tornata") for t in titles)
    assert last["reading"]["status"] == "online" and "last_blackout" in last


def test_api_aggiunta_e_prova(env, nut_server):
    from werkzeug.security import generate_password_hash
    from astreo_monitor.web import app as webapp
    web = dataclasses.replace(env.web, password_hash=generate_password_hash("p"))
    app = webapp.create_app(dataclasses.replace(env, web=web)); app.testing = True
    auth = {"Authorization": "Basic " + base64.b64encode(f"{web.username}:p".encode()).decode()}
    nut_server.VARS["ups.status"] = "OL"
    with mock.patch("astreo_monitor.schema.check", return_value=[]):
        c = app.test_client()
        d = {"name": "Studio", "backend": "nut", "host": "127.0.0.1", "port": 34931, "ups_name": "eaton"}
        assert c.post("/api/v1/ups/discover", json=d, headers=auth).get_json()["ups"][0]["name"] == "eaton"
        assert c.post("/api/v1/ups/test", json=d, headers=auth).get_json()["reading"]["status"] == "online"
        assert c.post("/api/v1/ups", json={**d, "host": "non valido!"}, headers=auth).status_code == 400
        assert c.post("/api/v1/ups", json=d, headers=auth).status_code == 201
        lst = c.get("/api/v1/ups", headers=auth).get_json()["ups"]
        assert lst[0]["name"] == "Studio"
        assert c.get(f"/api/v1/ups/{lst[0]['id']}/history?range=7d", headers=auth).status_code == 200
        assert c.delete(f"/api/v1/ups/{lst[0]['id']}", json={}, headers=auth).status_code == 200


def test_snmp_ups_mib_e_ricerca(nut_server):
    """4.6: lettura SNMP (UPS-MIB) con un finto UPS e ricerca automatica su NUT e SNMP."""
    import ipaddress
    import fake_snmp
    from astreo_monitor.ups import scan, snmp
    fake_snmp.serve(16163)
    r = snmp.read({"host": "127.0.0.1", "port": 16163})
    assert r.status == "battery" and r.charge == 76 and r.runtime_s == 840 and r.model == "5PX 1500"
    with pytest.raises(ups.UpsError):
        snmp.get("127.0.0.1", "public", ["1.3.6.1.2.1.1.1.0"], 16164, timeout=0.3)
    with mock.patch.object(scan, "PORTS", (("nut", 34931),)), mock.patch.object(scan, "SNMP_PORT", 16163):
        res = scan.scan(network=ipaddress.IPv4Network("127.0.9.0/30"))
    kinds = {(f["backend"], f["host"], f.get("ups_name")) for f in res["found"]}
    assert ("nut", "127.0.0.1", "eaton") in kinds and ("snmp", "127.0.0.1", None) in kinds
