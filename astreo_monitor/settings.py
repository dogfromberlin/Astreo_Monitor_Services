"""Impostazioni modificabili dalla dashboard, salvate nella tabella app_settings.

Il file di configurazione fornisce i valori INIZIALI; quando un valore viene
modificato dalla pagina Impostazioni, la versione nel DB ha la precedenza.
Le chiavi ammesse, i tipi e i limiti sono definiti qui (SPEC): nient'altro
può essere scritto, e i valori sono validati prima del salvataggio.
"""
from __future__ import annotations

import datetime as dt
import json
import re
from dataclasses import dataclass, replace
from typing import Any

from sqlalchemy import select

from . import db, models
from .config import Config, EmailConfig

CHANNELS = ("email", "telegram", "whatsapp")
SOURCES = {
    "connectivity": "Connessione (ping)",
    "speedtest": "Speedtest",
    "temperature": "Temperatura",
    "disk": "Disco",
    "services": "Servizi",
    "backup": "Backup database",
    "publicip": "IP pubblico",
    "expiry": "Scadenze",
    "smart": "Salute dei dischi",
    "updates": "Aggiornamenti di sistema",
    "restoretest": "Verifica del ripristino",
    "docker": "Container Docker",
    "pihole": "Pi-hole",
    "summary": "Riepilogo settimanale",
}


# Monitoraggi con stato (OK/WARNING/ALERT...) a cui si applica una regola di avviso
POLICY_SOURCES = ("connectivity", "speedtest", "temperature", "disk", "services", "backup", "expiry",
                  "smart", "updates", "restoretest", "docker", "pihole")
TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


@dataclass(frozen=True)
class Spec:
    type: type
    default: Any
    min: float | None = None
    max: float | None = None
    secret: bool = False
    label: str = ""
    choices: tuple | None = None
    kind: str = ""          # "time" = orario HH:MM


@dataclass(frozen=True)
class Policy:
    """Regola di avviso di un monitoraggio.

    mode "escalation": avvisa solo quando lo stato peggiora (OK->WARNING, WARNING->ALERT, ...),
                       mai quando migliora restando anomalo (ALERT->WARNING).
    mode "change":     avvisa a ogni cambio di stato.
    recovery:          avvisa anche quando si torna a OK.
    reminder_hours:    se lo stato resta anomalo (anche alternando WARNING e ALERT),
                       ripete l'avviso dopo queste ore dall'ultimo invio (0 = mai).
    """
    mode: str
    recovery: bool
    reminder_hours: float


