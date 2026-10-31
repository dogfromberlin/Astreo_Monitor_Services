"""Controlli sui file di installazione: ogni regola nasce da un problema già incontrato.

Se un test fallisce, il pacchetto NON va installato.
"""
import glob
import os
import re

import pytest

from astreo_monitor import schema
from astreo_monitor.collectors import units

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read(rel):
    return open(os.path.join(ROOT, rel), encoding="utf-8").read()


def files(pattern):
    return sorted(glob.glob(os.path.join(ROOT, pattern)))


# ----------------------------------------------------------------------- nginx
@pytest.mark.parametrize("path", files("deploy/nginx/*.conf"))
def test_nginx_compatibile_con_1_24(path):
    """2.2/2.3: 'http2 on;' non esiste in nginx 1.24 (Ubuntu 24.04) e blocca il reload."""
    assert not re.search(r"^\s*http2\s+on\s*;", open(path).read(), re.M)


def test_nginx_passa_host_con_porta():
    """2.3: senza $http_host il controllo dell'origine (CSRF) e ttyd --check-origin falliscono."""
    conf = read("deploy/nginx/astreo-monitor.conf")
    assert "proxy_set_header Host              $http_host" in conf
    assert "X-Forwarded-Proto https" in conf


# ----------------------------------------------------------------------- systemd
SERVICES = files("deploy/systemd/*.service")


@pytest.mark.parametrize("path", files("deploy/systemd/*.timer"))
def test_ogni_timer_ha_il_suo_servizio(path):
    unit = re.search(r"^Unit=(\S+)", open(path).read(), re.M).group(1)
    assert os.path.exists(os.path.join(ROOT, "deploy", "systemd", unit))


@pytest.mark.parametrize("path", SERVICES)
def test_i_moduli_avviati_esistono(path):
    for mod in re.findall(r"-m (astreo_monitor[\w.]*)", open(path).read()):
        rel = mod.replace(".", "/")
        assert os.path.exists(os.path.join(ROOT, rel + ".py")) or os.path.exists(os.path.join(ROOT, rel, "__main__.py")), mod


@pytest.mark.parametrize("path", SERVICES)
def test_cartelle_scrivibili_create_da_systemd(path):
    """2.5: ReadWritePaths su una cartella inesistente fa fallire il servizio (226/NAMESPACE)."""
    text = open(path).read()
    for p in re.findall(r"^ReadWritePaths=(\S+)", text, re.M):
        assert not p.startswith("/var/lib/"), f"usa StateDirectory= invece di ReadWritePaths={p}"


def test_ping_con_capability():
    """2.5.1: con NoNewPrivileges ping non ottiene CAP_NET_RAW e la connessione risulta DOWN."""
    text = read("deploy/systemd/astreo-connectivity.service")
    if "NoNewPrivileges=true" in text:
        assert "AmbientCapabilities=CAP_NET_RAW" in text


def test_polkit_copre_le_unit_controllabili():
    rule = read("deploy/polkit/50-astreo-monitor.rules")
    for unit in units.CONTROLLABLE:
        assert f'"{unit}"' in rule, f"{unit} manca nella regola polkit"
        assert os.path.exists(os.path.join(ROOT, "deploy", "systemd", unit)), f"{unit} non esiste"


def test_script_smart_senza_tipo_fisso():
    """2.5: con '-d scsi' indicato da --scan, smartctl non legge gli attributi SATA."""
    assert '-d "$type"' not in read("deploy/bin/astreo-smart-collect")


# ----------------------------------------------------------------------- SQL
@pytest.mark.parametrize("path", files("sql/*.sql"))
def test_nessun_go_nei_commenti(path):
    """2.1: SSMS e sqlcmd spezzano lo script su GO anche dentro /* */."""
    for block in re.findall(r"/\*.*?\*/", open(path, encoding="utf-8").read(), re.S):
        assert not re.search(r"^\s*GO\s*$", block, re.M | re.I)


@pytest.mark.parametrize("table,info", list(schema.TABLES.items()))
def test_mappa_dello_schema(table, info):
    """Il controllo dello schema deve indicare lo script giusto."""
    script = read(f"sql/{info[1]}")
    created = re.search(rf"CREATE TABLE dbo\.{table}\b", script, re.I)
    renamed = table == "system_temperature" and "sp_rename" in script
    assert created or renamed, f"{table} non è creata da sql/{info[1]}"


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
