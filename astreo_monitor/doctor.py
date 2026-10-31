"""Diagnosi dell'installazione di Astreo Monitor.

Controlla configurazione, database, servizi e file installati confrontandoli con
quelli del progetto, e indica per ogni problema il comando per correggerlo.
Va lanciato dopo ogni aggiornamento (finestra SSH su astreo):

    cd ~/Astreo_Monitor_Services
    sudo .venv/bin/python -m astreo_monitor.doctor

Con sudo può leggere anche i file riservati (regola polkit, configurazioni nginx);
senza sudo quei controlli risultano "non verificabili".
Codice di uscita: 0 tutto a posto, 1 almeno un errore.
"""
from __future__ import annotations

import argparse
import datetime as dt
import glob
import os
import pwd
import stat
import subprocess
import sys

import requests
import urllib3

from . import __version__, config as config_mod, db, schema

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OK, WARN, FAIL, SKIP = "OK", "ATTENZIONE", "ERRORE", "N/V"
SYMBOL = {OK: "✔", WARN: "⚠", FAIL: "✘", SKIP: "·"}
COLOR = {OK: "\033[32m", WARN: "\033[33m", FAIL: "\033[31m", SKIP: "\033[90m"}


class Report:
    def __init__(self):
        self.items: list[tuple[str, str, str, str, str]] = []

    def add(self, area: str, what: str, status: str, detail: str = "", fix: str = "") -> None:
        self.items.append((area, what, status, detail, fix))

    def print(self, color: bool) -> int:
        area = None
        for a, what, st, detail, fix in self.items:
            if a != area:
                print(f"\n== {a}")
                area = a
            c, r = (COLOR[st], "\033[0m") if color else ("", "")
            print(f"  {c}{SYMBOL[st]} {what}{r}" + (f" — {detail}" if detail else ""))
            if fix and st in (WARN, FAIL):
                for line in fix.splitlines():
                    print(f"      $ {line}")
        n = {s: sum(1 for i in self.items if i[2] == s) for s in (OK, WARN, FAIL, SKIP)}
        print(f"\nRisultato: {n[OK]} ok, {n[WARN]} da controllare, {n[FAIL]} errori, {n[SKIP]} non verificabili")
        return 1 if n[FAIL] else 0


def sh(*args: str) -> str:
    try:
        return subprocess.run(list(args), capture_output=True, text=True, timeout=15).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return ""


# --------------------------------------------------------------------- controlli
def check_config(rep: Report, cfg, path: str) -> None:
    A = "Configurazione"
    rep.add(A, f"file {path}", OK)
    st = os.stat(path)
    owner = pwd.getpwuid(st.st_uid).pw_name
    if st.st_mode & 0o077 or owner != "<utente>":
        rep.add(A, "permessi del config", WARN, f"{owner}, {stat.filemode(st.st_mode)} (attesi <utente> e -rw-------)",
                f"sudo chown <utente>:<utente> {path}\nsudo chmod 600 {path}")
    else:
        rep.add(A, "permessi del config", OK)
    nginx_site = os.path.exists("/etc/nginx/sites-enabled/astreo-monitor")
    if nginx_site and (cfg.web.host != "127.0.0.1" or not cfg.web.trusted_proxy):
        rep.add(A, "[web] dietro nginx", FAIL, f"host = {cfg.web.host}, trusted_proxy = {cfg.web.trusted_proxy or 'vuoto'}",
                f"sudo sed -i 's/^host = .*/host = 127.0.0.1/' {path}\n"
                f"grep -q '^trusted_proxy' {path} || sudo sed -i '/^\\[web\\]/a trusted_proxy = 127.0.0.1' {path}\n"
                "sudo systemctl restart astreo-monitor-web.service")
    else:
        rep.add(A, "[web] dietro nginx", OK if nginx_site else SKIP, "" if nginx_site else "sito nginx non installato")
    if cfg.terminal and cfg.terminal.enabled and not cfg.terminal.password_hash:
        rep.add(A, "[terminal]", FAIL, "enabled = true ma password_hash vuoto", "vedi docs/terminale.md")


