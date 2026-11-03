"""Accesso ai dati sui tre database: SQLite sempre, PostgreSQL e SQL Server se configurati.

    ASTREO_TEST_PG="host:porta:database:utente:password:admin:password_admin"
    ASTREO_TEST_MSSQL="host:porta:database:utente:password:admin:password_admin"
"""
import dataclasses
import datetime as dt
import os
import shutil
from unittest import mock

import pytest
from sqlalchemy import delete, func, select

from astreo_monitor import backends, db, events, migrate, models, notifier, schema, services_store
from astreo_monitor import settings as S
from astreo_monitor.web import history

ENGINES = ["sqlite"] + [e for e, var in (("postgresql", "ASTREO_TEST_PG"), ("mssql", "ASTREO_TEST_MSSQL"))
                        if os.environ.get(var)]


@pytest.fixture(params=ENGINES)
def dbcfg(request, cfg, tmp_path):
    engine = request.param
    if engine == "sqlite":
        dbc = dataclasses.replace(cfg.database, engine="sqlite", path=str(tmp_path / "test.db"))
        admin = (None, None)
    else:
        host, port, name, user, pwd, auser, apwd = os.environ[{"postgresql": "ASTREO_TEST_PG", "mssql": "ASTREO_TEST_MSSQL"}[engine]].split(":")
        dbc = dataclasses.replace(cfg.database, engine=engine, host=host, port=int(port), database=name, user=user, password=pwd)
        admin = (auser, apwd)
    c = dataclasses.replace(cfg, database=dbc, backup=dataclasses.replace(cfg.backup, local_dir=str(tmp_path / "bk"),
                                                                          github_repo="", databases=[name if engine != "sqlite" else "x"]
                                                                          if engine == "mssql" else []))
    migrate.run(c, *admin, out=lambda *_: None)
    with db.connect(dbc) as conn:                       # tabelle vuote per ogni test
        for t in reversed(models.metadata.sorted_tables):
            conn.execute(delete(t).where(t.c.id != 1) if t is models.hosts else delete(t))
    yield c
    db._engines.clear()


def test_schema_completo(dbcfg):
    with db.connect(dbcfg.database) as conn:
        assert schema.check(conn) == []
        assert migrate.current_revision(conn) == migrate.head_revision()


def test_impostazioni_e_stato(dbcfg):
    with db.connect(dbcfg.database) as conn:
        v = S.save(conn, dbcfg, {"speedtest.download_warning": 250, "notify.telegram.bot_token": "123:segreto"})
        assert v["speedtest.download_warning"] == 250 and v["notify.telegram.bot_token"] == "123:segreto"
        S.save(conn, dbcfg, {"speedtest.download_warning": 300})
        assert S.load(conn, dbcfg)["speedtest.download_warning"] == 300
        db.state_set(conn, "prova", {"a": [1, 2]})
        db.state_set(conn, "prova", {"a": [3]})
        assert db.state_get(conn, "prova") == {"a": [3]}


def test_servizi(dbcfg):
    with db.connect(dbcfg.database) as conn, \
         mock.patch.object(services_store.svc, "catalog", return_value=[{"unit": "uno.service"}, {"unit": "due.service"}]):
        services_store.upsert(conn, "uno.service", label="Uno")
        services_store.upsert(conn, "due.service", notify=True)
        services_store.reorder(conn, ["due.service", "uno.service"])
        rows = services_store.all_rows(conn)
        assert [r["unit"] for r in rows] == ["due.service", "uno.service"] and rows[0]["notify"] is True


