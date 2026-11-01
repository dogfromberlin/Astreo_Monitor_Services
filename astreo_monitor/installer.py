"""Installatore di Astreo Monitor.

Uso (dalla cartella del progetto, con sudo):
    sudo .venv/bin/python -m astreo_monitor.installer install       # installazione guidata
    sudo .venv/bin/python -m astreo_monitor.installer update        # dopo un aggiornamento del codice
    sudo .venv/bin/python -m astreo_monitor.installer enable-https  # aggiunge nginx, certificato e terminale
    sudo .venv/bin/python -m astreo_monitor.installer adopt         # installazione esistente (2.x): crea install.ini
    sudo .venv/bin/python -m astreo_monitor.installer diff          # file installati diversi dai modelli
    sudo .venv/bin/python -m astreo_monitor.installer apply         # riscrive i file dai modelli

Le risposte (nessun segreto) sono in <config_dir>/install.ini; i file di sistema (unit systemd,
nginx, polkit) si generano dai modelli in deploy/templates e non vanno modificati a mano.
Opzioni per i test: --root DIR (prefisso per tutti i percorsi di sistema), --no-system
(niente apt, systemctl, nginx, chown), --answers FILE (risposte senza domande).
"""
from __future__ import annotations

import argparse
import configparser
import difflib
import getpass
import grp
import ipaddress
import os
import pwd
import re
import secrets
import shutil
import socket
import subprocess
import sys
from dataclasses import asdict, dataclass, field, fields

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from . import __version__
from . import i18n as _i18n

LANG = _i18n.cli_language()


def _(text: str, **values) -> str:
    """Traduzione dei messaggi a terminale (lingua: ASTREO_LANG, install.ini o LANG)."""
    return _i18n.t(text, LANG, **values)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATES = os.path.join(ROOT, "deploy", "templates")

CORE_UNITS = ["astreo-monitor-web.service", "astreo-metrics.service", "astreo-metrics.timer",
              "astreo-publicip.service", "astreo-publicip.timer", "astreo-maintenance.service", "astreo-maintenance.timer",
              "astreo-connectivity.service", "astreo-connectivity.timer", "astreo-expiry.service", "astreo-expiry.timer",
              "astreo-health.service", "astreo-health.timer", "astreo-smart-collect.service", "astreo-smart-collect.timer",
              "astreo-summary.service", "astreo-summary.timer", "astreo-telegram.service",
              "astreo-checks.service", "astreo-checks.timer"]
MODULE_UNITS = {
    "speedtest": ["astreo-speedtest.service", "astreo-speedtest.timer"],
    "backup": ["astreo-backup.service", "astreo-backup.timer", "astreo-restoretest.service", "astreo-restoretest.timer"],
    "terminal": ["astreo-terminal.service"],
}
LONG_RUNNING = {"astreo-monitor-web.service", "astreo-telegram.service", "astreo-terminal.service"}
LABELS = {"nginx": "Nginx", "apache2": "Apache", "ssh": "SSH", "docker": "Docker", "mssql-server": "SQL Server",
          "postgresql": "PostgreSQL", "mysql": "MySQL", "mariadb": "MariaDB", "pihole-FTL": "Pi-hole", "smbd": "Samba",
          "nfs-server": "NFS", "cron": "Cron", "fail2ban": "Fail2ban", "ufw": "Firewall", "wg-quick@wg0": "WireGuard",
          "openvpn-server@server": "OpenVPN", "openvpn": "OpenVPN", "ollama": "Ollama", "home-assistant": "Home Assistant",
          "jellyfin": "Jellyfin", "plexmediaserver": "Plex", "transmission-daemon": "Transmission"}
KNOWN_SERVICES = ["nginx", "apache2", "ssh", "docker", "mssql-server", "postgresql", "mysql", "mariadb", "pihole-FTL",
                  "smbd", "nfs-server", "cron", "fail2ban", "ufw", "wg-quick@wg0", "openvpn-server@server", "openvpn",
                  "ollama", "home-assistant", "jellyfin", "plexmediaserver", "transmission-daemon"]


