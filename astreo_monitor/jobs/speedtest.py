"""Speedtest della connessione internet tramite gli endpoint di Cloudflare.

Download: GET  https://speed.cloudflare.com/__down?bytes=N
Upload:   POST https://speed.cloudflare.com/__up   (corpo da N byte)

Per ogni giro si aprono `streams` connessioni in parallelo e si misura il
throughput complessivo; il risultato è la MEDIANA dei giri riusciti.
I giri falliti vengono scartati (non contano come 0).

Stati: OK, WARNING, ALERT, DOWN (connessione assente). Quando avvisare lo decide
la regola configurata in Impostazioni (alert.speedtest.*): di default solo se lo
stato peggiora, più un promemoria dopo 36 ore di situazione anomala.
"""
from __future__ import annotations

import datetime as dt
import logging
import os
import statistics
import time
from concurrent.futures import ThreadPoolExecutor

import requests

from dataclasses import dataclass

from .. import __version__, db, i18n, models, notifier
from .. import settings as settings_mod
from ..config import Config
from .base import run

log = logging.getLogger("job.speedtest")

BASE = "https://speed.cloudflare.com"
HEADERS = {"User-Agent": f"astreo-monitor/{__version__}"}
PROVIDER = "cloudflare"



@dataclass
class Params:
    """Parametri effettivi: config come base, impostazioni della dashboard sopra."""
    download_alert: float
    download_warning: float
    upload_alert: float
    upload_warning: float
    streams: int
    rounds: int
    download_bytes: int
    upload_bytes: int
    timeout: int
    enabled: bool = True


def effective_params(cfg: Config, values: dict | None) -> Params:
    c = cfg.speedtest
    if values is None:
        return Params(c.download_alert, c.download_warning, c.upload_alert, c.upload_warning, c.streams,
                      c.rounds, c.download_bytes, c.upload_bytes, c.timeout)
    v = values
    return Params(
        v["speedtest.download_alert"], v["speedtest.download_warning"],
        v["speedtest.upload_alert"], v["speedtest.upload_warning"],
        v["speedtest.streams"], v["speedtest.rounds"],
        v["speedtest.download_mb"] * 1_000_000, v["speedtest.upload_mb"] * 1_000_000,
        c.timeout, v["speedtest.enabled"],
    )


def latency_ms(timeout: int, samples: int = 5) -> float | None:
    """Mediana del tempo di risposta di una richiesta minima (include TLS keep-alive)."""
    values = []
    with requests.Session() as s:
        s.headers.update(HEADERS)
        for _ in range(samples):
            try:
                t0 = time.perf_counter()
                s.get(f"{BASE}/__down?bytes=0", timeout=timeout).raise_for_status()
                values.append((time.perf_counter() - t0) * 1000)
            except requests.RequestException:
                pass
    # Il primo campione include l'handshake: lo scarto se ne ho abbastanza
    if len(values) > 2:
        values = values[1:]
    return round(statistics.median(values), 1) if values else None


def _download_one(nbytes: int, timeout: int) -> int:
    with requests.get(f"{BASE}/__down?bytes={nbytes}", headers=HEADERS, stream=True, timeout=timeout) as r:
        r.raise_for_status()
        total = 0
        for chunk in r.iter_content(chunk_size=256 * 1024):
            total += len(chunk)
        return total


def _upload_one(payload: bytes, timeout: int) -> int:
    r = requests.post(f"{BASE}/__up", data=payload, headers=HEADERS, timeout=timeout)
    r.raise_for_status()
    return len(payload)


def _round(fn, args, streams: int) -> float:
    """Un giro di misura con `streams` connessioni parallele -> Mbps."""
    t0 = time.perf_counter()
    with ThreadPoolExecutor(max_workers=streams) as ex:
        total = sum(ex.map(lambda _: fn(*args), range(streams)))
    elapsed = time.perf_counter() - t0
    return total * 8 / elapsed / 1_000_000


