"""4.2.1: posta in uscita. Gli avvisi si scrivono in coda dentro la transazione e si inviano dopo la conferma,
senza tenere bloccato il database durante l'invio; un canale che non risponde viene ritentato più tardi."""
import dataclasses
import datetime as dt
from unittest import mock

import pytest
from sqlalchemy import delete, select, update

from astreo_monitor import db, migrate, models, notifier
from astreo_monitor import settings as S

Q = models.notification_queue


@pytest.fixture()
def dbcfg(cfg, tmp_path):
    dbc = dataclasses.replace(cfg.database, engine="sqlite", path=str(tmp_path / "test.db"))
    c = dataclasses.replace(cfg, database=dbc)
    migrate.run(c, None, None, out=lambda *_: None)
    with db.connect(dbc) as conn:
        for t in (models.notification_queue, models.notification_log, models.app_settings):
            conn.execute(delete(t))
        S.save(conn, c, {"notify.telegram.enabled": True, "notify.telegram.bot_token": "123:abc",
                         "notify.telegram.chat_id": "42", "route.connectivity.telegram": True,
                         "route.connectivity.email": False})
    yield c
    db._engines.clear()


def queue(conn):
    return db.rows(conn, select(Q.c.channel, Q.c.attempts, Q.c.sent_at, Q.c.quiet, Q.c.error))


def test_invio_dopo_la_conferma_e_fuori_dalla_transazione(dbcfg):
    sent = []

    def fake(cfg, values, channel, source, subject, body):
        # durante l'invio il messaggio è già confermato: un'altra connessione lo vede (prima non sarebbe visibile)
        with db.connect(dbcfg.database) as other:
            committed = len(queue(other))
        sent.append((channel, subject, committed))
        return True, ""
    with mock.patch.object(notifier, "_send", side_effect=fake):
        with db.connect(dbcfg.database) as conn:
            assert notifier.dispatch(conn, dbcfg, "connectivity", "Connessione assente", "testo") is True
            assert sent == []                                      # niente rete mentre la transazione è aperta
        assert sent == [("telegram", "Connessione assente", 1)]    # inviato dopo la conferma
    with db.connect(dbcfg.database) as conn:
        rows = queue(conn)
        assert len(rows) == 1 and rows[0]["sent_at"] and rows[0]["attempts"] == 1 and not rows[0]["quiet"]
        log = db.rows(conn, select(models.notification_log.c.status, models.notification_log.c.ok))
        assert log == [{"status": "inviata", "ok": True}]


def test_transazione_annullata_nessun_messaggio(dbcfg):
    with mock.patch.object(notifier, "_send", return_value=(True, "")) as send:
        with pytest.raises(RuntimeError):
            with db.connect(dbcfg.database) as conn:
                notifier.dispatch(conn, dbcfg, "connectivity", "Connessione assente", "testo")
                raise RuntimeError("il job si è interrotto")
        assert not send.called
    with db.connect(dbcfg.database) as conn:
        assert queue(conn) == []                                   # né in coda né inviato: nessun doppione possibile


def test_canale_che_non_risponde_viene_ritentato(dbcfg):
    with mock.patch.object(notifier, "_send", return_value=(False, "timeout")):
        with db.connect(dbcfg.database) as conn:
            notifier.dispatch(conn, dbcfg, "connectivity", "Connessione assente", "testo")
    with db.connect(dbcfg.database) as conn:
        r = db.rows(conn, select(Q.c.attempts, Q.c.sent_at, Q.c.due_at, Q.c.error))[0]
        assert r["attempts"] == 1 and r["sent_at"] is None and r["error"] == "timeout"
        assert db.as_datetime(r["due_at"]) > dt.datetime.now()            # si ritenta più tardi, non subito
    with mock.patch.object(notifier, "_send", return_value=(True, "")) as send:
        assert notifier.deliver(dbcfg) == 0 and not send.called            # non è ancora il momento
        with db.connect(dbcfg.database) as conn:                           # è passato il tempo di attesa
            conn.execute(update(Q).values(due_at=dt.datetime.now() - dt.timedelta(minutes=1)))
        assert notifier.deliver(dbcfg) == 1
    with db.connect(dbcfg.database) as conn:
        assert queue(conn)[0]["sent_at"] and queue(conn)[0]["attempts"] == 2
        statuses = [r["status"] for r in db.rows(conn, select(models.notification_log.c.status)
                                                  .order_by(models.notification_log.c.id))]
        assert statuses == ["in coda", "inviata"]


def test_nessun_doppio_invio_da_due_processi(dbcfg):
    with db.connect(dbcfg.database) as conn:
        conn.execute(Q.insert().values(created_at=dt.datetime.now(), due_at=dt.datetime.now() - dt.timedelta(seconds=5),
                                       source="connectivity", channel="telegram", subject="x", body="y", attempts=0, quiet=False))
    calls = []

    def slow(cfg, values, channel, source, subject, body):
        calls.append(subject)
        if len(calls) == 1:                      # mentre il primo invia, un altro processo prova a inviare lo stesso
            assert notifier.deliver(dbcfg) == 0
        return True, ""
    with mock.patch.object(notifier, "_send", side_effect=slow):
        assert notifier.deliver(dbcfg) == 1
    assert calls == ["x"]


def test_fascia_di_silenzio_resta_separata(dbcfg):
    with db.connect(dbcfg.database) as conn:
        S.save(conn, dbcfg, {"quiet.enabled": True, "quiet.start": "00:00", "quiet.end": "23:59", "quiet.deliver_at": "23:59"})
    with mock.patch.object(notifier, "_send", return_value=(True, "")) as send:
        with db.connect(dbcfg.database) as conn:
            notifier.dispatch(conn, dbcfg, "connectivity", "Connessione assente", "testo")
        assert notifier.deliver(dbcfg) == 0 and not send.called            # trattenuto: non è posta da inviare subito
    with db.connect(dbcfg.database) as conn:
        assert queue(conn)[0]["quiet"] is True or queue(conn)[0]["quiet"] == 1


def test_transazione_lunga_dice_dove_va_il_tempo(dbcfg, caplog):
    """4.2.1: il registro distingue l'attesa del database dal lavoro lento fatto con la transazione aperta."""
    import logging
    import time
    with mock.patch.object(db, "SLOW_TRANSACTION_S", 0.2), caplog.at_level(logging.WARNING, logger="db"):
        with db.connect(dbcfg.database) as conn:
            conn.exec_driver_sql("select 1")
            time.sleep(0.3)                       # lavoro "lento" fuori dal database, a transazione aperta
    msg = next(r.getMessage() for r in caplog.records if "Transazione lunga" in r.getMessage())
    assert "1 istruzioni" in msg and "fuori dal database 0.3 s" in msg


def test_aggiornamento_sospende_i_job():
    """4.2.1: update.sh ferma i timer dei job prima di toccare codice e database e li riattiva alla fine."""
    import os
    text = open(os.path.join(os.path.dirname(__file__), "..", "update.sh"), encoding="utf-8").read()
    assert text.index("systemctl stop $PAUSED") < text.index('m "== 1. Codice"')
    assert "trap cleanup EXIT" in text and "resume_timers" in text.split("cleanup()")[1].splitlines()[0]