# =============================================================================== risposte
@dataclass
class Answers:
    user: str = "astreo"
    group: str = "astreo"
    home: str = "/home/astreo"
    project_dir: str = ROOT
    config_dir: str = "/etc/astreo-monitor"
    web_port: int = 5025
    db_engine: str = "sqlite"
    https: bool = False
    https_port: int = 5443
    server_ips: list = field(default_factory=list)
    server_names: list = field(default_factory=list)
    allowed_networks: list = field(default_factory=list)
    cert_file: str = "/etc/nginx/ssl/astreo.crt"
    key_file: str = "/etc/nginx/ssl/astreo.key"
    terminal: bool = False
    speedtest: bool = True
    backup: bool = False
    netpulse: bool = False
    netpulse_port: int = 8081
    netpulse_name: str = "netpulse.local"
    language: str = "it"

    # ---------------------------------------------------------------- file
    @staticmethod
    def path(config_dir: str, root: str = "") -> str:
        return root + os.path.join(config_dir, "install.ini")

    def save(self, root: str = "") -> str:
        cp = configparser.ConfigParser()
        cp["install"] = {k: (", ".join(v) if isinstance(v, list) else str(v).lower() if isinstance(v, bool) else str(v))
                         for k, v in asdict(self).items()}
        p = self.path(self.config_dir, root)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            f.write(f"# Astreo Monitor {__version__} - risposte dell'installatore (nessun segreto).\n"
                    "# Dopo una modifica: sudo .venv/bin/python -m astreo_monitor.installer apply\n")
            cp.write(f)
        return p

    @classmethod
    def load(cls, path: str) -> "Answers":
        cp = configparser.ConfigParser()
        if not cp.read(path, encoding="utf-8"):
            raise FileNotFoundError(path)
        sec = cp["install"]
        kw = {}
        for f in fields(cls):
            if f.name not in sec:
                continue
            raw = sec[f.name]
            if f.type == "bool":
                kw[f.name] = sec.getboolean(f.name)
            elif f.type == "int":
                kw[f.name] = int(raw)
            elif f.type == "list":
                kw[f.name] = [x.strip() for x in raw.split(",") if x.strip()]
            else:
                kw[f.name] = raw
        return cls(**kw)

    # ------------------------------------------------------------ derivati
    def units(self) -> list[str]:
        out = list(CORE_UNITS)
        for mod, units in MODULE_UNITS.items():
            if getattr(self, mod) and (mod != "terminal" or self.https):
                out += units
        return out


# =============================================================================== modelli
def _env() -> Environment:
    return Environment(loader=FileSystemLoader(TEMPLATES), undefined=StrictUndefined, keep_trailing_newline=True,
                       trim_blocks=True, lstrip_blocks=True)


def render(ans: Answers) -> dict[str, str]:
    """Contenuto di ogni file di sistema, per percorso di destinazione."""
    from .collectors import units as units_mod
    env = _env()
    ctx = {**asdict(ans), "terminal": ans.terminal and ans.https}
    out = {}
    for unit in ans.units():
        out[f"/etc/systemd/system/{unit}"] = env.get_template(f"systemd/{unit}.j2").render(ctx)
    installed = set(ans.units())
    ctx["controllable"] = [u for u in sorted(units_mod.CONTROLLABLE) if u in installed]
    out["/etc/polkit-1/rules.d/50-astreo-monitor.rules"] = env.get_template("polkit/50-astreo-monitor.rules.j2").render(ctx)
    if ans.https:
        out["/etc/nginx/sites-available/astreo-monitor"] = env.get_template("nginx/astreo-monitor.conf.j2").render(ctx)
        if ans.netpulse:
            out["/etc/nginx/sites-available/netpulse"] = env.get_template("nginx/netpulse.conf.j2").render(ctx)
    with open(os.path.join(ROOT, "deploy", "bin", "astreo-smart-collect"), encoding="utf-8") as f:
        out["/usr/local/sbin/astreo-smart-collect"] = f.read()
    return out


def diff(ans: Answers, root: str = "") -> list[tuple[str, str, str]]:
    """[(percorso, stato, diff)] con stato nuovo | diverso | uguale | non leggibile."""
    res = []
    for path, content in render(ans).items():
        real = root + path
        if not os.path.exists(real):
            res.append((path, "nuovo", ""))
            continue
        try:
            with open(real, encoding="utf-8") as f:
                current = f.read()
        except PermissionError:
            res.append((path, "non leggibile", ""))
            continue
        if current == content:
            res.append((path, "uguale", ""))
        else:
            d = "".join(difflib.unified_diff(current.splitlines(True), content.splitlines(True), "installato", "modello", n=1))
            res.append((path, "diverso", d))
    return res


# =============================================================================== sistema
class System:
    def __init__(self, root: str = "", enabled: bool = True):
        self.root, self.enabled = root, enabled

    def p(self, path: str) -> str:
        return self.root + path

    def run(self, *args: str, check: bool = True, input_text: str | None = None, quiet: bool = False) -> str:
        if not self.enabled:
            return ""
        res = subprocess.run(list(args), capture_output=True, text=True, input=input_text, check=False)
        if check and res.returncode != 0:
            shown = re.sub(r"PASSWORD '[^']*'", "PASSWORD '***'", " ".join(args))     # mai le password a schermo
            raise SystemExit(_("Comando non riuscito: {p0}\n{p1}", p0=shown, p1=(res.stderr or res.stdout).strip()))
        if not quiet and res.stdout.strip():
            print(res.stdout.strip())
        return res.stdout

    def apt(self, *packages: str) -> None:
        missing = [p for p in packages if not self.enabled or subprocess.run(
            ["dpkg-query", "-W", "-f=${Status}", p], capture_output=True, text=True).stdout != "install ok installed"]
        if missing and self.enabled:
            print(_("  installo: {p0}", p0=" ".join(missing)))
            self.run("apt-get", "install", "-y", "-q", *missing, quiet=True)

    def write(self, path: str, content: str, mode: int = 0o644, owner: str | None = None) -> None:
        real = self.p(path)
        os.makedirs(os.path.dirname(real), exist_ok=True)
        with open(real, "w", encoding="utf-8") as f:
            f.write(content)
        os.chmod(real, mode)
        if owner and self.enabled:
            shutil.chown(real, owner, grp.getgrgid(pwd.getpwnam(owner).pw_gid).gr_name)

    def systemctl(self, *args: str, check: bool = True) -> str:
        return self.run("systemctl", *args, check=check, quiet=True)


