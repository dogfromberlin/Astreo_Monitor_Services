"""Utenti della dashboard: password dell'amministratore e utente in sola lettura.

    sudo .venv/bin/python -m astreo_monitor.users password            # cambia la password dell'amministratore
    sudo .venv/bin/python -m astreo_monitor.users viewer NOME         # crea o aggiorna l'utente in sola lettura
    sudo .venv/bin/python -m astreo_monitor.users viewer --remove     # elimina l'utente in sola lettura
    sudo .venv/bin/python -m astreo_monitor.users list

Modifica la sezione [web] del config mantenendo commenti e permessi, poi riavvia la dashboard.
"""
from __future__ import annotations

import argparse
import getpass
import os
import re
import shutil
import subprocess
import sys

from werkzeug.security import generate_password_hash

from . import config as config_mod
from . import i18n as _i18n

LANG = _i18n.cli_language()


def _(text: str, **values) -> str:
    return _i18n.t(text, LANG, **values)


def set_values(path: str, section: str, values: dict[str, str | None]) -> None:
    """Imposta (o con None elimina) chiavi di una sezione INI senza toccare il resto del file."""
    lines = open(path, encoding="utf-8").read().split("\n")
    start = next((i for i, l in enumerate(lines) if l.strip() == f"[{section}]"), None)
    if start is None:
        lines += ["", f"[{section}]"]
        start = len(lines) - 1
    end = next((i for i in range(start + 1, len(lines)) if re.match(r"^\s*\[", lines[i])), len(lines))
    for key, value in values.items():
        rx = re.compile(rf"^\s*{re.escape(key)}\s*=")
        idx = next((i for i in range(start + 1, end) if rx.match(lines[i])), None)
        if value is None:
            if idx is not None:
                del lines[idx]
                end -= 1
        elif idx is not None:
            lines[idx] = f"{key} = {value}"
        else:
            insert_at = end
            while insert_at > start + 1 and not lines[insert_at - 1].strip():
                insert_at -= 1
            lines.insert(insert_at, f"{key} = {value}")
            end += 1
    st = os.stat(path)
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    os.chmod(path, st.st_mode & 0o777)
    if os.geteuid() == 0:
        os.chown(path, st.st_uid, st.st_gid)


def ask_password(label: str) -> str:
    while True:
        a = getpass.getpass(f"{label}: ")
        if len(a) < 8:
            print(_("  almeno 8 caratteri"))
            continue
        if getpass.getpass(_("  ripeti: ")) == a:
            return a
        print(_("  le due password non coincidono"))


def restart() -> None:
    if os.geteuid() == 0 and shutil.which("systemctl"):
        subprocess.run(["systemctl", "restart", "astreo-monitor-web.service"], check=False)
        print(_("Dashboard riavviata."))
    else:
        print(_("Riavvia la dashboard: sudo systemctl restart astreo-monitor-web.service"))


def main() -> None:
    parser = argparse.ArgumentParser(prog="astreo_monitor.users", description=_("Utenti della dashboard"))
    parser.add_argument("-c", "--config", default=os.environ.get("ASTREO_MONITOR_CONFIG", config_mod.DEFAULT_PATH))
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("password", help=_("cambia la password dell'amministratore"))
    v = sub.add_parser("viewer", help=_("utente in sola lettura"))
    v.add_argument("name", nargs="?")
    v.add_argument("--remove", action="store_true")
    sub.add_parser("list", help=_("mostra gli utenti"))
    args = parser.parse_args()
    cfg = config_mod.load(args.config)
    path = cfg.path
    if args.cmd == "list":
        print(_("Amministratore: {p0}", p0=cfg.web.username))
        print(_("Sola lettura: {p0}", p0=cfg.web.viewer_username or _("nessuno")))
        return
    if args.cmd == "password":
        pw = ask_password(_("Nuova password di {p0}", p0=cfg.web.username))
        set_values(path, "web", {"password_hash": generate_password_hash(pw)})
        print(_("Password aggiornata."))
    elif args.remove:
        set_values(path, "web", {"viewer_username": None, "viewer_password_hash": None})
        print(_("Utente in sola lettura eliminato."))
    else:
        if not args.name:
            sys.exit(_("Indica il nome: … users viewer NOME"))
        if args.name == cfg.web.username:
            sys.exit(_("Il nome deve essere diverso da quello dell'amministratore."))
        pw = ask_password(_("Password di {p0} (sola lettura)", p0=args.name))
        set_values(path, "web", {"viewer_username": args.name, "viewer_password_hash": generate_password_hash(pw)})
        print(_("Utente in sola lettura {p0} salvato: vede Server e Connessione, non Impostazioni, Terminale e processi.", p0=args.name))
    restart()


if __name__ == "__main__":
    main()