def test_storico_e_interruzioni(dbcfg):
    now = dt.datetime.now().replace(second=0, microsecond=0)
    start = now - dt.timedelta(hours=24)
    with db.connect(dbcfg.database) as conn:
        conn.execute(models.system_metrics.insert(), [
            {"timestamp": start + dt.timedelta(minutes=5 * i), "cpu_pct": float(i % 10), "load1": 0.5,
             "mem_used_pct": 30.0, "disk_used_pct": 50.0, "source": "v2"} for i in range(288)])
        conn.execute(models.system_temperature.insert(), [
            {"timestamp": start + dt.timedelta(minutes=5 * i), "adapter": "ISA", "device": "Package", "temperature": 50.0}
            for i in range(288)])
        rows = []
        for i in range(120):
            t = now - dt.timedelta(minutes=120 - i)
            down = 30 <= i < 40
            rows += [{"timestamp": t, "target": "1.1.1.1", "role": "internet", "sent": 5, "received": 0 if down else 5,
                      "loss_pct": 100.0 if down else 0.0, "rtt_avg_ms": None if down else 12.0},
                     {"timestamp": t, "target": "192.0.2.1", "role": "gateway", "sent": 5, "received": 5,
                      "loss_pct": 0.0, "rtt_avg_ms": 0.5}]
        conn.execute(models.connectivity_samples.insert(), rows)
        conn.execute(models.speedtest_results.insert().values(timestamp=now, download_mbps=600.0, upload_mbps=200.0,
                                                              latency_ms=10.0, status="OK", provider="cloudflare"))
    with db.connect(dbcfg.database) as conn:
        m = history.metrics(conn, start, now + dt.timedelta(minutes=1))
        assert m["bucket_s"] == 300 and 280 <= len(m["labels"]) <= 290 and m["mem"][0] == 30.0
        t = history.temperatures(conn, start, now + dt.timedelta(minutes=1))
        assert list(t["series"]) == ["ISA - Package"]
        c = history.connectivity(conn, now - dt.timedelta(hours=3), now + dt.timedelta(minutes=1))
        assert len(c["outages"]) == 1 and c["outages"][0]["minutes"] == 10 and c["down_minutes"] == 10
        assert set(c["series"]) == {"1.1.1.1", "192.0.2.1"}
        assert history.latest_speedtest(conn)["download_mbps"] == 600.0


def test_notifiche_coda_ed_eventi(dbcfg):
    sent = []
    fake = lambda conn, cfg, values, ch, src, subj, body: (sent.append((ch, subj, body)) or notifier._log(conn, ch, src, subj, True, "")) or (True, "")
    with db.connect(dbcfg.database) as conn, mock.patch.object(notifier, "send_channel", side_effect=fake), \
         mock.patch.object(S, "is_quiet", return_value=True):
        S.save(conn, dbcfg, {"quiet.enabled": True, "notify.email.enabled": True, "route.disk.email": True})
        assert notifier.dispatch(conn, dbcfg, "disk", "Disco: WARNING", "corpo")
        assert notifier.dispatch(conn, dbcfg, "disk", "Disco: ALERT", "corpo 2")
    with db.connect(dbcfg.database) as conn, mock.patch.object(notifier, "send_channel", side_effect=fake):
        S.save(conn, dbcfg, {"quiet.enabled": False})
        assert notifier.flush_queue(conn, dbcfg) == 2
        assert len(sent) == 1 and "2 avvisi posticipati" in sent[0][1]
        assert db.scalar(conn, select(func.count()).select_from(models.notification_queue)
                         .where(models.notification_queue.c.sent_at.is_(None))) == 0
        assert events.record(conn, "reboot", "info", "Riavvio", ref="reboot:1")
        assert not events.record(conn, "reboot", "info", "Riavvio", ref="reboot:1")
        lst = events.list_events(conn, dt.datetime.now() - dt.timedelta(hours=1), dt.datetime.now() + dt.timedelta(hours=1))
        assert [e["kind"] for e in lst].count("reboot") == 1


def test_pulizia(dbcfg):
    from astreo_monitor.jobs import maintenance
    old = dt.datetime.now() - dt.timedelta(days=400)
    with db.connect(dbcfg.database) as conn:
        conn.execute(models.system_metrics.insert(), [{"timestamp": old, "cpu_pct": 1.0, "source": "v2"},
                                                      {"timestamp": dt.datetime.now(), "cpu_pct": 1.0, "source": "v2"}])
    maintenance.main(dbcfg, dry_run=False)
    with db.connect(dbcfg.database) as conn:
        assert db.scalar(conn, select(func.count()).select_from(models.system_metrics)) == 1


def test_riepilogo(dbcfg):
    from astreo_monitor.jobs import weekly_summary
    with db.connect(dbcfg.database) as conn:
        subject, body = weekly_summary.build(conn, dt.datetime.now())
        subject_en, body_en = weekly_summary.build(conn, dt.datetime.now(), {"ui.language": "en"})
    assert "Riepilogo settimanale" in subject and "CONNESSIONE" in body
    assert "Weekly summary" in subject_en and "CONNECTION" in body_en and "CONNESSIONE" not in body_en