def apply(ans: Answers, sysm: System, verbose: bool = True) -> list[str]:
    """Scrive i file generati dai modelli; ritorna quelli cambiati."""
    changed = []
    for path, status, _diff in diff(ans, sysm.root):
        if status == "uguale":
            continue
        mode = 0o755 if path.endswith("astreo-smart-collect") else 0o644
        sysm.write(path, render(ans)[path], mode)
        changed.append(path)
        if verbose:
            print(_("  creato: {p0}", p0=path) if status == "nuovo" else _("  aggiornato: {p0}", p0=path))
    # unit non più previste (modulo disattivato): fermate e rimosse
    for old in sorted(os.listdir(sysm.p("/etc/systemd/system")) if os.path.isdir(sysm.p("/etc/systemd/system")) else []):
        if old.startswith("astreo-") and old not in ans.units() and (old.endswith(".service") or old.endswith(".timer")):
            sysm.systemctl("disable", "--now", old, check=False)
            os.remove(sysm.p(f"/etc/systemd/system/{old}"))
            changed.append(f"/etc/systemd/system/{old}")
            print(_("  rimosso: /etc/systemd/system/{p0} (modulo disattivato)", p0=old))
    if ans.https:
        enabled = sysm.p("/etc/nginx/sites-enabled")
        os.makedirs(enabled, exist_ok=True)
        for site in ["astreo-monitor"] + (["netpulse"] if ans.netpulse else []):
            link = os.path.join(enabled, site)
            if not os.path.islink(link):
                if os.path.exists(link):
                    os.remove(link)
                os.symlink(f"/etc/nginx/sites-available/{site}", link)
    if changed and sysm.enabled:
        sysm.systemctl("daemon-reload")
        if any("polkit" in c for c in changed):
            sysm.systemctl("restart", "polkit", check=False)
        if ans.https and any("nginx" in c for c in changed):
            sysm.run("nginx", "-t", quiet=True)
            sysm.systemctl("reload", "nginx")
    return changed


def enable_units(ans: Answers, sysm: System) -> None:
    for u in ans.units():
        if u.endswith(".timer") or u in LONG_RUNNING:
            sysm.systemctl("enable", "--now", u)


# =============================================================================== rilevamento
def detect_user() -> tuple[str, str, str]:
    name = os.environ.get("SUDO_USER") or getpass.getuser()
    pw = pwd.getpwnam(name)
    return name, grp.getgrgid(pw.pw_gid).gr_name, pw.pw_dir


def detect_network() -> tuple[list[str], list[str], list[str]]:
    """(IP del server, nomi, reti) dalle interfacce: escluse loopback, docker e bridge."""
    ips, nets = [], []
    try:
        out = subprocess.run(["ip", "-4", "-o", "addr"], capture_output=True, text=True).stdout
    except OSError:
        out = ""
    for line in out.splitlines():
        parts = line.split()
        iface, cidr = parts[1], parts[3]
        if iface == "lo" or iface.startswith(("docker", "br-", "veth")):
            continue
        ip = cidr.split("/")[0]
        ips.append(ip)
        nets.append(str(ipaddress.ip_interface(cidr).network))
    host = socket.gethostname()
    return ips, [host, f"{host}.local"], nets


def detect_services() -> list[str]:
    try:
        out = subprocess.run(["systemctl", "list-units", "--type=service", "--state=running", "--no-legend", "--plain"],
                             capture_output=True, text=True).stdout
    except OSError:
        return []
    running = {line.split()[0] for line in out.splitlines() if line.strip()}
    return [s for s in KNOWN_SERVICES if f"{s}.service" in running]


# =============================================================================== domande
class Asker:
    def __init__(self, preset: dict | None = None):
        self.preset = preset            # risposte da file (--answers): nessuna domanda

    def ask(self, key: str, question: str, default: str = "") -> str:
        if self.preset is not None:
            return str(self.preset.get(key, default))
        v = input(f"{question}{f' [{default}]' if default else ''}: ").strip()
        return v or default

    def yes(self, key: str, question: str, default: bool) -> bool:
        if self.preset is not None:
            v = self.preset.get(key, default)
            return v if isinstance(v, bool) else str(v).lower() in ("1", "true", "si", "sì", "yes", "s", "y")
        v = input(f"{question} [{'S/n' if default else 's/N'}]: ").strip().lower()
        return default if not v else v in ("s", "si", "sì", "y", "yes")

    def secret(self, key: str, question: str, confirm: bool = True, allow_empty: bool = False) -> str:
        if self.preset is not None:
            return str(self.preset.get(key, ""))
        while True:
            a = getpass.getpass(f"{question}: ")
            if not a and allow_empty:
                return ""
            if len(a) < 8 and not allow_empty:
                print(_("  almeno 8 caratteri"))
                continue
            if not confirm or getpass.getpass("  ripeti: ") == a:
                return a
            print(_("  le due password non coincidono"))


