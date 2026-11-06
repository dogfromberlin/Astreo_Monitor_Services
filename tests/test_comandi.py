"""4.3: comandi avvia / ferma / riavvia dai servizi della dashboard agli agenti, firmati e con doppio consenso."""
import base64
import dataclasses
import datetime as dt
import json
import os
from unittest import mock

import pytest
from sqlalchemy import delete, select, update

from astreo_monitor import commands as C
from astreo_monitor import db, hosts, migrate, models


@pytest.fixture()
def env(cfg, tmp_path):
    dbc = dataclasses.replace(cfg.database, engine="sqlite", path=str(tmp_path / "test.db"))
    c = dataclasses.replace(cfg, database=dbc)
    migrate.run(c, None, None, out=lambda *_: None)
    key = C.key_path(c.path)
    C.ensure_key(key)
    with db.connect(dbc) as conn:
        conn.execute(delete(models.hosts).where(models.hosts.c.id != 1))
        hid, token = hosts.create(conn, "ATLAS", "windows", "Spooler,WinDefend")
    yield c, hid, token, key
    db._engines.clear()


def client(c):
    from werkzeug.security import generate_password_hash
    from astreo_monitor.web import app as webapp
    web = dataclasses.replace(c.web, password_hash=generate_password_hash("prova"))
    app = webapp.create_app(dataclasses.replace(c, web=web))
    app.testing = True
    auth = {"Authorization": "Basic " + base64.b64encode(f"{web.username}:prova".encode()).decode()}
    return app.test_client(), auth


def test_firma_e_verifica(env):
    c, hid, token, key = env
    pub = C.public_key(key)
    cmd = C.build(key, C.token_tag(token), "restart", "Spooler", "mario")
    assert C.check(cmd, pub, C.token_tag(token), ["Spooler"], []) is None
    assert C.check(dict(cmd, payload=cmd["payload"].replace("Spooler", "WinDefend")), pub, C.token_tag(token),
                   ["Spooler", "WinDefend"], []) == "firma non valida"
    assert C.check(cmd, pub, C.token_tag("agt_altro_agente_xxxxxxxxxxxx"), ["Spooler"], []) == "comando destinato a un altro agente"
    assert C.check(cmd, pub, C.token_tag(token), ["WinDefend"], []) == "servizio non tra quelli controllati"
    assert C.check(cmd, pub, C.token_tag(token), ["Spooler"], [cmd["id"]]) == "comando già eseguito"
    later = dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=C.VALID_MINUTES + 1)
    assert C.check(cmd, pub, C.token_tag(token), ["Spooler"], [], now=later) == "comando scaduto"
    other = os.path.join(os.path.dirname(key), "altra.key")
    C.ensure_key(other)                                          # firmato con un'altra chiave: rifiutato
    assert C.check(C.build(other, C.token_tag(token), "stop", "Spooler", "x"), pub, C.token_tag(token), ["Spooler"], []) == "firma non valida"


