"""Agente Linux: raccoglie i dati di questo server e li invia al server centrale.

Avviato ogni minuto da astreo-agent.timer. Non apre porte, non ha database né dashboard.
  - servizi: a ogni cambio di stato e comunque ogni 5 minuti
  - metriche (CPU media esatta del periodo, load, memoria, swap, disco) e temperature: ogni 5 minuti
  - riavvio: quando l'ora di avvio cambia
  - 4.2: dischi (SMART, se c'è smartctl) e aggiornamenti in sospeso: ogni 6 ore; container Docker: ogni 5 minuti
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
import re
import sys
import time

import glob
import shutil
import subprocess

import requests

from .. import __version__
from ..collectors import sensors, services, smart, system, updates
from ..integrations import docker as docker_mod

log = logging.getLogger("agent")
DEFAULT_CONFIG = "/etc/astreo-agent/agent.ini"
METRICS_EVERY = 290          # secondi (il timer gira ogni minuto)
SERVICES_EVERY = 290
HEALTH_EVERY = 6 * 3600       # 4.2: dischi e aggiornamenti
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
        self.refresh_now = False
        # 4.3: comandi dal centrale, solo se permessi qui e con la chiave pubblica salvata all'installazione
        self.allow_commands = a.getboolean("allow_commands", fallback=False)
        self.allow_update = a.getboolean("allow_update", fallback=False)
        conf_dir = os.path.dirname(os.path.abspath(path))
        try:
            self.commands_pub = json.load(open(os.path.join(conf_dir, "commands.pub.json"), encoding="utf-8"))
        except (OSError, ValueError):
            self.commands_pub = None
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
                          "uptime_s": int(time.time() - curr["boot_time"]),
                          "disks": [{k: d[k] for k in ("mountpoint", "device", "fstype", "total_mb", "used_mb", "free_mb", "used_pct")}
                                    for d in system.disks()][:32]})
            temps = [{"adapter": t["adapter"], "device": t["device"], "value": t["value"]} for t in sensors.read()]
            if temps:
                items.append({"type": "temperatures", "time": iso, "sensors": temps[:64]})
            self.state["cpu_times"], self.state["metrics_sent"] = curr, time.time()
            conts = containers()
            if conts is not None:
                items.append({"type": "containers", "time": iso, **conts})
        if time.time() - self.state.get("health_sent", 0) >= HEALTH_EVERY:
            items.append({"type": "health", "time": iso, **health(now)})
            self.state["health_sent"] = time.time()
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

    def send(self, poll: bool = True) -> int:
        """Invia la coda a blocchi. Ritorna gli elementi consegnati.

        4.3: anche con la coda vuota fa una richiesta (poll), così i comandi del centrale arrivano entro un minuto.
        """
        sent = 0
        files = self.pending()
        first = True
        while files or (first and poll):
            first = False
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
                new = [u for u in answer.get("services", []) if isinstance(u, str)][:60]
                if new != self.state.get("services") or answer.get("refresh"):
                    self.refresh_now = True                   # 4.3: servizi cambiati o "Aggiorna": stato subito
                self.state["services"] = new
                if answer.get("commands"):
                    self.run_commands(answer["commands"])
            elif r.status_code == 400:
                log.error("Dati rifiutati dal centrale (%s): li scarto", r.text[:200])
                for f in batch:
                    os.remove(os.path.join(self.queue, f))
            else:
                log.error("Il centrale ha risposto %d (%s): riprovo al prossimo giro", r.status_code, r.text[:120])
                return sent
        return sent

    def services_item(self, now: dt.datetime) -> dict:
        units = self.state.get("services", [])
        current = [{"unit": x["unit"], "label": x["label"], "up": x["up"], "state": x["state"]}
                   for x in services.statuses([{"unit": u, "label": u.removesuffix(".service")} for u in units])]
        self.state["services_sig"], self.state["services_sent"] = [(x["unit"], x["up"]) for x in current], time.time()
        return {"type": "services", "time": now.isoformat(), "services": current}

    # ---------------------------------------------------------------- 4.3: comandi
    def run_commands(self, cmds: list) -> None:
        from .. import commands
        done = self.state.setdefault("commands_done", [])
        results = []
        for c in cmds[:10]:
            cid = str((c or {}).get("id", ""))[:32] if isinstance(c, dict) else ""
            is_update = '"action":"update"' in str((c or {}).get("payload", "")) if isinstance(c, dict) else False
            if not self.allow_commands and not (is_update and self.allow_update):
                reason = "comandi non permessi su questo server (reinstalla l'agente con --allow-commands)"
            elif not self.commands_pub:
                reason = "chiave dei comandi mancante su questo server (reinstalla l'agente con --allow-commands)"
            else:
                reason = commands.check(c, self.commands_pub, commands.token_tag(self.token), self.state.get("services", []), done,
                                        allow_update=self.allow_update)
                if not reason and is_update:
                    reason = "aggiornamento dalla dashboard non ancora disponibile per l'agente Linux: usa install.sh --agent … --update"
            if reason:
                log.warning("Comando %s rifiutato: %s", cid, reason)
                if reason != "comando già eseguito":
                    results.append({"type": "command_result", "time": dt.datetime.now().isoformat(timespec="seconds"),
                                    "id": cid, "ok": False, "detail": reason})
                continue
            p = commands.parse(c)
            done.append(p["id"])
            ok, detail = execute(p["action"], p["unit"])
            (log.info if ok else log.warning)("Comando %s %s da %s: %s", p["action"], p["unit"], p.get("by"), "ok" if ok else detail)
            results.append({"type": "command_result", "time": dt.datetime.now().isoformat(timespec="seconds"),
                            "id": p["id"], "ok": ok, "detail": detail})
        self.state["commands_done"] = done[-200:]
        if results:
            now = dt.datetime.now().replace(microsecond=0)
            units = self.state.get("services", [])
            current = [{"unit": x["unit"], "label": x["label"], "up": x["up"], "state": x["state"]}
                       for x in services.statuses([{"unit": u, "label": u.removesuffix(".service")} for u in units])]
            results.append({"type": "services", "time": now.isoformat(), "services": current})
            self.state["services_sig"], self.state["services_sent"] = [(x["unit"], x["up"]) for x in current], time.time()
            self.enqueue(results)
            self.save()

    def save(self) -> None:
        with open(self.state_path + ".tmp", "w", encoding="utf-8") as f:
            json.dump(self.state, f)
        os.replace(self.state_path + ".tmp", self.state_path)


def execute(action: str, unit: str) -> tuple[bool, str]:
    """Esegue avvia / ferma / riavvia con systemctl (l'agente gira come root)."""
    if action not in ("start", "stop", "restart") or not re.match(r"^[A-Za-z0-9@._:-]{1,200}$", unit):
        return False, "comando non valido"
    try:
        res = subprocess.run(["systemctl", action, unit], capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, f"systemctl non riuscito: {exc.__class__.__name__}"
    if res.returncode != 0:
        return False, (res.stderr or res.stdout).strip()[:300] or f"codice {res.returncode}"
    state = subprocess.run(["systemctl", "is-active", unit], capture_output=True, text=True, timeout=30).stdout.strip()
    return True, f"stato: {state}"


def smart_disks(now: dt.datetime) -> tuple[bool, list[dict]]:
    """4.2: SMART dei dischi con smartctl (l'agente gira come root). Senza smartctl: nessun dato."""
    exe = shutil.which("smartctl") or ("/usr/sbin/smartctl" if os.path.exists("/usr/sbin/smartctl") else None)
    if not exe:
        return False, []
    try:
        scan = subprocess.run([exe, "--scan"], capture_output=True, text=True, timeout=30).stdout
    except (OSError, subprocess.TimeoutExpired):
        return True, []
    out = []
    for line in scan.splitlines()[:16]:
        dev = line.split(" ", 1)[0]
        if not dev.startswith("/dev/"):
            continue
        try:
            res = subprocess.run([exe, "--json=c", "-a", dev], capture_output=True, text=True, timeout=60)
            d = smart.parse(json.loads(res.stdout), os.path.basename(dev), now)
        except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
            d = {"device": os.path.basename(dev), "error": f"lettura non riuscita: {exc.__class__.__name__}"}
        out.append({k: d.get(k) for k in ("device", "model", "passed", "temperature", "wear_used_pct", "reallocated",
                                           "pending", "uncorrectable", "media_errors", "error")})
    return True, out


def health(now: dt.datetime) -> dict:
    available, disks = smart_disks(now)
    data = {"smart_available": available, "disks": disks}
    if shutil.which("apt"):
        p = updates.pending()
        data["updates"] = {"total": p.get("total", 0), "security": p.get("security", [])[:100],
                           "security_count": len(p.get("security", [])), "reboot": updates.reboot(), "error": p.get("error")}
    elif glob.glob("/var/run/reboot-required"):
        data["updates"] = {"total": 0, "security": [], "reboot": {"required": True}}
    return data


def containers() -> dict | None:
    """4.2: container Docker. None = Docker non installato; 4.3: installato ma fermo = running False, senza errori."""
    if not shutil.which("docker"):
        return None
    present, detail = docker_mod.detect()
    if not present:
        return {"running": False, "detail": detail[:200], "containers": []}
    return {"running": True, "containers": [{k: c.get(k) for k in ("name", "image", "state", "status", "health", "restart_policy")}
                                            for c in docker_mod.containers(with_stats=False)][:200]}


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
    if agent.refresh_now:                  # 4.3: servizi nuovi o "Aggiorna": stato dei servizi nello stesso giro
        agent.enqueue([agent.services_item(dt.datetime.now().replace(microsecond=0))])
    if agent.pending():                    # 4.3: esiti dei comandi e stato dei servizi, inviati subito
        sent += agent.send(poll=False)
    agent.save()
    if sent:
        log.info("Inviati %d dati al server centrale", sent)
    return 0


if __name__ == "__main__":
    sys.exit(main())