def as_list(v: str) -> list[str]:
    return [x.strip() for x in str(v).split(",") if x.strip()]


# =============================================================================== database
def setup_database(ans: Answers, ask: Asker, sysm: System) -> tuple[dict, tuple[str | None, str | None]]:
    """Prepara il database. Ritorna (sezione [database] del config, credenziali admin per migrate)."""
    if ans.db_engine == "sqlite":
        path = ask.ask("db_path", _("File del database SQLite"), "/var/lib/astreo-monitor/astreo_monitor.db")
        os.makedirs(os.path.dirname(sysm.p(path)), exist_ok=True)
        if sysm.enabled:
            shutil.chown(os.path.dirname(path), ans.user, ans.group)
        return {"engine": "sqlite", "path": path}, (None, None)

    if ans.db_engine == "postgresql":
        host = ask.ask("db_host", _("Server PostgreSQL (127.0.0.1 = installalo qui)"), "127.0.0.1")
        name = ask.ask("db_name", _("Nome del database"), "astreo_monitor")
        user = ask.ask("db_user", _("Utente dell'applicazione"), "astreo_app")
        password = ask.ask("db_password", "", "") or secrets.token_urlsafe(18)
        if host in ("127.0.0.1", "localhost") and sysm.enabled:
            sysm.apt("postgresql", "postgresql-client")
            sql = (f"DO $$ BEGIN IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{user}') THEN "
                   f"CREATE ROLE \"{user}\" LOGIN CREATEDB PASSWORD '{password}'; ELSE "
                   f"ALTER ROLE \"{user}\" LOGIN CREATEDB PASSWORD '{password}'; END IF; END $$;")
            sysm.run("runuser", "-u", "postgres", "--", "psql", "-q", "-v", "ON_ERROR_STOP=1", "-c", sql, quiet=True)
            exists = sysm.run("runuser", "-u", "postgres", "--", "psql", "-tAc", f"SELECT 1 FROM pg_database WHERE datname = '{name}'",
                              quiet=True).strip()
            if exists != "1":
                sysm.run("runuser", "-u", "postgres", "--", "psql", "-q", "-c", f'CREATE DATABASE "{name}" OWNER "{user}"', quiet=True)
            print(_("  PostgreSQL: database {p0}, utente {p1} (proprietario: crea lui le tabelle)", p0=name, p1=user))
            admin = (user, password)        # proprietario del database: nessun amministratore necessario
        else:
            admin = (ask.ask("db_admin_user", _("Amministratore PostgreSQL per creare le tabelle"), "postgres"),
                     ask.secret("db_admin_password", _("Password dell'amministratore"), confirm=False))
        return {"engine": "postgresql", "host": host, "port": "5432", "database": name, "user": user,
                "password": password}, admin

    # SQL Server (deve già esistere)
    host = ask.ask("db_host", _("Server SQL Server"), "127.0.0.1")
    port = ask.ask("db_port", _("Porta"), "1433")
    name = ask.ask("db_name", _("Nome del database (creato se manca)"), "astreo_monitor")
    user = ask.ask("db_user", _("Login dell'applicazione (creato se manca)"), "astreo_monitor_app")
    password = ask.ask("db_password", "", "") or (secrets.token_urlsafe(14) + "Aa1!")
    admin_user = ask.ask("db_admin_user", _("Amministratore SQL Server"), "sa")
    admin_password = ask.secret("db_admin_password", _("Password di {p0}", p0=admin_user), confirm=False)
    if sysm.enabled or ask.preset is not None:
        mssql_prepare(host, int(port), name, user, password, admin_user, admin_password, ans.backup)
    return {"engine": "mssql", "host": host, "port": port, "database": name, "user": user, "password": password}, \
        (admin_user, admin_password)


