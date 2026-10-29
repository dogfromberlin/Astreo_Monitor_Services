"""Backup notturno dei database SQL Server con copia su GitHub.

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
import hashlib
import json
import logging
import os
import shutil
import socket
import subprocess

from .. import __version__, db, notifier
from ..config import BackupConfig, Config
from .base import run

log = logging.getLogger("job.db_backup")

PREFIX = "backup-"
GH_ENV = {**os.environ, "GH_NO_UPDATE_NOTIFIER": "1", "GH_PROMPT_DISABLED": "1", "NO_COLOR": "1"}


class BackupError(Exception):
    pass


# --------------------------------------------------------------- utilità
def sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


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


def quote_name(name: str) -> str:
    return "[" + name.replace("]", "]]") + "]"


# ---------------------------------------------------------------- passi
def check_environment(b: BackupConfig) -> list[str]:
    """Controlli preliminari: ritorna l'elenco dei problemi trovati."""
    problems = []
    if not shutil.which("zstd"):
        problems.append("comando zstd non trovato (sudo apt install zstd)")
    if b.github_repo and not shutil.which("gh"):
        problems.append("comando gh non trovato")
    if not os.path.isdir(b.sql_dir):
        problems.append(f"cartella {b.sql_dir} inesistente")
    elif not os.access(b.sql_dir, os.R_OK | os.W_OK | os.X_OK):
        problems.append(f"l'utente corrente non può leggere/scrivere in {b.sql_dir}")
    if not 1 <= b.zstd_level <= 19:
        problems.append("zstd_level deve essere tra 1 e 19")
    return problems


def backup_one(conn, name: str, stamp: str, run_dir: str, b: BackupConfig) -> dict:
    bak = os.path.join(b.sql_dir, f"{name}_{stamp}.bak")
    dst = os.path.join(run_dir, f"{name}.bak.zst")
    try:
        log.info("%s: backup in corso", name)
        db.run_command(
            conn,
            f"BACKUP DATABASE {quote_name(name)} TO DISK = %s WITH COPY_ONLY, CHECKSUM, INIT, NAME = %s",
            (bak, f"astreo-monitor {stamp}"),
        )
        db.run_command(conn, "RESTORE VERIFYONLY FROM DISK = %s WITH CHECKSUM", (bak,))
        size_bak = os.path.getsize(bak)
        log.info("%s: backup verificato (%s), compressione", name, human(size_bak))
        res = subprocess.run(
            ["zstd", "-q", f"-{b.zstd_level}", "-T0", "--rm", bak, "-o", dst],
            timeout=b.timeout, capture_output=True, text=True, check=False,
        )
        if res.returncode != 0:
            raise BackupError(f"zstd: {(res.stderr or res.stdout).strip()}")
        size_zst = os.path.getsize(dst)
        digest = sha256(dst)
        log.info("%s: %s -> %s", name, human(size_bak), human(size_zst))
        return {"database": name, "file": os.path.basename(dst), "bak_bytes": size_bak,
                "zst_bytes": size_zst, "sha256": digest}
    finally:
        if os.path.exists(bak):
            try:
                os.remove(bak)
            except OSError as exc:
                log.warning("Impossibile rimuovere %s: %s", bak, exc)


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
    now = dt.datetime.now()
    stamp = now.strftime("%Y%m%d-%H%M%S")

    problems = check_environment(b)
    with db.connect(cfg.database, autocommit=True, timeout=b.timeout) as conn:
        online = {r["name"] for r in db.query(conn, "SELECT name FROM sys.databases WHERE state_desc = 'ONLINE'")}
        sql_version = db.query_one(conn, "SELECT CAST(SERVERPROPERTY('ProductVersion') AS varchar(32)) AS v")["v"]
        missing = [d for d in b.databases if d not in online]

        if dry_run:
            for p in problems:
                log.error("Problema: %s", p)
            for d in b.databases:
                if d in missing:
                    log.error("Database %s: NON trovato o non online", d)
                    continue
                perm = db.query_one(conn, "SELECT HAS_PERMS_BY_NAME(%s, 'DATABASE', 'BACKUP DATABASE') AS p", (d,))["p"]
                if perm == 1:
                    log.info("Database %s: ok, permesso di backup presente", d)
                else:
                    log.error("Database %s: manca il permesso BACKUP DATABASE (esegui sql/004_backup.sql)", d)
                    problems.append(f"{d}: permesso di backup mancante")
            verify = db.query_one(conn, "SELECT HAS_PERMS_BY_NAME('master', 'DATABASE', 'CREATE DATABASE') AS p")["p"]
            if verify == 1:
                log.info("Permesso CREATE DATABASE in master (per RESTORE VERIFYONLY): ok")
            else:
                log.error("Manca CREATE DATABASE in master, necessario per RESTORE VERIFYONLY (esegui sql/004_backup.sql)")
                problems.append("permesso CREATE DATABASE mancante")
            if b.github_repo and shutil.which("gh"):
                try:
                    gh(["repo", "view", b.github_repo, "--json", "name"], timeout=30)
                    log.info("Repository GitHub %s raggiungibile", b.github_repo)
                except BackupError as exc:
                    log.error("Repository GitHub non utilizzabile: %s", exc)
                    problems.append(str(exc))
            log.info("Destinazione locale: %s (conservo %d copie), GitHub: %s (conservo %d)",
                     b.local_dir, b.local_keep, b.github_repo or "disattivato", b.github_keep)
            return 1 if problems or missing else 0

        errors = list(problems) + [f"{d}: database non trovato o non online" for d in missing]
        results: list[dict] = []
        release_url = None
        run_dir = os.path.join(b.local_dir, PREFIX + stamp)

        if not problems:
            os.makedirs(run_dir)  # nome con i secondi: sempre nuovo
            for name in b.databases:
                if name in missing:
                    continue
                try:
                    results.append(backup_one(conn, name, stamp, run_dir, b))
                except Exception as exc:  # noqa: BLE001
                    log.error("%s: backup fallito: %s", name, exc)
                    errors.append(f"{name}: {exc}")

            if results:
                extra = write_manifest(run_dir, stamp, results, sql_version)
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
        summary = {
            "time": now.isoformat(timespec="seconds"), "status": status, "release": release_url,
            "local_dir": run_dir if results else None, "databases": results, "errors": errors,
        }
        db.state_set(conn, "backup:last", summary)

        state = notifier.AlertState(conn, "backup")
        should_notify, previous = state.update(status, b.reminder_hours)
        if should_notify and b.notify:
            lines = [f"Backup del {now:%d/%m/%Y %H:%M}: {status} (precedente: {previous or 'n/d'})", ""]
            lines += [f"- {r['database']}: {human(r['bak_bytes'])} -> {human(r['zst_bytes'])}" for r in results]
            if release_url:
                lines += ["", f"Release: {release_url}"]
            if errors:
                lines += ["", "Errori:"] + [f"- {e}" for e in errors]
            subject = "Backup database tornato OK" if status == "OK" else "Backup database FALLITO"
            if notifier.send_email(cfg.email, subject, "\n".join(lines) + "\n"):
                state.mark_notified()
        state.save()

    log.info("Backup terminato: %s, %d database salvati, %d errori", status, len(results), len(errors))
    return 0 if status == "OK" else 1


def entrypoint() -> None:
    run("db_backup", "Backup dei database SQL Server con copia su GitHub", main)


if __name__ == "__main__":
    entrypoint()
