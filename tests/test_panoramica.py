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
        from astreo_monitor import settings as _s
        _s.save(conn, c, {"backup.no_backup_dismissed": True})    # l'avviso "nessun backup" ha il suo test
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
        assert ui_prefs.load(conn, "mario") == {"theme": "system", "layout": {}}
        ui_prefs.save(conn, "mario", {"theme": "dark"})
        assert ui_prefs.load(conn, "mario")["theme"] == "dark"
        assert ui_prefs.load(conn, "famiglia")["theme"] == "system"            # ogni utente la sua
        ui_prefs.save(conn, "x" * 200, {"theme": "light"})                       # nomi lunghi: chiave entro 64 caratteri
        assert ui_prefs.load(conn, "x" * 200)["theme"] == "light"


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


def test_servizio_tolto_sparisce_subito(dbcfg):
    """4.1: un servizio tolto da un server collegato sparisce subito, senza aspettare il prossimo invio dell'agente."""
    from sqlalchemy import update
    from astreo_monitor import hosts
    now = dt.datetime.now().replace(microsecond=0)
    with db.connect(dbcfg.database) as conn:
        conn.execute(insert(models.hosts).values(name="ATLAS", kind="windows", enabled=True, sort_order=1, created_at=now,
                                                 last_seen=now, services="WinDefend,Spooler"))
        db.state_set(conn, "host:2:services", {"time": now.isoformat(), "services": [
            {"unit": "WinDefend", "label": "Defender", "up": False, "state": "stopped"},
            {"unit": "Spooler", "label": "Stampa", "up": True, "state": "running"}]})
    assert {x["key"] for x in build(dbcfg)["todo"]} >= {"service:2:WinDefend"}
    with db.connect(dbcfg.database) as conn:
        conn.execute(update(models.hosts).where(models.hosts.c.id == 2).values(services="Spooler"))
        # anche prima della pulizia, la lettura mostra solo i servizi ancora configurati
        atlas = next(h for h in hosts.listing(conn, 10) if h["id"] == 2)
        assert [s["unit"] for s in atlas["services_state"]["services"]] == ["Spooler"]
        hosts.prune_services(conn, 2)
        assert [s["unit"] for s in db.state_get(conn, "host:2:services")["services"]] == ["Spooler"]
    d = build(dbcfg)
    assert not any(x["key"].startswith("service:2:") for x in d["todo"])
    assert d["services"]["down"] == []


def test_disposizione_delle_card(dbcfg):
    """4.1: Personalizza salva ordine e card nascoste per sezione; niente sezioni o nomi arbitrari."""
    good = {"layout": {"ov-kpis": {"order": ["backup", "servers"], "hidden": ["connection"]}, "srv-detail": {"order": ["history"]}}}
    v = ui_prefs.validate(good)
    assert v["layout"]["ov-kpis"] == {"order": ["backup", "servers"], "hidden": ["connection"]}
    assert v["layout"]["srv-detail"] == {"order": ["history"], "hidden": []}
    for bad in ({"layout": {"altro": {"order": []}}}, {"layout": {"ov-kpis": {"order": ["<script>"]}}},
                {"layout": {"ov-kpis": {"order": ["a"] * 61}}}, {"layout": {"ov-kpis": {"ordine": []}}}, {"layout": []}):
        with pytest.raises(ValueError):
            ui_prefs.validate(bad)
    with db.connect(dbcfg.database) as conn:
        ui_prefs.save(conn, "mario", {"theme": "dark"})
        ui_prefs.save(conn, "mario", v)
        p = ui_prefs.load(conn, "mario")
        assert p["theme"] == "dark" and p["layout"]["ov-kpis"]["hidden"] == ["connection"]   # il tema resta


def test_indice_della_guida_per_la_ricerca():
    from astreo_monitor import help as help_mod
    for lang in ("it", "en"):
        refs = {e["ref"]: e for e in help_mod.index(lang)}
        assert "dashboard#da-controllare" in refs and "dashboard#personalizza" in refs and "dashboard#ricerca" in refs
        assert all(e["title"] for e in refs.values())