def mssql_prepare(host, port, name, user, password, admin_user, admin_password, backup: bool) -> None:
    """Database, login e utente dell'applicazione; con il backup anche i permessi e le procedure firmate."""
    import pymssql
    c = pymssql.connect(server=host, port=port, user=admin_user, password=admin_password, autocommit=True, tds_version="7.3")
    cur = c.cursor()
    q = lambda s: s.replace("]", "]]")                      # noqa: E731
    cur.execute(f"IF DB_ID(%s) IS NULL CREATE DATABASE [{q(name)}]", (name,))
    cur.execute("SELECT 1 FROM sys.server_principals WHERE name = %s", (user,))
    if cur.fetchone():
        cur.execute(f"ALTER LOGIN [{q(user)}] WITH PASSWORD = %s", (password,))
    else:
        cur.execute(f"CREATE LOGIN [{q(user)}] WITH PASSWORD = %s, CHECK_POLICY = ON, CHECK_EXPIRATION = OFF", (password,))
    cur.execute(f"USE [{q(name)}]; IF DATABASE_PRINCIPAL_ID(%s) IS NULL CREATE USER [{q(user)}] FOR LOGIN [{q(user)}]; "
                f"ALTER ROLE db_datareader ADD MEMBER [{q(user)}]; ALTER ROLE db_datawriter ADD MEMBER [{q(user)}];", (user,))
    if backup:
        cur.execute(f"USE [{q(name)}]; ALTER ROLE db_backupoperator ADD MEMBER [{q(user)}];")
        cur.execute(f"USE master; IF DATABASE_PRINCIPAL_ID(%s) IS NULL CREATE USER [{q(user)}] FOR LOGIN [{q(user)}]; "
                    f"GRANT CREATE DATABASE TO [{q(user)}];", (user,))
        with open(os.path.join(ROOT, "sql", "008_verifica_ripristino.sql"), encoding="utf-8") as f:
            script = f.read().replace("astreo_monitor_app", user)
        for batch in re.split(r"^\s*GO\s*$", script, flags=re.M | re.I):
            if batch.strip():
                cur.execute(batch)
                while cur.nextset():
                    pass
    c.close()
    print(f"  SQL Server: database {name}, login {user}" + (_(" con permessi di backup") if backup else ""))


# =============================================================================== HTTPS e terminale
def setup_https(ans: Answers, sysm: System) -> None:
    sysm.apt("nginx", "mkcert")
    ca_dir = os.path.join(ans.config_dir, "ca")
    os.makedirs(sysm.p(ca_dir), mode=0o700, exist_ok=True)
    if not os.path.exists(sysm.p(ans.cert_file)):
        names = ans.server_ips + ans.server_names + ["localhost", "127.0.0.1"] + ([ans.netpulse_name] if ans.netpulse else [])
        os.makedirs(os.path.dirname(sysm.p(ans.cert_file)), exist_ok=True)
        if sysm.enabled:
            sysm.run("env", f"CAROOT={ca_dir}", "mkcert", "-cert-file", ans.cert_file, "-key-file", ans.key_file,
                     *dict.fromkeys(names), quiet=True)
            os.chmod(ans.key_file, 0o600)
            shutil.copy(os.path.join(ca_dir, "rootCA.pem"), os.path.join(ans.config_dir, "astreo-ca.crt"))
            os.chmod(os.path.join(ans.config_dir, "astreo-ca.crt"), 0o644)
        print(_("  certificato creato per: {p0}", p0=', '.join(dict.fromkeys(names))))
    else:
        print(_("  certificato esistente mantenuto: {p0}", p0=ans.cert_file))


def setup_terminal(ans: Answers, sysm: System) -> None:
    sysm.apt("ttyd")
    if sysm.enabled:
        sysm.systemctl("disable", "--now", "ttyd.service", check=False)   # quello del pacchetto occupa la porta 7681
    env_file = os.path.join(ans.config_dir, "terminal.env")
    snippet = "/etc/nginx/snippets/astreo-terminal-auth.conf"
    if not os.path.exists(sysm.p(env_file)):
        import base64
        cred = f"astreo:{secrets.token_hex(24)}"
        sysm.write(env_file, f"TTYD_CREDENTIAL={cred}\n", 0o600)
        sysm.write(snippet, f'proxy_set_header Authorization "Basic {base64.b64encode(cred.encode()).decode()}";\n', 0o600)
        print(_("  credenziale interna nginx ↔ ttyd creata"))


# =============================================================================== configurazione
def write_config(ans: Answers, sysm: System, dbsec: dict, web_password: str, terminal_password: str,
                 services: list[str], backup_extra: dict) -> str:
    from werkzeug.security import generate_password_hash
    path = os.path.join(ans.config_dir, "config.ini")
    cp = configparser.ConfigParser(interpolation=None)
    cp.read(os.path.join(ROOT, "config.example.ini"), encoding="utf-8")
    cp.remove_section("database")
    cp["database"] = dbsec
    w = cp["web"]
    w["host"] = "127.0.0.1" if ans.https else "0.0.0.0"
    w["port"] = str(ans.web_port)
    w["username"] = ans.user
    w["password_hash"] = generate_password_hash(web_password)
    w["trusted_proxy"] = "127.0.0.1" if ans.https else ""
    w["https_port"] = str(ans.https_port if ans.https else 0)
    w["ca_cert"] = os.path.join(ans.config_dir, "astreo-ca.crt")
    if cp.has_section("email"):
        cp["email"]["enabled"] = "false"          # si configura da Impostazioni > Notifiche
    cp.remove_section("services")
    cp["services"] = {s: f"{s} | {LABELS.get(s, s)}" for s in services}   # chiave = unit | etichetta
    if ans.backup:
        cp["backup"]["github_repo"] = ""
        for k, v in backup_extra.items():
            cp["backup"][k] = v
    else:
        cp.remove_section("backup")
    if ans.netpulse:
        tok = os.path.join(ans.config_dir, "netpulse_token")
        if not os.path.exists(sysm.p(tok)):
            sysm.write(tok, secrets.token_urlsafe(32) + "\n", 0o600, owner=ans.user)
        cp["netpulse"] = {"token_file": tok}
    else:
        cp.remove_section("netpulse")
    cp.remove_section("terminal")
    if ans.https and ans.terminal:
        cp["terminal"] = {"enabled": "true", "password_hash": generate_password_hash(terminal_password),
                          "session_minutes": "15", "allowed_networks": ", ".join(ans.allowed_networks)}
    from io import StringIO
    buf = StringIO()
    cp.write(buf)
    sysm.write(path, _("# Astreo Monitor {p0} - generato dall'installatore. Guida: docs/configurazione.md\n", p0=__version__)
               + buf.getvalue(), 0o600, owner=ans.user)
    return path


