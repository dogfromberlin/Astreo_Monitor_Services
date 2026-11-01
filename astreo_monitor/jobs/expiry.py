"""Controllo giornaliero delle scadenze: certificati HTTPS e token GitHub.

- Certificati: si collega a ogni host:porta configurato e legge la data di
  scadenza del certificato presentato (funziona anche con certificati autofirmati).
- Token GitHub: chiede a GitHub, tramite la CLI gh già autenticata, l'header
  github-authentication-token-expiration (assente = token senza scadenza).
Ogni voce ha il suo stato (OK / WARNING / ALERT) e i suoi avvisi.
"""
from __future__ import annotations

import datetime as dt
import logging
import os
import shutil
import socket
import ssl
import subprocess

from .. import db, i18n, notifier
from .. import settings as settings_mod
from ..config import Config
from .base import run

log = logging.getLogger("job.expiry")


def cert_expiry(endpoint: str) -> dt.datetime:
    host, _, port = endpoint.rpartition(":")
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    with socket.create_connection((host or endpoint, int(port or 443)), timeout=10) as sock:
        with ctx.wrap_socket(sock, server_hostname=host or endpoint) as tls:
            der = tls.getpeercert(binary_form=True)
    pem = ssl.DER_cert_to_PEM_cert(der)
    out = subprocess.run(["openssl", "x509", "-noout", "-enddate"], input=pem, capture_output=True, text=True, timeout=10)
    raw = out.stdout.strip().split("=", 1)[-1]          # es. "Nov 27 10:00:00 2026 GMT"
    return dt.datetime.strptime(raw, "%b %d %H:%M:%S %Y %Z")


def github_token_expiry() -> dt.datetime | None | str:
    """Data di scadenza, None se senza scadenza, stringa con l'errore se non verificabile."""
    if not shutil.which("gh"):
        return "CLI gh non trovata"
    env = {**os.environ, "GH_NO_UPDATE_NOTIFIER": "1", "GH_PROMPT_DISABLED": "1"}
    res = subprocess.run(["gh", "api", "-i", "rate_limit"], capture_output=True, text=True, timeout=30, env=env)
    if res.returncode != 0:
        return (res.stderr or res.stdout).strip()[:200] or "gh api non riuscita"
    for line in res.stdout.splitlines():
        if line.lower().startswith("github-authentication-token-expiration:"):
            value = line.split(":", 1)[1].strip()            # es. "2026-11-27 00:00:00 UTC"
            return dt.datetime.strptime(value.replace(" UTC", ""), "%Y-%m-%d %H:%M:%S")
        if not line.strip():
            break                                         # fine degli header
    return None


def level(days: float, values: dict) -> str:
    if days <= values["expiry.alert_days"]:
        return "ALERT"
    if days <= values["expiry.warning_days"]:
        return "WARNING"
    return "OK"


def collect(values: dict) -> list[dict]:
    now = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
    items = []
    for ep in [x.strip() for x in values["expiry.endpoints"].split(",") if x.strip()]:
        item = {"key": f"cert:{ep}", "name": f"Certificato HTTPS {ep}", "expires": None, "days": None}
        try:
            exp = cert_expiry(ep)
            item.update(expires=exp.isoformat(timespec="minutes"), days=round((exp - now).total_seconds() / 86400, 1))
            item["status"] = level(item["days"], values)
        except Exception as exc:  # noqa: BLE001
            item.update(status="UNKNOWN", error=str(exc)[:200])
        items.append(item)
    if values["expiry.github"]:
        item = {"key": "github-token", "name": "Token GitHub (gh)", "expires": None, "days": None}
        try:
            exp = github_token_expiry()
            if isinstance(exp, str):
                item.update(status="UNKNOWN", error=exp)
            elif exp is None:
                item.update(status="OK", note="senza scadenza")
            else:
                item.update(expires=exp.isoformat(timespec="minutes"), days=round((exp - now).total_seconds() / 86400, 1))
                item["status"] = level(item["days"], values)
        except Exception as exc:  # noqa: BLE001
            item.update(status="UNKNOWN", error=str(exc)[:200])
        items.append(item)
    return items


def main(cfg: Config, dry_run: bool) -> int:
    with db.connect(cfg.database) as conn:
        values = settings_mod.load(conn, cfg)
    items = collect(values)
    for it in items:
        log.info("%s: %s, %s giorni%s", it["name"], it["status"], it["days"], f" ({it.get('error') or it.get('note')})"
                 if it.get("error") or it.get("note") else "")
    if dry_run:
        return 0

    now = dt.datetime.now()
    with db.connect(cfg.database) as conn:
        db.state_set(conn, "expiry:last", {"time": now.isoformat(timespec="seconds"), "items": items})
        rule = settings_mod.policy(values, "expiry")
        lang = i18n.lang_of(values)
        tr = i18n.translator(lang)
        for it in items:
            if it["status"] == "UNKNOWN":
                continue
            state = notifier.AlertState(conn, f"expiry:{it['key']}")
            should_notify, reason, _prev = state.evaluate(it["status"], rule)
            if should_notify:
                name = i18n.translate_stored(it["name"], lang)
                if it["status"] == "OK":
                    subject = tr("{nome}: rinnovato", nome=name)
                    body = tr("{nome} ora scade il {data}.", nome=name, data=it["expires"][:10] if it["expires"] else tr("mai"))
                else:
                    subject = tr("{nome} scade tra {giorni} giorni", nome=name, giorni=max(0, int(it["days"])))
                    body = "\n".join(x for x in (notifier.reason_line(reason, state, lang),
                                                 tr("{nome} scade il {data} (tra {giorni} giorni).", nome=name,
                                                    data=it["expires"][:10], giorni=f"{it['days']:.0f}"),
                                                 tr("Procedura di rinnovo: {doc}", doc="docs/scadenze.md")) if x)
                if notifier.dispatch(conn, cfg, "expiry", subject, body, detected_at=now):
                    state.mark_notified()
            state.save()
    return 0


def entrypoint() -> None:
    run("expiry", "Controlla la scadenza di certificati HTTPS e token GitHub", main)


if __name__ == "__main__":
    entrypoint()
