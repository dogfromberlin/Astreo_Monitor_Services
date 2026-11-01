"""Logica pura: fascia di silenzio, regole di avviso, ping, SMART, NetPulse."""
import datetime as dt
import json
import os
from unittest import mock

import pytest

from astreo_monitor import notifier
from astreo_monitor import settings as S
from astreo_monitor.collectors import smart
from astreo_monitor.jobs import connectivity
from astreo_monitor.web import netpulse_compat

HERE = os.path.dirname(__file__)


# ------------------------------------------------------------- fascia di silenzio
QUIET = {"quiet.enabled": True, "quiet.start": "23:00", "quiet.end": "07:00", "quiet.deliver_at": "08:00"}


@pytest.mark.parametrize("when,quiet,due", [
    ("2026-10-30 23:30", True, "2026-10-31 08:00"),
    ("2026-10-31 02:14", True, "2026-10-31 08:00"),
    ("2026-10-31 06:59", True, "2026-10-31 08:00"),
    ("2026-10-31 07:00", False, None),
    ("2026-10-31 07:30", False, None),
    ("2026-10-31 22:59", False, None),
])
def test_fascia_di_silenzio(when, quiet, due):
    w = dt.datetime.fromisoformat(when)
    assert S.is_quiet(QUIET, w) is quiet
    if due:
        assert S.deferred_until(QUIET, w) == dt.datetime.fromisoformat(due)


def test_fascia_disattivata():
    assert not S.is_quiet({**QUIET, "quiet.enabled": False}, dt.datetime(2026, 10, 31, 2, 0))


# ------------------------------------------------------------- regole di avviso
class State(notifier.AlertState):
    def __init__(self):  # senza DB
        self.data = {}


def run_sequence(rule, seq, start=dt.datetime(2026, 10, 30, 0, 5)):
    clock = [start]

    class FakeDT(dt.datetime):
        @classmethod
        def now(cls, tz=None):
            return clock[0]

    st, out = State(), []
    with mock.patch.object(notifier.dt, "datetime", FakeDT):
        for status, hours in seq:
            notify, reason, _ = st.evaluate(status, rule)
            if notify:
                st.mark_notified()
            out.append((status, notify, reason))
            clock[0] += dt.timedelta(hours=hours)
    return out


def test_regola_solo_se_peggiora():
    rule = S.Policy("escalation", False, 36)
    res = run_sequence(rule, [("OK", 4), ("WARNING", 4), ("WARNING", 4), ("ALERT", 4), ("WARNING", 4),
                              ("ALERT", 4), ("ALERT", 4), ("OK", 4), ("WARNING", 4), ("DOWN", 4)])
    assert [n for _, n, _ in res] == [False, True, False, True, False, True, False, False, True, True]


def test_promemoria_dopo_36_ore():
    rule = S.Policy("escalation", False, 36)
    res = run_sequence(rule, [("WARNING", 4)] * 20)
    reminders = [i for i, (_, n, r) in enumerate(res) if n and r == "promemoria"]
    assert reminders == [9, 18]          # 36 ore dopo il primo avviso, poi di nuovo dopo 36


def test_regola_a_ogni_cambio_con_rientro():
    rule = S.Policy("change", True, 0)
    res = run_sequence(rule, [("OK", 1), ("WARNING", 1), ("ALERT", 1), ("WARNING", 1), ("OK", 1)])
    assert [n for _, n, _ in res] == [False, True, True, True, True]
    assert res[-1][2] == "rientro"


# ------------------------------------------------------------- ping
PING_OK = "5 packets transmitted, 5 received, 0% packet loss, time 812ms\nrtt min/avg/max/mdev = 1.1/12.5/20.2/3.1 ms\n"
PING_KO = "5 packets transmitted, 0 received, 100% packet loss, time 812ms\n"


def fake_ping(outputs):
    def run(args, **kw):
        assert kw.get("env", {}).get("LC_ALL") == "C", "ping va eseguito in inglese (LC_ALL=C)"
        return mock.Mock(stdout=outputs[args[-1]], returncode=0)
    return run


