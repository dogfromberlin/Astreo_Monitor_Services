"""4.3: comandi dal centrale agli agenti (avvia / ferma / riavvia un servizio controllato).

Sicurezza, in breve:
  - nessuna porta aperta sugli agenti: i comandi viaggiano nella risposta all'invio dei dati (ogni minuto);
  - doppio consenso: "Consenti comandi" sul centrale (per server) e allow_commands nella configurazione
    dell'agente, scelta sul server stesso all'installazione;
  - ogni comando è firmato (RSA 2048, SHA-256) con una chiave privata che sta in un file del centrale, non nel
    database; l'agente lo verifica con la chiave pubblica ricevuta all'installazione;
  - un comando vale pochi minuti, è legato al token di quell'agente, si esegue una volta sola e riguarda solo i
    servizi già nell'elenco di quelli controllati per quel server.

La firma usa openssl (già presente per HTTPS); la verifica sull'agente Linux è in Python puro, quella sull'agente
Windows usa RSACryptoServiceProvider di .NET.
"""
from __future__ import annotations

import base64
import datetime as dt
import hashlib
import json
import os
import secrets
import subprocess

ACTIONS = ("start", "stop", "restart")
UPDATE = "update"           # 4.3: aggiornamento dell'agente (permesso separato: allow_update)
VALID_MINUTES = 10
KEY_NAME = "commands.key"
PUB_NAME = "commands.pub.json"


class CommandError(Exception):
    pass


# ---------------------------------------------------------------------------- chiavi (centrale)
def key_path(config_path: str) -> str:
    return os.path.join(os.path.dirname(os.path.abspath(config_path)), KEY_NAME)


def ensure_key(path: str) -> bool:
    """Crea la chiave privata se manca. Ritorna True se l'ha creata."""
    if os.path.exists(path):
        return False
    tmp = path + ".tmp"
    subprocess.run(["openssl", "genrsa", "-out", tmp, "2048"], check=True, capture_output=True, timeout=60)
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)
    return True


def public_key(path: str) -> dict:
    """Chiave pubblica in forma semplice (modulo ed esponente), facile da usare anche da PowerShell."""
    res = subprocess.run(["openssl", "rsa", "-in", path, "-noout", "-modulus"], check=True, capture_output=True,
                         text=True, timeout=30)
    n = res.stdout.strip().split("=", 1)[1].lower()
    pub = {"alg": "RSA-SHA256", "n": n, "e": 65537}
    pub["fingerprint"] = fingerprint(pub)
    return pub


def fingerprint(pub: dict) -> str:
    return hashlib.sha256(f"{pub['n']}:{pub['e']}".encode()).hexdigest()


