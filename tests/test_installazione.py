"""Controlli sui file di installazione: ogni regola nasce da un problema già incontrato.

Se un test fallisce, il pacchetto NON va installato.
"""
import glob
import os
import re

import pytest

from astreo_monitor.collectors import units

# Parole composte a pezzi: la riscrittura della storia del repository non deve modificarle
PERSONAL_USER = "mar" + "co"

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read(rel):
    return open(os.path.join(ROOT, rel), encoding="utf-8").read()


def files(pattern):
    return sorted(glob.glob(os.path.join(ROOT, pattern), recursive=True))


# ------------------------------------------- file generati dai modelli (installer)
from astreo_monitor import installer  # noqa: E402

FULL = installer.Answers(user="utente", group="utente", home="/home/utente", project_dir="/opt/astreo", https=True,
                         server_ips=["10.0.0.5"], server_names=["srv"], allowed_networks=["10.0.0.0/24", "172.16.5.0/24"],
                         terminal=True, speedtest=True, backup=True, netpulse=True)
RENDERED = installer.render(FULL)
UNITS = {os.path.basename(p): c for p, c in RENDERED.items() if p.startswith("/etc/systemd/system/")}
SERVICES = sorted(u for u in UNITS if u.endswith(".service"))
NGINX = {p: c for p, c in RENDERED.items() if "/nginx/" in p}


def test_tutti_i_modelli_sono_usati():
    used = {f"systemd/{u}.j2" for u in UNITS} | {"polkit/50-astreo-monitor.rules.j2", "nginx/astreo-monitor.conf.j2",
                                                  "nginx/netpulse.conf.j2"}
    present = {os.path.relpath(p, installer.TEMPLATES) for p in files("deploy/templates/*/*.j2")}
    assert present == used


def test_nessun_valore_personale_nei_modelli():
    """Fase 2: i modelli non devono contenere utente, percorsi o indirizzi di un'installazione specifica."""
    for p in files("deploy/templates/*/*.j2"):
        text = open(p, encoding="utf-8").read()
        for bad in (PERSONAL_USER, "/home/", "192.168.", "10." + "8.0.", "astreo.local"):
            assert bad not in text, f"{os.path.relpath(p, ROOT)} contiene {bad}"


def test_valori_compilati():
    web = UNITS["astreo-monitor-web.service"]
    assert "User=utente" in web and "WorkingDirectory=/opt/astreo" in web
    for c in RENDERED.values():
        assert "{{" not in c and "{%" not in c


def test_http_senza_nginx_ne_terminale():
    ans = installer.Answers(user="u", group="u", home="/home/u", https=False, terminal=True, backup=False, speedtest=False)
    r = installer.render(ans)
    assert not any("/nginx/" in p for p in r)
    assert "/etc/systemd/system/astreo-terminal.service" not in r            # terminale solo con HTTPS
    assert "/etc/systemd/system/astreo-backup.timer" not in r and "/etc/systemd/system/astreo-speedtest.timer" not in r


@pytest.mark.parametrize("path", sorted(NGINX))
def test_nginx_compatibile_con_1_24(path):
    """2.2/2.3: 'http2 on;' non esiste in nginx 1.24 (Ubuntu 24.04) e blocca il reload."""
    assert not re.search(r"^\s*http2\s+on\s*;", NGINX[path], re.M)


def test_nginx_passa_host_con_porta():
    """2.3: senza $http_host il controllo dell'origine (CSRF) e ttyd --check-origin falliscono."""
    conf = NGINX["/etc/nginx/sites-available/astreo-monitor"]
    assert "proxy_set_header Host              $http_host" in conf
    assert "X-Forwarded-Proto https" in conf
    assert "allow 10.0.0.0/24;" in conf and "allow 172.16.5.0/24;" in conf and "deny  all;" in conf


@pytest.mark.parametrize("unit", sorted(u for u in UNITS if u.endswith(".timer")))
def test_ogni_timer_ha_il_suo_servizio(unit):
    target = re.search(r"^Unit=(\S+)", UNITS[unit], re.M).group(1)
    assert target in UNITS


@pytest.mark.parametrize("unit", SERVICES)
def test_i_moduli_avviati_esistono(unit):
    for mod in re.findall(r"-m (astreo_monitor[\w.]*)", UNITS[unit]):
        rel = mod.replace(".", "/")
        assert os.path.exists(os.path.join(ROOT, rel + ".py")) or os.path.exists(os.path.join(ROOT, rel, "__main__.py")), mod


