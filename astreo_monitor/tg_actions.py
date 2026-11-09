"""4.5: pulsanti sotto gli avvisi su Telegram (🔕 Silenzia 1 h, ▶ Avvia, ⚡ Accendi, 📊 Apri).

Ogni pulsante porta solo un identificativo corto (callback_data ≤ 64 byte); l'azione vera sta in monitor_state
(chiave tg:actions) per 48 ore. Il bot la esegue solo se il tocco arriva dalla chat configurata, come i comandi.
"""
from __future__ import annotations

import datetime as dt
import secrets

from sqlalchemy import select

from . import db, i18n, models, silences

KEY = "tg:actions"
KEEP_HOURS = 48


def _store(conn, action: dict, now: dt.datetime) -> str:
    acts = {k: v for k, v in (db.state_get(conn, KEY) or {}).items()
            if dt.datetime.fromisoformat(v["expires"]) > now}
    aid = secrets.token_hex(5)
    acts[aid] = {**action, "expires": (now + dt.timedelta(hours=KEEP_HOURS)).isoformat(timespec="seconds")}
    db.state_set(conn, KEY, acts)
    return aid


def buttons(conn, meta: dict | None, lang: str, now: dt.datetime | None = None) -> dict | None:
    """Tastiera "inline" per un avviso, o None se non c'è nulla di utile da proporre."""
    if not meta or not meta.get("key"):
        return None
    now = now or dt.datetime.now().replace(microsecond=0)
    _ = i18n.translator(lang)
    key, source, status = meta["key"], meta.get("source"), meta.get("status")
    host_id, unit = silences.parse_key(key)
    host = db.one(conn, select(models.hosts).where(models.hosts.c.id == host_id)) if host_id else None
    row = []
    if status not in (None, "OK"):
        if unit:
            target = {"scope": "service", "host_id": host_id, "unit": unit}
            label = f"{host['name'] if host else ''} · {unit}"
        elif host_id != 1:
            target = {"scope": "host", "host_id": host_id}
            label = host["name"] if host else str(host_id)
        else:
            target = {"scope": "source", "source": source}
            label = source or "avvisi"
        row.append({"text": "🔕 " + _("Silenzia 1 h"),
                    "callback_data": "a:" + _store(conn, {"type": "silence", "target": target, "label": label}, now)})
        if unit and host and host_id != 1 and host.get("allow_commands"):
            row.append({"text": "▶ " + _("Avvia"), "callback_data": "a:" + _store(
                conn, {"type": "command", "host_id": host_id, "unit": unit, "action": "start", "label": unit}, now)})
        if key.endswith(":online") and host and host_id != 1:
            net = db.state_get(conn, f"host:{host_id}:net") or {}
            if host.get("wol_mac") or net.get("mac"):
                row.append({"text": "⚡ " + _("Accendi"),
                            "callback_data": "a:" + _store(conn, {"type": "wake", "host_id": host_id, "label": host["name"]}, now)})
    base = (db.state_get(conn, "ui:base_url") or {}).get("url")
    if base and base.startswith("https://"):
        frag = f"#server/{host_id}" if host_id else "#panoramica"
        if source == "connectivity":
            frag = "#connessione"
        row.append({"text": "📊 " + _("Apri"), "url": f"{base}/{frag}"})
    return {"inline_keyboard": [row]} if row else None


def perform(conn, cfg, aid: str, user: str, lang: str) -> tuple[bool, str]:
    """Esegue l'azione di un pulsante. Ritorna (riuscita, testo da mostrare)."""
    _ = i18n.translator(lang)
    acts = db.state_get(conn, KEY) or {}
    a = acts.get(aid)
    if not a or dt.datetime.fromisoformat(a["expires"]) < dt.datetime.now():
        return False, _("Pulsante scaduto: usa i comandi o la dashboard")
    if a["type"] == "silence":
        try:
            it = silences.add(conn, a["target"]["scope"], host_id=a["target"].get("host_id"), source=a["target"].get("source"),
                              unit=a["target"].get("unit"), minutes=60, by=user, label=a["label"])
        except silences.SilenceError as exc:
            return False, str(exc)
        return True, "🔕 " + _("{p0}: silenziato fino alle {p1}", p0=a["label"], p1=it["until"][11:16])
    if a["type"] == "command":
        import os
        from . import commands, hosts
        key = commands.key_path(cfg.path)
        host = db.one(conn, select(models.hosts).where(models.hosts.c.id == a["host_id"]))
        if not host or not host["allow_commands"] or not os.path.exists(key) or not host["token_hash"]:
            return False, _("Comandi non consentiti per questo server")
        signed = commands.build(key, host["token_hash"][:24], a["action"], a["unit"], user)
        hosts.queue_command(conn, host, signed, a["action"], a["unit"], user, commands.parse(signed)["expires"])
        return True, "▶ " + _("{p0}: comando inviato, parte entro un minuto", p0=a["label"])
    if a["type"] == "wake":
        from . import events, wol
        host = db.one(conn, select(models.hosts).where(models.hosts.c.id == a["host_id"]))
        net = db.state_get(conn, f"host:{a['host_id']}:net") or {}
        mac = (host or {}).get("wol_mac") or net.get("mac")
        if not mac:
            return False, _("Indirizzo MAC sconosciuto")
        try:
            wol.send(mac, net.get("ip"), (host or {}).get("wol_broadcast"))
        except (wol.WolError, OSError) as exc:
            return False, str(exc)
        events.record(conn, "host", "info", "Accensione richiesta da Telegram", mac, host_id=a["host_id"])
        return True, "⚡ " + _("{p0}: pacchetto di accensione inviato", p0=a["label"])
    return False, _("Azione sconosciuta")
