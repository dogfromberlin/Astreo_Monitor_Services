"""Bot Telegram: risponde ai comandi nella chat configurata (Impostazioni > Notifiche > Telegram).

Servizio: astreo-telegram.service (python -m astreo_monitor.telegram_bot), long polling.
Sicurezza: risponde SOLO ai messaggi della chat impostata come Chat ID; da qualsiasi
altra chat i comandi vengono ignorati e registrati nel journal.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import sys
import threading
import time

import psutil
import requests

from sqlalchemy import true as sa_true, select

from . import __version__, config as config_mod, db, i18n, logging_setup, models, services_store
from . import settings as settings_mod
from .collectors import sensors, services, system, units

log = logging.getLogger("telegram")
API = "https://api.telegram.org/bot{token}/{method}"
# (comando italiano, comando inglese, descrizione): entrambi i comandi funzionano sempre;
# il menu di Telegram mostra quelli della lingua scelta nella dashboard.
COMMANDS = [
    ("stato", "status", "Riepilogo; con un nome (/stato ATLAS) il dettaglio di quel server"),
    ("connessione", "connection", "Connessione: ping, ultimo speedtest, disponibilità"),
    ("speedtest", "speedtest", "Avvia uno speedtest e mostra il risultato"),
    ("servizi", "services", "Servizi monitorati; con un nome (/servizi ATLAS) quelli di quel server"),
    ("controlli", "checks", "Dischi, aggiornamenti, scadenze, backup"),
    ("aiuto", "help", "Elenco dei comandi"),
]
ALIASES = {en: it for it, en, _d in COMMANDS}
CHECK_NAMES: dict[str, str] = {}          # id -> nome dei controlli, aggiornato a ogni comando
HOST_NAMES: dict[str, str] = {}           # id -> nome dei server collegati
ICON = {"OK": "🟢", "WARNING": "🟡", "ALERT": "🔴", "DOWN": "🔴", "UNKNOWN": "⚪"}


def alert_name(key: str, tr=lambda s, **kw: s.format(**kw)) -> str:
    """Nome leggibile di un allarme (chiave di monitor_state senza 'alert:')."""
    kind, _, rest = key.partition(":")
    if kind == "service":
        return tr("Servizio {p0}", p0=rest.removesuffix(".service"))
    if kind == "expiry":
        return tr("Token GitHub (gh)") if rest == "github-token" else tr("Certificato HTTPS {p0}", p0=rest.removeprefix("cert:"))
    if kind == "smart":
        return tr("Disco {p0}", p0=rest)
    if kind == "check":
        return CHECK_NAMES.get(rest, tr("Dispositivi e servizi"))
    if kind == "host":                                    # host:<id>:online | disk | temperature | service:<unit>
        hid, _, what = rest.partition(":")
        name = HOST_NAMES.get(hid, f"server {hid}")
        if what == "online":
            return name
        if what.startswith("service:"):
            return f"{name}: " + tr("Servizio {p0}", p0=what[8:].removesuffix(".service"))
        return f"{name}: " + tr({"disk": "Disco", "temperature": "Temperatura"}.get(what, what))
    return tr(settings_mod.SOURCES.get(kind, kind))


class Bot:
    def __init__(self, cfg):
        self.cfg = cfg
        self.offset = None
        self.token = ""
        self.chat_id = ""
        self.session = requests.Session()
        self.commands_set_for = None
        self.lang = "it"

    # ------------------------------------------------------------- API
    def call(self, method: str, timeout_s: int = 20, **params):
        r = self.session.post(API.format(token=self.token, method=method), json=params, timeout=timeout_s)
        data = r.json()
        if not data.get("ok"):
            raise RuntimeError(data.get("description", f"HTTP {r.status_code}"))
        return data["result"]

    def send(self, chat_id, text: str) -> None:
        for chunk in [text[i:i + 3800] for i in range(0, len(text), 3800)] or [""]:
            try:
                self.call("sendMessage", chat_id=chat_id, text=chunk, disable_web_page_preview=True)
            except Exception as exc:  # noqa: BLE001
                log.error("Risposta Telegram non inviata: %s", str(exc).replace(self.token, "***"))

    # ---------------------------------------------------- configurazione
    def reload(self) -> bool:
        """Rilegge token, chat e interruttore dalle impostazioni. True se il bot deve rispondere."""
        try:
            with db.connect(self.cfg.database) as conn:
                v = settings_mod.load(conn, self.cfg)
        except db.DatabaseError as exc:
            log.warning("Impostazioni non leggibili: %s", exc)
            return False
        self.token = v["notify.telegram.bot_token"]
        self.chat_id = str(v["notify.telegram.chat_id"]).strip()
        self.lang = i18n.lang_of(v)
        active = bool(v["telegram.commands"] and self.token and self.chat_id)
        if active and self.commands_set_for != (self.token, self.lang):
            try:
                self.call("setMyCommands", commands=[{"command": en if self.lang == "en" else it,
                                                      "description": i18n.t(d, self.lang)} for it, en, d in COMMANDS])
                self.commands_set_for = (self.token, self.lang)
                log.info("Menu dei comandi registrato su Telegram")
            except Exception as exc:  # noqa: BLE001
                log.warning("Menu dei comandi non registrato: %s", str(exc).replace(self.token, "***"))
        return active

    # ------------------------------------------------------------ loop
    def run(self) -> None:
        log.info("Bot Telegram di Astreo Monitor %s avviato", __version__)
        while True:
            if not self.reload():
                time.sleep(30)
                continue
            try:
                params = {"timeout": 50, "allowed_updates": ["message"]}
                if self.offset:
                    params["offset"] = self.offset
                updates = self.call("getUpdates", timeout_s=60, **params)
            except Exception as exc:  # noqa: BLE001
                log.warning("getUpdates non riuscito: %s", str(exc).replace(self.token, "***"))
                time.sleep(15)
                continue
            for u in updates:
                self.offset = u["update_id"] + 1
                msg = u.get("message") or u.get("channel_post")
                if not msg or not msg.get("text", "").startswith("/"):
                    continue
                chat = str(msg["chat"]["id"])
                parts = msg["text"].split(maxsplit=1)
                cmd = parts[0][1:].split("@")[0].lower()
                arg = parts[1].strip()[:64] if len(parts) > 1 else ""
                who = (msg.get("from") or {}).get("username") or (msg.get("from") or {}).get("first_name", "?")
                if chat != self.chat_id:
                    log.warning("Comando /%s ignorato: chat %s non autorizzata (da %s)", cmd, chat, who)
                    continue
                log.info("Comando /%s da %s", cmd, who)
                threading.Thread(target=self.handle, args=(chat, cmd, arg), daemon=True).start()

    # -------------------------------------------------------- comandi
    def tr(self, text, **kw):
        return i18n.t(text, self.lang, **kw)

    def refresh_language(self) -> None:
        """Lingua letta a ogni comando: vale subito dopo il cambio nella dashboard."""
        try:
            with db.connect(self.cfg.database) as conn:
                self.lang = i18n.lang_of(settings_mod.load(conn, self.cfg))
        except db.DatabaseError:
            pass

    def handle(self, chat, cmd: str, arg: str = "") -> None:
        cmd = ALIASES.get(cmd, cmd)
        self.refresh_language()
        try:
            if arg and cmd in ("stato", "servizi"):          # 4.2: /stato nome-server, /servizi nome-server
                self.cmd_host(chat, arg, services_only=cmd == "servizi")
                return
            handler = {"stato": self.cmd_stato, "connessione": self.cmd_connessione, "speedtest": self.cmd_speedtest,
                       "servizi": self.cmd_servizi, "controlli": self.cmd_controlli}.get(cmd, self.cmd_aiuto)
            handler(chat)
        except Exception as exc:  # noqa: BLE001
            log.exception("Errore nel comando /%s", cmd)
            self.send(chat, self.tr("Errore nel comando /{cmd}: {err}", cmd=cmd, err=exc))

    def cmd_aiuto(self, chat) -> None:
        lines = [self.tr("Comandi di Astreo Monitor:"), ""]
        for it, en, d in COMMANDS:
            main, other = (en, it) if self.lang == "en" else (it, en)
            lines.append(f"/{main} — {self.tr(d)}" + (f"  (/{other})" if other != main else ""))
        lines += ["", self.tr("Ogni comando funziona anche nell'altra lingua (tra parentesi). "
                              "La lingua delle risposte si sceglie nella dashboard (IT / EN in fondo alla pagina).")]
        self.send(chat, "\n".join(lines))

    def cmd_stato(self, chat) -> None:
        snap = system.snapshot(self.cfg.metrics.root_disk)
        temps = sensors.read()
        hot = max((t["value"] for t in temps), default=None)
        with db.connect(self.cfg.database) as conn:
            mon = services_store.monitored(conn, self.cfg)
            con = db.state_get(conn, "connectivity:last") or {}
            alerts = db.state_rows(conn, "alert:")
            CHECK_NAMES.update({str(c["id"]): c["name"] for c in db.rows(conn, select(models.checks.c.id, models.checks.c.name))})
            from . import hosts as hosts_mod
            from . import settings as _st
            host_list = hosts_mod.listing(conn, int(_st.load(conn, self.cfg)["hosts.offline_minutes"]))
            HOST_NAMES.update({str(h["id"]): h["name"] for h in host_list})
        st = services.statuses(mon)
        down = [s["label"] for s in st if not s["up"]]
        active = []
        for r in alerts:
            try:
                v = json.loads(r["value"] or "{}")
            except ValueError:
                continue
            if v.get("status") not in (None, "OK"):
                active.append(f"{ICON.get(v['status'], '•')} {alert_name(r['key'][6:], self.tr)}: {v['status']}")
        up = dt.timedelta(seconds=snap["uptime"]["uptime_s"])
        lines = [
            "🖥 " + self.tr("{host} — acceso da {g} g {h} h", host=snap["hostname"], g=up.days, h=up.seconds // 3600),
            self.tr("CPU {cpu}% · load {load} · RAM {ram}% · disco {disco}%", cpu=f"{snap['cpu_pct']:.0f}",
                    load=snap["load"]["load1"], ram=f"{snap['memory']['used_pct']:.0f}", disco=f"{snap['root_disk_pct']:.0f}")
            + (f" · {hot:.0f} °C" if hot is not None else ""),
            f"{ICON.get(con.get('status'), '⚪')} " + self.tr("Connessione: {stato} — {testo}", stato=con.get("status", "n/d"),
                                                               testo=i18n.translate_stored(con.get("text", ""), self.lang)),
            ("🟢 " + self.tr("Servizi: tutti attivi ({n})", n=len(st))) if not down
            else "🔴 " + self.tr("Servizi fermi: {elenco}", elenco=", ".join(down)),
        ]
        others = [h for h in host_list if h["kind"] != "local" and h["enabled"]]
        if others:
            icon = {"OK": "🟢", "DOWN": "🔴", "WAITING": "⚪"}
            lines += ["", self.tr("Server collegati:")] + [
                f"{icon.get(h['status'], '⚪')} {h['name']}"
                + (f" — CPU {(h['snapshot'] or {}).get('cpu_pct', 0):.0f}% · RAM {(h['snapshot'] or {}).get('mem_used_pct', 0):.0f}%"
                   if h["status"] == "OK" and h["snapshot"] else (" — " + self.tr("non raggiungibile") if h["status"] == "DOWN" else ""))
                for h in others]
        lines += ["", self.tr("Allarmi attivi:")] + active if active else ["", self.tr("Nessun allarme attivo.")]
        self.send(chat, "\n".join(lines))

    # -------------------------------------------------------- 4.2: un server per nome
    def find_host(self, name: str):
        from . import hosts as hosts_mod
        with db.connect(self.cfg.database) as conn:
            values = settings_mod.load(conn, self.cfg)
            lst = hosts_mod.listing(conn, int(values["hosts.offline_minutes"]))
        n = name.lower()
        exact = [h for h in lst if (h["name"] or "").lower() == n]
        part = exact or [h for h in lst if (h["name"] or "").lower().startswith(n)] or \
            [h for h in lst if n in (h["name"] or "").lower()]
        return part, lst

    def cmd_host(self, chat, name: str, services_only: bool = False) -> None:
        found, lst = self.find_host(name)
        if len(found) != 1:
            names = ", ".join(h["name"] for h in lst)
            self.send(chat, (self.tr("Più server corrispondono a «{p0}»: {p1}", p0=name, p1=", ".join(h["name"] for h in found)) if found
                             else self.tr("Nessun server di nome «{p0}». Server: {p1}", p0=name, p1=names)))
            return
        h = found[0]
        if h["kind"] == "local":                              # il centrale: come i comandi senza nome
            (self.cmd_servizi if services_only else self.cmd_stato)(chat)
            return
        icon = {"OK": "🟢", "DOWN": "🔴", "WAITING": "⚪", "DISABLED": "⚪"}
        svc = (h.get("services_state") or {}).get("services", [])
        if services_only:
            ico = {"up": "🟢", "down": "🔴", "rest": "⚪", "pending": "⏳", "unseen": "⚪", "missing": "🟡"}
            body = "\n".join(f"{ico.get(x.get('status') or ('up' if x['up'] else 'down'), '⚪')} {x['label']} ({x.get('state') or '–'})"
                             for x in svc) or \
                self.tr("Nessun servizio indicato per questo server (Impostazioni → Server collegati).")
            self.send(chat, self.tr("Servizi di {p0}:", p0=h["name"]) + "\n" + body)
            return
        snap = h.get("snapshot") or {}
        lines = [f"{icon.get(h['status'], '⚪')} {h['name']} — " + {
            "OK": self.tr("raggiungibile"), "DOWN": self.tr("non raggiungibile"), "WAITING": self.tr("in attesa del primo invio"),
            "DISABLED": self.tr("disattivato")}.get(h["status"], h["status"]),
            self.tr("{os} · agente {ver} · ultimo invio {quando}", os=h.get("os_info") or h["kind"], ver=h.get("agent_version") or "–",
                    quando=(h.get("last_seen") or "–")[:16].replace("T", " "))]
        if h["status"] == "OK" and snap:
            up = dt.timedelta(seconds=int(snap.get("uptime_s") or 0))
            lines.append(self.tr("CPU {cpu}% · RAM {ram}% · disco {disco}% · acceso da {g} g {o} h",
                                 cpu=f"{snap.get('cpu_pct') or 0:.0f}", ram=f"{snap.get('mem_used_pct') or 0:.0f}",
                                 disco=f"{snap.get('disk_used_pct') or 0:.0f}", g=up.days, o=up.seconds // 3600)
                         + (f" · {snap['temperature_max']:.0f} °C" if snap.get("temperature_max") is not None else ""))
            down = [x["label"] for x in svc if x.get("status", "up" if x["up"] else "down") == "down"]   # 4.3
            lines.append(("🟢 " + self.tr("Servizi: tutti attivi ({n})", n=len(svc))) if not down
                         else "🔴 " + self.tr("Servizi fermi: {elenco}", elenco=", ".join(down)))
        hl = h.get("health") or {}
        upd = hl.get("updates") or {}
        if upd.get("security_count"):
            lines.append("🟡 " + self.tr("{p0} aggiornamenti di sicurezza da installare", p0=upd["security_count"]))
        if (upd.get("reboot") or {}).get("required"):
            lines.append("🟡 " + self.tr("riavvio richiesto"))
        conts = (h.get("containers") or {}).get("containers", [])
        if conts:
            stopped = [c["name"] for c in conts if c.get("state") != "running"]
            lines.append(("🟢 " + self.tr("Container: tutti in esecuzione ({n})", n=len(conts))) if not stopped
                         else "🔴 " + self.tr("Container fermi: {elenco}", elenco=", ".join(stopped)))
        self.send(chat, "\n".join(lines))

    def cmd_connessione(self, chat) -> None:
        from .web import history
        now = dt.datetime.now()
        with db.connect(self.cfg.database) as conn:
            con = db.state_get(conn, "connectivity:last") or {}
            last = history.latest_speedtest(conn)
            day = history.connectivity(conn, now - dt.timedelta(hours=24), now)
        lines = [f"{ICON.get(con.get('status'), '⚪')} Ping: {con.get('status', 'n/d')} — "
                 + i18n.translate_stored(con.get("text", ""), self.lang)]
        for s in con.get("samples", []):
            lines.append(f"   {s['target']}: {s['received']}/{s['sent']}" + (f", {s['rtt_avg_ms']:.0f} ms" if s.get("rtt_avg_ms") else ""))
        if day.get("availability") is not None:
            lines.append(self.tr("Ultime 24 ore: disponibilità {pct}%, interruzioni {n}", pct=f"{day['availability']:.2f}",
                                 n=len(day["outages"])))
        if last:
            lines.append(self.tr("Speedtest {stato} alle {ora}", stato=last["status"], ora=last["timestamp"][11:16])
                         + f": ↓ {last['download_mbps'] or 0:.0f} ↑ {last['upload_mbps'] or 0:.0f} Mbps, {last['latency_ms'] or 0:.0f} ms")
        self.send(chat, "\n".join(lines))

    def cmd_speedtest(self, chat) -> None:
        from .web import history
        with db.connect(self.cfg.database) as conn:
            before = (history.latest_speedtest(conn) or {}).get("timestamp")
        try:
            units.control("astreo-speedtest.service", "start")
        except units.UnitControlError as exc:
            self.send(chat, self.tr("Speedtest non avviato: {err}", err=exc))
            return
        self.send(chat, "⏱ " + self.tr("Speedtest avviato, il risultato arriva tra circa un minuto…"))
        for _ in range(36):
            time.sleep(5)
            with db.connect(self.cfg.database) as conn:
                last = history.latest_speedtest(conn)
            if last and last["timestamp"] != before:
                self.send(chat, f"{ICON.get(last['status'], '•')} Speedtest {last['status']}: ↓ {last['download_mbps'] or 0:.0f} Mbps"
                                f" ↑ {last['upload_mbps'] or 0:.0f} Mbps, "
                                + self.tr("latenza {ms} ms", ms=f"{last['latency_ms'] or 0:.0f}"))
                return
        self.send(chat, self.tr("Nessun risultato dopo 3 minuti: lo speedtest potrebbe essere sospeso (Impostazioni → Speedtest)."))

    def cmd_servizi(self, chat) -> None:
        with db.connect(self.cfg.database) as conn:
            st = services.statuses(services_store.monitored(conn, self.cfg))
        self.send(chat, self.tr("Servizi monitorati:") + "\n" + "\n".join(f"{'🟢' if s['up'] else '🔴'} {s['label']} ({s['state']})" for s in st))

    def cmd_controlli(self, chat) -> None:
        with db.connect(self.cfg.database) as conn:
            health = db.state_get(conn, "health:last") or {}
            exp = db.state_get(conn, "expiry:last") or {}
            bk = db.state_get(conn, "backup:last") or {}
            rt = db.state_get(conn, "restoretest:last") or {}
            hb = db.state_get(conn, "heartbeat:last") or {}
            checks_rows = [{**c, "state": db.state_get(conn, f"check:{c['id']}")}
                           for c in db.rows(conn, select(models.checks.c.id, models.checks.c.name)
                                            .where(models.checks.c.enabled == sa_true())
                                            .order_by(models.checks.c.sort_order, models.checks.c.id))]
        lines = []
        for d in health.get("disks", []):
            lines.append(f"{ICON.get(d.get('status'), '⚪')} " + self.tr("Disco {p0}", p0=d["device"])
                         + f": {d.get('status')} — {d.get('temperature')} °C"
                         + (self.tr(", usura {p0}%", p0=d["wear_used_pct"]) if d.get("wear_used_pct") is not None else "")
                         + (f" ({'; '.join(i18n.translate_stored(r, self.lang) for r in d['reasons'])})" if d.get("reasons") else ""))
        u = health.get("updates") or {}
        if u:
            lines.append(f"{ICON.get(u.get('status'), '⚪')} " + self.tr("Aggiornamenti: {tot} in sospeso, {sic} di sicurezza",
                                                                         tot=u.get("total", 0), sic=len(u.get("security", [])))
                         + (self.tr(", riavvio richiesto") if (u.get("reboot") or {}).get("required") else ""))
        for it in exp.get("items", []):
            lines.append(f"{ICON.get(it.get('status'), '⚪')} {i18n.translate_stored(it['name'], self.lang)}: "
                         + (i18n.translate_stored(it.get("note") or "", self.lang)
                            or (self.tr("{p0} giorni", p0=int(it["days"])) if it.get("days") is not None else it.get("error", "n/d"))))
        if bk:
            lines.append(f"{ICON.get(bk.get('status'), '⚪')} Backup: " + self.tr("{p0} alle {p1}", p0=bk.get("status"),
                                                                                    p1=str(bk.get("time", ""))[:16].replace("T", " ")))
        if rt:
            lines.append(f"{ICON.get(rt.get('status'), '⚪')} " + self.tr("Verifica ripristino: {stato} il {data}",
                                                                          stato=rt.get("status"), data=str(rt.get("time", ""))[:10]))
        if checks_rows:
            for c in checks_rows:
                st = c.get("state") or {}
                lines.append(f"{ICON.get(st.get('status'), '⚪')} {c['name']}: {st.get('status', '…')}"
                             + (f" — {i18n.translate_stored(st.get('warning') or st.get('detail') or '', self.lang)}"
                                if st.get("status") != "OK" else ""))
        if hb:
            lines.append(f"{'🟢' if hb.get('ok') else '🔴'} Heartbeat: "
                         + self.tr("{p0} alle {p1}", p0=self.tr("inviato") if hb.get("ok") else self.tr("non inviato"),
                                   p1=str(hb.get("time", ""))[11:16]))
        self.send(chat, "\n".join(lines) or self.tr("Nessun dato ancora raccolto."))


def main() -> None:
    parser = argparse.ArgumentParser(prog="astreo_monitor.telegram_bot", description="Bot Telegram di Astreo Monitor")
    parser.add_argument("-c", "--config")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()
    logging_setup.setup(args.verbose)
    try:
        cfg = config_mod.load(args.config)
    except config_mod.ConfigError as exc:
        log.error("%s", exc)
        sys.exit(2)
    psutil.cpu_percent(None)
    Bot(cfg).run()


if __name__ == "__main__":
    main()
