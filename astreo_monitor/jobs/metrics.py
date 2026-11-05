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

from .. import db, events, heartbeat, i18n, models, notifier, services_store
from ..integrations import docker as docker_mod
from ..integrations import pihole as pihole_mod
from .. import settings as settings_mod
from .. import hosts as hosts_mod
from ..collectors import sensors, services, system
from ..config import Config
from .base import run

log = logging.getLogger("job.metrics")



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

        stamp = now.replace(microsecond=0)
        conn.execute(models.system_metrics.insert().values(
            timestamp=stamp, cpu_pct=cpu, load1=ld["load1"], load5=ld["load5"], load15=ld["load15"],
            mem_used_pct=mem["used_pct"], mem_used_mb=mem["used_mb"], swap_used_pct=mem["swap_used_pct"],
            disk_used_pct=disk_pct, source="v2"))
        if temps:
            conn.execute(models.system_temperature.insert(),
                         [{"timestamp": stamp, "adapter": t["adapter"], "device": t["device"], "temperature": t["value"]}
                          for t in temps])
        db.state_set(conn, "metrics:cpu_times", curr_times)

        log.info("Salvato: CPU %.2f%% | load %s | RAM %.1f%% | disco %s%% | %d temperature",
                 cpu, ld["load1"], mem["used_pct"], disk_pct, len(temps))

        # --- Allarmi -------------------------------------------------------
        values = settings_mod.load(conn, cfg)
        lang = i18n.lang_of(values)
        _ = i18n.translator(lang)
        lim = hosts_mod.local_limits(conn, cfg)          # 4.2: soglie del server centrale (o quelle generali)
        checks = []
        if temps:
            hottest = max(temps, key=lambda t: t["value"])
            checks.append((
                "temperature",
                level(hottest["value"], lim["temp_warning"], lim["temp_alert"]),
                _("Temperatura massima {t} °C ({sensore})", t=f"{hottest['value']:.1f}",
                  sensore=f"{hottest['adapter']} / {hottest['device']}") + "\n"
                + _("Soglie: warning {w} °C, alert {a} °C", w=lim["temp_warning"], a=lim["temp_alert"]),
            ))
        checks.append((
            "disk",
            level(disk_pct, lim["disk_warning"], lim["disk_alert"]),
            _("Disco {disco} occupato al {pct}%", disco=cfg.metrics.root_disk, pct=disk_pct) + "\n"
            + _("Soglie: warning {w}%, alert {a}%", w=lim["disk_warning"], a=lim["disk_alert"]),
        ))

        for key, status, text in checks:
            state = notifier.AlertState(conn, key)
            should_notify, reason, previous = state.evaluate(status, settings_mod.policy(values, key))
            if should_notify:
                name = _({"temperature": "Temperatura", "disk": "Disco"}[key])
                subject = _("Allarme {nome} rientrato", nome=name.lower()) if status == "OK" else f"{name}: {status}"
                body = "\n".join(x for x in (notifier.reason_line(reason, state, lang), text,
                                              _("Stato precedente: {stato}", stato=previous or "n/d")) if x)
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
                subject = _("Servizio {nome} di nuovo attivo", nome=s["label"]) if s["up"] else \
                    _("Servizio {nome} fermo ({stato})", nome=s["label"], stato=s["state"])
                body = "\n".join(x for x in (
                    notifier.reason_line(reason, state, lang),
                    _("Servizio: {nome} ({unit})", nome=s["label"], unit=s["unit"]), _("Stato: {stato}", stato=s["state"]),
                    _("Stato precedente: {stato}", stato=previous or "n/d"),
                    _("Dettaglio: {comando}", comando=f"systemctl status {s['unit']}")) if x)
                if notifier.dispatch(conn, cfg, "services", subject, body, detected_at=now):
                    state.mark_notified()
            state.save()

        # --- Eventi per i grafici e moduli opzionali ------------------------
        for name, func in (("eventi", record_events), ("docker", check_docker), ("pi-hole", check_pihole)):
            try:
                func(conn, cfg, values, now)
            except Exception as exc:  # noqa: BLE001
                log.error("Controllo %s non riuscito: %s", name, exc)

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


