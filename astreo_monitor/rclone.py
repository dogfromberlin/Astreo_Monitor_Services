"""Copie dei backup con rclone: cartelle di rete, NAS, Backblaze B2, S3, Google Drive, SFTP…

Le destinazioni (`remote:percorso` di rclone, oppure un percorso locale come /mnt/nas/astreo)
si impostano in Impostazioni > Backup. I remote si creano una volta con `rclone config`
come utente dei servizi (configurazione in ~/.config/rclone/rclone.conf, che contiene le credenziali).
Ogni backup finisce in <destinazione>/backup-AAAAMMGG-HHMMSS/ ed è verificato con `rclone check`.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess

PREFIX = "backup-"
DEST_RE = re.compile(r"^(/[^\0]*|[A-Za-z0-9_.\- ]+:[^\0]*)$")


class RcloneError(Exception):
    pass


def available() -> bool:
    return shutil.which("rclone") is not None


def parse(text: str) -> list[str]:
    """Destinazioni dall'impostazione (una per riga o separate da virgola)."""
    return [d.strip().rstrip("/") for d in re.split(r"[\n,]", text or "") if d.strip()]


def validate(dest: str) -> None:
    if "://" in dest:
        raise RcloneError(f"Destinazione non valida: {dest} (gli indirizzi come ftp:// o smb:// vanno configurati come "
                          "remote con «rclone config», poi si indica remote:percorso)")
    if not DEST_RE.match(dest) or ".." in dest.split("/"):
        raise RcloneError(f"Destinazione non valida: {dest} (usa remote:percorso oppure un percorso assoluto)")


def _run(args: list[str], timeout: int = 1800) -> str:
    if not available():
        raise RcloneError("rclone non installato (sudo apt install rclone)")
    env = {**os.environ, "RCLONE_CONFIG_PASS": ""}
    res = subprocess.run(["rclone", *args], capture_output=True, text=True, timeout=timeout, env=env)
    if res.returncode != 0:
        err = (res.stderr or res.stdout).strip().splitlines()
        last = re.sub(r"^\d{4}/\d\d/\d\d \d\d:\d\d:\d\d\s+(\w+\s*:\s*)?", "", err[-1]) if err else ""
        raise RcloneError((last or f"rclone: codice {res.returncode}")[:300])
    return res.stdout


def remotes() -> list[str]:
    try:
        return [r.strip() for r in _run(["listremotes"], timeout=30).splitlines() if r.strip()]
    except (RcloneError, OSError, subprocess.TimeoutExpired):
        return []


def test(dest: str) -> str:
    """Verifica che la destinazione sia raggiungibile e scrivibile. Ritorna una descrizione."""
    validate(dest)
    _run(["mkdir", dest], timeout=120)
    probe = f"{dest}/.astreo-prova"
    _run(["touch", probe], timeout=120)
    _run(["deletefile", probe], timeout=120)
    n = len([x for x in _run(["lsf", dest, "--dirs-only"], timeout=120).splitlines() if x.startswith(PREFIX)])
    return f"raggiungibile e scrivibile, {n} backup presenti"


def upload(run_dir: str, dest: str, timeout: int) -> str:
    """Copia la cartella del backup e verifica i file a destinazione. Ritorna il percorso remoto."""
    validate(dest)
    target = f"{dest}/{os.path.basename(run_dir.rstrip('/'))}"
    _run(["copy", run_dir, target, "--retries", "3", "--low-level-retries", "10"], timeout=timeout)
    _run(["check", run_dir, target, "--one-way"], timeout=timeout)       # dimensioni e hash dove disponibili
    return target


def prune(dest: str, keep: int) -> list[str]:
    """Elimina i backup più vecchi oltre `keep` (solo cartelle backup-*)."""
    if keep <= 0:
        return []
    dirs = sorted(d.rstrip("/") for d in _run(["lsf", dest, "--dirs-only"], timeout=300).splitlines()
                  if d.startswith(PREFIX))
    old = dirs[:-keep] if len(dirs) > keep else []
    for d in old:
        _run(["purge", f"{dest}/{d}"], timeout=600)
    return old
