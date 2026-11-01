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

from . import __version__, config as config_mod, db, i18n, logging_setup, services_store
from . import settings as settings_mod
from .collectors import sensors, services, system, units

log = logging.getLogger("telegram")
API = "https://api.telegram.org/bot{token}/{method}"
# (comando italiano, comando inglese, descrizione): entrambi i comandi funzionano sempre;
# il menu di Telegram mostra quelli della lingua scelta nella dashboard.
COMMANDS = [
    ("stato", "status", "Riepilogo del server"),
    ("connessione", "connection", "Connessione: ping, ultimo speedtest, disponibilità"),
    ("speedtest", "speedtest", "Avvia uno speedtest e mostra il risultato"),
    ("servizi", "services", "Stato dei servizi monitorati"),
    ("controlli", "checks", "Dischi, aggiornamenti, scadenze, backup"),
    ("aiuto", "help", "Elenco dei comandi"),
]
ALIASES = {en: it for it, en, _d in COMMANDS}
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
                cmd = msg["text"].split()[0][1:].split("@")[0].lower()
                who = (msg.get("from") or {}).get("username") or (msg.get("from") or {}).get("first_name", "?")
                if chat != self.chat_id:
                    log.warning("Comando /%s ignorato: chat %s non autorizzata (da %s)", cmd, chat, who)
                    continue
                log.info("Comando /%s da %s", cmd, who)
                threading.Thread(target=self.handle, args=(chat, cmd), daemon=True).start()

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

    def handle(self, chat, cmd: str) -> None:
        cmd = ALIASES.get(cmd, cmd)
        self.refresh_language()
        try:
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
        lines += ["", self.tr("Allarmi attivi:")] + active if active else ["", self.tr("Nessun allarme attivo.")]
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
