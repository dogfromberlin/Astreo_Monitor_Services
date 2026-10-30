"""Caricamento della configurazione da file INI.

Il percorso del file si ricava, in ordine:
1. argomento esplicito (es. --config da riga di comando);
2. variabile d'ambiente ASTREO_MONITOR_CONFIG;
3. /etc/astreo-monitor/config.ini
"""
from __future__ import annotations

import configparser
import os
from dataclasses import dataclass, field

DEFAULT_PATH = "/etc/astreo-monitor/config.ini"


class ConfigError(Exception):
    """Configurazione mancante o non valida."""


def _list(value: str) -> list[str]:
    return [v.strip() for v in value.replace("\n", ",").split(",") if v.strip()]


@dataclass
class DatabaseConfig:
    host: str
    port: int
    database: str
    user: str
    password: str
    login_timeout: int = 10
    timeout: int = 30


@dataclass
class EmailConfig:
    enabled: bool
    sender: str
    recipients: list[str]
    smtp_host: str
    smtp_port: int
    security: str  # ssl | starttls | none
    username: str
    password: str
    subject_prefix: str


@dataclass
class ServiceDef:
    key: str
    unit: str
    label: str


@dataclass
class WebConfig:
    host: str
    port: int
    threads: int
    username: str
    password_hash: str
    services: list[ServiceDef] = field(default_factory=list)
    trusted_proxy: str = ""     # es. 127.0.0.1 quando la dashboard è dietro nginx (HTTPS)


@dataclass
class MetricsConfig:
    root_disk: str
    temp_warning: float
    temp_alert: float
    disk_warning: float
    disk_alert: float
    notify: bool
    reminder_hours: float


@dataclass
class SpeedtestConfig:
    download_alert: float
    download_warning: float
    upload_alert: float
    upload_warning: float
    streams: int
    rounds: int
    download_bytes: int
    upload_bytes: int
    timeout: int
    notify: bool
    reminder_hours: float


@dataclass
class PublicIpConfig:
    providers: list[str]
    timeout: int
    notify: bool


@dataclass
class RetentionConfig:
    metrics_days: int
    temperature_days: int
    speedtest_days: int
    publicip_days: int
    connectivity_days: int = 90


@dataclass
class BackupConfig:
    databases: list[str]
    sql_dir: str          # cartella vista da SQL Server, dove scrive il .bak
    local_dir: str        # copie compresse conservate su astreo
    local_keep: int
    github_repo: str      # owner/nome; vuoto = nessun upload
    github_keep: int
    zstd_level: int
    timeout: int
    notify: bool
    reminder_hours: float


@dataclass
class NetpulseConfig:
    token: str            # stesso token del vecchio NetPulse: il widget Windows resta invariato


@dataclass
class TerminalConfig:
    enabled: bool
    password_hash: str          # password SEPARATA da quella della dashboard
    session_minutes: int
    allowed_networks: list[str]


@dataclass
class Config:
    path: str
    database: DatabaseConfig
    email: EmailConfig
    web: WebConfig
    metrics: MetricsConfig
    speedtest: SpeedtestConfig
    publicip: PublicIpConfig
    retention: RetentionConfig
    backup: BackupConfig | None = None
    netpulse: NetpulseConfig | None = None
    terminal: TerminalConfig | None = None


