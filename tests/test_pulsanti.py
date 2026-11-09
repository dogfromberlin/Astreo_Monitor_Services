"""4.5: pulsanti sotto gli avvisi su Telegram."""
import dataclasses
from unittest import mock

import pytest
from sqlalchemy import delete, update

from astreo_monitor import db, hosts, migrate, models, notifier, silences, tg_actions
from astreo_monitor import settings as S


@pytest.fixture()
def env(cfg, tmp_path):
    dbc = dataclasses.replace(cfg.database, engine="sqlite", path=str(tmp_path / "t.db"))
    c = dataclasses.replace(cfg, database=dbc)
    migrate.run(c, None, None, out=lambda *_: None)
    with db.connect(dbc) as conn:
        conn.execute(delete(models.hosts).where(models.hosts.c.id != 1))
        for t in (models.monitor_state, models.notification_queue, models.notification_log):
            conn.execute(delete(t))
        hid, _tok = hosts.create(conn, "ATLAS", "windows", "Spooler")
        conn.execute(update(models.hosts).where(models.hosts.c.id == hid).values(allow_commands=True))
        db.state_set(conn, f"host:{hid}:net", {"mac": "aa:bb:cc:00:11:22", "ip": "192.168.10.42"})
        db.state_set(conn, "ui:base_url", {"url": "https://astreo.example:5443"})
        S.save(conn, c, {"notify.telegram.enabled": True, "notify.telegram.bot_token": "1:x", "notify.telegram.chat_id": "7",
                         "route.services.telegram": True, "route.services.email": False})
    yield c, hid
    db._engines.clear()


def test_pulsanti_per_servizio_fermo_e_server_spento(env):
    c, hid = env
    with db.connect(c.database) as conn:
        kb = tg_actions.buttons(conn, {"key": f"alert:host:{hid}:service:Spooler", "source": "services", "status": "ALERT"}, "it")
        texts = [b["text"] for b in kb["inline_keyboard"][0]]
        assert texts[0].startswith("🔕") and any("Avvia" in x for x in texts) and texts[-1].startswith("📊")
        assert kb["inline_keyboard"][0][-1]["url"] == f"https://astreo.example:5443/#server/{hid}"
        assert all(len(b.get("callback_data", "")) <= 64 for b in kb["inline_keyboard"][0])
        kb2 = tg_actions.buttons(conn, {"key": f"alert:host:{hid}:online", "source": "hosts", "status": "DOWN"}, "it")
        assert any("Accendi" in b["text"] for b in kb2["inline_keyboard"][0])
        ok_kb = tg_actions.buttons(conn, {"key": f"alert:host:{hid}:online", "source": "hosts", "status": "OK"}, "it")
        assert [b["text"][:1] for b in ok_kb["inline_keyboard"][0]] == ["📊"]          # rientro: solo "Apri"
        # tocco su "Silenzia 1 h"
        aid = kb["inline_keyboard"][0][0]["callback_data"][2:]
        ok, text = tg_actions.perform(conn, c, aid, "telegram (mario)", "it")
        assert ok and "silenziato fino alle" in text
        s = silences.active(conn)[0]
        assert s["scope"] == "service" and s["unit"] == "Spooler" and s["host_id"] == hid
        assert tg_actions.perform(conn, c, "inesistente", "x", "it")[0] is False


def test_avviso_telegram_con_i_pulsanti(env):
    c, hid = env
    sent = []
    with mock.patch.object(notifier, "send_telegram", side_effect=lambda *a: sent.append(a) or (True, "")):
        with db.connect(c.database) as conn:
            st = notifier.AlertState(conn, f"host:{hid}:service:Spooler")
            st.evaluate("OK", S.Policy("escalation", True, 0, 0, "services"))
            st.save()
            st = notifier.AlertState(conn, f"host:{hid}:service:Spooler")
            notify, _r, _p = st.evaluate("ALERT", S.Policy("escalation", True, 0, 0, "services"))
            assert notify
            notifier.dispatch(conn, c, "services", "[ATLAS] Servizio Spooler fermo", "fermo")
            st.save()
    assert len(sent) == 1 and sent[0][4] and "inline_keyboard" in sent[0][4]
