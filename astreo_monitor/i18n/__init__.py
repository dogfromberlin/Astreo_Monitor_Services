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


def translator(lang: str | None):
    """Funzione di traduzione per una lingua: _ = translator("en"); _("Disco {d}", d="sda")."""
    lang = normalize(lang)
    return lambda text, **values: t(text, lang, **values)


def lang_of(values: dict) -> str:
    """Lingua scelta nelle impostazioni (dict caricato con settings.load)."""
    return normalize(values.get("ui.language"))


# Testi composti in italiano dai job e salvati (eventi, stato in monitor_state): si traducono quando
# si leggono, riconoscendo il modello da cui sono stati composti. Ogni modello è anche una chiave del catalogo.
STORED_TEMPLATES = [
    # eventi
    "Riavvio del server", "Servizio {p0} ripartito", "Servizio {p0} fermo", "Container {p0} riavviato",
    "Container {p0}: {p1}", "Pi-hole: {p0}", "riavvii totali: {p0}", "kernel {p0}",
    # Pi-hole
    "Blocco della pubblicità: {p0}", "Blocco attivo, {p0}% delle richieste bloccate", "Pi-hole non risponde: {p0}",
    # connessione
    "Né il router né Internet rispondono: problema di rete locale o del router.",
    "Il router risponde ma Internet no: interruzione della linea o del provider.",
    "Perdita di pacchetti fino al {p0}% (soglia {p1}%).", "Latenza media {p0} ms (soglia {p1} ms).",
    "Latenza media {p0} ms, nessuna perdita significativa.",
    # dischi e aggiornamenti
    "autodiagnosi SMART FALLITA: il disco prevede un guasto", "{p0} settori in attesa di riallocazione",
    "{p0} settori non correggibili", "{p0} errori del supporto (NVMe)", "{p0} settori riallocati", "usura SSD al {p0}%",
    "temperatura {p0} °C", "dati SMART fermi dal {p0}: astreo-smart-collect non gira", "file non leggibile: {p0}",
    "{p0} aggiornamenti di sicurezza da installare", "riavvio richiesto dal {p0}",
    # scadenze
    "Certificato HTTPS {p0}", "Token GitHub (gh)", "senza scadenza", "CLI gh non trovata",
    # errori di validazione delle impostazioni e delle richieste
    "{p0}: massimo {p1}", "{p0}: minimo {p1}", "{p0}: orario non valido, usa il formato HH:MM", "Destinatari non validi: {p0}",
    "Impostazione sconosciuta: {p0}", "{p0}: valore troppo lungo", "{p0}: valore non valido ({p1})", "{p0}: valori ammessi {p1}",
    "{p0}: la soglia di alert deve essere minore o uguale a quella di warning",
    # backup e ripristino
    "DBCC CHECKDB pulito", "pg_restore completato", "integrity_check ok", "hash diverso da SHA256SUMS: file danneggiato",
    "nessun backup in {p0}", "verifica parziale (solo lettura dell'archivio): concedi CREATEDB a {p0}",
]
_STORED_RX: list = []


def translate_stored(text: str, lang: str) -> str:
    if not text or normalize(lang) == DEFAULT:
        return text
    if not _STORED_RX:
        import re
        for tpl in STORED_TEMPLATES:
            rx = "^" + re.escape(tpl)
            for k in ("p0", "p1"):
                rx = rx.replace(re.escape("{" + k + "}"), f"(?P<{k}>.+?)")
            _STORED_RX.append((re.compile(rx + "$"), tpl))
    for rx, tpl in _STORED_RX:
        m = rx.match(text)
        if m:
            return t(tpl, lang, **m.groupdict())
    return t(text, lang)


def translate_fields(obj, lang: str, fields=("text", "name", "note", "error", "check", "reasons", "title", "detail")):
    """Traduce in profondità i campi testuali noti di uno stato salvato (dict/list annidati)."""
    if normalize(lang) == DEFAULT:
        return obj
    if isinstance(obj, list):
        return [translate_fields(x, lang, fields) for x in obj]
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if k in fields and isinstance(v, str):
                out[k] = translate_stored(v, lang)
            elif k in fields and isinstance(v, list) and all(isinstance(x, str) for x in v):
                out[k] = [translate_stored(x, lang) for x in v]
            else:
                out[k] = translate_fields(v, lang, fields)
        return out
    return obj
