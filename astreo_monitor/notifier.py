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


def _post(url: str, secrets_: tuple, **kw) -> tuple[bool, str]:
    """POST con gestione degli errori; i segreti non compaiono mai nei messaggi."""
    try:
        r = requests.post(url, timeout=20, **kw)
        if r.ok:
            return True, ""
        detail = r.text.strip()[:200]
        out = f"HTTP {r.status_code}" + (f": {detail}" if detail else "")
    except requests.RequestException as exc:
        out = str(exc)
    for sec in secrets_:
        if sec:
            out = out.replace(sec, "***")
    return False, out[:300]


def send_ntfy(server: str, topic: str, token: str, subject: str, body: str) -> tuple[bool, str]:
    """ntfy (https://ntfy.sh o server proprio): pubblicazione JSON, quindi titoli con accenti senza problemi."""
    if not server or not topic:
        return False, "server o argomento mancanti"
    priority = 4 if any(w in subject for w in ("ALERT", "DOWN", "FALLIT", "FAILED", "fermo", "stopped")) else 3
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    return _post(server.rstrip("/"), (token,), headers=headers,
                 json={"topic": topic, "title": f"[Astreo] {subject}", "message": body.strip()[:4000],
                       "priority": priority, "tags": ["computer"]})


def send_gotify(server: str, token: str, subject: str, body: str) -> tuple[bool, str]:
    if not server or not token:
        return False, "server o token mancanti"
    priority = 8 if any(w in subject for w in ("ALERT", "DOWN", "FALLIT", "FAILED")) else 5
    return _post(f"{server.rstrip('/')}/message", (token,), headers={"X-Gotify-Key": token},
                 json={"title": f"[Astreo] {subject}", "message": body.strip()[:4000], "priority": priority})


def send_discord(webhook: str, subject: str, body: str) -> tuple[bool, str]:
    if not webhook:
        return False, "URL del webhook mancante"
    text = f"**[Astreo] {subject}**\n{body.strip()}"
    return _post(webhook, (webhook,), json={"content": text[:1990] + ("…" if len(text) > 1990 else ""),
                                            "allowed_mentions": {"parse": []}})


def send_webhook(url: str, secret: str, source: str, subject: str, body: str) -> tuple[bool, str]:
    """Webhook generico: JSON con evento, oggetto e testo (per Home Assistant, n8n, script propri…)."""
    if not url:
        return False, "URL mancante"
    import socket
    from . import __version__
    payload = {"source": source, "subject": subject, "body": body.strip(), "host": socket.gethostname(),
               "time": dt.datetime.now().isoformat(timespec="seconds"), "version": __version__}
    headers = {"Authorization": f"Bearer {secret}"} if secret else {}
    return _post(url, (url, secret), json=payload, headers=headers)


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
    """Invia subito e registra l'esito (messaggi di prova dalla dashboard, riepilogo della fascia di silenzio)."""
    ok, err = _send(cfg, values, channel, source, subject, body)
    _log(conn, channel, source, subject, ok, err)
    return ok, err