def record_events(conn, cfg, values, now) -> None:
    """Riavvii e cambi di stato dei servizi monitorati, come eventi sui grafici."""
    if not db.state_get(conn, "events:reboots_imported"):
        n = events.backfill_reboots(conn)
        db.state_set(conn, "events:reboots_imported", True)
        log.info("Importati %d riavvii passati come eventi", n)
    boot = dt.datetime.fromtimestamp(system.cpu_times_snapshot()["boot_time"]).replace(second=0, microsecond=0)
    if db.state_get(conn, "events:boot") != boot.isoformat():
        events.record(conn, "reboot", "info", "Riavvio del server", "", f"reboot:{boot:%Y%m%d%H%M}", boot)
        db.state_set(conn, "events:boot", boot.isoformat())

    last = db.state_get(conn, "events:services", {}) or {}
    current = {}
    for s in services.statuses(services_store.monitored(conn, cfg)):
        current[s["unit"]] = s["state"]
        before = last.get(s["unit"])
        if before is not None and (before == "active") != s["up"]:
            events.record(conn, "service", "info" if s["up"] else "alert",
                          f"Servizio {s['label']} {'ripartito' if s['up'] else 'fermo'}", f"{before} → {s['state']}", when=now)
    db.state_set(conn, "events:services", current)


def check_docker(conn, cfg, values, now) -> None:
    present, _ = docker_mod.detect()
    if not present:
        return
    conts = docker_mod.containers(with_stats=False)
    last = db.state_get(conn, "events:containers", {}) or {}
    current = {}
    rule = settings_mod.policy(values, "docker")
    for c in conts:
        current[c["name"]] = {"state": c["state"], "restarts": c["restart_count"]}
        prev = last.get(c["name"])
        if prev and prev["state"] != c["state"]:
            events.record(conn, "container", "info" if c["state"] == "running" else "alert",
                          f"Container {c['name']}: {c['state']}", f"{prev['state']} → {c['state']}", when=now)
        elif prev and c["restart_count"] > prev.get("restarts", 0):
            events.record(conn, "container", "warning", f"Container {c['name']} riavviato",
                          f"riavvii totali: {c['restart_count']}", when=now)
        status = docker_mod.evaluate(c)
        state = notifier.AlertState(conn, f"docker:{c['name']}")
        should_notify, reason, previous = state.evaluate(status, rule)
        if should_notify:
            lang = i18n.lang_of(values)
            _ = i18n.translator(lang)
            subject = _("Container {nome} di nuovo regolare", nome=c["name"]) if status == "OK" else f"Container {c['name']}: {c['state']}"
            body = "\n".join(x for x in (notifier.reason_line(reason, state, lang),
                                          f"Container: {c['name']} ({c['image']})", _("Stato: {stato}", stato=c["status"]),
                                          _("Riavvii: {n} — politica: {politica}", n=c["restart_count"],
                                            politica=c["restart_policy"] or _("nessuna")),
                                          _("Dettaglio: {comando}", comando=f"docker logs --tail 50 {c['name']}")) if x)
            if notifier.dispatch(conn, cfg, "docker", subject, body, detected_at=now):
                state.mark_notified()
        state.save()
    db.state_set(conn, "events:containers", current)


def check_pihole(conn, cfg, values, now) -> None:
    present, _ = pihole_mod.detect(values["pihole.url"])
    if not present or not values["pihole.password"]:
        return
    client = pihole_mod.Client(values["pihole.url"], values["pihole.password"])
    ov, err = None, None
    try:
        ov = client.overview()
    except Exception as exc:  # noqa: BLE001
        err = str(exc)[:200]
    finally:
        client.logout()
    status, text = pihole_mod.evaluate(ov, err)
    lang = i18n.lang_of(values)
    _ = i18n.translator(lang)
    state = notifier.AlertState(conn, "pihole")
    should_notify, reason, previous = state.evaluate(status, settings_mod.policy(values, "pihole"))
    if previous is not None and previous != status:
        events.record(conn, "pihole", "info" if status == "OK" else "alert", f"Pi-hole: {status}", text, when=now)
    if should_notify:
        subject = _("Pi-hole di nuovo regolare") if status == "OK" else f"Pi-hole: {status}"
        body = "\n".join(x for x in (notifier.reason_line(reason, state, lang), events.translate(text, lang),
                                      _("Controllo: {comando}", comando="systemctl status pihole-FTL --no-pager")) if x)
        if notifier.dispatch(conn, cfg, "pihole", subject, body, detected_at=now):
            state.mark_notified()
    state.save()


def entrypoint() -> None:
    run("metrics", "Salva su DB CPU, load, memoria, disco e temperature", main)


if __name__ == "__main__":
    entrypoint()
