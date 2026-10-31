"""Backup notturno del database (SQL Server, PostgreSQL o SQLite) con copia su GitHub.

Il backup vero e proprio è specifico per database (vedi astreo_monitor/backends.py).

Per ogni database in [backup] databases:
  1. BACKUP DATABASE ... WITH COPY_ONLY, CHECKSUM  -> file .bak in sql_dir
  2. RESTORE VERIFYONLY ... WITH CHECKSUM          -> il file è ripristinabile
  3. compressione zstd in local_dir/backup-AAAAMMGG-HHMMSS/<db>.bak.zst (il .bak viene rimosso)
  4. SHA-256 di ogni file
Poi: SHA256SUMS e manifest.json, upload come Release nel repository GitHub
privato `github_repo` (tramite la CLI gh già autenticata), retention locale e
su GitHub, stato in monitor_state ed email solo a cambio di stato.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import os
import shutil
import socket
import subprocess

from .. import __version__, backends, db, notifier
from ..backends import BackupError
from .. import settings as settings_mod
from ..config import BackupConfig, Config
from .base import run

log = logging.getLogger("job.db_backup")

PREFIX = "backup-"
GH_ENV = {**os.environ, "GH_NO_UPDATE_NOTIFIER": "1", "GH_PROMPT_DISABLED": "1", "NO_COLOR": "1"}


# --------------------------------------------------------------- utilità
def human(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{n} B"
        n /= 1024
    return str(n)


def gh(args: list[str], timeout: int = 600) -> str:
    res = subprocess.run(["gh", *args], capture_output=True, text=True, timeout=timeout, env=GH_ENV, check=False)
    if res.returncode != 0:
        raise BackupError(f"gh {' '.join(args[:2])}: {(res.stderr or res.stdout).strip()}")
    return res.stdout.strip()


# ---------------------------------------------------------------- passi
def write_manifest(run_dir: str, stamp: str, results: list[dict], sql_version: str) -> list[str]:
    sums = os.path.join(run_dir, "SHA256SUMS")
    with open(sums, "w", encoding="utf-8") as f:
        for r in results:
            f.write(f"{r['sha256']}  {r['file']}\n")
    manifest = os.path.join(run_dir, "manifest.json")
    with open(manifest, "w", encoding="utf-8") as f:
        json.dump({
            "created": stamp, "host": socket.gethostname(), "tool": f"astreo-monitor {__version__}",
            "sql_server": sql_version, "databases": results,
        }, f, indent=2, ensure_ascii=False)
    return [sums, manifest]


def upload(b: BackupConfig, stamp: str, when: dt.datetime, files: list[str], results: list[dict]) -> str:
    tag = PREFIX + stamp
    notes = "\n".join(
        [f"Backup di {socket.gethostname()} del {when:%d/%m/%Y %H:%M}", ""]
        + [f"- `{r['database']}`: {human(r['bak_bytes'])} -> {human(r['zst_bytes'])} (sha256 `{r['sha256'][:12]}…`)" for r in results]
        + ["", "Ripristino: vedi docs/backup-database.md nel repository Astreo_Monitor_Services."]
    )
    out = gh(["release", "create", tag, *files, "--repo", b.github_repo,
              "--title", f"Backup DB {when:%d/%m/%Y %H:%M}", "--notes", notes], timeout=b.timeout)
    url = out.splitlines()[-1] if out else ""
    log.info("Release pubblicata: %s", url or tag)
    return url


def prune_github(b: BackupConfig) -> int:
    if b.github_keep <= 0:
        return 0
    data = json.loads(gh(["release", "list", "--repo", b.github_repo, "--limit", "1000", "--json", "tagName"]) or "[]")
    tags = sorted((r["tagName"] for r in data if r["tagName"].startswith(PREFIX)), reverse=True)
    old = tags[b.github_keep:]
    for tag in old:
        gh(["release", "delete", tag, "--repo", b.github_repo, "--yes", "--cleanup-tag"])
        log.info("GitHub: eliminata release %s", tag)
    return len(old)


def prune_local(b: BackupConfig) -> int:
    if b.local_keep <= 0:
        return 0
    dirs = sorted((d for d in os.listdir(b.local_dir) if d.startswith(PREFIX)
                   and os.path.isdir(os.path.join(b.local_dir, d))), reverse=True)
    old = dirs[b.local_keep:]
    for d in old:
        shutil.rmtree(os.path.join(b.local_dir, d))
        log.info("Locale: eliminato %s", d)
    return len(old)


# ----------------------------------------------------------------- main
def main(cfg: Config, dry_run: bool) -> int:
    b = cfg.backup
    if b is None:
        log.error("Sezione [backup] mancante nella configurazione")
        return 2
    be = backends.get(cfg.database)
    now = dt.datetime.now()
    stamp = now.strftime("%Y%m%d-%H%M%S")
    names = be.databases(cfg.database, b)
    try:
        problems, version = be.check(cfg.database, b)
    except Exception as exc:  # noqa: BLE001
        problems, version = [f"controllo non riuscito: {exc}"], "?"

    if dry_run:
        log.info("Database: %s — da salvare: %s", version, ", ".join(names))
        for p in problems:
            log.error("Problema: %s", p)
        if b.github_repo and shutil.which("gh"):
            try:
                gh(["repo", "view", b.github_repo, "--json", "name"], timeout=30)
                log.info("Repository GitHub %s raggiungibile", b.github_repo)
            except BackupError as exc:
                log.error("Repository GitHub non utilizzabile: %s", exc)
                problems.append(str(exc))
        log.info("Destinazione locale: %s (conservo %d copie), GitHub: %s (conservo %d)",
                 b.local_dir, b.local_keep, b.github_repo or "disattivato", b.github_keep)
        return 1 if problems else 0

    # i problemi di permessi del solo test di ripristino (PostgreSQL senza CREATEDB) non bloccano il backup
    blocking = [p for p in problems if "verifica mensile" not in p]
    errors = list(blocking)
    results: list[dict] = []
    release_url = None
    run_dir = os.path.join(b.local_dir, PREFIX + stamp)
    if not blocking:
        os.makedirs(run_dir)  # nome con i secondi: sempre nuovo
        for name in names:
            try:
                log.info("%s: backup in corso", name)
                r = be.backup(cfg.database, b, name, stamp, run_dir)
                log.info("%s: %s -> %s", name, human(r["bak_bytes"]), human(r["zst_bytes"]))
                results.append(r)
            except Exception as exc:  # noqa: BLE001
                log.error("%s: backup fallito: %s", name, exc)
                errors.append(f"{name}: {exc}")
        if results:
            extra = write_manifest(run_dir, stamp, results, version)
            if b.github_repo:
                try:
                    files = [os.path.join(run_dir, r["file"]) for r in results] + extra
                    release_url = upload(b, stamp, now, files, results)
                    prune_github(b)
                except (BackupError, subprocess.TimeoutExpired) as exc:
                    log.error("Upload su GitHub fallito (la copia locale resta): %s", exc)
                    errors.append(f"upload GitHub: {exc}")
        else:
            shutil.rmtree(run_dir, ignore_errors=True)
        prune_local(b)

    status = "OK" if not errors else "ALERT"
    with db.connect(cfg.database) as conn:
        db.state_set(conn, "backup:last", {
            "time": now.isoformat(timespec="seconds"), "status": status, "release": release_url,
            "engine": cfg.database.engine, "local_dir": run_dir if results else None, "databases": results, "errors": errors})
        state = notifier.AlertState(conn, "backup")
        should_notify, reason, previous = state.evaluate(status, settings_mod.policy(settings_mod.load(conn, cfg), "backup"))
        if should_notify:
            intro = notifier.reason_line(reason, state)
            lines = ([intro, ""] if intro else []) + [f"Backup del {now:%d/%m/%Y %H:%M}: {status} (precedente: {previous or 'n/d'})", ""]
            lines += [f"- {r['database']}: {human(r['bak_bytes'])} -> {human(r['zst_bytes'])}" for r in results]
            if release_url:
                lines += ["", f"Release: {release_url}"]
            if errors:
                lines += ["", "Errori:"] + [f"- {e}" for e in errors]
            subject = "Backup database tornato OK" if status == "OK" else "Backup database FALLITO"
            if notifier.dispatch(conn, cfg, "backup", subject, "\n".join(lines) + "\n", detected_at=now):
                state.mark_notified()
        state.save()
    log.info("Backup terminato: %s, %d database salvati, %d errori", status, len(results), len(errors))
    return 0 if status == "OK" else 1


def entrypoint() -> None:
    run("db_backup", "Backup del database con copia su GitHub", main)


if __name__ == "__main__":
    entrypoint()
