"""CPU, memoria, load, dischi, uptime e processi tramite psutil."""
from __future__ import annotations

import datetime as dt
import os
import time

import psutil

MB = 1024 * 1024
SKIP_FS = {"squashfs", "tmpfs", "devtmpfs", "overlay", "proc", "sysfs", "nsfs", "fuse.snapfuse"}


def cpu_percent(interval: float = 0.5) -> float:
    return round(psutil.cpu_percent(interval=interval), 1)


def cpu_times_snapshot() -> dict:
    """Contatori CPU cumulativi: servono a calcolare la media esatta tra due letture."""
    t = psutil.cpu_times()._asdict()
    t["boot_time"] = psutil.boot_time()
    t["wall"] = time.time()
    return t


def cpu_percent_between(prev: dict, curr: dict) -> float | None:
    """Percentuale di CPU occupata tra due snapshot. None se non confrontabili."""
    if not prev or prev.get("boot_time") != curr.get("boot_time"):
        return None
    # Intervallo troppo breve (misura poco precisa) o troppo lungo (job fermo a lungo)
    elapsed = curr.get("wall", 0) - prev.get("wall", 0)
    if not 30 <= elapsed <= 3600:
        return None
    keys = [k for k in curr if k not in ("boot_time", "wall") and k in prev]
    total = sum(curr[k] - prev[k] for k in keys)
    idle = (curr["idle"] - prev["idle"]) + (curr.get("iowait", 0) - prev.get("iowait", 0))
    if total <= 0:
        return None
    return round(max(0.0, min(100.0, (total - idle) / total * 100)), 2)


def memory() -> dict:
    vm = psutil.virtual_memory()
    sw = psutil.swap_memory()
    return {
        "total_mb": vm.total // MB,
        "used_mb": (vm.total - vm.available) // MB,
        "available_mb": vm.available // MB,
        "buffers_cache_mb": (getattr(vm, "buffers", 0) + getattr(vm, "cached", 0)) // MB,
        "used_pct": round((vm.total - vm.available) / vm.total * 100, 1),
        "swap_total_mb": sw.total // MB,
        "swap_used_mb": sw.used // MB,
        "swap_used_pct": round(sw.percent, 1),
    }


def load() -> dict:
    l1, l5, l15 = os.getloadavg()
    return {"load1": round(l1, 2), "load5": round(l5, 2), "load15": round(l15, 2), "cpu_count": psutil.cpu_count()}


def disks() -> list[dict]:
    seen, out = set(), []
    for part in psutil.disk_partitions(all=False):
        if part.fstype in SKIP_FS or part.device in seen or part.mountpoint.startswith("/snap"):
            continue
        seen.add(part.device)
        try:
            u = psutil.disk_usage(part.mountpoint)
        except (PermissionError, OSError):
            continue
        out.append({
            "device": part.device,
            "mountpoint": part.mountpoint,
            "fstype": part.fstype,
            "total_mb": u.total // MB,
            "used_mb": u.used // MB,
            "free_mb": u.free // MB,
            "used_pct": round(u.percent, 1),
        })
    return sorted(out, key=lambda d: d["mountpoint"])


def disk_used_pct(path: str = "/") -> float:
    return round(psutil.disk_usage(path).percent, 1)


def uptime() -> dict:
    boot = dt.datetime.fromtimestamp(psutil.boot_time())
    return {"boot_time": boot.isoformat(timespec="seconds"), "uptime_s": int(time.time() - psutil.boot_time())}


def processes(limit: int = 15, sample: float = 0.5) -> list[dict]:
    """Processi ordinati per CPU (come `top`, ma strutturati)."""
    procs = []
    for p in psutil.process_iter(["pid", "name", "username"]):
        try:
            p.cpu_percent(None)
            procs.append(p)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    time.sleep(sample)
    rows = []
    for p in procs:
        try:
            with p.oneshot():
                rows.append({
                    "pid": p.pid,
                    "name": p.info["name"],
                    "user": p.info["username"],
                    "cpu_pct": round(p.cpu_percent(None), 1),
                    "mem_pct": round(p.memory_percent(), 1),
                    "rss_mb": p.memory_info().rss // MB,
                    "command": " ".join(p.cmdline())[:160] or p.info["name"],
                })
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass
    rows.sort(key=lambda r: (r["cpu_pct"], r["mem_pct"]), reverse=True)
    return rows[:limit]


def snapshot(root_disk: str = "/") -> dict:
    """Tutto ciò che serve alla dashboard in una chiamata."""
    return {
        "cpu_pct": cpu_percent(0.3),
        "memory": memory(),
        "load": load(),
        "disks": disks(),
        "root_disk_pct": disk_used_pct(root_disk),
        "uptime": uptime(),
        "hostname": os.uname().nodename,
        "time": dt.datetime.now().isoformat(timespec="seconds"),
    }
