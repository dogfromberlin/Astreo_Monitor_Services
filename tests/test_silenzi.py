"""4.4: silenzia per un po'. Durante un silenzio niente avvisi; alla fine, se il problema c'è ancora, l'avviso parte."""
import dataclasses
import datetime as dt
import types
from unittest import mock

import pytest
from sqlalchemy import delete

from astreo_monitor import db, migrate, models, notifier, silences
from astreo_monitor import settings as S


@pytest.fixture()
def dbcfg(cfg, tmp_path):
    dbc = dataclasses.replace(cfg.database, engine="sqlite", path=str(tmp_path / "t.db"))
    c = dataclasses.replace(cfg, database=dbc)
    migrate.run(c, None, None, out=lambda *_: None)
    with db.connect(dbc) as conn:
        conn.execute(delete(models.monitor_state))
    yield c
    db._engines.clear()


T0 = dt.datetime(2026, 11, 8, 10, 0)


def evaluate(c, key, status, minute, source="services"):
    class Fake(dt.datetime):
        @classmethod
        def now(cls, tz=None):
            return T0 + dt.timedelta(minutes=minute)
    clock = types.SimpleNamespace(datetime=Fake, timedelta=dt.timedelta)
    with mock.patch.object(notifier, "dt", clock), mock.patch.object(silences, "_now", lambda: T0 + dt.timedelta(minutes=minute)), \
         db.connect(c.database) as conn:
        st = notifier.AlertState(conn, key)
        out = st.evaluate(status, S.Policy("escalation", True, 0, 0, source))
        if out[0]:
            st.mark_notified()
        st.save()
        return out[:2]


def test_corrispondenze():
    assert silences.parse_key("alert:host:2:service:Spooler") == (2, "Spooler")
    assert silences.parse_key("alert:service:nginx.service") == (1, "nginx.service")
    assert silences.parse_key("alert:connectivity") == (1, None)


def test_silenzio_rimanda_l_avviso_alla_fine(dbcfg):
    with db.connect(dbcfg.database) as conn:
        silences.add(conn, "host", host_id=2, minutes=60, now=T0)
    evaluate(dbcfg, "host:2:service:Spooler", "OK", 0)
    assert evaluate(dbcfg, "host:2:service:Spooler", "ALERT", 5) == (False, None)      # silenziato
    assert evaluate(dbcfg, "host:2:service:Spooler", "ALERT", 30) == (False, None)
    assert evaluate(dbcfg, "host:2:service:Spooler", "ALERT", 61) == (True, "peggioramento")   # finito: parte
    assert evaluate(dbcfg, "host:2:service:Spooler", "OK", 70) == (True, "rientro")


def test_problema_risolto_durante_il_silenzio(dbcfg):
    with db.connect(dbcfg.database) as conn:
        silences.add(conn, "source", source="connectivity", minutes=30, now=T0)
    evaluate(dbcfg, "connectivity", "OK", 0, "connectivity")
    assert evaluate(dbcfg, "connectivity", "DOWN", 2, "connectivity") == (False, None)
    assert evaluate(dbcfg, "connectivity", "OK", 10, "connectivity") == (False, None)    # nessun rientro
    assert evaluate(dbcfg, "connectivity", "OK", 40, "connectivity") == (False, None)    # e niente dopo


def test_validazione_e_sostituzione(dbcfg):
    with db.connect(dbcfg.database) as conn:
        for bad in ({"scope": "x", "minutes": 10}, {"scope": "host", "minutes": 10}, {"scope": "all", "minutes": 0},
                    {"scope": "all", "minutes": 99999}):
            with pytest.raises(silences.SilenceError):
                silences.add(conn, bad.pop("scope"), **bad)
        a = silences.add(conn, "all", minutes=30)
        b = silences.add(conn, "all", minutes=60)                       # stesso oggetto: sostituito
        assert [s["id"] for s in silences.active(conn)] == [b["id"]] and a["id"] != b["id"]
        assert silences.remove(conn, b["id"]) and silences.active(conn) == []


def test_bot_durata():
    from astreo_monitor.telegram_bot import Bot
    now = dt.datetime(2026, 11, 8, 22, 30)
    assert Bot.parse_duration("30m", now) == 30 and Bot.parse_duration("2h", now) == 120 and Bot.parse_duration("1g", now) == 1440
    assert Bot.parse_duration("domattina", now) == 570 and Bot.parse_duration("ATLAS", now) is None