def build_spec(cfg: Config) -> dict[str, Spec]:
    s = cfg.speedtest
    spec: dict[str, Spec] = {
        # --- speedtest
        "speedtest.enabled": Spec(bool, True, label="Speedtest attivo"),
        "speedtest.download_warning": Spec(float, s.download_warning, 1, 100000, label="Download: soglia warning (Mbps)"),
        "speedtest.download_alert": Spec(float, s.download_alert, 0, 100000, label="Download: soglia alert (Mbps)"),
        "speedtest.upload_warning": Spec(float, s.upload_warning, 1, 100000, label="Upload: soglia warning (Mbps)"),
        "speedtest.upload_alert": Spec(float, s.upload_alert, 0, 100000, label="Upload: soglia alert (Mbps)"),
        "speedtest.streams": Spec(int, s.streams, 1, 16, label="Connessioni parallele"),
        "speedtest.rounds": Spec(int, s.rounds, 1, 10, label="Giri di misura"),
        "speedtest.download_mb": Spec(int, max(1, s.download_bytes // 1_000_000), 1, 200, label="MB scaricati per connessione"),
        "speedtest.upload_mb": Spec(int, max(1, s.upload_bytes // 1_000_000), 1, 100, label="MB inviati per connessione"),
        # --- controllo continuo della connessione (ping ogni minuto)
        "connectivity.enabled": Spec(bool, True, label="Controllo continuo attivo"),
        "connectivity.targets": Spec(str, "gateway, 1.1.1.1, 8.8.8.8", label="Destinazioni (gateway = router)"),
        "connectivity.loss_warning": Spec(float, 20, 1, 100, label="Perdita pacchetti per WARNING (%)"),
        "connectivity.rtt_warning": Spec(float, 100, 1, 5000, label="Latenza per WARNING (ms)"),
        # --- heartbeat verso un servizio esterno (es. healthchecks.io)
        "heartbeat.enabled": Spec(bool, False, label="Heartbeat attivo"),
        "heartbeat.url": Spec(str, "", secret=True, label="URL di ping"),
        # --- scadenze
        "expiry.warning_days": Spec(int, 15, 1, 365, label="Avviso WARNING a (giorni)"),
        "expiry.alert_days": Spec(int, 3, 0, 365, label="Avviso ALERT a (giorni)"),
        "expiry.endpoints": Spec(str, ", ".join(
            ([f"127.0.0.1:{cfg.web.https_port}"] if cfg.web.https_port else [])
            + (["127.0.0.1:8081"] if cfg.netpulse else [])), label="Certificati da controllare (host:porta)"),
        "expiry.github": Spec(bool, True, label="Controlla il token GitHub usato da gh"),
        # --- canali
        "notify.email.enabled": Spec(bool, cfg.email.enabled, label="Email"),
        "email.smtp_host": Spec(str, cfg.email.smtp_host, label="Server SMTP"),
        "email.smtp_port": Spec(int, cfg.email.smtp_port, 1, 65535, label="Porta"),
        "email.security": Spec(str, cfg.email.security, choices=("ssl", "starttls", "none"), label="Sicurezza"),
        "email.username": Spec(str, cfg.email.username, label="Utente SMTP"),
        "email.password": Spec(str, cfg.email.password, secret=True, label="Password SMTP"),
        "email.sender": Spec(str, cfg.email.sender, label="Mittente"),
        "email.recipients": Spec(str, ", ".join(cfg.email.recipients), label="Destinatari (separati da virgola)"),
        "email.subject_prefix": Spec(str, cfg.email.subject_prefix, label="Prefisso oggetto"),
        # --- fascia di silenzio
        "quiet.enabled": Spec(bool, False, label="Fascia di silenzio attiva"),
        "quiet.start": Spec(str, "23:00", kind="time", label="Inizio"),
        "quiet.end": Spec(str, "07:00", kind="time", label="Fine"),
        "quiet.deliver_at": Spec(str, "08:00", kind="time", label="Recapito degli avvisi trattenuti"),
        "notify.telegram.enabled": Spec(bool, False, label="Telegram"),
        "notify.telegram.bot_token": Spec(str, "", secret=True, label="Token del bot"),
        "notify.telegram.chat_id": Spec(str, "", label="Chat ID"),
        "telegram.commands": Spec(bool, False, label="Rispondi ai comandi (/stato, /speedtest, ...)"),
        # --- moduli: visibilità nella dashboard (compaiono solo se rilevati sul server)
        "ui.docker": Spec(bool, True, label="Mostra la sezione Docker"),
        "ui.pihole": Spec(bool, True, label="Mostra la sezione Pi-hole"),
        "ui.events": Spec(bool, True, label="Mostra gli eventi sui grafici"),
        "pihole.url": Spec(str, "http://127.0.0.1:8080", label="Indirizzo di Pi-hole (API v6)"),
        "pihole.password": Spec(str, "", secret=True, label="Password per le app di Pi-hole"),
        # --- salute dei dischi e aggiornamenti
        "smart.temp_warning": Spec(float, 60, 30, 90, label="Temperatura disco per WARNING (°C)"),
        "smart.wear_warning": Spec(float, 80, 1, 100, label="Usura SSD per WARNING (%)"),
        "notify.whatsapp.enabled": Spec(bool, False, label="WhatsApp"),
        "notify.whatsapp.phone": Spec(str, "", label="Numero (con prefisso, senza +)"),
        "notify.whatsapp.apikey": Spec(str, "", secret=True, label="API key CallMeBot"),
    }
    # --- instradamento: quale evento va su quale canale
    email_default = {
        "speedtest": s.notify, "temperature": cfg.metrics.notify, "disk": cfg.metrics.notify,
        "services": True, "backup": cfg.backup.notify if cfg.backup else True, "publicip": cfg.publicip.notify,
        "connectivity": True, "expiry": True, "smart": True, "updates": True, "restoretest": True, "summary": True,
        "docker": True, "pihole": True,
    }
    # --- regole di avviso per monitoraggio
    backup_rem = cfg.backup.reminder_hours if cfg.backup else 24
    policy_default = {
        "connectivity": ("change", True, 0.0),
        "smart": ("escalation", True, 24.0),
        "updates": ("escalation", False, 168.0),
        "restoretest": ("change", True, 0.0),
        "docker": ("change", True, 24.0),
        "pihole": ("change", True, 24.0),
        "expiry": ("escalation", True, 24.0),
        "speedtest": ("escalation", False, 36.0),
        "temperature": ("change", True, cfg.metrics.reminder_hours),
        "disk": ("change", True, cfg.metrics.reminder_hours),
        "services": ("change", True, cfg.metrics.reminder_hours),
        "backup": ("change", True, backup_rem),
    }
    for src, (mode, rec, rem) in policy_default.items():
        spec[f"alert.{src}.mode"] = Spec(str, mode, choices=("escalation", "change"))
        spec[f"alert.{src}.recovery"] = Spec(bool, rec)
        spec[f"alert.{src}.reminder_hours"] = Spec(float, float(rem), 0, 720)
    for src in SOURCES:
        spec[f"route.{src}.email"] = Spec(bool, email_default[src])
        spec[f"route.{src}.telegram"] = Spec(bool, False)
        spec[f"route.{src}.whatsapp"] = Spec(bool, False)
    return spec


class SettingsError(ValueError):
    pass


def _coerce(key: str, sp: Spec, value: Any) -> Any:
    try:
        if sp.type is bool:
            if isinstance(value, bool):
                return value
            if str(value).lower() in ("1", "true", "yes", "on"):
                return True
            if str(value).lower() in ("0", "false", "no", "off", ""):
                return False
            raise ValueError
        if sp.type is int:
            v = int(value)
        elif sp.type is float:
            v = float(value)
        else:
            v = str(value).strip()
            if len(v) > 500:
                raise SettingsError(f"{key}: valore troppo lungo")
            if sp.choices and v not in sp.choices:
                raise SettingsError(f"{key}: valori ammessi {', '.join(sp.choices)}")
            if sp.kind == "time" and not TIME_RE.match(v):
                raise SettingsError(f"{key}: orario non valido, usa il formato HH:MM")
            return v
    except (TypeError, ValueError) as exc:
        raise SettingsError(f"{key}: valore non valido ({value!r})") from exc
    if sp.min is not None and v < sp.min:
        raise SettingsError(f"{key}: minimo {sp.min:g}")
    if sp.max is not None and v > sp.max:
        raise SettingsError(f"{key}: massimo {sp.max:g}")
    return v


def load(conn, cfg: Config) -> dict[str, Any]:
    """Valori effettivi: default dal config, sovrascritti da quelli nel DB."""
    spec = build_spec(cfg)
    values = {k: sp.default for k, sp in spec.items()}
    t = models.app_settings
    for row in db.rows(conn, select(t.c.key, t.c.value)):
        key = row["key"]
        if key in spec and row["value"] is not None:
            try:
                values[key] = _coerce(key, spec[key], json.loads(row["value"]))
            except (ValueError, SettingsError):
                pass  # valore corrotto: resta il default
    return values


def save(conn, cfg: Config, changes: dict[str, Any]) -> dict[str, Any]:
    """Valida e salva le modifiche. I segreti vuoti o mascherati non vengono toccati."""
    spec = build_spec(cfg)
    clean = {}
    for key, value in changes.items():
        if key not in spec:
            raise SettingsError(f"Impostazione sconosciuta: {key}")
        sp = spec[key]
        if sp.secret and (value is None or str(value).strip() == "" or "•" in str(value)):
            continue
        clean[key] = _coerce(key, sp, value)

    current = load(conn, cfg)
    merged = {**current, **clean}
    for kind in ("download", "upload"):
        if merged[f"speedtest.{kind}_alert"] > merged[f"speedtest.{kind}_warning"]:
            raise SettingsError(f"{kind}: la soglia di alert deve essere minore o uguale a quella di warning")
    if merged["quiet.start"] == merged["quiet.end"]:
        raise SettingsError("Fascia di silenzio: inizio e fine non possono coincidere")
    if in_window(_t(merged["quiet.deliver_at"]), _t(merged["quiet.start"]), _t(merged["quiet.end"])):
        raise SettingsError("L'orario di recapito deve essere fuori dalla fascia di silenzio (può coincidere con la fine)")
    if merged["expiry.alert_days"] > merged["expiry.warning_days"]:
        raise SettingsError("Scadenze: i giorni di ALERT devono essere minori o uguali a quelli di WARNING")
    if clean.get("heartbeat.url") and not str(clean["heartbeat.url"]).startswith(("https://", "http://")):
        raise SettingsError("Heartbeat: l'URL deve iniziare con https://")
    if clean.get("pihole.url") and not str(clean["pihole.url"]).startswith(("http://", "https://")):
        raise SettingsError("Pi-hole: l'indirizzo deve iniziare con http:// o https://")
    if clean.get("email.recipients") is not None:
        bad = [r for r in _split(clean["email.recipients"]) if "@" not in r]
        if bad:
            raise SettingsError(f"Destinatari non validi: {', '.join(bad)}")

    for key, value in clean.items():
        payload = json.dumps(value)
        db.kv_set(conn, models.app_settings, key, payload)
    return load(conn, cfg)


def _split(text: str) -> list[str]:
    return [x.strip() for x in str(text).replace(";", ",").split(",") if x.strip()]


def _t(hhmm: str) -> dt.time:
    h, m = hhmm.split(":")
    return dt.time(int(h), int(m))


def in_window(t: dt.time, start: dt.time, end: dt.time) -> bool:
    """True se t cade nella fascia [start, end), anche a cavallo della mezzanotte."""
    if start == end:
        return False
    if start < end:
        return start <= t < end
    return t >= start or t < end


def quiet_window(values: dict) -> tuple[dt.time, dt.time, dt.time] | None:
    """(inizio, fine, recapito) se la fascia di silenzio è attiva, altrimenti None."""
    if not values.get("quiet.enabled"):
        return None
    return _t(values["quiet.start"]), _t(values["quiet.end"]), _t(values["quiet.deliver_at"])


def is_quiet(values: dict, when: dt.datetime) -> bool:
    w = quiet_window(values)
    return bool(w) and in_window(when.time(), w[0], w[1])


def deferred_until(values: dict, when: dt.datetime) -> dt.datetime:
    """Momento di recapito di un avviso nato in fascia di silenzio."""
    start, end, deliver = quiet_window(values)
    end_dt = dt.datetime.combine(when.date(), end)
    if end_dt <= when:
        end_dt += dt.timedelta(days=1)
    due = dt.datetime.combine(end_dt.date(), deliver)
    if due < end_dt:
        due += dt.timedelta(days=1)
    return due


def policy(values: dict, source: str) -> Policy:
    return Policy(values[f"alert.{source}.mode"], values[f"alert.{source}.recovery"],
                  values[f"alert.{source}.reminder_hours"])


def email_config(cfg: Config, values: dict) -> EmailConfig:
    """Configurazione email effettiva: config.ini sovrascritto dalle impostazioni della dashboard."""
    return replace(
        cfg.email,
        enabled=values["notify.email.enabled"],
        smtp_host=values["email.smtp_host"],
        smtp_port=values["email.smtp_port"],
        security=values["email.security"],
        username=values["email.username"],
        password=values["email.password"],
        sender=values["email.sender"],
        recipients=_split(values["email.recipients"]),
        subject_prefix=values["email.subject_prefix"],
    )


def mask(value: str) -> str:
    if not value:
        return ""
    return "••••" + value[-4:] if len(value) > 6 else "••••"


def public_view(cfg: Config, values: dict[str, Any]) -> dict:
    """Versione da mostrare nella dashboard: segreti mascherati, più i metadati dei campi."""
    spec = build_spec(cfg)
    out_values = {k: (mask(v) if spec[k].secret else v) for k, v in values.items()}
    meta = {k: {"type": sp.type.__name__, "min": sp.min, "max": sp.max, "secret": sp.secret, "label": sp.label,
                "choices": list(sp.choices) if sp.choices else None, "kind": sp.kind}
            for k, sp in spec.items()}
    return {"values": out_values, "meta": meta, "channels": list(CHANNELS), "sources": SOURCES,
            "policy_sources": {k: SOURCES[k] for k in POLICY_SOURCES}}