def _policy(delay, recovery=True, mode="escalation", reminder=0):
    from astreo_monitor import settings
    return settings.Policy(mode, recovery, reminder, delay)


def test_avvisa_dopo_x_minuti(dbcfg):
    """4.2: con un'attesa, un'interruzione più breve non manda né l'avviso né il rientro."""
    from astreo_monitor import notifier
    t0 = dt.datetime(2026, 11, 5, 10, 0)

    def at(minute, status, delay=3):
        class Fake(dt.datetime):
            @classmethod
            def now(cls, tz=None):
                return t0 + dt.timedelta(minutes=minute)
        import types
        clock = types.SimpleNamespace(datetime=Fake, timedelta=dt.timedelta)
        with mock.patch.object(notifier, "dt", clock), db.connect(dbcfg.database) as conn:
            st = notifier.AlertState(conn, "connectivity")
            out = st.evaluate(status, _policy(delay))
            if out[0]:
                st.mark_notified()
            st.save()
            return out[0], out[1]

    at(0, "OK")
    assert at(1, "DOWN") == (False, None)            # caduta di un minuto…
    assert at(2, "OK") == (False, None)              # …e rientro: nessun messaggio
    assert at(10, "DOWN") == (False, None)           # nuova caduta, ancora in attesa
    assert at(12, "DOWN") == (False, None)
    assert at(13, "DOWN") == (True, "peggioramento")  # 3 minuti di fila: parte l'avviso
    assert at(14, "DOWN") == (False, None)           # una sola volta
    assert at(15, "OK") == (True, "rientro")         # e il rientro, perché l'avviso era partito


def test_senza_attesa_come_prima(dbcfg):
    from astreo_monitor import notifier
    with db.connect(dbcfg.database) as conn:
        st = notifier.AlertState(conn, "disk")
        assert st.evaluate("OK", _policy(0))[0] is False
        assert st.evaluate("WARNING", _policy(0)) [:2] == (True, "peggioramento")
        assert st.evaluate("OK", _policy(0))[:2] == (True, "rientro")


def test_impostazioni_per_server(dbcfg):
    from astreo_monitor import hosts
    assert hosts.clean_settings({"disk_warning": "70", "disk_alert": "", "notify_offline": False, "offline_minutes": "30"}, 2) == \
        {"disk_warning": 70.0, "disk_alert": None, "notify_offline": False, "offline_minutes": 30}
    assert "notify_offline" not in hosts.clean_settings({"notify_offline": False}, 1)          # non per il centrale
    for bad in ({"disk_warning": 95, "disk_alert": 90}, {"temp_alert": 500}, {"offline_minutes": 1}, {"disk_warning": "x"}):
        with pytest.raises(hosts.HostError):
            hosts.clean_settings(bad, 2)
    lim = hosts.limits({"disk_warning": 70}, dbcfg)
    assert lim["disk_warning"] == 70 and lim["disk_alert"] == dbcfg.metrics.disk_alert
    # server spento volutamente: informazione, non allarme
    now = dt.datetime.now().replace(microsecond=0)
    with db.connect(dbcfg.database) as conn:
        conn.execute(insert(models.hosts).values(name="PC", kind="windows", enabled=True, sort_order=1, created_at=now,
                                                 last_seen=now - dt.timedelta(hours=3), notify_offline=False, disk_warning=70))
    d = build(dbcfg)
    pc = next(x for x in d["todo"] if x["key"] == "host:2")
    assert pc["severity"] == "info" and d["status"]["level"] == "ok"