@pytest.mark.parametrize("router,internet,expected", [
    (PING_OK, PING_OK, "OK"), (PING_OK, PING_KO, "DOWN"), (PING_KO, PING_KO, "DOWN"),
])
def test_classificazione_connessione(router, internet, expected):
    outs = {"<IP-LAN>": router, "1.1.1.1": internet, "8.8.8.8": internet}
    values = {"connectivity.loss_warning": 20, "connectivity.rtt_warning": 100}
    with mock.patch.object(connectivity.subprocess, "run", side_effect=fake_ping(outs)):
        res = [{**connectivity.ping(t), "role": r} for t, r in (("<IP-LAN>", "gateway"), ("1.1.1.1", "internet"), ("8.8.8.8", "internet"))]
    status, text = connectivity.classify(res, values)
    assert status == expected
    if expected == "DOWN":
        assert ("router" in text.lower()) or ("provider" in text.lower())


# ------------------------------------------------------------- SMART
def test_smart_sata():
    d = smart.parse(json.load(open(os.path.join(HERE, "fixtures", "smart_sata.json"))), "sda", dt.datetime.now())
    assert d["model"] == "RS512GSSD310" and d["temperature"] == 36 and d["wear_used_pct"] == 3
    assert smart.evaluate(d, 60, 80) == ("OK", [])
    assert smart.evaluate({**d, "pending": 2}, 60, 80)[0] == "ALERT"
    assert smart.evaluate({**d, "reallocated": 1}, 60, 80)[0] == "WARNING"
    assert smart.evaluate({**d, "passed": False}, 60, 80)[0] == "ALERT"


# ------------------------------------------------------------- NetPulse
def test_bucket_netpulse():
    start = dt.datetime(2026, 10, 30, 0, 0)
    rows = [{"timestamp": (start + dt.timedelta(hours=h)).isoformat(sep=" "), "upload": 200.0, "download": 600.0}
            for h in range(0, 24, 4)]
    b = netpulse_compat.bucket_series(rows, start, start + dt.timedelta(hours=24), 32)
    assert 2 <= len(b) <= 32
    assert sum(x["samples"] for x in b) == len(rows)


# ------------------------------------------------------------- traduzioni dei messaggi
def test_messaggi_python_tradotti():
    """Ogni testo dei messaggi (notifiche, bot, riepilogo, testi salvati) ha la traduzione inglese."""
    import glob
    import re
    from astreo_monitor import i18n, telegram_bot
    root = os.path.join(os.path.dirname(HERE), "astreo_monitor")
    cat = json.load(open(os.path.join(root, "i18n", "en.json"), encoding="utf-8"))
    keys = set(i18n.STORED_TEMPLATES) | {d for _i, _e, d in telegram_bot.COMMANDS}
    for f in glob.glob(os.path.join(root, "**", "*.py"), recursive=True):
        src = open(f, encoding="utf-8").read()
        for m in re.finditer(r'(?<![\w.])(?:_|tr|self\.tr|i18n\.t)\(\s*"((?:[^"\\]|\\.)*)"(?:\s*\n?\s*"((?:[^"\\]|\\.)*)")?', src):
            keys.add((m.group(1) + (m.group(2) or "")).replace('\\"', '"').replace("\\n", "\n"))
    missing = sorted(k for k in keys if k not in cat)
    assert not missing, missing[:10]


@pytest.mark.parametrize("text,expected", [
    ("Latenza media 12 ms, nessuna perdita significativa.", "Average latency 12 ms, no significant loss."),
    ("Certificato HTTPS 127.0.0.1:5443", "HTTPS certificate 127.0.0.1:5443"),
    ("Container web: exited", "Container web: exited"),
    ("3 settori riallocati", "3 reallocated sectors"),
    ("testo sconosciuto", "testo sconosciuto"),
])
def test_testi_salvati_tradotti(text, expected):
    from astreo_monitor import i18n
    assert i18n.translate_stored(text, "en") == expected
    assert i18n.translate_stored(text, "it") == text


def test_comandi_bot_in_due_lingue():
    from astreo_monitor import telegram_bot
    assert telegram_bot.ALIASES["status"] == "stato" and telegram_bot.ALIASES["checks"] == "controlli"