def load(path: str | None = None) -> Config:
    path = path or os.environ.get("ASTREO_MONITOR_CONFIG") or DEFAULT_PATH
    if not os.path.isfile(path):
        raise ConfigError(f"File di configurazione non trovato: {path}")

    # interpolation=None: le password possono contenere '%' e '$'
    cp = configparser.ConfigParser(interpolation=None, inline_comment_prefixes=("#", ";"))
    cp.read(path, encoding="utf-8")

    def sec(name: str) -> configparser.SectionProxy:
        if not cp.has_section(name):
            raise ConfigError(f"Sezione [{name}] mancante in {path}")
        return cp[name]

    try:
        db = sec("database")
        database = DatabaseConfig(
            host=db.get("host"),
            port=db.getint("port", 1433),
            database=db.get("database"),
            user=db.get("user"),
            password=db.get("password", ""),
            login_timeout=db.getint("login_timeout", 10),
            timeout=db.getint("timeout", 30),
        )

        em = sec("email")
        email = EmailConfig(
            enabled=em.getboolean("enabled", True),
            sender=em.get("sender", ""),
            recipients=_list(em.get("recipients", "")),
            smtp_host=em.get("smtp_host", "smtp.gmail.com"),
            smtp_port=em.getint("smtp_port", 465),
            security=em.get("security", "ssl").lower(),
            username=em.get("username", ""),
            password=em.get("password", ""),
            subject_prefix=em.get("subject_prefix", "[Astreo Monitor]"),
        )

        services = []
        if cp.has_section("services"):
            for key, raw in cp["services"].items():
                unit, _, label = raw.partition("|")
                services.append(ServiceDef(key=key.strip(), unit=unit.strip(), label=(label.strip() or key.strip())))

        w = sec("web")
        web = WebConfig(
            host=w.get("host", "0.0.0.0"),
            port=w.getint("port", 5025),
            threads=w.getint("threads", 8),
            username=w.get("username", ""),
            password_hash=w.get("password_hash", ""),
            services=services,
            trusted_proxy=w.get("trusted_proxy", "").strip(),
        )

        m = sec("metrics")
        metrics = MetricsConfig(
            root_disk=m.get("root_disk", "/"),
            temp_warning=m.getfloat("temp_warning", 85),
            temp_alert=m.getfloat("temp_alert", 95),
            disk_warning=m.getfloat("disk_warning", 85),
            disk_alert=m.getfloat("disk_alert", 95),
            notify=m.getboolean("notify", True),
            reminder_hours=m.getfloat("reminder_hours", 24),
        )

        s = sec("speedtest")
        speedtest = SpeedtestConfig(
            download_alert=s.getfloat("download_alert"),
            download_warning=s.getfloat("download_warning"),
            upload_alert=s.getfloat("upload_alert"),
            upload_warning=s.getfloat("upload_warning"),
            streams=s.getint("streams", 4),
            rounds=s.getint("rounds", 3),
            download_bytes=s.getint("download_bytes", 25_000_000),
            upload_bytes=s.getint("upload_bytes", 10_000_000),
            timeout=s.getint("timeout", 60),
            notify=s.getboolean("notify", False),
            reminder_hours=s.getfloat("reminder_hours", 24),
        )

        p = sec("publicip")
        publicip = PublicIpConfig(
            providers=_list(p.get("providers", "https://checkip.amazonaws.com")),
            timeout=p.getint("timeout", 10),
            notify=p.getboolean("notify", True),
        )

        r = sec("retention")
        retention = RetentionConfig(
            metrics_days=r.getint("metrics_days", 365),
            temperature_days=r.getint("temperature_days", 365),
            speedtest_days=r.getint("speedtest_days", 0),
            publicip_days=r.getint("publicip_days", 0),
            connectivity_days=r.getint("connectivity_days", 90),
        )
        backup = None
        if cp.has_section("backup"):
            b = cp["backup"]
            backup = BackupConfig(
                databases=_list(b.get("databases", "astreo_monitor")),
                sql_dir=b.get("sql_dir", "/srv/sqlbackup"),
                local_dir=b.get("local_dir", "/home/<utente>/backups/sql"),
                local_keep=b.getint("local_keep", 7),
                github_repo=b.get("github_repo", "").strip(),
                github_keep=b.getint("github_keep", 30),
                zstd_level=b.getint("zstd_level", 19),
                timeout=b.getint("timeout", 900),
                notify=b.getboolean("notify", True),
                reminder_hours=b.getfloat("reminder_hours", 24),
            )
        terminal = None
        if cp.has_section("terminal"):
            t = cp["terminal"]
            terminal = TerminalConfig(
                enabled=t.getboolean("enabled", False),
                password_hash=t.get("password_hash", "").strip(),
                session_minutes=max(1, min(t.getint("session_minutes", 15), 240)),
                allowed_networks=_list(t.get("allowed_networks", "<IP-LAN>/24")),
            )

        netpulse = None
        if cp.has_section("netpulse"):
            token = cp["netpulse"].get("token", "").strip()
            token_file = cp["netpulse"].get("token_file", "").strip()
            if not token and token_file and os.path.isfile(token_file):
                with open(token_file, encoding="utf-8") as f:
                    token = f.read().strip()
            if token:
                netpulse = NetpulseConfig(token=token)
    except (ValueError, KeyError) as exc:
        raise ConfigError(f"Valore non valido in {path}: {exc}") from exc

    if email.security not in ("ssl", "starttls", "none"):
        raise ConfigError("[email] security deve essere ssl, starttls oppure none")

    return Config(path, database, email, web, metrics, speedtest, publicip, retention, backup, netpulse, terminal)
