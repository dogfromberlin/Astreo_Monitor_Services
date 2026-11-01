"""Salute del sistema: dischi (SMART) e aggiornamenti in sospeso. Ogni 6 ore.

I dati SMART li scrive astreo-smart-collect.service (root) pochi minuti prima.
Stato degli aggiornamenti: WARNING se ci sono aggiornamenti di sicurezza da
installare o se il sistema chiede un riavvio.
"""
from __future__ import annotations

import datetime as dt
import logging

from .. import db, i18n, notifier
from .. import settings as settings_mod
from ..collectors import smart, updates
from ..config import Config
from .base import run

log = logging.getLogger("job.system_health")
STALE_HOURS = 24


def main(cfg: Config, dry_run: bool) -> int:
    now = dt.datetime.now()
    with db.connect(cfg.database) as conn:
        values = settings_mod.load(conn, cfg)

    disks = smart.read_disks()
    for d in disks:
        d["status"], d["reasons"] = smart.evaluate(d, values["smart.temp_warning"], values["smart.wear_warning"])
        if d.get("read_at") and now - dt.datetime.fromisoformat(d["read_at"]) > dt.timedelta(hours=STALE_HOURS):
            d["status"], d["reasons"] = "UNKNOWN", [f"dati SMART fermi dal {d['read_at']}: astreo-smart-collect non gira"]
        log.info("Disco %s (%s): %s %s", d["device"], d.get("model"), d["status"], "; ".join(d["reasons"]))
    if not disks:
        log.warning("Nessun dato SMART in %s: astreo-smart-collect.timer è attivo?", smart.SMART_DIR)

    pend = updates.pending()
    rb = updates.reboot()
    reasons = []
    if pend.get("security"):
        reasons.append(f"{len(pend['security'])} aggiornamenti di sicurezza da installare")
    if rb["required"]:
        reasons.append(f"riavvio richiesto dal {rb['since'].replace('T', ' ')}")
    upd_status = "WARNING" if reasons else "OK"
    log.info("Aggiornamenti: %s (%d in sospeso, %d di sicurezza, riavvio %s)", upd_status, pend.get("total", 0),
             len(pend.get("security", [])), "richiesto" if rb["required"] else "no")
    if dry_run:
        return 0

    with db.connect(cfg.database) as conn:
        db.state_set(conn, "health:last", {"time": now.isoformat(timespec="seconds"), "disks": disks,
                                           "updates": {**pend, "reboot": rb, "status": upd_status, "reasons": reasons}})
        lang = i18n.lang_of(values)
        tr = i18n.translator(lang)
        # --- dischi
        for d in disks:
            if d["status"] == "UNKNOWN":
                continue
            state = notifier.AlertState(conn, f"smart:{d['device']}")
            ok, reason, _ = state.evaluate(d["status"], settings_mod.policy(values, "smart"))
            if ok:
                name = tr("Disco {p0}", p0=f"{d['device']} ({d.get('model') or tr('sconosciuto')})")
                subject = tr("{nome}: nella norma", nome=name) if d["status"] == "OK" else f"{name}: {d['status']}"
                body = "\n".join(x for x in (
                    notifier.reason_line(reason, state, lang),
                    "\n".join(f"- {i18n.translate_stored(r, lang)}" for r in d["reasons"]) or tr("Nessuna anomalia."),
                    tr("Temperatura: {t} °C — ore di accensione: {ore}", t=d.get("temperature"), ore=d.get("power_on_hours"))
                    + (tr(" — usura: {p0}%", p0=d["wear_used_pct"]) if d.get("wear_used_pct") is not None else ""),
                    tr("Dettaglio: {comando}", comando="sudo smartctl -a /dev/" + d["device"]),
                    tr("Con un disco in ALERT verifica subito che i backup siano recenti (docs/backup-database.md).")) if x)
                if notifier.dispatch(conn, cfg, "smart", subject, body, detected_at=now):
                    state.mark_notified()
            state.save()
        # --- aggiornamenti
        state = notifier.AlertState(conn, "updates")
        ok, reason, _ = state.evaluate(upd_status, settings_mod.policy(values, "updates"))
        if ok:
            if upd_status == "OK":
                subject = tr("Sistema aggiornato")
                body = tr("Nessun aggiornamento di sicurezza in sospeso e nessun riavvio richiesto.")
            else:
                subject = tr("Aggiornamenti di sistema in sospeso")
                lines = [notifier.reason_line(reason, state, lang)] + [f"- {i18n.translate_stored(r, lang)}" for r in reasons]
                if pend.get("security"):
                    lines += ["", tr("Pacchetti di sicurezza: {elenco}", elenco=", ".join(pend["security"][:25])
                                     + (" …" if len(pend["security"]) > 25 else ""))]
                lines += ["", tr("Per installarli (sul server):"), "sudo apt update && sudo apt upgrade",
                          tr("e, se richiesto, sudo reboot")]
                body = "\n".join(x for x in lines if x is not None)
            if notifier.dispatch(conn, cfg, "updates", subject, body, detected_at=now):
                state.mark_notified()
        state.save()
    return 0


def entrypoint() -> None:
    run("system_health", "Controlla dischi (SMART) e aggiornamenti di sistema", main)


if __name__ == "__main__":
    entrypoint()