# =============================================================================== comandi
def cmd_install(args, sysm: System) -> None:
    preset = None
    if args.answers:
        cp = configparser.ConfigParser(interpolation=None)
        cp.read(args.answers, encoding="utf-8")
        preset = dict(cp["answers"])
    ask = Asker(preset)
    global LANG
    LANG = _i18n.normalize(ask.ask("language", "Lingua / Language (it, en)", LANG))
    os.environ["ASTREO_LANG"] = LANG                  # vale anche per migrate e diagnosi lanciati da qui
    user, group, home = detect_user()
    ips, names, nets = detect_network()
    print(_("\n=== Astreo Monitor {p0} — installazione ===\n", p0=__version__))
    a = Answers(language=LANG)
    a.user = ask.ask("user", _("Utente con cui girano i servizi"), user)
    pw = pwd.getpwnam(a.user) if sysm.enabled else None
    a.group = grp.getgrgid(pw.pw_gid).gr_name if pw else ask.ask("group", _("Gruppo"), group)
    a.home = pw.pw_dir if pw else ask.ask("home", _("Cartella home"), home)
    a.config_dir = ask.ask("config_dir", _("Cartella della configurazione"), "/etc/astreo-monitor")
    a.web_port = int(ask.ask("web_port", _("Porta interna della dashboard"), "5025"))
    a.db_engine = ask.ask("db_engine", _("Database: sqlite, postgresql o mssql"), "sqlite").lower()
    if a.db_engine not in ("sqlite", "postgresql", "mssql"):
        raise SystemExit(_("Database non valido"))
    a.https = ask.yes("https", _("Dashboard in HTTPS con nginx (consigliato; necessario per il terminale)"), True)
    if a.https:
        a.https_port = int(ask.ask("https_port", _("Porta HTTPS"), "5443"))
        a.server_ips = as_list(ask.ask("server_ips", _("IP del server (per il certificato)"), ", ".join(ips)))
        a.server_names = as_list(ask.ask("server_names", _("Nomi del server"), ", ".join(names)))
        a.terminal = ask.yes("terminal", _("Terminale web (shell nel browser, con password separata)"), True)
    a.allowed_networks = as_list(ask.ask("allowed_networks", _("Reti ammesse al terminale (LAN, VPN)"), ", ".join(nets))) \
        if a.terminal else []
    a.speedtest = ask.yes("speedtest", _("Speedtest periodico"), True)
    a.backup = ask.yes("backup", _("Backup notturno del database (con copia facoltativa su GitHub)"), True)
    a.netpulse = a.https and ask.yes("netpulse", _("Compatibilità con il widget Windows NetPulse"), False)
    services = as_list(ask.ask("services", _("Servizi da monitorare"), ", ".join(detect_services())))

    print("\n--- " + _("Database"))
    if sysm.enabled and a.db_engine != "sqlite":
        sysm.apt("zstd")
    dbsec, admin = setup_database(a, ask, sysm)
    backup_extra = {}
    if a.backup:
        backup_extra = {"local_dir": ask.ask("backup_dir", _("Cartella dei backup"), os.path.join(a.home, "backups", "astreo")),
                        "github_repo": ask.ask("github_repo", _("Repository GitHub privato per i backup (vuoto = nessuno)"), ""),
                        "databases": dbsec.get("database", "astreo_monitor")}
        if a.db_engine == "mssql":
            backup_extra["sql_dir"] = ask.ask("sql_dir", _("Cartella condivisa con SQL Server per i file .bak"), "/srv/sqlbackup")
        os.makedirs(sysm.p(backup_extra["local_dir"]), exist_ok=True)
        if sysm.enabled:
            shutil.chown(backup_extra["local_dir"], a.user, a.group)
            sysm.apt("zstd")

    print("\n--- " + _("Accesso"))
    web_password = ask.secret("web_password", _("Password della dashboard (utente {p0})", p0=a.user))
    term_password = ask.secret("terminal_password", _("Password del terminale (diversa dalla precedente)")) if a.terminal else ""
    os.makedirs(sysm.p(a.config_dir), exist_ok=True)
    if a.https:
        print("\n--- HTTPS")
        setup_https(a, sysm)
        if a.terminal:
            setup_terminal(a, sysm)
    cfg_path = write_config(a, sysm, dbsec, web_password, term_password, services, backup_extra)
    a.save(sysm.root)
    print(_("  configurazione: {p0}", p0=cfg_path))

    print(_("\n--- Schema del database"))
    from . import config as config_mod, migrate
    loaded = config_mod.load(sysm.p(cfg_path))
    migrate.run(loaded, *admin, out=print)
    from . import db, settings as settings_mod
    with db.connect(loaded.database) as conn:            # lingua di dashboard, notifiche e bot
        settings_mod.save(conn, loaded, {"ui.language": LANG})

    print("\n--- " + _("Servizi"))
    if sysm.enabled:
        sysm.apt("smartmontools", "iputils-ping")
    apply(a, sysm)
    if sysm.enabled:
        enable_units(a, sysm)
    url = f"https://{(a.server_ips or ['IP-del-server'])[0]}:{a.https_port}/" if a.https else \
        f"http://{(ips or ['IP-del-server'])[0]}:{a.web_port}/"
    print(_("\nInstallazione completata. Dashboard: {p0}  (utente {p1})", p0=url, p1=a.user))
    if not a.https:
        print(_("ATTENZIONE: connessione NON cifrata (HTTP). Per HTTPS e terminale: sudo bash update.sh --enable-https"))
    elif a.https:
        print(_("Per evitare gli avvisi del browser installa la CA sui dispositivi: {p0}astreo-ca.crt (docs/certificato.md)", p0=url))
    if sysm.enabled:
        subprocess.run([sys.executable, "-m", "astreo_monitor.doctor", "-c", cfg_path, "--no-color"])