def canonical(cmd: dict) -> bytes:
    """Testo firmato: chiavi in ordine, senza spazi, solo ASCII. Viaggia così com'è (campo payload), quindi
    l'agente verifica esattamente i byte firmati, senza dover ricostruire il JSON."""
    return json.dumps(cmd, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def sign(path: str, data: bytes) -> str:
    res = subprocess.run(["openssl", "dgst", "-sha256", "-sign", path, "-binary"], input=data, check=True,
                         capture_output=True, timeout=30)
    return base64.b64encode(res.stdout).decode()


def token_tag(token: str) -> str:
    """Lega il comando a un agente: impronta parziale del suo token (il token non viaggia)."""
    return hashlib.sha256(token.encode()).hexdigest()[:24]


def build(key: str, token_hash_or_tag: str, action: str, unit: str, user: str, now: dt.datetime | None = None,
          **extra) -> dict:
    if action not in ACTIONS + (UPDATE,):
        raise CommandError("Comando non valido")
    now = (now or dt.datetime.now(dt.timezone.utc)).replace(microsecond=0)
    cmd = {"id": secrets.token_hex(8), "agent": token_hash_or_tag, "action": action, "unit": unit, "by": user[:40],
           "issued": now.isoformat(), "expires": (now + dt.timedelta(minutes=VALID_MINUTES)).isoformat(), **extra}
    data = canonical(cmd)
    return {"id": cmd["id"], "payload": data.decode(), "sig": sign(key, data)}


# ---------------------------------------------------------------------------- verifica (agente Linux)
# DigestInfo DER di SHA-256 (RFC 8017, 9.2): prefisso fisso davanti all'impronta
_SHA256_PREFIX = bytes.fromhex("3031300d060960864801650304020105000420")


def verify(pub: dict, data: bytes, sig_b64: str) -> bool:
    """Verifica RSASSA-PKCS1-v1_5 con SHA-256, confrontando l'intera codifica attesa (niente parsing della firma)."""
    try:
        n, e = int(pub["n"], 16), int(pub["e"])
        sig = base64.b64decode(sig_b64, validate=True)
    except (KeyError, ValueError, TypeError):
        return False
    k = (n.bit_length() + 7) // 8
    if len(sig) != k or k < 256:                     # almeno 2048 bit
        return False
    s = int.from_bytes(sig, "big")
    if s >= n:
        return False
    em = pow(s, e, n).to_bytes(k, "big")
    t = _SHA256_PREFIX + hashlib.sha256(data).digest()
    expected = b"\x00\x01" + b"\xff" * (k - len(t) - 3) + b"\x00" + t
    return secrets.compare_digest(em, expected)


def parse(cmd: dict) -> dict:
    """Contenuto del comando (dopo check)."""
    return json.loads(cmd["payload"])


def check(cmd: dict, pub: dict, own_tag: str, allowed_units: list[str], done: list[str],
          now: dt.datetime | None = None, allow_update: bool = False) -> str | None:
    """Controlli dell'agente prima di eseguire. Ritorna il motivo del rifiuto, o None se il comando è valido."""
    if not isinstance(cmd, dict) or not isinstance(cmd.get("sig"), str) or not isinstance(cmd.get("payload"), str):
        return "comando senza firma"
    if not verify(pub, cmd["payload"].encode(), cmd["sig"]):
        return "firma non valida"
    try:
        cmd = json.loads(cmd["payload"])
    except ValueError:
        return "comando non leggibile"
    if cmd.get("agent") != own_tag:
        return "comando destinato a un altro agente"
    if cmd.get("id") in done:
        return "comando già eseguito"
    if cmd.get("action") == UPDATE:
        if not allow_update:
            return "aggiornamento non permesso su questo server (reinstalla l'agente con l'opzione di aggiornamento)"
    elif cmd.get("action") not in ACTIONS:
        return "azione non ammessa"
    elif cmd.get("unit") not in allowed_units:
        return "servizio non tra quelli controllati"
    now = now or dt.datetime.now(dt.timezone.utc)
    try:
        issued, expires = dt.datetime.fromisoformat(cmd["issued"]), dt.datetime.fromisoformat(cmd["expires"])
    except (KeyError, ValueError, TypeError):
        return "date non valide"
    if now > expires or issued - now > dt.timedelta(minutes=5):        # orologi un po' diversi: 5 minuti di tolleranza
        return "comando scaduto"
    return None


# ---------------------------------------------------------------------------- 4.3: pacchetto di aggiornamento
WINDOWS_FILES = ("astreo-agent.ps1", "AstreoTls.ps1")


def windows_package(project_dir: str, key: str, tag: str, version: str) -> dict:
    """File dell'agente Windows con impronte, in un manifesto firmato (l'agente verifica firma e impronte)."""
    files = []
    for name in WINDOWS_FILES:
        data = open(os.path.join(project_dir, "agent", "windows", name), "rb").read()
        files.append({"name": name, "sha256": hashlib.sha256(data).hexdigest(), "content": base64.b64encode(data).decode()})
    now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
    manifest = {"kind": "windows", "version": version, "agent": tag, "issued": now.isoformat(),
                "expires": (now + dt.timedelta(minutes=VALID_MINUTES)).isoformat(),
                "files": [{"name": f["name"], "sha256": f["sha256"]} for f in files]}
    data = canonical(manifest)
    return {"payload": data.decode(), "sig": sign(key, data), "files": files}
