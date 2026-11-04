"""Aiuto in linea: le pagine della guida (docs/<lingua>/*.md) trasformate in HTML per la dashboard.

La guida è la stessa che si legge su GitHub: una sola fonte, sempre della versione installata.
I collegamenti tra pagine (`backup.md#rclone`) diventano navigazione interna al pannello d'aiuto.
"""
from __future__ import annotations

import functools
import os
import re

import markdown

from . import i18n

DOCS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs")
PAGE_RE = re.compile(r"^[a-z0-9-]+$")


class HelpError(Exception):
    pass


def pages(lang: str) -> list[str]:
    folder = os.path.join(DOCS, i18n.normalize(lang))
    try:
        return sorted(f[:-3] for f in os.listdir(folder) if f.endswith(".md"))
    except OSError:
        return []


@functools.lru_cache(maxsize=64)
def _render(path: str, mtime: float) -> tuple[str, str]:
    text = open(path, encoding="utf-8").read()
    title = next((line[2:].strip() for line in text.splitlines() if line.startswith("# ")), "")
    html = markdown.markdown(text, extensions=["tables", "fenced_code", "sane_lists"], output_format="html")
    # collegamenti tra pagine della guida -> navigazione interna (data-help)
    html = re.sub(r'<a href="([a-z0-9-]+)\.md(?:#([a-z0-9-]+))?">',
                  lambda m: f'<a href="#" data-help="{m.group(1)}{"#" + m.group(2) if m.group(2) else ""}">', html)
    html = re.sub(r'<a href="(https?://[^"]+)">', r'<a href="\1" target="_blank" rel="noopener">', html)
    return title, html


def page(lang: str, name: str) -> dict:
    lang = i18n.normalize(lang)
    if not PAGE_RE.match(name or ""):
        raise HelpError("pagina non valida")
    path = os.path.join(DOCS, lang, f"{name}.md")
    if not os.path.isfile(path):
        raise HelpError("pagina non trovata")
    title, html = _render(path, os.path.getmtime(path))
    return {"page": name, "lang": lang, "title": title, "html": html}


@functools.lru_cache(maxsize=8)
def _index(lang: str, stamp: float) -> list[dict]:
    out = []
    for name in pages(lang):
        text = open(os.path.join(DOCS, lang, f"{name}.md"), encoding="utf-8").read()
        title = next((line[2:].strip() for line in text.splitlines() if line.startswith("# ")), name)
        out.append({"ref": name, "page": title, "title": title})
        # capitoli con ancora: <a id="x"></a> seguito dal titolo "## ..."
        for anchor, heading in re.findall(r'<a id="([a-z0-9-]+)"></a>\s*\n#{2,3} ([^\n]+)', text):
            out.append({"ref": f"{name}#{anchor}", "page": title, "title": heading.strip()})
    return out


def index(lang: str) -> list[dict]:
    """4.1: pagine e capitoli della guida, per la ricerca Ctrl K della dashboard."""
    lang = i18n.normalize(lang)
    folder = os.path.join(DOCS, lang)
    try:
        stamp = max(os.path.getmtime(os.path.join(folder, f)) for f in os.listdir(folder))
    except (OSError, ValueError):
        return []
    return _index(lang, stamp)
