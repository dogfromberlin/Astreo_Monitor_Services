"""Invio email (unico punto del progetto) e allarmi a cambio di stato.

`AlertState` evita lo spam: notifica solo quando lo stato cambia
(es. OK -> WARNING, WARNING -> OK) e, se lo stato resta anomalo,
ripete il promemoria ogni `reminder_hours` (0 = mai).
"""
from __future__ import annotations

import datetime as dt
import logging
import re
import smtplib
import ssl

import requests
from email.message import EmailMessage
from email.utils import formatdate, make_msgid

from . import db
from .config import EmailConfig

log = logging.getLogger(__name__)

OK = "OK"
SEVERITY = {"OK": 0, "WARNING": 1, "ALERT": 2, "DOWN": 3}


def send_email(cfg: EmailConfig, subject: str, body: str) -> bool:
    """Invia una mail di testo. Non solleva eccezioni: ritorna True/False."""
    if not cfg.enabled:
        log.info("Email disabilitate da configurazione, non invio: %s", subject)
        return False
    if not cfg.recipients:
        log.warning("Nessun destinatario configurato, non invio: %s", subject)
        return False

    msg = EmailMessage()
    msg["Subject"] = f"{cfg.subject_prefix} {subject}".strip()
    msg["From"] = cfg.sender
    msg["To"] = ", ".join(cfg.recipients)
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain="astreo")
    msg.set_content(body)

    try:
        context = ssl.create_default_context()
        if cfg.security == "ssl":
            server = smtplib.SMTP_SSL(cfg.smtp_host, cfg.smtp_port, timeout=30, context=context)
        else:
            server = smtplib.SMTP(cfg.smtp_host, cfg.smtp_port, timeout=30)
        with server:
            if cfg.security == "starttls":
                server.starttls(context=context)
            if cfg.username:
                server.login(cfg.username, cfg.password)
            server.send_message(msg)
        log.info("Email inviata a %s: %s", msg["To"], subject)
        return True
    except Exception as exc:  # noqa: BLE001
        log.error("Invio email fallito (%s): %s", subject, exc)
        return False


# --------------------------------------------------------------------------
# Telegram e WhatsApp
# --------------------------------------------------------------------------
CHAT_LIMIT = 1500


def _chat_text(subject: str, body: str) -> str:
    text = f"[Astreo] {subject}\n\n{body.strip()}"
    return text if len(text) <= CHAT_LIMIT else text[: CHAT_LIMIT - 1] + "…"


def send_telegram(bot_token: str, chat_id: str, subject: str, body: str) -> tuple[bool, str]:
    if not bot_token or not chat_id:
        return False, "token del bot o chat ID mancanti"
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{bot_token}/sendMessage",
            json={"chat_id": chat_id, "text": _chat_text(subject, body), "disable_web_page_preview": True},
            timeout=20,
        )
        data = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        if r.ok and data.get("ok"):
            return True, ""
        return False, data.get("description") or f"HTTP {r.status_code}"
    except requests.RequestException as exc:
        return False, str(exc).replace(bot_token, "***")


def send_whatsapp(phone: str, apikey: str, subject: str, body: str) -> tuple[bool, str]:
    """WhatsApp tramite CallMeBot (servizio gratuito per inviare messaggi a sé stessi)."""
    if not phone or not apikey:
        return False, "numero o API key mancanti"
    try:
        r = requests.get(
            "https://api.callmebot.com/whatsapp.php",
            params={"phone": phone, "text": _chat_text(subject, body), "apikey": apikey},
            timeout=30,
        )
        plain = re.sub(r"<[^>]+>", "", r.text).strip()
        low = plain.lower()
        if r.ok and "error" not in low and ("queued" in low or "sent" in low):
            return True, ""
        return False, plain[:200] or f"HTTP {r.status_code}"
    except requests.RequestException as exc:
        return False, str(exc).replace(apikey, "***")


# --------------------------------------------------------------------------
# Invio su tutti i canali abilitati per una sorgente
# --------------------------------------------------------------------------
def _log(conn, channel: str, source: str, subject: str, ok: bool, error: str, status: str | None = None) -> None:
    status = status or ("inviata" if ok else "fallita")
    try:
        from . import db as _db
        from . import models
        conn.execute(models.notification_log.insert().values(
            timestamp=_db.now(), channel=channel, source=source, subject=subject[:200], ok=bool(ok),
            error=(error or None) and error[:400], status=status))
    except Exception as exc:  # noqa: BLE001
        log.warning("Registro notifiche non aggiornato: %s", exc)


