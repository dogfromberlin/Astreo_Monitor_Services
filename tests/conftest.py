"""Configurazione comune ai test: config di prova generato dal config di esempio."""
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


@pytest.fixture()
def cfg(tmp_path):
    from werkzeug.security import generate_password_hash
    from astreo_monitor import config
    text = open(os.path.join(ROOT, "config.example.ini"), encoding="utf-8").read()
    text = text.replace("password_hash =\n", f"password_hash = {generate_password_hash('prova')}\n", 1)
    text = text.replace("host = <IP-LAN>", "host = 127.0.0.1").replace("login_timeout = 10", "login_timeout = 1")
    p = tmp_path / "config.ini"
    p.write_text(text, encoding="utf-8")
    return config.load(str(p))
