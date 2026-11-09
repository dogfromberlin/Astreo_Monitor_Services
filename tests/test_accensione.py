"""4.4: Wake-on-LAN."""
import base64
import dataclasses
import datetime as dt
from unittest import mock

import pytest
from sqlalchemy import delete, select

from astreo_monitor import db, hosts, migrate, models, wol


def test_mac_e_pacchetto():
    assert wol.normalize("00-1A-2b-3C-4d-5E") == wol.normalize("001a.2b3c.4d5e") == "00:1a:2b:3c:4d:5e"
    assert wol.normalize("zz:00:00:00:00:00") is None and wol.normalize("00:00:00:00:00:00") is None
    p = wol.packet("00:11:22:33:44:55")
    assert len(p) == 102 and p[:6] == b"\xff" * 6 and p[6:12] == bytes.fromhex("001122334455")
    assert wol.targets("192.168.10.42", None) == ["192.168.10.255", "255.255.255.255"]
    assert wol.targets(None, "10.0.0.255") == ["10.0.0.255", "255.255.255.255"]
    with pytest.raises(wol.WolError):
        wol.targets(None, "nonvalido")


@pytest.fixture()
def env(cfg, tmp_path):
    dbc = dataclasses.replace(cfg.database, engine="sqlite", path=str(tmp_path / "t.db"))
    c = dataclasses.replace(cfg, database=dbc)
    migrate.run(c, None, None, out=lambda *_: None)
    with db.connect(dbc) as conn:
        conn.execute(delete(models.hosts).where(models.hosts.c.id != 1))
        hid, token = hosts.create(conn, "ATLAS", "windows", "")
    yield c, hid, token
    db._engines.clear()


def test_mac_dall_agente_e_accensione(env):
    from werkzeug.security import generate_password_hash
    from astreo_monitor.web import app as webapp
    c, hid, token = env
    old = (dt.datetime.now() - dt.timedelta(hours=2)).replace(microsecond=0).isoformat()
    with db.connect(c.database) as conn:
        host = db.one(conn, select(models.hosts).where(models.hosts.c.id == hid))
        hosts.ingest(conn, host, {"agent": {"version": "4.4.0"}, "items": [
            {"type": "metrics", "time": old, "cpu_pct": 1, "mac": "AA-BB-CC-00-11-22", "ip": "192.168.10.42"}]})
        conn.execute(models.hosts.update().where(models.hosts.c.id == hid).values(last_seen=dt.datetime.now() - dt.timedelta(hours=2)))
        h = next(x for x in hosts.listing(conn, 10) if x["id"] == hid)
    assert h["net"]["mac"] == "aa:bb:cc:00:11:22" and h["status"] == "DOWN"
    web = dataclasses.replace(c.web, password_hash=generate_password_hash("p"))
    app = webapp.create_app(dataclasses.replace(c, web=web)); app.testing = True
    auth = {"Authorization": "Basic " + base64.b64encode(f"{web.username}:p".encode()).decode()}
    sent = []

    class FakeSock:
        def __init__(self, *a): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def setsockopt(self, *a): pass
        def sendto(self, data, addr): sent.append((data, addr))
    with mock.patch("astreo_monitor.schema.check", return_value=[]), mock.patch.object(wol.socket, "socket", FakeSock):
        r = app.test_client().post(f"/api/v1/hosts/{hid}/wake", json={}, headers=auth)
    assert r.status_code == 200 and r.get_json()["targets"] == ["192.168.10.255", "255.255.255.255"]
    assert len(sent) == 12 and sent[0][0] == wol.packet("aa:bb:cc:00:11:22")
    with pytest.raises(hosts.HostError):
        hosts.clean_settings({"wol_mac": "non un mac"}, hid)
    assert hosts.clean_settings({"wol_mac": "00-11-22-33-44-55", "wol_broadcast": ""}, hid) == {"wol_mac": "00:11:22:33:44:55", "wol_broadcast": None}