def send_channel(conn, cfg, values: dict, channel: str, source: str, subject: str, body: str) -> tuple[bool, str]:
    if channel == "email":
        from . import settings as settings_mod
        ok = send_email(settings_mod.email_config(cfg, values), subject, body)
        err = "" if ok else "invio fallito (vedi journal)"
    elif channel == "telegram":
        ok, err = send_telegram(values["notify.telegram.bot_token"], values["notify.telegram.chat_id"], subject, body)
    elif channel == "whatsapp":
        ok, err = send_whatsapp(values["notify.whatsapp.phone"], values["notify.whatsapp.apikey"], subject, body)
    else:
        return False, f"canale sconosciuto {channel}"
    if ok:
        log.info("Notifica %s inviata: %s", channel, subject)
    else:
        log.error("Notifica %s fallita (%s): %s", channel, subject, err)
    _log(conn, channel, source, subject, ok, err)
    return ok, err


def _fmt(when: dt.datetime, lang: str = "it") -> str:
    return when.strftime("%H:%M on %d/%m/%Y" if lang == "en" else "%H:%M del %d/%m/%Y")


def dispatch(conn, cfg, source: str, subject: str, body: str, detected_at: dt.datetime | None = None) -> bool:
    """Invia l'avviso su ogni canale abilitato e instradato per `source`.

    Nella fascia di silenzio l'avviso viene messo in coda (notification_queue) e
    recapitato all'orario impostato da flush_queue(). Ritorna True se almeno un
    canale l'ha consegnato o messo in coda.
    """
    from . import settings as settings_mod

    values = settings_mod.load(conn, cfg)
    now = dt.datetime.now()
    detected_at = detected_at or now
    channels = [c for c in settings_mod.CHANNELS
                if values.get(f"notify.{c}.enabled") and values.get(f"route.{source}.{c}")]
    if not channels:
        log.info("Nessun canale attivo per '%s': avviso non inviato (%s)", source, subject)
        return False

    if settings_mod.is_quiet(values, now):
        due = settings_mod.deferred_until(values, now)
        from . import models
        for channel in channels:
            conn.execute(models.notification_queue.insert().values(
                created_at=detected_at.replace(microsecond=0), due_at=due, source=source, channel=channel,
                subject=subject[:200], body=body, attempts=0))
            _log(conn, channel, source, subject, True, f"recapito alle {_fmt(due)}", status="in coda")
        log.info("Fascia di silenzio: '%s' trattenuto fino alle %s", subject, _fmt(due))
        return True

    full = f"{body.rstrip()}\n\nRilevato e inviato alle {_fmt(detected_at)}."
    delivered = False
    for channel in channels:
        ok, _ = send_channel(conn, cfg, values, channel, source, subject, full)
        delivered = delivered or ok
    return delivered


MAX_ATTEMPTS = 5


def flush_queue(conn, cfg) -> int:
    """Recapita gli avvisi trattenuti dalla fascia di silenzio ormai scaduti.

    Un solo messaggio per canale: l'avviso originale se è uno solo, altrimenti un
    riepilogo. Ogni avviso riporta l'orario in cui è stato rilevato e la fascia
    che l'ha trattenuto. Ritorna il numero di avvisi recapitati.
    """
    from . import db as _db
    from . import settings as settings_mod

    values = settings_mod.load(conn, cfg)
    now = dt.datetime.now()
    if settings_mod.is_quiet(values, now):
        return 0  # siamo ancora nella fascia (es. fascia modificata dopo l'accodamento)
    from sqlalchemy import select, update
    from . import models
    Q = models.notification_queue
    q = select(Q.c.id, Q.c.created_at, Q.c.due_at, Q.c.source, Q.c.channel, Q.c.subject, Q.c.body, Q.c.attempts) \
        .where(Q.c.sent_at.is_(None), Q.c.attempts < MAX_ATTEMPTS).order_by(Q.c.created_at)
    if values.get("quiet.enabled"):
        q = q.where(Q.c.due_at <= now)
    rows = _db.rows(conn, q)
    if not rows:
        return 0
    from . import i18n
    lang = i18n.lang_of(values)
    _ = i18n.translator(lang)
    window = f"{values['quiet.start']}–{values['quiet.end']}"
    sent = 0
    by_channel: dict[str, list[dict]] = {}
    for r in rows:
        by_channel.setdefault(r["channel"], []).append(r)

    for channel, items in by_channel.items():
        if not values.get(f"notify.{channel}.enabled"):
            continue  # canale disattivato nel frattempo: resta in coda finché non lo riattivi
        nota = _("Inviato alle {quando}, posticipato per la fascia di silenzio {fascia}.", quando=_fmt(now, lang), fascia=window)
        if len(items) == 1:
            r = items[0]
            subject = _("{oggetto} (posticipato)", oggetto=r["subject"])
            body = r["body"].rstrip() + "\n\n" + _("Rilevato alle {quando}.", quando=_fmt(_db.as_datetime(r["created_at"]), lang)) \
                + f"\n{nota}"
            source = r["source"]
        else:
            subject = _("{n} avvisi posticipati", n=len(items))
            parts = [_("Avvisi trattenuti durante la fascia di silenzio {fascia}, in ordine di rilevamento.", fascia=window), ""]
            for r in items:
                label = _(settings_mod.SOURCES.get(r["source"], r["source"]))
                parts += [f"■ {r['subject']}  [" + _("{fonte}, rilevato alle {quando}", fonte=label,
                                                       quando=_fmt(_db.as_datetime(r["created_at"]), lang)) + "]",
                          r["body"].rstrip(), ""]
            parts.append(nota)
            body = "\n".join(parts)
            source = "riepilogo"
        ok, err = send_channel(conn, cfg, values, channel, source, subject, body)
        ids = [r["id"] for r in items]
        if ok:
            conn.execute(update(Q).where(Q.c.id.in_(ids)).values(sent_at=_db.now()))
            sent += len(items)
        else:
            conn.execute(update(Q).where(Q.c.id.in_(ids)).values(attempts=Q.c.attempts + 1, error=(err or "")[:400]))
    return sent