def _send(cfg, values: dict, channel: str, source: str, subject: str, body: str) -> tuple[bool, str]:
    """Invio vero e proprio su un canale. Nessun accesso al database: si può chiamare fuori dalle transazioni."""
    if channel == "email":
        from . import settings as settings_mod
        ok = send_email(settings_mod.email_config(cfg, values), subject, body)
        err = "" if ok else "invio fallito (vedi journal)"
    elif channel == "telegram":
        ok, err = send_telegram(values["notify.telegram.bot_token"], values["notify.telegram.chat_id"], subject, body)
    elif channel == "whatsapp":
        ok, err = send_whatsapp(values["notify.whatsapp.phone"], values["notify.whatsapp.apikey"], subject, body)
    elif channel == "ntfy":
        ok, err = send_ntfy(values["notify.ntfy.url"], values["notify.ntfy.topic"], values["notify.ntfy.token"], subject, body)
    elif channel == "gotify":
        ok, err = send_gotify(values["notify.gotify.url"], values["notify.gotify.token"], subject, body)
    elif channel == "discord":
        ok, err = send_discord(values["notify.discord.webhook"], subject, body)
    elif channel == "webhook":
        ok, err = send_webhook(values["notify.webhook.url"], values["notify.webhook.secret"], source, subject, body)
    else:
        return False, f"canale sconosciuto {channel}"
    if ok:
        log.info("Notifica %s inviata: %s", channel, subject)
    else:
        log.error("Notifica %s fallita (%s): %s", channel, subject, err)
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

    from . import models
    if settings_mod.is_quiet(values, now):
        due = settings_mod.deferred_until(values, now)
        for channel in channels:
            conn.execute(models.notification_queue.insert().values(
                created_at=detected_at.replace(microsecond=0), due_at=due, source=source, channel=channel,
                subject=subject[:200], body=body, attempts=0, quiet=True))
            _log(conn, channel, source, subject, True, f"recapito alle {_fmt(due)}", status="in coda")
        log.info("Fascia di silenzio: '%s' trattenuto fino alle %s", subject, _fmt(due))
        return True

    # 4.2.1: "posta in uscita". Qui si scrive solo il messaggio in coda, nella stessa transazione dello stato
    # dell'avviso; l'invio vero (rete, timeout) parte dopo la conferma della transazione, fuori da ogni blocco
    # sul database, con ritenti automatici se un canale non risponde.
    for channel in channels:
        conn.execute(models.notification_queue.insert().values(
            created_at=detected_at.replace(microsecond=0), due_at=now.replace(microsecond=0), source=source,
            channel=channel, subject=subject[:200], body=body, attempts=0, quiet=False))
    db.after_commit(lambda: deliver(cfg), key="notify")
    log.info("Avviso in uscita su %s: %s", ", ".join(channels), subject)
    return True


# 4.2.1: intervallo prima di ritentare un invio non riuscito (minuti, per tentativo)
RETRY_MINUTES = (1, 2, 5, 15, 30)
LEASE_MINUTES = 5          # chi prende in carico un messaggio lo "prenota": nessun doppio invio da due processi