def load_answers(args, sysm: System) -> Answers:
    p = Answers.path(args.config_dir, sysm.root)
    if not os.path.exists(p):
        raise SystemExit(_("{p0} non trovato: per un'installazione esistente lancia prima 'sudo .venv/bin/python -m astreo_monitor.installer adopt'", p0=p))
    return Answers.load(p)


def cmd_diff(args, sysm: System) -> int:
    ans = load_answers(args, sysm)
    worst = 0
    for path, status, d in diff(ans, sysm.root):
        print(f"{status:>14}  {path}")
        if d and args.verbose:
            print(d)
        worst = max(worst, 0 if status == "uguale" else 1)
    return worst


def cmd_update(args, sysm: System, enable_https: bool = False) -> None:
    from . import config as config_mod, migrate
    ans = load_answers(args, sysm)
    cfg_path = os.path.join(ans.config_dir, "config.ini")
    if enable_https and not ans.https:
        ask = Asker()
        ips, names, nets = detect_network()
        ans.https = True
        ans.https_port = int(ask.ask("https_port", _("Porta HTTPS"), "5443"))
        ans.server_ips = as_list(ask.ask("server_ips", _("IP del server"), ", ".join(ips)))
        ans.server_names = as_list(ask.ask("server_names", _("Nomi del server"), ", ".join(names)))
        ans.terminal = ask.yes("terminal", _("Attivare il terminale web"), True)
        setup_https(ans, sysm)
        cp = configparser.ConfigParser(interpolation=None)
        cp.read(sysm.p(cfg_path), encoding="utf-8")
        cp["web"]["host"], cp["web"]["trusted_proxy"], cp["web"]["https_port"] = "127.0.0.1", "127.0.0.1", str(ans.https_port)
        if ans.terminal:
            from werkzeug.security import generate_password_hash
            ans.allowed_networks = as_list(ask.ask("allowed_networks", _("Reti ammesse al terminale"), ", ".join(nets)))
            setup_terminal(ans, sysm)
            cp["terminal"] = {"enabled": "true", "session_minutes": "15", "allowed_networks": ", ".join(ans.allowed_networks),
                              "password_hash": generate_password_hash(ask.secret("terminal_password", _("Password del terminale")))}
        from io import StringIO
        buf = StringIO()
        cp.write(buf)
        sysm.write(cfg_path, buf.getvalue(), 0o600, owner=ans.user)
        ans.save(sysm.root)
    print(_("--- File di sistema"))
    changed = apply(ans, sysm)
    if not changed:
        print(_("  nessuna modifica"))
    print(_("--- Schema del database"))
    cfg = config_mod.load(sysm.p(cfg_path))
    from . import db
    with db.connect(cfg.database) as conn:
        st = migrate.status(conn)
    if st["current"] == st["head"] and not st["legacy_2x"]:
        print(_("  già aggiornato (revisione {p0})", p0=st['head']))
    else:
        admin = (None, None)
        if cfg.database.engine == "mssql" or (cfg.database.engine == "postgresql" and cfg.database.host not in ("127.0.0.1", "localhost")):
            default = "sa" if cfg.database.engine == "mssql" else "postgres"
            admin = (default, getpass.getpass(_("Password di {p0} per aggiornare lo schema: ", p0=default)))
        elif cfg.database.engine == "postgresql":
            admin = (cfg.database.user, cfg.database.password)
        migrate.run(cfg, *admin)
    if sysm.enabled:
        enable_units(ans, sysm)
        sysm.systemctl("restart", *[u for u in ans.units() if u in LONG_RUNNING])
        print("--- " + _("Diagnosi"))
        subprocess.run([sys.executable, "-m", "astreo_monitor.doctor", "-c", sysm.p(cfg_path), "--no-color"])