@pytest.mark.skipif(not shutil.which("zstd"), reason="zstd non installato")
def test_backup_e_ripristino(dbcfg):
    if dbcfg.database.engine == "mssql":
        pytest.skip("backup SQL Server: richiede la cartella condivisa con il server (provato su astreo)")
    if dbcfg.database.engine == "postgresql" and not shutil.which("pg_dump"):
        pytest.skip("pg_dump non installato")
    be = backends.get(dbcfg.database)
    with db.connect(dbcfg.database) as conn:
        conn.execute(models.system_metrics.insert().values(timestamp=dt.datetime.now(), cpu_pct=5.0, source="v2"))
    run_dir = os.path.join(dbcfg.backup.local_dir, "backup-test")
    os.makedirs(run_dir)
    name = be.databases(dbcfg.database, dbcfg.backup)[0]
    r = be.backup(dbcfg.database, dbcfg.backup, name, "test", run_dir)
    assert r["zst_bytes"] > 0 and len(r["sha256"]) == 64
    t = be.restore_test(dbcfg.database, dbcfg.backup, os.path.join(run_dir, r["file"]))
    assert t["status"] in ("OK", "WARNING"), t
    if t["status"] == "OK":
        assert t["tables"] >= len(models.metadata.tables) and t["rows"] >= 1


def test_controlli_job_e_storico(dbcfg):
    from unittest import mock as _m
    from astreo_monitor import checks as checks_mod
    from astreo_monitor.jobs import checks as checks_job
    with db.connect(dbcfg.database) as conn:
        conn.execute(models.checks.insert(), [
            {"name": "NAS", "kind": "ping", "target": "nas", "interval_s": 60, "timeout_s": 5, "retries": 1,
             "verify_tls": True, "cert_warning_days": 14, "enabled": True, "sort_order": 10, "updated_at": db.now()},
            {"name": "Spento", "kind": "tcp", "target": "x", "port": 1, "interval_s": 60, "timeout_s": 5, "retries": 1,
             "verify_tls": True, "cert_warning_days": 14, "enabled": False, "sort_order": 20, "updated_at": db.now()}])
    fake = lambda c: checks_mod.Result(c["name"] != "NAS", None, "nessuna risposta su 3")
    with _m.patch.object(checks_mod, "run", side_effect=fake), _m.patch.object(checks_job.notifier, "dispatch", return_value=True):
        assert checks_job.main(dbcfg, dry_run=False) == 0
    with db.connect(dbcfg.database) as conn:
        assert db.scalar(conn, select(func.count()).select_from(models.check_results)) == 1     # quello disattivato no
        nas_id = db.scalar(conn, select(models.checks.c.id).where(models.checks.c.name == "NAS"))
        assert db.state_get(conn, f"check:{nas_id}")["status"] == "DOWN"
        subject, body = __import__("astreo_monitor.jobs.weekly_summary", fromlist=["x"]).build(conn, dt.datetime.now() + dt.timedelta(minutes=1))
        assert "NAS: disponibilità 0.00%" in body


def test_esportazione_prometheus_e_stato(dbcfg):
    from astreo_monitor import exporter
    with db.connect(dbcfg.database) as conn:
        conn.execute(models.speedtest_results.insert().values(timestamp=dt.datetime.now(), download_mbps=600.0,
                                                              upload_mbps=200.0, latency_ms=9.0, status="OK", provider="cloudflare"))
        db.state_set(conn, "connectivity:last", {"status": "WARNING", "samples": [
            {"target": "1.1.1.1", "role": "internet", "rtt_avg_ms": 12.5, "loss_pct": 0.0}]})
        text = exporter.metrics(conn, dbcfg)
        st = exporter.status(conn, dbcfg)
    assert exporter.valid_metric_text(text), text
    assert "astreo_speedtest_download_mbps 600" in text and "astreo_connectivity_status 1" in text
    assert 'astreo_connectivity_rtt_ms{target="1.1.1.1",role="internet"} 12.5' in text
    assert st["speedtest"]["download_mbps"] == 600.0 and st["connection"] == "WARNING"