class AlertState:
    """Stato persistente di un allarme, salvato in monitor_state."""

    def __init__(self, conn, key: str):
        self.conn = conn
        self.key = f"alert:{key}"
        self.data = db.state_get(conn, self.key, {}) or {}

    @property
    def status(self) -> str:
        return self.data.get("status", OK)

    def evaluate(self, new_status: str, rule) -> tuple[bool, str | None, str | None]:
        """Applica la regola (settings.Policy). Ritorna (avvisare, motivo, stato_precedente).

        motivo: "primo", "peggioramento", "cambio", "rientro", "promemoria".
        """
        now = dt.datetime.now()
        previous = self.data.get("status")
        notify, reason = False, None

        if previous is None:
            notify, reason = new_status != OK, "primo"
        elif new_status != previous:
            if new_status == OK:
                notify, reason = bool(rule.recovery), "rientro"
            elif rule.mode == "change":
                notify, reason = True, "cambio"
            elif SEVERITY.get(new_status, 0) > SEVERITY.get(previous, 0):
                notify, reason = True, "peggioramento"

        # inizio e fine della situazione anomala (WARNING/ALERT/... anche alternati)
        if new_status == OK:
            self.data.pop("anomaly_since", None)
        elif previous in (None, OK) or "anomaly_since" not in self.data:
            self.data["anomaly_since"] = now.isoformat(timespec="seconds")

        if not notify and new_status != OK and rule.reminder_hours > 0:
            anchor = self.data.get("last_notified")
            since = self.data.get("anomaly_since")
            # l'ultimo avviso deve appartenere alla situazione anomala in corso
            if anchor is None or (since and anchor < since):
                anchor = since
            if anchor and now - dt.datetime.fromisoformat(anchor) >= dt.timedelta(hours=rule.reminder_hours):
                notify, reason = True, "promemoria"

        if new_status != previous:
            self.data["since"] = now.isoformat(timespec="seconds")
        self.data["status"] = new_status
        self.data["checked_at"] = now.isoformat(timespec="seconds")
        return notify, reason, previous

    @property
    def anomaly_since(self) -> dt.datetime | None:
        v = self.data.get("anomaly_since")
        return dt.datetime.fromisoformat(v) if v else None

    def mark_notified(self) -> None:
        self.data["last_notified"] = dt.datetime.now().isoformat(timespec="seconds")

    def save(self) -> None:
        db.state_set(self.conn, self.key, self.data)


def reason_line(reason: str | None, state: "AlertState", lang: str = "it") -> str:
    """Riga che spiega perché parte l'avviso."""
    from . import i18n
    _ = i18n.translator(lang)
    since = state.anomaly_since
    if reason == "promemoria" and since:
        return _("Promemoria: situazione anomala ininterrotta dal {dal}.", dal=f"{since:%d/%m/%Y %H:%M}")
    if reason == "peggioramento":
        return _("Avviso: la situazione è peggiorata.")
    if reason == "rientro":
        return _("La situazione è tornata nella norma.")
    return ""


def worst(statuses: list[str]) -> str:
    return max(statuses, key=lambda s: SEVERITY.get(s, 0)) if statuses else OK