def measure(fn, args, cfg: Params, label: str) -> float | None:
    results = []
    for i in range(cfg.rounds):
        try:
            mbps = _round(fn, args, cfg.streams)
            results.append(mbps)
            log.info("%s giro %d/%d: %.1f Mbps", label, i + 1, cfg.rounds, mbps)
        except Exception as exc:  # noqa: BLE001
            log.warning("%s giro %d/%d fallito: %s", label, i + 1, cfg.rounds, exc)
    return round(statistics.median(results), 1) if results else None


def classify(dl: float | None, ul: float | None, c: Params) -> str:
    if dl is None and ul is None:
        return "DOWN"
    if (dl is not None and dl < c.download_alert) or (ul is not None and ul < c.upload_alert) or dl is None or ul is None:
        return "ALERT"
    if dl < c.download_warning or ul < c.upload_warning:
        return "WARNING"
    return "OK"


def fmt(v: float | None) -> str:
    return "n/d" if v is None else f"{v:.1f} Mbps"


def main(cfg: Config, dry_run: bool) -> int:
    try:
        with db.connect(cfg.database) as conn:
            values = settings_mod.load(conn, cfg)
    except db.DatabaseError as exc:
        if not dry_run:
            raise
        log.warning("Impostazioni non leggibili dal DB, uso il config: %s", exc)
        values = None
    c = effective_params(cfg, values)
    if not c.enabled:
        if dry_run:
            log.info("Speedtest sospeso dalle Impostazioni: in dry-run misuro comunque")
        else:
            log.info("Speedtest sospeso dalle Impostazioni: nessuna misura")
            return 0

    now = dt.datetime.now()
    error = None

    lat = latency_ms(min(c.timeout, 10))
    if lat is None:
        log.error("Cloudflare non raggiungibile: connessione assente?")
        dl = ul = None
        error = "Endpoint di test non raggiungibile"
    else:
        log.info("Latenza: %.1f ms", lat)
        dl = measure(_download_one, (c.download_bytes, c.timeout), c, "Download")
        payload = os.urandom(c.upload_bytes)
        ul = measure(_upload_one, (payload, c.timeout), c, "Upload")
        if dl is None or ul is None:
            error = "Misura incompleta: " + ", ".join(n for n, v in (("download", dl), ("upload", ul)) if v is None)

    status = classify(dl, ul, c)
    log.info("Risultato: %s | DL %s | UL %s | latenza %s ms", status, fmt(dl), fmt(ul), lat)

    if dry_run:
        return 0

    with db.connect(cfg.database) as conn:
        conn.execute(models.speedtest_results.insert().values(
            timestamp=now.replace(microsecond=0), download_mbps=dl, upload_mbps=ul, latency_ms=lat,
            status=status, provider=PROVIDER, error=error))
        state = notifier.AlertState(conn, "speedtest")
        should_notify, reason, previous = state.evaluate(status, settings_mod.policy(settings_mod.load(conn, cfg), "speedtest"))
        if should_notify:
            lang = i18n.lang_of(settings_mod.load(conn, cfg))
            _ = i18n.translator(lang)
            subject = _("Connessione internet tornata OK") if status == "OK" else _("Connessione internet: {stato}", stato=status)
            intro = notifier.reason_line(reason, state, lang)
            body = (
                (f"{intro}\n\n" if intro else "")
                + _("Esito speedtest delle {quando}", quando=f"{now:%d/%m/%Y %H:%M}") + "\n\n"
                + _("Stato:      {stato} (precedente: {prima})", stato=status, prima=previous or "n/d") + "\n"
                + f"Download:   {fmt(dl)}  (warning < {c.download_warning:g}, alert < {c.download_alert:g})\n"
                + f"Upload:     {fmt(ul)}  (warning < {c.upload_warning:g}, alert < {c.upload_alert:g})\n"
                + _("Latenza:    {ms} ms", ms=lat if lat is not None else "n/d") + "\n"
            )
            if error:
                body += "\n" + _("Dettaglio: {comando}", comando=error) + "\n"
            if notifier.dispatch(conn, cfg, "speedtest", subject, body, detected_at=now):
                state.mark_notified()
        state.save()
    return 0


def entrypoint() -> None:
    run("speedtest", "Misura download/upload/latenza e salva il risultato su DB", main)


if __name__ == "__main__":
    entrypoint()