@pytest.mark.parametrize("unit", SERVICES)
def test_cartelle_scrivibili_create_da_systemd(unit):
    """2.5: ReadWritePaths su una cartella inesistente fa fallire il servizio (226/NAMESPACE)."""
    for p in re.findall(r"^ReadWritePaths=(\S+)", UNITS[unit], re.M):
        assert not p.startswith("/var/lib/"), f"usa StateDirectory= invece di ReadWritePaths={p}"


def test_ping_con_capability():
    """2.5.1: con NoNewPrivileges ping non ottiene CAP_NET_RAW e la connessione risulta DOWN."""
    text = UNITS["astreo-connectivity.service"]
    if "NoNewPrivileges=true" in text:
        assert "AmbientCapabilities=CAP_NET_RAW" in text


def test_polkit_copre_le_unit_controllabili():
    rule = RENDERED["/etc/polkit-1/rules.d/50-astreo-monitor.rules"]
    assert 'subject.user !== "utente"' in rule
    for unit in units.CONTROLLABLE:
        assert f'"{unit}"' in rule, f"{unit} manca nella regola polkit"
        assert unit in UNITS, f"{unit} non esiste"


def test_script_smart_senza_tipo_fisso():
    """2.5: con '-d scsi' indicato da --scan, smartctl non legge gli attributi SATA."""
    assert '-d "$type"' not in read("deploy/bin/astreo-smart-collect")


# ----------------------------------------------------------------------- SQL
@pytest.mark.parametrize("path", files("sql/*.sql"))
def test_nessun_go_nei_commenti(path):
    """2.1: SSMS e sqlcmd spezzano lo script su GO anche dentro /* */."""
    for block in re.findall(r"/\*.*?\*/", open(path, encoding="utf-8").read(), re.S):
        assert not re.search(r"^\s*GO\s*$", block, re.M | re.I)


def test_modelli_e_migrazioni_coincidono(tmp_path):
    """models.py e le migrazioni devono descrivere lo stesso schema: altrimenti manca una migrazione."""
    from alembic.autogenerate import compare_metadata
    from alembic.runtime.migration import MigrationContext
    from sqlalchemy import create_engine
    from astreo_monitor import migrate, models
    from astreo_monitor.config import DatabaseConfig
    dbc = DatabaseConfig(host="", port=0, database="", user="", password="", engine="sqlite", path=str(tmp_path / "m.db"))
    cfg = type("C", (), {"database": dbc})()
    migrate.run(cfg, None, None, out=lambda *_: None)
    with create_engine(f"sqlite:///{dbc.path}").connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), models.metadata)
    assert diff == [], f"models.py diverso dalle migrazioni: {diff}"


# ----------------------------------------------------------------------- documentazione
@pytest.mark.parametrize("path", files("docs/*.md"))
def test_sed_su_etc_con_sudo(path):
    """2.3: 'sed -i' su /etc/astreo-monitor fallisce senza sudo (cartella di root) e non modifica nulla."""
    for line in open(path, encoding="utf-8"):
        if re.search(r"\bsed -i\b.*\s/etc/", line):
            assert re.search(r"sudo\s+sed -i", line), f"{os.path.basename(path)}: {line.strip()}"


# ----------------------------------------------------------------------- pagina
def test_data_view_solo_sulle_viste():
    """2.3.1: un data-view fuori dalle viste nascondeva l'intera pagina (schermata nera)."""
    html = "".join(read(f) for f in ("astreo_monitor/web/templates/index.html",
                                       "astreo_monitor/web/templates/_connessione.html",
                                       "astreo_monitor/web/templates/_impostazioni.html",
                                       "astreo_monitor/web/templates/_terminale.html"))
    for tag in re.findall(r"<[^>]*\sdata-view=\"[^\"]*\"[^>]*>", html):
        assert 'class="view"' in tag, tag
    js = "".join(read(f) for f in files("astreo_monitor/web/static/js/*.js"))
    assert "dataset.view =" not in js


