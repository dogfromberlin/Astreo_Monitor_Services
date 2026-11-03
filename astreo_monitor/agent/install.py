"""Installazione e aggiornamento dell'agente Linux (eseguito da install.sh --agent e da update.sh).

    sudo bash install.sh --agent https://CENTRALE:5443 --token agt_… --ca-sha256 …
    sudo .venv/bin/python -m astreo_monitor.agent.install --update

Scarica la CA del centrale e ne verifica l'impronta SHA256 (mostrata dalla dashboard insieme al token),
salva configurazione e token (solo root), genera le unit systemd, prova il collegamento e avvia il timer.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import re
import subprocess
import sys

import requests
import urllib3

CONF_DIR = "/etc/astreo-agent"
UNIT_DIR = "/etc/systemd/system"
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
UNITS = ("astreo-agent.service", "astreo-agent.timer")


def fail(msg: str) -> None:
    sys.exit(f"ERRORE: {msg}")


def fetch_ca(central: str, expected: str | None) -> bytes:
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    try:                                   # la CA si verifica con l'impronta, non con TLS (non la conosciamo ancora)
        r = requests.get(f"{central}/astreo-ca.crt", timeout=20, verify=False)
    except requests.RequestException as exc:
        fail(f"server centrale non raggiungibile ({exc.__class__.__name__}): controlla indirizzo, rete o VPN")
    if r.status_code != 200 or b"BEGIN CERTIFICATE" not in r.content:
        fail("il server centrale non ha fornito il certificato della CA (HTTPS attivo sul centrale?)")
    got = hashlib.sha256(r.content).hexdigest()
    if expected:
        if got.lower() != expected.lower():
            fail(f"l'impronta della CA non coincide ({got}): possibile intercettazione, installazione interrotta")
    else:
        print(f"Impronta SHA256 della CA del centrale: {got}")
        if input("Coincide con quella mostrata dalla dashboard? [s/N] ").strip().lower() not in ("s", "si", "sì", "y", "yes"):
            fail("installazione annullata")
    return r.content


def render_units() -> None:
    for name in UNITS:
        text = open(os.path.join(ROOT, "deploy", "templates", "agent", name + ".j2"), encoding="utf-8").read()
        with open(os.path.join(UNIT_DIR, name), "w", encoding="utf-8") as f:
            f.write(text.replace("{{ project_dir }}", ROOT))
    subprocess.run(["systemctl", "daemon-reload"], check=True)


def test_connection() -> None:
    import configparser
    cp = configparser.ConfigParser(interpolation=None)
    cp.read(os.path.join(CONF_DIR, "agent.ini"))
    central = cp["agent"]["central"]
    token = open(os.path.join(CONF_DIR, "token")).read().strip()
    try:
        r = requests.post(f"{central}/api/v1/agents/ingest", json={"agent": {"kind": "linux"}, "items": []}, timeout=20,
                          verify=os.path.join(CONF_DIR, "central-ca.crt"), headers={"Authorization": f"Bearer {token}"})
    except requests.exceptions.SSLError:
        fail("certificato del centrale non valido per l'indirizzo usato: usa un IP o un nome presente nel certificato")
    except requests.RequestException as exc:
        fail(f"server centrale non raggiungibile ({exc.__class__.__name__})")
    if r.status_code == 401:
        fail("token rifiutato: generane uno nuovo dalla dashboard (Impostazioni → Server collegati)")
    if r.status_code != 200:
        fail(f"il centrale ha risposto {r.status_code}: {r.text[:200]}")
    print("Collegamento al server centrale: OK")


def install(args) -> None:
    central = args.agent.rstrip("/")
    if not re.match(r"^https://[^\s/]+$", central):
        fail("indirizzo del centrale non valido: usa https://IP-o-NOME:PORTA (senza percorso)")
    if not re.match(r"^agt_[A-Za-z0-9_\-]{20,}$", args.token or ""):
        fail("token non valido: copialo dalla dashboard (Impostazioni → Server collegati)")
    os.makedirs(CONF_DIR, mode=0o700, exist_ok=True)
    os.chmod(CONF_DIR, 0o700)
    with open(os.path.join(CONF_DIR, "central-ca.crt"), "wb") as f:
        f.write(fetch_ca(central, args.ca_sha256))
    fd = os.open(os.path.join(CONF_DIR, "token"), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(args.token + "\n")
    with open(os.path.join(CONF_DIR, "agent.ini"), "w", encoding="utf-8") as f:
        f.write(f"""# Astreo Monitor - agente. Guida: docs/it/agents.md
[agent]
central = {central}
token_file = {CONF_DIR}/token
ca_file = {CONF_DIR}/central-ca.crt
state_dir = /var/lib/astreo-agent
root_disk = /
""")
    test_connection()
    render_units()
    subprocess.run(["systemctl", "enable", "--now", "astreo-agent.timer"], check=True)
    subprocess.run(["systemctl", "start", "astreo-agent.service"], check=False)
    print("Agente installato: i dati compaiono nella dashboard del centrale entro un paio di minuti.")


def update() -> None:
    if not os.path.exists(os.path.join(CONF_DIR, "agent.ini")):
        fail(f"agente non installato ({CONF_DIR}/agent.ini mancante)")
    render_units()
    test_connection()
    subprocess.run(["systemctl", "enable", "--now", "astreo-agent.timer"], check=True)
    print("Agente aggiornato.")


def main() -> None:
    if os.geteuid() != 0:
        fail("serve sudo")
    p = argparse.ArgumentParser(prog="astreo_monitor.agent.install")
    p.add_argument("--agent", help="indirizzo del server centrale, es. https://192.0.2.10:5443")
    p.add_argument("--token")
    p.add_argument("--ca-sha256", dest="ca_sha256")
    p.add_argument("--update", action="store_true")
    args = p.parse_args()
    update() if args.update else install(args)


if __name__ == "__main__":
    main()
