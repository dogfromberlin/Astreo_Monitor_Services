"""Traduzioni dell'interfaccia (italiano e inglese).

La chiave è il testo italiano: se una traduzione manca compare l'italiano, mai un errore.
I cataloghi sono file JSON accanto a questo modulo (en.json); l'italiano non ha catalogo.
Segnaposto: {nome}, sostituiti con .format(**valori) dopo la traduzione.

Uso: t("Salva", "en") -> "Save";  t("Disco {d} pieno", "en", d="sda").
"""
from __future__ import annotations

import json
import os

LANGUAGES = {"it": "Italiano", "en": "English"}
DEFAULT = "it"
_HERE = os.path.dirname(os.path.abspath(__file__))
_catalogs: dict[str, dict[str, str]] = {}


def catalog(lang: str) -> dict[str, str]:
    if lang == DEFAULT or lang not in LANGUAGES:
        return {}
    if lang not in _catalogs:
        path = os.path.join(_HERE, f"{lang}.json")
        try:
            with open(path, encoding="utf-8") as f:
                _catalogs[lang] = json.load(f)
        except (OSError, ValueError):
            _catalogs[lang] = {}
    return _catalogs[lang]


def t(text: str, lang: str = DEFAULT, **values) -> str:
    out = catalog(lang).get(text) or text
    return out.format(**values) if values else out


def normalize(lang: str | None) -> str:
    lang = (lang or "").lower()[:2]
    return lang if lang in LANGUAGES else DEFAULT