def check_database(rep: Report, cfg) -> None:
    A = "Database"
    try:
        with db.connect(cfg.database) as conn:
            where = cfg.database.path if cfg.database.engine == "sqlite" else f"{cfg.database.host} ({cfg.database.user})"
            rep.add(A, f"connessione {cfg.database.engine}: {where}", OK)
            problems = schema.check(conn, cfg.backup.databases if cfg.backup and cfg.database.engine == "mssql" else None)
            if not problems:
                rep.add(A, "schema (tabelle, colonne, procedure, permessi)", OK)
            for p in problems:
                rep.add(A, p["item"], FAIL, p["problem"], p["fix"])
            state = {r["key"]: r for r in db.state_rows(conn)}
    except Exception as exc:  # noqa: BLE001
        rep.add(A, "connessione", FAIL, str(exc)[:200], "systemctl status mssql-server --no-pager\nverifica [database] nel config")
        return

    B = "Dati recenti (i job girano?)"
    now = dt.datetime.now()
    expected = [("metrics:cpu_times", 15, "astreo-metrics.timer"), ("connectivity:last", 5, "astreo-connectivity.timer"),
                ("health:last", 7 * 60, "astreo-health.timer"), ("publicip:current", 60, "astreo-publicip.timer"),
                ("expiry:last", 26 * 60, "astreo-expiry.timer"), ("backup:last", 26 * 60, "astreo-backup.timer")]
    for key, minutes, timer in expected:
        row = state.get(key)
        if not row:
            rep.add(B, key, WARN, "nessun dato", f"systemctl status {timer} --no-pager")
            continue
        age = now - db.as_datetime(row["updated_at"])
        st_ = OK if age <= dt.timedelta(minutes=minutes) else WARN
        rep.add(B, key, st_, f"aggiornato {int(age.total_seconds() // 60)} min fa (atteso entro {minutes})",
                f"systemctl list-timers {timer} --no-pager\njournalctl -u {timer.replace('.timer', '.service')} -n 20 --no-pager")


def check_web(rep: Report, cfg) -> None:
    A = "Dashboard"
    verify = cfg.web.ca_cert if os.path.exists(cfg.web.ca_cert) else False
    if verify is False:
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    urls = ([(f"https://127.0.0.1:{cfg.web.https_port}/api/v1/health", verify)] if cfg.web.https_port else []) + \
        [(f"http://127.0.0.1:{cfg.web.port}/api/v1/health", True)]
    for url, v in urls:
        try:
            h = requests.get(url, timeout=10, verify=v).json()
        except requests.exceptions.SSLError as exc:
            rep.add(A, url, FAIL, f"certificato non valido: {str(exc)[:120]}", "vedi docs/certificato.md")
            continue
        except Exception:  # noqa: BLE001
            continue
        if h.get("version") != __version__:
            rep.add(A, "versione in esecuzione", FAIL, f"il server esegue la {h.get('version')}, il codice è la {__version__}",
                    "sudo systemctl restart astreo-monitor-web.service")
        else:
            rep.add(A, f"risponde su {url.rsplit('/api', 1)[0]}", OK, f"versione {__version__}")
        if h.get("schema_ok") is False:
            rep.add(A, "schema visto dalla dashboard", FAIL, ", ".join(h.get("schema_fixes", [])),
                    "vedi la sezione Database (la dashboard ricontrolla ogni 30 secondi)")
        return
    rep.add(A, "risposta", FAIL, "la dashboard non risponde",
            "systemctl status astreo-monitor-web.service nginx --no-pager")


