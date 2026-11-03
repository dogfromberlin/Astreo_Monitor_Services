"""La guida (docs/it e docs/en) è anche l'aiuto in linea: le due lingue devono restare allineate.

Per ogni pagina: esiste in entrambe le lingue, con le stesse ancore (nello stesso ordine), gli stessi
livelli di titolo, lo stesso numero di tabelle e di blocchi di codice; i collegamenti interni portano a
pagine e ancore esistenti.
"""
import glob
import os
import re

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS = os.path.join(ROOT, "docs")
LANGS = ("it", "en")


def pages(lang):
    return sorted(os.path.basename(p) for p in glob.glob(os.path.join(DOCS, lang, "*.md")))


def read(lang, page):
    return open(os.path.join(DOCS, lang, page), encoding="utf-8").read()


def structure(text):
    no_code = re.sub(r"```.*?```", "", text, flags=re.S)
    return {
        "anchors": re.findall(r'<a id="([a-z0-9-]+)"></a>', text),
        "headings": [len(m) for m in re.findall(r"^(#+) ", no_code, flags=re.M)],
        "tables": len(re.findall(r"^\|[-| ]+\|$", no_code, flags=re.M)),
        "code_blocks": text.count("```") // 2,
    }


def test_stesse_pagine_nelle_due_lingue():
    assert pages("it") == pages("en")
    assert "index.md" in pages("it")


@pytest.mark.parametrize("page", pages("it"))
def test_stessa_struttura(page):
    it, en = structure(read("it", page)), structure(read("en", page))
    for key in it:
        assert it[key] == en[key], f"{page}: {key} diversi tra italiano ed inglese: {it[key]} / {en[key]}"


@pytest.mark.parametrize("lang", LANGS)
def test_collegamenti_interni(lang):
    broken = []
    anchors = {p: set(structure(read(lang, p))["anchors"]) for p in pages(lang)}
    for p in pages(lang):
        for target in re.findall(r"\]\(([^)\s]+)\)", read(lang, p)):
            if target.startswith(("http://", "https://", "mailto:")):
                continue
            page, _, anchor = target.partition("#")
            page = page or p
            if page not in anchors:
                broken.append(f"{lang}/{p} → {target}")
            elif anchor and anchor not in anchors[page]:
                broken.append(f"{lang}/{p} → {target} (ancora mancante)")
    assert not broken, broken


def test_indice_completo():
    """Ogni pagina è raggiungibile dall'indice."""
    for lang in LANGS:
        linked = set(re.findall(r"\]\(([a-z0-9-]+\.md)", read(lang, "index.md")))
        assert set(pages(lang)) - {"index.md"} <= linked, lang


def test_riferimenti_alla_guida_nel_progetto():
    """Ogni docs/…/pagina.md citato da codice, modelli e README esiste."""
    missing = []
    for path in glob.glob(os.path.join(ROOT, "**", "*"), recursive=True):
        rel = os.path.relpath(path, ROOT)
        if os.path.isdir(path) or rel.startswith((".git", "docs" + os.sep)) or "__pycache__" in rel:
            continue
        if not rel.endswith((".py", ".j2", ".html", ".js", ".json", ".md", ".sh", ".ini", ".yml")):
            continue
        for ref in re.findall(r"docs/((?:it|en)/[a-z0-9-]+\.md)", open(path, encoding="utf-8", errors="ignore").read()):
            if not os.path.exists(os.path.join(DOCS, ref)):
                missing.append(f"{rel}: docs/{ref}")
    assert not missing, missing