# ----------------------------------------------------------------------- installatore
def test_installazione_completa_in_cartella_di_prova(tmp_path):
    """install senza domande, in una cartella di prova: file, config, risposte e schema SQLite."""
    import subprocess
    import sys
    db_path = tmp_path / "data" / "astreo.db"
    ans = tmp_path / "answers.ini"
    ans.write_text(f"""[answers]
user = utente
group = utente
home = /home/utente
db_engine = sqlite
db_path = {db_path}
https = false
speedtest = true
backup = false
services = ssh, docker
web_password = Password123
""", encoding="utf-8")
    root = tmp_path / "root"
    env = {**os.environ, "ASTREO_LANG": "it"}
    res = subprocess.run([sys.executable, "-m", "astreo_monitor.installer", "install", "--root", str(root), "--no-system",
                          "--answers", str(ans)], capture_output=True, text=True, cwd=ROOT, env=env)
    assert res.returncode == 0, res.stderr + res.stdout
    assert "NON cifrata" in res.stdout                                   # avviso HTTP
    cfg_text = (root / "etc/astreo-monitor/config.ini").read_text(encoding="utf-8")
    assert "engine = sqlite" in cfg_text and "host = 0.0.0.0" in cfg_text and "[terminal]" not in cfg_text
    assert "ssh = ssh | SSH" in cfg_text
    assert (root / "etc/astreo-monitor/install.ini").exists() and db_path.exists()
    assert not (root / "etc/nginx").exists()
    res = subprocess.run([sys.executable, "-m", "astreo_monitor.installer", "diff", "--root", str(root), "--no-system"],
                         capture_output=True, text=True, cwd=ROOT)
    assert res.returncode == 0 and "diverso" not in res.stdout and "nuovo" not in res.stdout


@pytest.mark.parametrize("env,expected", [({}, "it"), ({"LANG": "en_US.UTF-8"}, "en"), ({"ASTREO_LANG": "en", "LANG": "it_IT"}, "en")])
def test_lingua_degli_script(env, expected):
    """3.0.0b5: gli script usano set -u; senza LANG la lettura della lingua non deve fallire."""
    import subprocess
    res = subprocess.run(["bash", "-c", "set -euo pipefail; . scripts/lingua.sh; echo $_L"], cwd=ROOT,
                         capture_output=True, text=True, env={"PATH": "/usr/bin:/bin", **env})
    assert res.returncode == 0, res.stderr
    assert res.stdout.strip() == expected


def test_nessun_riferimento_personale_nel_repository():
    """Fase 4: il repository pubblico non contiene dati di un'installazione specifica.
    Il nome utente GitHub è ammesso solo dove indica il repository o il titolare della licenza."""
    allowed_owner = {"README.md", "README.it.md", "LICENSE", "docs/en/installation.md", "docs/installazione-guidata.md",
                     "CONTRIBUTING.md", "SECURITY.md", "CHANGELOG.md", ".github/workflows/release.yml"}
    bad = re.compile("|".join([rf"\b{PERSONAL_USER}\b", "192\\.168\\.1\\.(2|25[0-9])\\b", "10\\." + "8\\.0\\.",
                               "Shobu" + "Base", "astreo-db-" + "backups", r"\bastreo\.local\b", "@" + "gmail\\.com"]), re.I)
    found = []
    for path in glob.glob(os.path.join(ROOT, "**", "*"), recursive=True):
        rel = os.path.relpath(path, ROOT)
        if os.path.isdir(path) or rel.startswith((".git" + os.sep, ".venv")) or "__pycache__" in rel or rel.endswith((".png", ".ico", ".zst")):
            continue
        if rel == os.path.join("tests", "test_installazione.py"):
            continue
        try:
            text = open(path, encoding="utf-8").read()
        except (UnicodeDecodeError, OSError):
            continue
        text = text.replace("Marco (dogfromberlin)", "")
        for m in bad.finditer(text):
            found.append(f"{rel}: {m.group(0)}")
        if "dogfromberlin" in text and rel not in allowed_owner:
            found.append(f"{rel}: dogfromberlin")
    assert not found, found[:15]


def test_confronti_booleani_portabili():
    """3.2: .is_(True) diventa 'IS 1', che SQL Server rifiuta. Usare == true() di SQLAlchemy."""
    for path in files("astreo_monitor/**/*.py"):
        text = open(path, encoding="utf-8").read()
        assert ".is_(True)" not in text and ".is_(False)" not in text and "is_(sa_true())" not in text, path