# ----------------------------------------------------------------------- 4.0: server collegati
def test_server_collegati(dbcfg):
    from unittest import mock as _m
    from astreo_monitor import hosts as H
    from astreo_monitor.jobs import hosts as hosts_job
    from astreo_monitor.web import history as hist
    now = dt.datetime.now().replace(microsecond=0)
    with db.connect(dbcfg.database) as conn:
        assert db.scalar(conn, select(models.hosts.c.kind).where(models.hosts.c.id == 1)) == "local"
        hid, token = H.create(conn, "nas", "linux", "ssh.service, cron.service")
        assert db.scalar(conn, select(models.hosts.c.token_hash).where(models.hosts.c.id == hid)) == H.token_hash(token)
        assert H.by_token(conn, token)["id"] == hid and H.by_token(conn, "agt_falso") is None
        with pytest.raises(H.HostError):
            H.create(conn, "NAS", "linux")                          # nome già usato
        host = H.by_token(conn, token)
        iso = (now - dt.timedelta(minutes=1)).isoformat()
        r = H.ingest(conn, host, {"agent": {"version": "4.0.0", "os": "Debian 12"}, "items": [
            {"type": "metrics", "time": iso, "cpu_pct": 12.5, "mem_used_pct": 40, "disk_used_pct": 50, "load1": 0.5,
             "disks": [{"mountpoint": "/", "used_pct": 50, "total_mb": 1000, "used_mb": 500, "free_mb": 500},
                       {"mountpoint": "/srv/dati", "used_pct": 91, "total_mb": 9000, "used_mb": 8190, "free_mb": 810}]},
            {"type": "temperatures", "time": iso, "sensors": [{"adapter": "coretemp", "device": "Package", "value": 55}]},
            {"type": "services", "time": iso, "services": [{"unit": "ssh.service", "label": "ssh", "up": True, "state": "active"}]},
            {"type": "metrics", "time": iso, "cpu_pct": 500},                        # fuori intervallo: scartato da solo
            {"type": "boot", "time": iso, "boot_time": (now - dt.timedelta(days=5)).isoformat()}]})
        assert r["accepted"] == 4 and len(r["rejected"]) == 1 and r["services"] == ["ssh.service", "cron.service"]
        H.ingest(conn, host, {"items": [{"type": "services", "time": now.isoformat(),
                                         "services": [{"unit": "ssh.service", "label": "ssh", "up": False, "state": "failed"}]}]})
        h = [x for x in H.listing(conn, 10) if x["id"] == hid][0]
        assert h["status"] == "OK" and h["os_info"] == "Debian 12" and h["snapshot"]["disks"][1]["mountpoint"] == "/srv/dati"
        start, end = now - dt.timedelta(hours=1), now + dt.timedelta(minutes=5)
        assert hist.metrics(conn, start, end, hid)["cpu"] == [12.5]
        assert hist.metrics(conn, start, end)["cpu"] == []              # il centrale non vede i dati dell'agente
        titles = [e["title"] for e in events.list_events(conn, now - dt.timedelta(days=6), end, host_id=hid)]
        assert "Riavvio del server" in titles and "Servizio ssh fermo" in titles
        assert not [e for e in events.list_events(conn, start, end) if e["title"] == "Servizio ssh fermo"]
    sent = []
    with _m.patch.object(hosts_job.notifier, "dispatch", side_effect=lambda c, cfg, src, subj, body, **k: sent.append((src, subj)) or True):
        hosts_job.main(dbcfg, dry_run=False)
        assert ("disk", "[nas] Disco: WARNING") in sent and ("services", "[nas] Servizio ssh fermo (failed)") in sent
        with db.connect(dbcfg.database) as conn:                       # nessun invio da 15 minuti
            conn.execute(models.hosts.update().where(models.hosts.c.id == hid).values(last_seen=now - dt.timedelta(minutes=15)))
        sent.clear()
        hosts_job.main(dbcfg, dry_run=False)
        assert sent == [("hosts", "nas: non raggiungibile")]
    with db.connect(dbcfg.database) as conn:
        assert any(e["title"] == "nas: non raggiungibile" for e in events.list_events(conn, start, end, host_id=hid))
        new = H.regenerate(conn, hid)
        assert H.by_token(conn, token) is None and H.by_token(conn, new)["id"] == hid
        H.remove(conn, hid)
        assert db.scalar(conn, select(func.count()).select_from(models.system_metrics).where(models.system_metrics.c.host_id == hid)) == 0
        assert db.state_get(conn, f"host:{hid}:snapshot") is None
        with pytest.raises(H.HostError):
            H.remove(conn, 1)
