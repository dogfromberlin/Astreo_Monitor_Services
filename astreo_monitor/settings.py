"""Impostazioni modificabili dalla dashboard, salvate nella tabella app_settings.

Il file di configurazione fornisce i valori INIZIALI; quando un valore viene
modificato dalla pagina Impostazioni, la versione nel DB ha la precedenza.
Le chiavi ammesse, i tipi e i limiti sono definiti qui (SPEC): nient'altro
può essere scritto, e i valori sono validati prima del salvataggio.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from . import db
from .config import Config

CHANNELS = ("email", "telegram", "whatsapp")
SOURCES = {
    "speedtest": "Speedtest",
    "temperature": "Temperatura",
    "disk": "Disco",
    "services": "Servizi",
    "backup": "Backup database",
    "publicip": "IP pubblico",
}


@dataclass(frozen=True)
class Spec:
    type: type
    default: Any
    min: float | None = None
    max: float | None = None
    secret: bool = False
    label: str = ""


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
        "speedtest.reminder_hours": Spec(float, s.reminder_hours, 0, 720, label="Promemoria se resta anomalo (ore, 0 = mai)"),
        # --- canali
        "notify.email.enabled": Spec(bool, cfg.email.enabled, label="Email"),
        "notify.telegram.enabled": Spec(bool, False, label="Telegram"),
        "notify.telegram.bot_token": Spec(str, "", secret=True, label="Token del bot"),
        "notify.telegram.chat_id": Spec(str, "", label="Chat ID"),
        "notify.whatsapp.enabled": Spec(bool, False, label="WhatsApp"),
        "notify.whatsapp.phone": Spec(str, "", label="Numero (con prefisso, senza +)"),
        "notify.whatsapp.apikey": Spec(str, "", secret=True, label="API key CallMeBot"),
    }
    # --- instradamento: quale evento va su quale canale
    email_default = {
        "speedtest": s.notify, "temperature": cfg.metrics.notify, "disk": cfg.metrics.notify,
        "services": True, "backup": cfg.backup.notify if cfg.backup else True, "publicip": cfg.publicip.notify,
    }
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
    for row in db.query(conn, "SELECT [key], [value] FROM app_settings"):
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

    for key, value in clean.items():
        payload = json.dumps(value)
        if not db.execute(conn, "UPDATE app_settings SET [value] = %s, updated_at = SYSDATETIME() WHERE [key] = %s", (payload, key)):
            db.execute(conn, "INSERT INTO app_settings ([key], [value], updated_at) VALUES (%s, %s, SYSDATETIME())", (key, payload))
    return load(conn, cfg)


def mask(value: str) -> str:
    if not value:
        return ""
    return "••••" + value[-4:] if len(value) > 6 else "••••"


def public_view(cfg: Config, values: dict[str, Any]) -> dict:
    """Versione da mostrare nella dashboard: segreti mascherati, più i metadati dei campi."""
    spec = build_spec(cfg)
    out_values = {k: (mask(v) if spec[k].secret else v) for k, v in values.items()}
    meta = {k: {"type": sp.type.__name__, "min": sp.min, "max": sp.max, "secret": sp.secret, "label": sp.label}
            for k, sp in spec.items()}
    return {"values": out_values, "meta": meta, "channels": list(CHANNELS), "sources": SOURCES,
            "email": {"recipients": cfg.email.recipients, "smtp": f"{cfg.email.smtp_host}:{cfg.email.smtp_port}"}}
