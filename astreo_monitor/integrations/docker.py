"""Modulo Docker: container, stato, risorse, riavvii (tramite la CLI docker, utente nel gruppo docker)."""
from __future__ import annotations

import json
import shutil
import subprocess


def _run(*args: str, timeout: int = 20) -> subprocess.CompletedProcess:
    return subprocess.run(["docker", *args], capture_output=True, text=True, timeout=timeout)


def detect() -> tuple[bool, str]:
    if not shutil.which("docker"):
        return False, "Docker non installato"
    try:
        res = _run("info", "--format", "{{.ServerVersion}}", timeout=10)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, f"Docker non risponde: {exc}"
    if res.returncode != 0:
        msg = (res.stderr or "").strip().splitlines()[-1:] or ["errore sconosciuto"]
        if "permission denied" in msg[0].lower():
            return False, "permesso negato: l'utente del servizio deve essere nel gruppo docker"
        return False, f"Docker non risponde: {msg[0][:150]}"
    return True, f"Docker {res.stdout.strip()}"


def _jsonlines(text: str) -> list[dict]:
    out = []
    for line in text.splitlines():
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except ValueError:
                pass
    return out


def containers(with_stats: bool = True) -> list[dict]:
    ps = _jsonlines(_run("ps", "-a", "--no-trunc", "--format", "{{json .}}").stdout)
    if not ps:
        return []
    ids = [c["ID"] for c in ps]
    inspect = {}
    res = _run("inspect", *ids)
    if res.returncode == 0:
        try:
            for i in json.loads(res.stdout):
                inspect[i["Id"]] = i
        except ValueError:
            pass
    stats = {}
    if with_stats and any(c.get("State") == "running" for c in ps):
        for s in _jsonlines(_run("stats", "--no-stream", "--no-trunc", "--format", "{{json .}}", timeout=30).stdout):
            stats[s.get("ID") or s.get("Container")] = s
    out = []
    for c in ps:
        i = inspect.get(c["ID"], {})
        st = i.get("State", {})
        s = stats.get(c["ID"], {})
        out.append({
            "id": c["ID"][:12], "name": c.get("Names", ""), "image": c.get("Image", ""),
            "state": c.get("State", st.get("Status", "")), "status": c.get("Status", ""),
            "health": (st.get("Health") or {}).get("Status"),
            "started_at": st.get("StartedAt"), "restart_count": i.get("RestartCount", 0),
            "restart_policy": ((i.get("HostConfig") or {}).get("RestartPolicy") or {}).get("Name", ""),
            "cpu": s.get("CPUPerc"), "mem": s.get("MemUsage"), "mem_pct": s.get("MemPerc"),
            "ports": c.get("Ports", ""),
        })
    return sorted(out, key=lambda x: (x["state"] != "running", x["name"]))


def evaluate(c: dict) -> str:
    """Stato per gli avvisi: un container con riavvio automatico deve essere in esecuzione e sano."""
    if c["state"] == "restarting":
        return "ALERT"
    if c["restart_policy"] in ("always", "unless-stopped", "on-failure") and c["state"] != "running":
        return "ALERT"
    if c.get("health") == "unhealthy":
        return "WARNING"
    return "OK"
