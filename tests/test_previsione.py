"""4.4: previsione del disco pieno."""
import dataclasses
import datetime as dt

import pytest
from sqlalchemy import delete, insert

from astreo_monitor import db, forecast, migrate, models


@pytest.fixture()
def dbcfg(cfg, tmp_path):
    dbc = dataclasses.replace(cfg.database, engine="sqlite", path=str(tmp_path / "t.db"))
    c = dataclasses.replace(cfg, database=dbc)
    migrate.run(c, None, None, out=lambda *_: None)
    with db.connect(dbc) as conn:
        conn.execute(delete(models.system_metrics))
        conn.execute(delete(models.monitor_state))
    yield c
    db._engines.clear()


NOW = dt.datetime(2026, 11, 20, 12, 0)


def fill(c, days, start_pct, per_day, noise=0.0, host=1):
    rows = []
    for i in range(int(days * 24 * 12)):                      # un campione ogni 5 minuti
        t = NOW - dt.timedelta(days=days) + dt.timedelta(minutes=5 * i)
        x = (t - (NOW - dt.timedelta(days=days))).total_seconds() / 86400
        rows.append({"timestamp": t, "disk_used_pct": start_pct + per_day * x + (noise if i % 2 else -noise),
                     "host_id": host, "source": "v2"})
    with db.connect(c.database) as conn:
        conn.execute(insert(models.system_metrics), rows)


def test_disco_che_cresce(dbcfg):
    fill(dbcfg, 14, 60, 2.0, noise=0.3)                        # 60% → 88% in 14 giorni: pieno tra ~6 giorni
    with db.connect(dbcfg.database) as conn:
        fc = forecast.get(conn, 1, NOW)
    assert fc["status"] == "growing" and 5 <= fc["days_left"] <= 7 and fc["r2"] > 0.9
    assert forecast.level(fc, 14) == "WARNING" and forecast.level(fc, 3) == "OK"


def test_disco_stabile_e_pochi_dati(dbcfg):
    fill(dbcfg, 14, 40, 0.0, noise=0.5)
    fill(dbcfg, 1, 50, 5.0, host=2)                             # un giorno solo: ancora in apprendimento
    with db.connect(dbcfg.database) as conn:
        assert forecast.get(conn, 1, NOW)["status"] == "stable"
        assert forecast.get(conn, 2, NOW)["status"] == "learning"
        assert forecast.get(conn, 3, NOW)["status"] == "nodata"


def test_salto_occasionale_non_fa_scattare(dbcfg):
    # copia grande 7 giorni fa, poi fermo: la retta sui 14 giorni sale, ma non è una crescita vera
    rows = []
    for i in range(14 * 24 * 12):
        t = NOW - dt.timedelta(days=14) + dt.timedelta(minutes=5 * i)
        rows.append({"timestamp": t, "disk_used_pct": 40.0 if t < NOW - dt.timedelta(days=7) else 60.0, "host_id": 1, "source": "v2"})
    with db.connect(dbcfg.database) as conn:
        conn.execute(insert(models.system_metrics), rows)
        fc = forecast.get(conn, 1, NOW, force=True)
    assert fc["status"] == "stable" and fc.get("irregular") and forecast.level(fc, 14) == "OK"


def test_retta():
    a, b, r2 = forecast.fit([(0, 10), (1, 12), (2, 14), (3, 16)])
    assert round(a, 3) == 10 and round(b, 3) == 2 and round(r2, 3) == 1
