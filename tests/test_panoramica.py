"""4.1: Panoramica (/api/v1/overview) e preferenze dell'interfaccia per utente (/api/v1/ui/prefs)."""
import contextlib
import dataclasses
import datetime as dt
from unittest import mock

import pytest
from sqlalchemy import delete, insert

from astreo_monitor import db, migrate, models, overview, ui_prefs

SNAP = {"hostname": "astreo", "time": "2026-11-04T10:00:00", "uptime": {"uptime_s": 90000}, "cpu_pct": 12.0,
        "memory": {"used_pct": 40.0}, "root_disk_pct": 50.0,
        "disks": [{"mountpoint": "/", "used_pct": 50.0}, {"mountpoint": "/data", "used_pct": 70.0}]}


@pytest.fixture()
def dbcfg(cfg, tmp_path):
    dbc = dataclasses.replace(cfg.database, engine="sqlite", path=str(tmp_path / "test.db"))
    c = dataclasses.replace(cfg, database=dbc)
    migrate.run(c, None, None, out=lambda *_: None)
    with db.connect(dbc) as conn:
        for t in reversed(models.metadata.sorted_tables):
            conn.execute(delete(t).where(t.c.id != 1) if t is models.hosts else delete(t))
    yield c
    db._engines.clear()


def build(c, services=(), lang="it"):
    with mock.patch.object(overview.system, "snapshot", return_value=SNAP), \
         mock.patch.object(overview.sensors, "read", return_value=[{"value": 48.0}]), \
         mock.patch.object(overview.services, "statuses", return_value=list(services)), \
         db.connect(c.database) as conn:
        return overview.build(conn, c, lang, 10)


def test_tutto_a_posto(dbcfg):
    d = build(dbcfg, [{"unit": "nginx.service", "label": "nginx", "up": True, "state": "active"}])
    assert d["status"]["level"] == "ok" and d["status"]["headline"] == "Tutto funziona"
    assert d["todo"] == [] and d["services"] == {"total": 1, "up": 1, "down": []}
    local = d["hosts"][0]
    assert local["kind"] == "local" and local["status"] == "OK" and local["temperature_max"] == 48.0
    assert d["connection"]["availability_7d"] is None and d["backup"]["status"] is None


def test_cose_da_controllare_in_ordine(dbcfg):
    now = dt.datetime.now().replace(microsecond=0)
    with db.connect(dbcfg.database) as conn:
        conn.execute(insert(models.hosts).values(name="ATLAS", kind="windows", enabled=True, sort_order=1, created_at=now,
                                                 last_seen=now - dt.timedelta(hours=2), services="WinDefend"))
        db.state_set(conn, "backup:last", {"time": now.isoformat(), "status": "ALERT", "errors": ["disco pieno"]})
        db.state_set(conn, "health:last", {"updates": {"security": ["openssl"], "reboot": {"required": False}}})
        db.state_set(conn, "connectivity:last", {"time": now.isoformat(), "status": "WARNING", "text": "Latenza media 120 ms (soglia 80 ms).",
                                                 "samples": [{"role": "internet", "rtt_avg_ms": 120.0}]})
    d = build(dbcfg, [{"unit": "pihole-FTL.service", "label": "Pi-hole", "up": False, "state": "failed"}])
    sev = [x["severity"] for x in d["todo"]]
    assert sev == sorted(sev, key=overview.SEVERITY_ORDER.get), sev          # prima gli urgenti
    keys = {x["key"] for x in d["todo"]}
    assert {"host:2", "service:1:pihole-FTL.service", "backup", "connection", "updates"} <= keys
    stop = next(x for x in d["todo"] if x["key"].startswith("service:"))
    assert stop["action"] == {"kind": "unmonitor", "host": 1, "unit": "pihole-FTL.service", "label": "Pi-hole"}
    assert d["status"]["level"] == "alert" and d["status"]["headline"].startswith("Attenzione")
    assert d["connection"]["latency_ms"] == 120.0
    assert next(h for h in d["hosts"] if h["name"] == "ATLAS")["status"] == "DOWN"


def test_panoramica_in_inglese(dbcfg):
    d = build(dbcfg, [{"unit": "x.service", "label": "x", "up": False, "state": "failed"}], lang="en")
    assert d["status"]["headline"] == "Attention · 1 thing to check"
    assert "service x stopped" in d["todo"][0]["title"]


def test_preferenze_valide_e_salvate(dbcfg):
    assert ui_prefs.validate({"theme": "light"}) == {"theme": "light"}
    for bad in ({"theme": "viola"}, {"colore": "rosso"}, {}, None, "light"):
        with pytest.raises(ValueError):
            ui_prefs.validate(bad)
    with db.connect(dbcfg.database) as conn:
        assert ui_prefs.load(conn, "mario") == {"theme": "system"}
        ui_prefs.save(conn, "mario", {"theme": "dark"})
        assert ui_prefs.load(conn, "mario") == {"theme": "dark"}
        assert ui_prefs.load(conn, "famiglia") == {"theme": "system"}            # ogni utente la sua
        ui_prefs.save(conn, "x" * 200, {"theme": "light"})                       # nomi lunghi: chiave entro 64 caratteri
        assert ui_prefs.load(conn, "x" * 200) == {"theme": "light"}


def test_preferenze_anche_in_sola_lettura(cfg):
    from werkzeug.security import generate_password_hash
    from astreo_monitor.web import app as webapp
    web = dataclasses.replace(cfg.web, viewer_username="famiglia", viewer_password_hash=generate_password_hash("sololettura"))
    viewer = {"Authorization": "Basic ZmFtaWdsaWE6c29sb2xldHR1cmE="}
    with mock.patch.object(db, "connect", return_value=contextlib.nullcontext(None)), \
         mock.patch("astreo_monitor.schema.check", return_value=[]), \
         mock.patch("astreo_monitor.settings.load", return_value={"ui.language": "it"}), \
         mock.patch.object(ui_prefs, "save", return_value={"theme": "dark"}) as save:
        app = webapp.create_app(dataclasses.replace(cfg, web=web))
        app.testing = True
        c = app.test_client()
        r = c.put("/api/v1/ui/prefs", json={"theme": "dark"}, headers=viewer)
        assert r.status_code == 200 and save.call_args[0][1] == "famiglia"
        assert c.put("/api/v1/ui/prefs", json={"theme": "viola"}, headers=viewer).status_code == 400
        assert c.put("/api/v1/settings", json={}, headers=viewer).status_code == 403          # il resto resta vietato
        html = c.get("/", headers=viewer).get_data(as_text=True)
        assert 'data-user="famiglia"' in html and 'data-view="panoramica"' in html
