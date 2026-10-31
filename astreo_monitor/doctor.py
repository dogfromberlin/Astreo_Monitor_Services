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
import filecmp
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


def same_file(installed: str, source: str) -> str | None:
    """OK, 'diverso', 'mancante' o None se non leggibile."""
    if not os.path.exists(installed):
        return "mancante"
    try:
        return OK if filecmp.cmp(installed, source, shallow=False) else "diverso"
    except PermissionError:
        return None


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
            rep.add(A, f"connessione a {cfg.database.host} ({cfg.database.user})", OK)
            problems = schema.check(conn, cfg.backup.databases if cfg.backup else None)
            if not problems:
                rep.add(A, "schema (tabelle, colonne, procedure, permessi)", OK)
            for p in problems:
                rep.add(A, p["item"], FAIL, p["problem"], f"nel client SQL, come sa: esegui sql/{p['script']}")
            state = {r["key"]: r for r in db.query(conn, "SELECT [key], updated_at FROM monitor_state")}
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
    for url, v in (("https://127.0.0.1:5443/api/v1/health", verify), (f"http://127.0.0.1:{cfg.web.port}/api/v1/health", True)):
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
            rep.add(A, "schema visto dalla dashboard", FAIL, ", ".join(h.get("schema_scripts", [])), "vedi la sezione Database")
        return
    rep.add(A, "risposta", FAIL, "né https://127.0.0.1:5443 né la porta locale rispondono",
            "systemctl status astreo-monitor-web.service nginx --no-pager")


def check_systemd(rep: Report, cfg) -> None:
    A = "Servizi systemd"
    files = sorted(glob.glob(os.path.join(ROOT, "deploy", "systemd", "astreo-*")))
    stale = []
    for src in files:
        name = os.path.basename(src)
        if name == "astreo-terminal.service" and not (cfg.terminal and cfg.terminal.enabled):
            continue
        res = same_file(f"/etc/systemd/system/{name}", src)
        if res == "mancante":
            rep.add(A, name, FAIL, "non installata", f"sudo cp deploy/systemd/{name} /etc/systemd/system/\nsudo systemctl daemon-reload")
            continue
        if res == "diverso":
            stale.append(name)
            rep.add(A, name, FAIL, "diversa da quella del progetto (versione vecchia?)",
                    f"sudo cp deploy/systemd/{name} /etc/systemd/system/\nsudo systemctl daemon-reload")
            continue
        unit_state = sh("systemctl", "show", name, "-p", "NeedDaemonReload,UnitFileState,ActiveState")
        props = dict(line.split("=", 1) for line in unit_state.splitlines() if "=" in line)
        if props.get("NeedDaemonReload") == "yes":
            rep.add(A, name, WARN, "modificata ma systemd usa ancora la versione precedente", "sudo systemctl daemon-reload")
            continue
        long_running = name.endswith(".timer") or name in ("astreo-monitor-web.service", "astreo-telegram.service",
                                                             "astreo-terminal.service")
        if long_running and props.get("UnitFileState") != "enabled":
            rep.add(A, name, FAIL, f"non abilitata ({props.get('UnitFileState', '?')})", f"sudo systemctl enable --now {name}")
        elif long_running and props.get("ActiveState") != "active":
            rep.add(A, name, FAIL, f"non attiva ({props.get('ActiveState', '?')})",
                    f"sudo systemctl restart {name}\njournalctl -u {name} -n 30 --no-pager")
        else:
            rep.add(A, name, OK)
    if stale:
        rep.add(A, "dopo la copia", WARN, "ricordati di riavviare i servizi aggiornati",
                "sudo systemctl restart astreo-monitor-web.service astreo-telegram.service")
    if sh("systemctl", "is-active", "ttyd.service") == "active":
        rep.add(A, "ttyd.service (del pacchetto)", FAIL, "attivo: occupa la porta 7681 del terminale",
                "sudo systemctl disable --now ttyd.service\nsudo systemctl restart astreo-terminal.service")


def check_files(rep: Report) -> None:
    A = "File installati"
    pairs = [("/usr/local/sbin/astreo-smart-collect", "deploy/bin/astreo-smart-collect",
              "sudo install -m 755 deploy/bin/astreo-smart-collect /usr/local/sbin/astreo-smart-collect"),
             ("/etc/polkit-1/rules.d/50-astreo-monitor.rules", "deploy/polkit/50-astreo-monitor.rules",
              "sudo cp deploy/polkit/50-astreo-monitor.rules /etc/polkit-1/rules.d/\nsudo systemctl restart polkit"),
             ("/etc/nginx/sites-available/astreo-monitor", "deploy/nginx/astreo-monitor.conf",
              "confronta con: diff deploy/nginx/astreo-monitor.conf /etc/nginx/sites-available/astreo-monitor\n"
              "(le righe allow possono essere state adattate alla tua VPN)"),
             ("/etc/nginx/sites-available/netpulse", "deploy/nginx/netpulse.conf",
              "confronta con: diff deploy/nginx/netpulse.conf /etc/nginx/sites-available/netpulse")]
    for installed, source, fix in pairs:
        res = same_file(installed, os.path.join(ROOT, source))
        if res is None:
            rep.add(A, installed, SKIP, "non leggibile: rilancia la diagnosi con sudo")
        elif res == OK:
            rep.add(A, installed, OK)
        else:
            sev = WARN if "nginx" in installed else FAIL
            rep.add(A, installed, sev, res, fix)
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
    check_files(rep)
    sys.exit(rep.print(not args.no_color and sys.stdout.isatty()))


if __name__ == "__main__":
    main()