def cmd_adopt(args, sysm: System) -> None:
    """Crea install.ini per un'installazione esistente, ricavando le risposte dai file presenti."""
    from . import config as config_mod
    cfg_path = os.path.join(args.config_dir, "config.ini")
    cfg = config_mod.load(sysm.p(cfg_path))
    a = Answers(config_dir=args.config_dir)
    unit = sysm.p("/etc/systemd/system/astreo-monitor-web.service")
    text = open(unit, encoding="utf-8").read() if os.path.exists(unit) else ""
    m = re.search(r"^User=(\S+)", text, re.M)
    a.user = m.group(1) if m else detect_user()[0]
    pw = pwd.getpwnam(a.user) if sysm.enabled else None
    a.group = grp.getgrgid(pw.pw_gid).gr_name if pw else (re.search(r"^Group=(\S+)", text, re.M) or [None, a.user])[1]
    a.home = pw.pw_dir if pw else f"/home/{a.user}"
    m = re.search(r"^WorkingDirectory=(\S+)", text, re.M)
    a.project_dir = m.group(1) if m else ROOT
    a.web_port = cfg.web.port
    a.db_engine = cfg.database.engine
    try:                                               # lingua già scelta nella dashboard
        from . import db, settings as settings_mod
        with db.connect(cfg.database) as conn:
            a.language = _i18n.normalize(settings_mod.load(conn, cfg)["ui.language"])
    except Exception:  # noqa: BLE001
        a.language = LANG
    site = sysm.p("/etc/nginx/sites-available/astreo-monitor")
    if os.path.exists(site):
        s = open(site, encoding="utf-8").read()
        a.https = True
        a.https_port = int(re.search(r"listen (\d+) ssl", s).group(1))
        a.cert_file = re.search(r"ssl_certificate\s+(\S+);", s).group(1)
        a.key_file = re.search(r"ssl_certificate_key\s+(\S+);", s).group(1)
        a.allowed_networks = re.findall(r"allow (\S+);", s)
        a.terminal = "location /terminal/" in s and bool(cfg.terminal and cfg.terminal.enabled)
    a.speedtest = os.path.exists(sysm.p("/etc/systemd/system/astreo-speedtest.timer"))
    a.backup = os.path.exists(sysm.p("/etc/systemd/system/astreo-backup.timer"))
    np = sysm.p("/etc/nginx/sites-available/netpulse")
    if os.path.exists(np):
        s = open(np, encoding="utf-8").read()
        a.netpulse = True
        a.netpulse_port = int(re.search(r"listen (\d+) ssl", s).group(1))
        a.netpulse_name = re.search(r"server_name (\S+);", s).group(1)
    if a.https and os.path.exists(sysm.p(a.cert_file)) and sysm.enabled:
        san = subprocess.run(["openssl", "x509", "-in", a.cert_file, "-noout", "-ext", "subjectAltName"],
                             capture_output=True, text=True).stdout
        a.server_ips = [x for x in re.findall(r"IP Address:([\d.]+)", san) if x != "127.0.0.1"]
        a.server_names = [x for x in re.findall(r"DNS:([^,\s]+)", san) if x not in ("localhost", a.netpulse_name)]
    p = a.save(sysm.root)
    print(_("Risposte ricavate dall'installazione esistente e salvate in {p0}:\n", p0=p))
    print(open(p, encoding="utf-8").read())
    print(_("Confronto tra i file installati e quelli generati dai modelli:\n"))
    for path, status, d in diff(a, sysm.root):
        print(f"{status:>14}  {path}")
        if d:
            print(d)


def main() -> None:
    parser = argparse.ArgumentParser(prog="astreo_monitor.installer", description=_("Installatore di Astreo Monitor"))
    parser.add_argument("command", choices=["install", "update", "enable-https", "adopt", "diff", "apply"])
    parser.add_argument("--config-dir", default="/etc/astreo-monitor")
    parser.add_argument("--answers", help=_("file con le risposte (sezione [answers]): nessuna domanda"))
    parser.add_argument("--root", default="", help=_("prefisso dei percorsi di sistema (test)"))
    parser.add_argument("--no-system", action="store_true", help=_("niente apt, systemctl, nginx, chown (test)"))
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()
    sysm = System(args.root.rstrip("/"), enabled=not args.no_system)
    if sysm.enabled and os.geteuid() != 0:
        raise SystemExit(_("Va eseguito con sudo: sudo .venv/bin/python -m astreo_monitor.installer ") + args.command)
    if args.command == "install":
        cmd_install(args, sysm)
    elif args.command == "update":
        cmd_update(args, sysm)
    elif args.command == "enable-https":
        cmd_update(args, sysm, enable_https=True)
    elif args.command == "adopt":
        cmd_adopt(args, sysm)
    elif args.command == "diff":
        sys.exit(cmd_diff(args, sysm))
    elif args.command == "apply":
        apply(load_answers(args, sysm), sysm)


if __name__ == "__main__":
    main()