def test_avvisi_cpu_e_memoria_spenti_di_serie(dbcfg):
    """4.2: gli avvisi di CPU e memoria esistono ma sono spenti; attivati, compaiono in Da controllare."""
    from astreo_monitor import hosts, settings
    from sqlalchemy import update
    with db.connect(dbcfg.database) as conn:
        values = settings.load(conn, dbcfg)
        assert values["load.alerts_enabled"] is False
        assert values["alert.cpu.delay_minutes"] == 15 and values["alert.memory.delay_minutes"] == 10
        assert hosts.limits({}, dbcfg, values)["cpu_warning"] == 90
        conn.execute(update(models.hosts).where(models.hosts.c.id == 1).values(cpu_warning=10, cpu_alert=20))
    busy = {**SNAP, "cpu_pct": 50.0}
    with mock.patch.object(overview.system, "snapshot", return_value=busy), \
         mock.patch.object(overview.sensors, "read", return_value=[]), \
         mock.patch.object(overview.services, "statuses", return_value=[]), db.connect(dbcfg.database) as conn:
        assert not any(x["key"].startswith("cpu:") for x in overview.build(conn, dbcfg, "it", 10)["todo"])
        settings.save(conn, dbcfg, {"load.alerts_enabled": True})
        d = overview.build(conn, dbcfg, "it", 10)
    cpu = next(x for x in d["todo"] if x["key"] == "cpu:1")
    assert cpu["severity"] == "alert" and d["hosts"][0]["limits"]["cpu_alert"] == 20


def test_salute_e_docker_dagli_agenti(dbcfg):
    """4.2: l'agente invia dischi, aggiornamenti e container; il centrale li mostra in Da controllare."""
    from astreo_monitor import hosts
    now = dt.datetime.now().replace(microsecond=0).isoformat()
    with db.connect(dbcfg.database) as conn:
        hid, _token = hosts.create(conn, "NAS", "linux", "")
        host = next(h for h in db.rows(conn, models.hosts.select()) if h["id"] == hid)
        r = hosts.ingest(conn, host, {"agent": {"version": "4.2.0", "kind": "linux"}, "items": [
            {"type": "metrics", "time": now, "cpu_pct": 5, "mem_used_pct": 20, "disk_used_pct": 30},
            {"type": "health", "time": now, "smart_available": True,
             "disks": [{"device": "sda", "model": "WD Red", "passed": True, "pending": 8, "temperature": 41},
                       {"device": "disk1", "model": "Samsung", "os_health": "Warning"}],
             "updates": {"total": 12, "security": ["openssl"], "security_count": 1, "reboot": {"required": True}}},
            {"type": "containers", "time": now, "containers": [
                {"name": "web", "image": "nginx", "state": "exited", "status": "Exited (1)", "restart_policy": "always"},
                {"name": "db", "image": "postgres", "state": "running", "status": "Up 2 days", "restart_policy": "always"}]}]})
        assert r["accepted"] == 3 and not r["rejected"]
        h = next(x for x in hosts.listing(conn, 10) if x["id"] == hid)
        assert h["health"]["disks"][0]["pending"] == 8 and h["health"]["updates"]["security_count"] == 1
        assert len(h["containers"]["containers"]) == 2
    keys = {x["key"]: x["severity"] for x in build(dbcfg)["todo"]}
    assert keys[f"smart:{hid}:sda"] == "alert" and keys[f"smart:{hid}:disk1"] == "warn"
    assert keys[f"docker:{hid}:web"] == "alert" and f"docker:{hid}:db" not in keys
    assert keys[f"updates:{hid}"] == "info" and keys[f"reboot:{hid}"] == "info"


def test_agenti_vecchi_senza_salute(dbcfg):
    """Un agente 4.0/4.1 non invia salute né container: nessun errore, nessuna voce nuova."""
    from astreo_monitor import hosts
    now = dt.datetime.now().replace(microsecond=0).isoformat()
    with db.connect(dbcfg.database) as conn:
        hid, _t = hosts.create(conn, "OLD", "windows", "")
        host = next(h for h in db.rows(conn, models.hosts.select()) if h["id"] == hid)
        hosts.ingest(conn, host, {"agent": {"version": "4.0.2"}, "items": [{"type": "metrics", "time": now, "cpu_pct": 1}]})
        h = next(x for x in hosts.listing(conn, 10) if x["id"] == hid)
        assert h["health"] is None and h["containers"] is None
    assert not any(x["key"].startswith(("smart:", "docker:")) for x in build(dbcfg)["todo"])


