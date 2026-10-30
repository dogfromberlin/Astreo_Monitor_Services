"""Raccolta periodica di CPU, load, memoria, disco e temperature.

- La CPU è la media ESATTA dell'intervallo trascorso dall'esecuzione
  precedente (differenza dei contatori cpu_times salvati in monitor_state);
  al primo avvio o dopo un riavvio si usa un campione di 5 secondi.
- Tutto viene scritto in una sola transazione.
- Allarmi a cambio di stato per temperatura massima e disco principale.
"""
from __future__ import annotations

import datetime as dt
import logging

from .. import db, heartbeat, notifier, services_store
from .. import settings as settings_mod
from ..collectors import sensors, services, system
from ..config import Config
from .base import run

log = logging.getLogger("job.metrics")

INSERT_METRICS = """
INSERT INTO system_metrics ([timestamp], cpu_pct, load1, load5, load15,
                            mem_used_pct, mem_used_mb, swap_used_pct, disk_used_pct, source)
VALUES (CONVERT(datetime2(0), %s, 126), %s, %s, %s, %s, %s, %s, %s, %s, 'v2')
"""
INSERT_TEMP = """
INSERT INTO system_temperature ([timestamp], adapter, device, temperature)
VALUES (CONVERT(datetime, %s, 126), %s, %s, %s)
"""


def level(value: float, warning: float, alert: float) -> str:
    if value >= alert:
        return "ALERT"
    if value >= warning:
        return "WARNING"
    return "OK"


def main(cfg: Config, dry_run: bool) -> int:
    now = dt.datetime.now()
    curr_times = system.cpu_times_snapshot()
    mem = system.memory()
    ld = system.load()
    disk_pct = system.disk_used_pct(cfg.metrics.root_disk)
    temps = sensors.read()

    if dry_run:
        cpu = system.cpu_percent(5)
        log.info("CPU %.1f%% | load %s | RAM %.1f%% | disco %s%% | %d sensori",
                 cpu, ld["load1"], mem["used_pct"], disk_pct, len(temps))
        for t in temps:
            log.info("  %s / %s: %.1f °C", t["adapter"], t["device"], t["value"])
        return 0

    with db.connect(cfg.database) as conn:
        prev_times = db.state_get(conn, "metrics:cpu_times")
        cpu = system.cpu_percent_between(prev_times, curr_times)
        if cpu is None:
            log.info("Nessuno snapshot CPU precedente valido: campiono 5 secondi")
            cpu = system.cpu_percent(5)
            curr_times = system.cpu_times_snapshot()

        stamp = db.ts(now)
        db.execute(conn, INSERT_METRICS, (
            stamp, cpu, ld["load1"], ld["load5"], ld["load15"],
            mem["used_pct"], mem["used_mb"], mem["swap_used_pct"], disk_pct,
        ))
        db.execute_many(conn, INSERT_TEMP, [(stamp, t["adapter"], t["device"], t["value"]) for t in temps])
        db.state_set(conn, "metrics:cpu_times", curr_times)

        log.info("Salvato: CPU %.2f%% | load %s | RAM %.1f%% | disco %s%% | %d temperature",
                 cpu, ld["load1"], mem["used_pct"], disk_pct, len(temps))

        # --- Allarmi -------------------------------------------------------
        checks = []
        if temps:
            hottest = max(temps, key=lambda t: t["value"])
            checks.append((
                "temperature",
                level(hottest["value"], cfg.metrics.temp_warning, cfg.metrics.temp_alert),
                f"Temperatura massima {hottest['value']:.1f} °C ({hottest['adapter']} / {hottest['device']})\n"
                f"Soglie: warning {cfg.metrics.temp_warning} °C, alert {cfg.metrics.temp_alert} °C",
            ))
        checks.append((
            "disk",
            level(disk_pct, cfg.metrics.disk_warning, cfg.metrics.disk_alert),
            f"Disco {cfg.metrics.root_disk} occupato al {disk_pct}%\n"
            f"Soglie: warning {cfg.metrics.disk_warning}%, alert {cfg.metrics.disk_alert}%",
        ))

        values = settings_mod.load(conn, cfg)
        for key, status, text in checks:
            state = notifier.AlertState(conn, key)
            should_notify, reason, previous = state.evaluate(status, settings_mod.policy(values, key))
            if should_notify:
                name = {"temperature": "Temperatura", "disk": "Disco"}[key]
                subject = f"Allarme {name.lower()} rientrato" if status == "OK" else f"{name}: {status}"
                body = "\n".join(x for x in (notifier.reason_line(reason, state), text,
                                              f"Stato precedente: {previous or 'n/d'}") if x)
                if notifier.dispatch(conn, cfg, key, subject, body, detected_at=now):
                    state.mark_notified()
            state.save()

        # --- Servizi con avviso attivo -----------------------------------------
        watched = [r for r in services_store.monitored(conn, cfg) if r["notify"]]
        rule = settings_mod.policy(values, "services")
        for s in services.statuses(watched):
            state = notifier.AlertState(conn, f"service:{s['unit']}")
            status = "OK" if s["up"] else "ALERT"
            should_notify, reason, previous = state.evaluate(status, rule)
            if should_notify:
                subject = f"Servizio {s['label']} di nuovo attivo" if s["up"] else f"Servizio {s['label']} fermo ({s['state']})"
                body = "\n".join(x for x in (
                    notifier.reason_line(reason, state),
                    f"Servizio: {s['label']} ({s['unit']})", f"Stato: {s['state']}",
                    f"Stato precedente: {previous or 'n/d'}", f"Dettaglio: systemctl status {s['unit']}") if x)
                if notifier.dispatch(conn, cfg, "services", subject, body, detected_at=now):
                    state.mark_notified()
            state.save()

        # --- Avvisi trattenuti dalla fascia di silenzio ----------------------
        problems = []
        try:
            n = notifier.flush_queue(conn, cfg)
            if n:
                log.info("Recapitati %d avvisi posticipati", n)
        except Exception as exc:  # noqa: BLE001
            log.error("Recapito degli avvisi posticipati non riuscito: %s", exc)
            problems.append(f"coda avvisi: {exc}")

        # --- Heartbeat: "sono vivo" verso il servizio esterno ----------------
        heartbeat.ping(conn, values, ok=not problems,
                       message=f"CPU {cpu:.1f}% RAM {mem['used_pct']}% disco {disk_pct}%" + (f" | {'; '.join(problems)}" if problems else ""))
    return 0


def entrypoint() -> None:
    run("metrics", "Salva su DB CPU, load, memoria, disco e temperature", main)


if __name__ == "__main__":
    entrypoint()
