"""Invio email (unico punto del progetto) e allarmi a cambio di stato.

`AlertState` evita lo spam: notifica solo quando lo stato cambia
(es. OK -> WARNING, WARNING -> OK) e, se lo stato resta anomalo,
ripete il promemoria ogni `reminder_hours` (0 = mai).
"""
from __future__ import annotations

import datetime as dt
import logging
import smtplib
import ssl
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
