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


def test_servizi_discontinui_e_appena_aggiunti(env):
    """4.3: discontinuo fermo = a riposo senza avvisi; servizio nuovo = in attesa; nome sbagliato = inesistente."""
    c, hid, token, key = env
    from astreo_monitor.jobs import hosts as job
    from astreo_monitor import notifier
    now = dt.datetime.now().replace(microsecond=0)
    with db.connect(c.database) as conn:
        conn.execute(update(models.hosts).where(models.hosts.c.id == hid).values(
            services="Spooler,WinDefend,Nuovo,Sbagliato", services_ondemand="Spooler"))
        hosts.prune_services(conn, hid)                                   # come dopo il salvataggio dalla dashboard
        host = db.one(conn, select(models.hosts).where(models.hosts.c.id == hid))
        ans = hosts.ingest(conn, host, {"agent": {"version": "4.3.0"}, "items": [
            {"type": "metrics", "time": now.isoformat(), "cpu_pct": 1},
            {"type": "services", "time": now.isoformat(), "services": [
                {"unit": "Spooler", "label": "Spooler di stampa", "up": False, "state": "stopped"},
                {"unit": "WinDefend", "label": "Defender", "up": False, "state": "stopped"},
                {"unit": "Sbagliato", "label": "Sbagliato", "up": False, "state": "not-found"}]}]})
        assert ans["refresh"] is True                                     # servizi cambiati: l'agente rimanda subito
        h = next(x for x in hosts.listing(conn, 10) if x["id"] == hid)
    st = {s["unit"]: s["status"] for s in h["services_state"]["services"]}
    assert st == {"Spooler": "rest", "WinDefend": "down", "Nuovo": "pending", "Sbagliato": "missing"}
    assert next(s for s in h["services_state"]["services"] if s["unit"] == "WinDefend")["protected"] is True
    with mock.patch.object(notifier, "dispatch", return_value=True) as sent:
        job.main(c, False)
    subjects = " | ".join(call.args[3] for call in sent.call_args_list)
    assert "Defender" in subjects and "Spooler" not in subjects and "Nuovo" not in subjects and "Sbagliato" not in subjects
    with db.connect(c.database) as conn:                                  # la richiesta di aggiornamento è stata consumata
        host = db.one(conn, select(models.hosts).where(models.hosts.c.id == hid))
        assert "refresh" not in hosts.ingest(conn, host, {"agent": {}, "items": []})


def test_aggiornamento_agente_windows(env):
    """4.3: comando firmato "update", permesso separato, pacchetto firmato con le impronte dei file."""
    import hashlib
    import re
    from astreo_monitor import __version__
    c, hid, token, key = env
    ps1 = open(os.path.join(os.path.dirname(__file__), "..", "agent", "windows", "astreo-agent.ps1"), encoding="utf-8").read()
    assert re.search(r"\$AgentVersion = '([^']+)'", ps1).group(1) == __version__          # versione allineata
    web, auth = client(c)
    agent = {"Authorization": f"Bearer {token}"}
    with mock.patch("astreo_monitor.schema.check", return_value=[]):
        assert web.post(f"/api/v1/hosts/{hid}/agent-update", json={}, headers=auth).status_code == 403
        assert web.post("/api/v1/agents/update-package", json={}, headers=agent).status_code == 403
        web.put(f"/api/v1/hosts/{hid}", json={"allow_update": True}, headers=auth)
        r = web.post(f"/api/v1/hosts/{hid}/agent-update", json={}, headers=auth)
        assert r.status_code == 200 and r.get_json()["version"] == __version__
        # basta il permesso di aggiornamento: i comandi ai servizi restano spenti
        ans = web.post("/api/v1/agents/ingest", json={"agent": {"version": "4.2.0"}, "items": []}, headers=agent).get_json()
        assert web.post(f"/api/v1/hosts/{hid}/services/Spooler/restart", json={}, headers=auth).status_code == 403
        pub = C.public_key(key)
        cmd = ans["commands"][0]
        assert C.check(cmd, pub, C.token_tag(token), [], [], allow_update=False).startswith("aggiornamento non permesso")
        assert C.check(cmd, pub, C.token_tag(token), [], [], allow_update=True) is None
        pkg = web.post("/api/v1/agents/update-package", json={}, headers=agent).get_json()
    assert C.verify(pub, pkg["payload"].encode(), pkg["sig"])
    m = json.loads(pkg["payload"])
    assert m["agent"] == C.token_tag(token) and {f["name"] for f in m["files"]} == {"astreo-agent.ps1", "AstreoTls.ps1"}
    for f in m["files"]:
        data = base64.b64decode(next(x["content"] for x in pkg["files"] if x["name"] == f["name"]))
        assert hashlib.sha256(data).hexdigest() == f["sha256"]


def test_discontinuo_scelto_alla_creazione(env):
    c, hid, token, key = env
    web, auth = client(c)
    with mock.patch("astreo_monitor.schema.check", return_value=[]):
        r = web.post("/api/v1/hosts", json={"name": "NAS", "kind": "linux", "services": "ssh.service,backup.service",
                                            "services_ondemand": ["backup.service"]}, headers=auth)
        assert r.status_code == 201
        nas = next(h for h in web.get("/api/v1/hosts", headers=auth).get_json()["hosts"] if h["name"] == "NAS")
    assert nas["services_ondemand"] == "backup.service"
    assert {s["unit"]: s["ondemand"] for s in nas["services_state"]["services"]} == {"ssh.service": False, "backup.service": True}


def test_agente_windows_non_si_ferma_per_i_comandi_esterni():
    """4.4.0.dev2: con ErrorActionPreference = Stop, un comando esterno che scrive su stderr (docker con il motore
    fermo) fermava l'agente a ogni giro senza scrivere nulla nel registro."""
    ps1 = open(os.path.join(os.path.dirname(__file__), "..", "agent", "windows", "astreo-agent.ps1"), encoding="utf-8").read()
    assert "function Invoke-Native" in ps1 and "trap {" in ps1
    import re
    assert not re.search(r"& \$docker\.Source [^\n]*2>\$null", ps1)          # niente più chiamate dirette a docker
