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
def _log(conn, channel: str, source: str, subject: str, ok: bool, error: str) -> None:
    try:
        from . import db as _db
        _db.execute(
            conn,
            "INSERT INTO notification_log ([timestamp], channel, source, subject, ok, error) "
            "VALUES (SYSDATETIME(), %s, %s, %s, %s, %s)",
            (channel, source, subject[:200], 1 if ok else 0, (error or None) and error[:400]),
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("Registro notifiche non aggiornato: %s", exc)


def send_channel(conn, cfg, values: dict, channel: str, source: str, subject: str, body: str) -> tuple[bool, str]:
    if channel == "email":
        ok = send_email(cfg.email, subject, body)
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


def dispatch(conn, cfg, source: str, subject: str, body: str) -> bool:
    """Invia la notifica su ogni canale abilitato e instradato per `source`.

    Ritorna True se almeno un canale l'ha consegnata.
    """
    from . import settings as settings_mod

    values = settings_mod.load(conn, cfg)
    delivered = False
    routed = False
    for channel in settings_mod.CHANNELS:
        if not values.get(f"notify.{channel}.enabled") or not values.get(f"route.{source}.{channel}"):
            continue
        routed = True
        ok, _ = send_channel(conn, cfg, values, channel, source, subject, body)
        delivered = delivered or ok
    if not routed:
        log.info("Nessun canale attivo per '%s': notifica non inviata (%s)", source, subject)
    return delivered


class AlertState:
    """Stato persistente di un allarme, salvato in monitor_state."""

    def __init__(self, conn, key: str):
        self.conn = conn
        self.key = f"alert:{key}"
        self.data = db.state_get(conn, self.key, {}) or {}

    @property
    def status(self) -> str:
        return self.data.get("status", OK)

    def update(self, new_status: str, reminder_hours: float) -> tuple[bool, str | None]:
        """Registra il nuovo stato. Ritorna (da_notificare, stato_precedente)."""
        now = dt.datetime.now()
        previous = self.data.get("status")
        notify = False

        if previous is None:
            # Primo avvio: si notifica solo se lo stato è già anomalo
            notify = new_status != OK
            self.data["since"] = now.isoformat(timespec="seconds")
        elif new_status != previous:
            notify = True
            self.data["since"] = now.isoformat(timespec="seconds")
        elif new_status != OK and reminder_hours > 0:
            last = self.data.get("last_notified")
            if last is None or now - dt.datetime.fromisoformat(last) >= dt.timedelta(hours=reminder_hours):
                notify = True

        self.data["status"] = new_status
        self.data["checked_at"] = now.isoformat(timespec="seconds")
        return notify, previous

    def mark_notified(self) -> None:
        self.data["last_notified"] = dt.datetime.now().isoformat(timespec="seconds")

    def save(self) -> None:
        db.state_set(self.conn, self.key, self.data)


def worst(statuses: list[str]) -> str:
    return max(statuses, key=lambda s: SEVERITY.get(s, 0)) if statuses else OK