def test_job_server_collegati_con_salute(dbcfg):
    """Il job degli avvisi dei server collegati valuta dischi, aggiornamenti e container senza errori."""
    from astreo_monitor import hosts, notifier
    from astreo_monitor.jobs import hosts as job
    now = dt.datetime.now().replace(microsecond=0).isoformat()
    with db.connect(dbcfg.database) as conn:
        hid, _t = hosts.create(conn, "NAS", "linux", "")
        host = next(h for h in db.rows(conn, models.hosts.select()) if h["id"] == hid)
        hosts.ingest(conn, host, {"agent": {"version": "4.2.0"}, "items": [
            {"type": "metrics", "time": now, "cpu_pct": 99, "mem_used_pct": 20},
            {"type": "health", "time": now, "disks": [{"device": "sda", "passed": False}], "updates": {"total": 0}},
            {"type": "containers", "time": now, "containers": [{"name": "web", "state": "restarting", "restart_policy": "always"}]}]})
    with mock.patch.object(notifier, "dispatch", return_value=True) as sent:
        assert job.main(dbcfg, False) == 0
    subjects = " | ".join(c.args[3] for c in sent.call_args_list)
    assert "Disco sda" in subjects and "Container web" in subjects and "CPU" not in subjects   # CPU: avvisi spenti



def test_avviso_nessun_backup(dbcfg):
    """4.2: senza copie fuori dal server c'è l'avviso; con una destinazione aspetta il primo backup riuscito."""
    from astreo_monitor import settings
    with db.connect(dbcfg.database) as conn:
        settings.save(conn, dbcfg, {"backup.no_backup_dismissed": False, "backup.github_enabled": False})
        db.state_set(conn, "backup:last", {"time": dt.datetime.now().isoformat(), "status": "OK", "destinations": []})
    d = build(dbcfg)
    assert d["backup"]["warning"] == "none" and any(x["key"] == "nobackup" and x["severity"] == "warn" for x in d["todo"])
    with db.connect(dbcfg.database) as conn:
        settings.save(conn, dbcfg, {"backup.rclone_destinations": "/mnt/nas/astreo"})
    assert build(dbcfg)["backup"]["warning"] == "pending"                       # configurato, ma nessun backup ancora
    with db.connect(dbcfg.database) as conn:
        db.state_set(conn, "backup:last", {"time": dt.datetime.now().isoformat(), "status": "OK",
                                           "destinations": [{"dest": "/mnt/nas/astreo", "ok": True}]})
    d = build(dbcfg)
    assert d["backup"]["warning"] is None and not any(x["key"] == "nobackup" for x in d["todo"])
    with db.connect(dbcfg.database) as conn:                                   # tolte tutte le destinazioni: ricompare
        settings.save(conn, dbcfg, {"backup.rclone_destinations": ""})
    assert build(dbcfg)["backup"]["warning"] == "none"
    with db.connect(dbcfg.database) as conn:                                   # "non mostrare più"
        settings.save(conn, dbcfg, {"backup.no_backup_dismissed": True})
    assert build(dbcfg)["backup"]["warning"] is None
    with pytest.raises(settings.SettingsError):
        with db.connect(dbcfg.database) as conn:
            settings.save(conn, dbcfg, {"backup.github_enabled": True, "backup.github_repo": ""})
    with pytest.raises(settings.SettingsError):
        with db.connect(dbcfg.database) as conn:
            settings.save(conn, dbcfg, {"backup.github_repo": "non valido"})


