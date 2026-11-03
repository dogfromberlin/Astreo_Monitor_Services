"""Agente Linux: raccoglie i dati di questo server e li invia al server centrale.

Avviato ogni minuto da astreo-agent.timer. Non apre porte, non ha database né dashboard.
  - servizi: a ogni cambio di stato e comunque ogni 5 minuti
  - metriche (CPU media esatta del periodo, load, memoria, swap, disco) e temperature: ogni 5 minuti
  - riavvio: quando l'ora di avvio cambia
Ciò che non si riesce a inviare resta in coda (state_dir/queue) fino a 24 ore.

    python -m astreo_monitor.agent.run [-c /etc/astreo-agent/agent.ini] [--dry-run]
"""
from __future__ import annotations

import argparse
import configparser
import datetime as dt
import json
import logging
import os
import platform
import sys
import time

import requests

from .. import __version__
from ..collectors import sensors, services, system

log = logging.getLogger("agent")
DEFAULT_CONFIG = "/etc/astreo-agent/agent.ini"
METRICS_EVERY = 290          # secondi (il timer gira ogni minuto)
SERVICES_EVERY = 290
QUEUE_MAX_AGE = 24 * 3600
BATCH = 200


class Agent:
    def __init__(self, path: str):
        cp = configparser.ConfigParser(interpolation=None)
        if not cp.read(path, encoding="utf-8"):
            raise SystemExit(f"Configurazione dell'agente non trovata: {path}")
        a = cp["agent"]
        self.central = a["central"].rstrip("/")
        self.token = open(a.get("token_file", "/etc/astreo-agent/token"), encoding="utf-8").read().strip()
        self.ca = a.get("ca_file", "/etc/astreo-agent/central-ca.crt")
        self.root_disk = a.get("root_disk", "/")
        self.dir = a.get("state_dir", "/var/lib/astreo-agent")
        self.queue = os.path.join(self.dir, "queue")
        os.makedirs(self.queue, mode=0o700, exist_ok=True)
        self.state_path = os.path.join(self.dir, "state.json")
        try:
            self.state = json.load(open(self.state_path, encoding="utf-8"))
        except (OSError, ValueError):
            self.state = {}

    # ------------------------------------------------------------------ raccolta
    def collect(self, now: dt.datetime) -> list[dict]:
        items = []
        iso = now.isoformat(timespec="seconds")
        boot = dt.datetime.fromtimestamp(system.cpu_times_snapshot()["boot_time"]).replace(microsecond=0).isoformat()
        if self.state.get("boot") != boot:
            if self.state.get("boot"):                       # al primo avvio dell'agente non è un riavvio
                items.append({"type": "boot", "time": iso, "boot_time": boot})
            self.state["boot"] = boot
        units = self.state.get("services", [])
        if units:
            current = [{"unit": s["unit"], "label": s["label"], "up": s["up"], "state": s["state"]}
                       for s in services.statuses([{"unit": u, "label": u.removesuffix(".service")} for u in units])]
            sig = [(s["unit"], s["up"]) for s in current]
            if sig != [tuple(x) for x in self.state.get("services_sig", [])] or \
                    time.time() - self.state.get("services_sent", 0) >= SERVICES_EVERY:
                items.append({"type": "services", "time": iso, "services": current})
                self.state["services_sig"], self.state["services_sent"] = sig, time.time()
        if time.time() - self.state.get("metrics_sent", 0) >= METRICS_EVERY:
            curr = system.cpu_times_snapshot()
            cpu = system.cpu_percent_between(self.state.get("cpu_times"), curr)
            if cpu is None:
                cpu = system.cpu_percent(2)
                curr = system.cpu_times_snapshot()
            mem, ld = system.memory(), system.load()
            items.append({"type": "metrics", "time": iso, "cpu_pct": round(cpu, 2), "load1": ld["load1"],
                          "load5": ld["load5"], "load15": ld["load15"], "mem_used_pct": mem["used_pct"],
                          "mem_used_mb": mem["used_mb"], "mem_total_mb": mem.get("total_mb"),
                          "swap_used_pct": mem["swap_used_pct"], "disk_used_pct": system.disk_used_pct(self.root_disk),
                          "uptime_s": int(time.time() - curr["boot_time"])})
            temps = [{"adapter": t["adapter"], "device": t["device"], "value": t["value"]} for t in sensors.read()]
            if temps:
                items.append({"type": "temperatures", "time": iso, "sensors": temps[:64]})
            self.state["cpu_times"], self.state["metrics_sent"] = curr, time.time()
        return items

    # ---------------------------------------------------------------- coda e invio
    def enqueue(self, items: list[dict]) -> None:
        for i, it in enumerate(items):
            name = os.path.join(self.queue, f"{time.time_ns()}-{i:03d}.json")
            with open(name + ".tmp", "w", encoding="utf-8") as f:
                json.dump(it, f)
            os.replace(name + ".tmp", name)

    def pending(self) -> list[str]:
        files = sorted(f for f in os.listdir(self.queue) if f.endswith(".json"))
        limit = time.time_ns() - QUEUE_MAX_AGE * 1_000_000_000
        old = [f for f in files if int(f.split("-")[0]) < limit]
        for f in old:
            os.remove(os.path.join(self.queue, f))
        if old:
            log.warning("Scartati %d dati più vecchi di 24 ore (server centrale irraggiungibile)", len(old))
        return [f for f in files if f not in old]

    def send(self) -> int:
        """Invia la coda a blocchi. Ritorna gli elementi consegnati."""
        sent = 0
        files = self.pending()
        while files:
            batch, files = files[:BATCH], files[BATCH:]
            items = []
            for f in batch:
                try:
                    items.append(json.load(open(os.path.join(self.queue, f), encoding="utf-8")))
                except (OSError, ValueError):
                    os.remove(os.path.join(self.queue, f))
            payload = {"agent": {"version": __version__, "kind": "linux", "hostname": platform.node(),
                                 "os": os_info()}, "items": items}
            try:
                r = requests.post(f"{self.central}/api/v1/agents/ingest", json=payload, timeout=30,
                                  verify=self.ca if os.path.exists(self.ca) else True,
                                  headers={"Authorization": f"Bearer {self.token}",
                                           "User-Agent": f"astreo-agent/{__version__}"})
            except requests.RequestException as exc:
                log.warning("Server centrale non raggiungibile (%s): %d dati in coda", exc.__class__.__name__,
                            len(batch) + len(files))
                return sent
            if r.status_code == 200:
                for f in batch:
                    try:
                        os.remove(os.path.join(self.queue, f))
                    except OSError:
                        pass
                sent += len(batch)
                answer = r.json()
                self.state["services"] = [u for u in answer.get("services", []) if isinstance(u, str)][:60]
            elif r.status_code == 400:
                log.error("Dati rifiutati dal centrale (%s): li scarto", r.text[:200])
                for f in batch:
                    os.remove(os.path.join(self.queue, f))
            else:
                log.error("Il centrale ha risposto %d (%s): riprovo al prossimo giro", r.status_code, r.text[:120])
                return sent
        return sent

    def save(self) -> None:
        with open(self.state_path + ".tmp", "w", encoding="utf-8") as f:
            json.dump(self.state, f)
        os.replace(self.state_path + ".tmp", self.state_path)


def os_info() -> str:
    try:
        rel = dict(line.rstrip().split("=", 1) for line in open("/etc/os-release") if "=" in line)
        return rel.get("PRETTY_NAME", "Linux").strip('"')
    except OSError:
        return f"{platform.system()} {platform.release()}"


def main() -> int:
    p = argparse.ArgumentParser(prog="astreo_monitor.agent.run", description="Agente di Astreo Monitor")
    p.add_argument("-c", "--config", default=os.environ.get("ASTREO_AGENT_CONFIG", DEFAULT_CONFIG))
    p.add_argument("--dry-run", action="store_true", help="raccoglie e mostra i dati senza inviarli")
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s", stream=sys.stdout)
    agent = Agent(args.config)
    items = agent.collect(dt.datetime.now().replace(microsecond=0))
    if args.dry_run:
        print(json.dumps(items, indent=1, ensure_ascii=False))
        return 0
    agent.enqueue(items)
    sent = agent.send()
    agent.save()
    if sent:
        log.info("Inviati %d dati al server centrale", sent)
    return 0


if __name__ == "__main__":
    sys.exit(main())
