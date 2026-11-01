"""Controllo dell'IP pubblico.

Interroga i provider configurati, valida le risposte con il modulo
`ipaddress` e sceglie il valore indicato dalla maggioranza. Se nessun
provider risponde con un IP valido NON aggiorna nulla (niente falsi allarmi).
Ogni variazione viene storicizzata in public_ip_history e notificata.
"""
from __future__ import annotations

import datetime as dt
import ipaddress
import logging
from collections import Counter

import requests

from .. import __version__, db, models, notifier
from ..config import Config
from .base import run

log = logging.getLogger("job.public_ip")

HEADERS = {"User-Agent": f"astreo-monitor/{__version__}"}
STATE_KEY = "publicip:current"


def query_providers(providers: list[str], timeout: int) -> list[str]:
    found = []
    for url in providers:
        try:
            r = requests.get(url, headers=HEADERS, timeout=timeout)
            r.raise_for_status()
            ip = str(ipaddress.ip_address(r.text.strip()))
            log.info("%s -> %s", url, ip)
            found.append(ip)
        except (requests.RequestException, ValueError) as exc:
            log.warning("%s non utilizzabile: %s", url, exc)
    return found


def main(cfg: Config, dry_run: bool) -> int:
    now = dt.datetime.now()
    answers = query_providers(cfg.publicip.providers, cfg.publicip.timeout)
    if not answers:
        log.error("Nessun provider ha restituito un IP valido: controllo saltato")
        return 1
    ip, votes = Counter(answers).most_common(1)[0]
    if len(answers) > 1 and votes <= len(answers) / 2:
        log.error("I provider non concordano %s e manca una maggioranza: controllo saltato", answers)
        return 1
    if votes < len(answers):
        log.warning("I provider non concordano %s: uso %s (maggioranza)", answers, ip)

    if dry_run:
        log.info("IP pubblico attuale: %s", ip)
        return 0

    with db.connect(cfg.database) as conn:
        current = db.state_get(conn, STATE_KEY) or {}
        previous = current.get("ip")
        if previous == ip:
            log.info("IP invariato: %s", ip)
            current["checked_at"] = now.isoformat(timespec="seconds")
        else:
            conn.execute(models.public_ip_history.insert().values(
                timestamp=now.replace(microsecond=0), ip=ip, previous_ip=previous))
            current = {"ip": ip, "since": now.isoformat(timespec="seconds"), "checked_at": now.isoformat(timespec="seconds")}
            if previous is None:
                log.info("Primo rilevamento IP pubblico: %s", ip)
            else:
                log.warning("IP pubblico cambiato: %s -> %s", previous, ip)
                from .. import i18n
                from .. import settings as settings_mod
                _ = i18n.translator(i18n.lang_of(settings_mod.load(conn, cfg)))
                notifier.dispatch(
                    conn, cfg, "publicip",
                    _("IP pubblico cambiato in {ip}", ip=ip),
                    _("L'IP pubblico del server è cambiato alle {quando}.", quando=f"{now:%d/%m/%Y %H:%M}") + "\n\n"
                    + _("Precedente: {ip}", ip=previous) + "\n" + _("Attuale:    {ip}", ip=ip) + "\n\n"
                    + _("Aggiorna eventuali DNS, client VPN o regole che usano l'indirizzo."),
                )
        db.state_set(conn, STATE_KEY, current)
    return 0


def entrypoint() -> None:
    run("public_ip", "Controlla l'IP pubblico e notifica le variazioni", main)


if __name__ == "__main__":
    entrypoint()