def check_systemd(rep: Report, cfg) -> None:
    """Unit e file di sistema confrontati con quelli generati dai modelli (installer)."""
    from . import installer
    A = "Servizi e file di sistema"
    ini = installer.Answers.path(os.path.dirname(cfg.path))
    if not os.path.exists(ini):
        rep.add(A, "install.ini", WARN, "risposte dell'installatore assenti: i file non sono verificabili",
                "sudo .venv/bin/python -m astreo_monitor.installer adopt")
        return
    ans = installer.Answers.load(ini)
    for path, status, _ in installer.diff(ans):
        name = os.path.basename(path)
        if status == "non leggibile":
            rep.add(A, path, SKIP, "non leggibile: rilancia la diagnosi con sudo")
            continue
        if status != "uguale":
            only_comments = False
            if status == "diverso":
                cur = [x for x in open(path, encoding="utf-8").read().splitlines() if x.strip() and not x.lstrip().startswith(("#", "//"))]
                new = [x for x in installer.render(ans)[path].splitlines() if x.strip() and not x.lstrip().startswith(("#", "//"))]
                only_comments = [x.replace(" ", "") for x in cur] == [x.replace(" ", "") for x in new]
            rep.add(A, path, WARN if only_comments else FAIL,
                    "differisce solo nei commenti" if only_comments else ("mancante" if status == "nuovo" else "diverso dal modello"),
                    "sudo .venv/bin/python -m astreo_monitor.installer diff -v\nsudo .venv/bin/python -m astreo_monitor.installer apply")
            continue
        if not path.startswith("/etc/systemd/system/"):
            rep.add(A, path, OK)
            continue
        props = dict(line.split("=", 1) for line in sh("systemctl", "show", name, "-p",
                     "NeedDaemonReload,UnitFileState,ActiveState").splitlines() if "=" in line)
        if props.get("NeedDaemonReload") == "yes":
            rep.add(A, name, WARN, "modificata ma systemd usa ancora la versione precedente", "sudo systemctl daemon-reload")
        elif (name.endswith(".timer") or name in installer.LONG_RUNNING) and props.get("UnitFileState") != "enabled":
            rep.add(A, name, FAIL, f"non abilitata ({props.get('UnitFileState', '?')})", f"sudo systemctl enable --now {name}")
        elif (name.endswith(".timer") or name in installer.LONG_RUNNING) and props.get("ActiveState") != "active":
            rep.add(A, name, FAIL, f"non attiva ({props.get('ActiveState', '?')})",
                    f"sudo systemctl restart {name}\njournalctl -u {name} -n 30 --no-pager")
        else:
            rep.add(A, name, OK)
    if ans.terminal and sh("systemctl", "is-active", "ttyd.service") == "active":
        rep.add(A, "ttyd.service (del pacchetto)", FAIL, "attivo: occupa la porta 7681 del terminale",
                "sudo systemctl disable --now ttyd.service\nsudo systemctl restart astreo-terminal.service")
    smart_files = glob.glob("/var/lib/astreo-monitor/smart/*.json")
    if not smart_files:
        rep.add(A, "dati SMART", WARN, "nessun file in /var/lib/astreo-monitor/smart",
                "sudo systemctl start astreo-smart-collect.service\njournalctl -u astreo-smart-collect -n 20 --no-pager")
    else:
        age = dt.datetime.now() - dt.datetime.fromtimestamp(max(os.path.getmtime(f) for f in smart_files))
        rep.add(A, "dati SMART", OK if age < dt.timedelta(hours=7) else WARN, f"aggiornati {int(age.total_seconds() // 3600)} h fa")


def main() -> None:
    parser = argparse.ArgumentParser(prog="astreo_monitor.doctor", description="Diagnosi dell'installazione")
    parser.add_argument("-c", "--config", default=os.environ.get("ASTREO_MONITOR_CONFIG", config_mod.DEFAULT_PATH))
    parser.add_argument("--no-color", action="store_true")
    args = parser.parse_args()
    rep = Report()
    print(f"Astreo Monitor {__version__} — diagnosi dell'installazione ({dt.datetime.now():%d/%m/%Y %H:%M})")
    print(f"Progetto: {ROOT}" + ("" if os.geteuid() == 0 else "   (senza sudo: alcuni file non sono verificabili)"))
    try:
        cfg = config_mod.load(args.config)
    except config_mod.ConfigError as exc:
        rep.add("Configurazione", args.config, FAIL, str(exc))
        sys.exit(rep.print(not args.no_color and sys.stdout.isatty()))
    check_config(rep, cfg, cfg.path)
    check_database(rep, cfg)
    check_web(rep, cfg)
    check_systemd(rep, cfg)
    sys.exit(rep.print(not args.no_color and sys.stdout.isatty()))


if __name__ == "__main__":
    main()