def test_tempi_del_database_misurati(dbcfg):
    """4.2: le query vengono misurate per il registro delle richieste lente."""
    st = db.start_stats("prova")
    with db.connect(dbcfg.database) as conn:
        conn.exec_driver_sql("select 1")
    assert st["query"] > 0 and st["connect"] > 0 and "connessione al database" in db.describe(st)


def test_bot_stato_di_un_server_e_riepilogo(dbcfg):
    """4.2: /stato nome-server e la sezione per server del riepilogo settimanale."""
    from astreo_monitor import hosts, telegram_bot
    from astreo_monitor.jobs import weekly_summary
    now = dt.datetime.now().replace(microsecond=0)
    with db.connect(dbcfg.database) as conn:
        hid, _t = hosts.create(conn, "ATLAS", "windows", "WinDefend")
        host = next(h for h in db.rows(conn, models.hosts.select()) if h["id"] == hid)
        hosts.ingest(conn, host, {"agent": {"version": "4.2.0"}, "items": [
            {"type": "metrics", "time": now.isoformat(), "cpu_pct": 12, "mem_used_pct": 40, "disk_used_pct": 55, "uptime_s": 7200},
            {"type": "services", "time": now.isoformat(), "services": [{"unit": "WinDefend", "label": "Defender", "up": False, "state": "stopped"}]}]})
        lines = weekly_summary.per_host(conn, now - dt.timedelta(days=7), now + dt.timedelta(minutes=1), lambda text, **k: text.format(**k))
    assert "SERVER ATLAS" in lines and any("Picchi: CPU 12%" in x for x in lines)
    bot = telegram_bot.Bot.__new__(telegram_bot.Bot)
    bot.cfg, bot.lang, sent = dbcfg, "it", []
    bot.send = lambda chat, text: sent.append(text)
    bot.handle("x", "status", "atl")                               # comando inglese, nome abbreviato
    bot.handle("x", "servizi", "ATLAS")
    bot.handle("x", "stato", "nessuno")
    assert "ATLAS" in sent[0] and "Servizi fermi: Defender" in sent[0]
    assert "Defender" in sent[1] and "Nessun server di nome" in sent[2]


def test_salvataggio_senza_connessioni_annidate(dbcfg):
    """4.2: salvare le impostazioni non deve aprire una seconda connessione mentre la prima ha righe modificate
    (su SQL Server restava bloccata fino al timeout di 30 secondi)."""
    import base64
    from werkzeug.security import generate_password_hash
    from astreo_monitor.web import app as webapp
    web = dataclasses.replace(dbcfg.web, password_hash=generate_password_hash("prova"))
    app = webapp.create_app(dataclasses.replace(dbcfg, web=web))
    app.testing = True
    auth = {"Authorization": "Basic " + base64.b64encode(f"{web.username}:prova".encode()).decode()}
    real, depth, worst = db.connect, [0], [0]

    @contextlib.contextmanager
    def counting(*a, **k):
        depth[0] += 1
        worst[0] = max(worst[0], depth[0])
        try:
            with real(*a, **k) as c:
                yield c
        finally:
            depth[0] -= 1

    with mock.patch.object(db, "connect", counting), mock.patch("astreo_monitor.schema.check", return_value=[]):
        c = app.test_client()
        for _ in range(2):
            webapp_lang_expired(app)
            worst[0] = 0
            r = c.put("/api/v1/settings", json={"alert.connectivity.delay_minutes": 3}, headers=auth)
            assert r.status_code == 200 and worst[0] == 1, worst[0]


def webapp_lang_expired(app):
    """Fa scadere la lingua in cache, come dopo 30 secondi senza richieste (il caso che bloccava)."""
    for cell in (app.view_functions["api_settings_update"].__closure__ or ()):
        v = cell.cell_contents
        if isinstance(v, dict) and "checked" in v and "lang" in v:
            v["checked"] = 0.0