def deliver(cfg, limit: int = 50) -> int:
    """Invia i messaggi in uscita (non della fascia di silenzio) già dovuti. Ritorna quanti sono stati consegnati.

    Ogni messaggio si prenota con una transazione brevissima, si invia senza transazioni aperte, poi si registra
    l'esito con un'altra transazione brevissima. Dopo un errore si ritenta più tardi (RETRY_MINUTES), fino a
    MAX_ATTEMPTS tentativi.
    """
    from sqlalchemy import select, update
    from . import i18n, models
    from . import settings as settings_mod
    Q = models.notification_queue
    now = dt.datetime.now().replace(microsecond=0)
    try:
        with db.connect(cfg.database) as conn:
            values = settings_mod.load(conn, cfg)
            rows = db.rows(conn, select(Q.c.id, Q.c.created_at, Q.c.source, Q.c.channel, Q.c.subject, Q.c.body, Q.c.attempts)
                           .where(Q.c.sent_at.is_(None), Q.c.quiet == False, Q.c.attempts < MAX_ATTEMPTS,  # noqa: E712
                                  Q.c.due_at <= now).order_by(Q.c.created_at).limit(limit))
    except Exception as exc:  # noqa: BLE001 - riproverà il prossimo job
        log.warning("Posta in uscita non letta: %s", exc)
        return 0
    lang = i18n.lang_of(values)
    _ = i18n.translator(lang)
    sent = 0
    for r in rows:
        if not values.get(f"notify.{r['channel']}.enabled"):
            continue                                   # canale spento nel frattempo: resta in coda finché non torna
        with db.connect(cfg.database) as conn:         # prenotazione: un solo processo invia ogni messaggio
            claimed = conn.execute(update(Q).where(Q.c.id == r["id"], Q.c.sent_at.is_(None), Q.c.due_at <= now)
                                   .values(due_at=now + dt.timedelta(minutes=LEASE_MINUTES))).rowcount
        if not claimed:
            continue
        detected = db.as_datetime(r["created_at"])
        sending = dt.datetime.now()
        tail = (_("Rilevato e inviato alle {quando}.", quando=_fmt(detected, lang)) if sending - detected < dt.timedelta(minutes=2)
                else _("Rilevato alle {r}, inviato alle {i}.", r=_fmt(detected, lang), i=_fmt(sending, lang)))
        ok, err = _send(cfg, values, r["channel"], r["source"], r["subject"], f"{r['body'].rstrip()}\n\n{tail}")
        attempts = r["attempts"] + 1
        with db.connect(cfg.database) as conn:
            if ok:
                conn.execute(update(Q).where(Q.c.id == r["id"]).values(sent_at=db.now(), attempts=attempts, error=None))
                _log(conn, r["channel"], r["source"], r["subject"], True, "" if attempts == 1 else f"al tentativo {attempts}")
                sent += 1
            else:
                last = attempts >= MAX_ATTEMPTS
                wait = RETRY_MINUTES[min(attempts - 1, len(RETRY_MINUTES) - 1)]
                conn.execute(update(Q).where(Q.c.id == r["id"]).values(
                    attempts=attempts, error=(err or "")[:400], due_at=now + dt.timedelta(minutes=wait)))
                _log(conn, r["channel"], r["source"], r["subject"], False,
                     (err or "") + ("" if last else f" (nuovo tentativo tra {wait} min)"),
                     status="fallita" if last else "in coda")
    return sent


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
        .where(Q.c.sent_at.is_(None), Q.c.attempts < MAX_ATTEMPTS, Q.c.quiet == True).order_by(Q.c.created_at)  # noqa: E712
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

        # 4.2: attesa prima dell'avviso. L'anomalia deve durare almeno delay_minutes di fila;
        # nel frattempo l'avviso resta "in attesa" e parte appena il tempo è passato.
        delay = float(getattr(rule, "delay_minutes", 0) or 0)
        since_iso = self.data.get("anomaly_since")
        if delay > 0:
            if new_status == OK:
                notified = self.data.get("last_notified")
                # rientro solo se di questa anomalia era partito un avviso
                if notify and (self.data.get("pending") or not notified or (since_iso and notified < since_iso)):
                    notify, reason = False, None
                self.data.pop("pending", None)
            else:
                start = since_iso if previous not in (None, OK) and since_iso else now.isoformat(timespec="seconds")
                elapsed = now - dt.datetime.fromisoformat(start)
                if notify:
                    if elapsed < dt.timedelta(minutes=delay):
                        self.data["pending"] = reason          # rimandato: lo ricorda per quando il tempo è passato
                        notify, reason = False, None
                    else:
                        self.data.pop("pending", None)
                elif self.data.get("pending") and elapsed >= dt.timedelta(minutes=delay):
                    notify, reason = True, self.data.pop("pending")

        # 4.4: silenzio attivo ("silenzia per un po'"): l'avviso resta in attesa e parte alla fine del silenzio
        # se il problema c'è ancora; un rientro durante il silenzio non manda nulla
        from . import silences
        conn = getattr(self, "conn", None)
        sil = silences.match(conn, self.key, getattr(rule, "source", None), now) if conn is not None else None
        if sil:
            if new_status == OK:
                self.data.pop("pending", None)
                if notify:
                    notify, reason = False, None
            elif notify and reason != "promemoria":
                self.data["pending"] = reason
                notify, reason = False, None
            self.data["silenced_until"] = sil["until"]
        else:
            self.data.pop("silenced_until", None)
            if not notify and new_status != OK and delay <= 0 and self.data.get("pending"):
                notify, reason = True, self.data.pop("pending")         # silenzio finito, problema ancora presente

        # inizio e fine della situazione anomala (WARNING/ALERT/... anche alternati)
        if new_status == OK:
            self.data.pop("anomaly_since", None)
        elif previous in (None, OK) or "anomaly_since" not in self.data:
            self.data["anomaly_since"] = now.isoformat(timespec="seconds")

        if not notify and new_status != OK and rule.reminder_hours > 0 and not self.data.get("pending") and not sil:
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