def test_comando_dalla_dashboard_all_agente_e_ritorno(env):
    c, hid, token, key = env
    web, auth = client(c)
    with mock.patch("astreo_monitor.schema.check", return_value=[]):
        url = f"/api/v1/hosts/{hid}/services/Spooler/restart"
        assert web.post(url, json={}, headers=auth).status_code == 403                    # consenso del centrale spento
        assert web.put(f"/api/v1/hosts/{hid}", json={"allow_commands": True}, headers=auth).status_code == 200
        assert web.post(f"/api/v1/hosts/{hid}/services/Altro/restart", json={}, headers=auth).status_code == 400   # non controllato
        r = web.post(url, json={}, headers=auth)
        assert r.status_code == 200
        cid = r.get_json()["id"]
        # l'agente riceve il comando firmato nella risposta al suo invio
        agent = {"Authorization": f"Bearer {token}"}
        ans = web.post("/api/v1/agents/ingest", json={"agent": {"version": "4.3.0"}, "items": []}, headers=agent).get_json()
        assert [x["id"] for x in ans["commands"]] == [cid]
        pub = web.post("/api/v1/agents/commands-key", json={}, headers=agent).get_json()
        assert C.check(ans["commands"][0], pub, C.token_tag(token), ans["services"], []) is None
        # esito
        now = dt.datetime.now().replace(microsecond=0).isoformat()
        web.post("/api/v1/agents/ingest", json={"agent": {"version": "4.3.0"}, "items": [
            {"type": "command_result", "time": now, "id": cid, "ok": True, "detail": "stato: running"}]}, headers=agent)
        st = web.get(f"/api/v1/hosts/{hid}/commands", headers=auth).get_json()
        assert st["pending"] == [] and st["results"][-1]["ok"] is True
        ans = web.post("/api/v1/agents/ingest", json={"agent": {}, "items": []}, headers=agent).get_json()
        assert ans["commands"] == []
    with db.connect(c.database) as conn:
        ev = db.rows(conn, select(models.events.c.title).where(models.events.c.host_id == hid))
    assert any("riavviato dalla dashboard" in e["title"] for e in ev)


def test_sola_lettura_non_comanda(env):
    c, hid, token, key = env
    from werkzeug.security import generate_password_hash
    from astreo_monitor.web import app as webapp
    web = dataclasses.replace(c.web, viewer_username="famiglia", viewer_password_hash=generate_password_hash("x"))
    with db.connect(c.database) as conn:
        conn.execute(update(models.hosts).where(models.hosts.c.id == hid).values(allow_commands=True))
    app = webapp.create_app(dataclasses.replace(c, web=web))
    app.testing = True
    h = {"Authorization": "Basic " + base64.b64encode(b"famiglia:x").decode()}
    with mock.patch("astreo_monitor.schema.check", return_value=[]):
        assert app.test_client().post(f"/api/v1/hosts/{hid}/services/Spooler/stop", json={}, headers=h).status_code == 403


def test_agente_linux_esegue_solo_comandi_validi(env, tmp_path):
    c, hid, token, key = env
    from astreo_monitor.agent import run as agent_run
    conf = tmp_path / "agent"
    conf.mkdir()
    (conf / "token").write_text(token)
    (conf / "commands.pub.json").write_text(json.dumps(C.public_key(key)))
    ini = conf / "agent.ini"
    ini.write_text(f"[agent]\ncentral = https://x:5443\ntoken_file = {conf/'token'}\nstate_dir = {tmp_path/'state'}\nallow_commands = true\n")
    a = agent_run.Agent(str(ini))
    a.state["services"] = ["cron.service"]
    good = C.build(key, C.token_tag(token), "restart", "cron.service", "mario")
    bad = C.build(key, C.token_tag(token), "stop", "ssh.service", "mario")        # firmato ma non controllato
    with mock.patch.object(agent_run, "execute", return_value=(True, "stato: active")) as ex, \
         mock.patch.object(agent_run.services, "statuses", return_value=[]):
        a.run_commands([good, bad, good])                                        # il secondo "good" è un doppione
    ex.assert_called_once_with("restart", "cron.service")
    items = [json.load(open(os.path.join(a.queue, f))) for f in sorted(os.listdir(a.queue))]
    res = [i for i in items if i["type"] == "command_result"]
    assert [r["ok"] for r in res] == [True, False] and "non tra quelli controllati" in res[1]["detail"]
    # senza consenso locale: rifiutato anche se firmato
    ini.write_text(ini.read_text().replace("allow_commands = true", "allow_commands = false"))
    b = agent_run.Agent(str(ini))
    b.state["services"] = ["cron.service"]
    with mock.patch.object(agent_run, "execute") as ex2, mock.patch.object(agent_run.services, "statuses", return_value=[]):
        b.run_commands([C.build(key, C.token_tag(token), "restart", "cron.service", "mario")])
    assert not ex2.called
