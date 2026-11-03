# Sviluppo

<a id="architettura"></a>
## Architettura

| Componente | Cosa fa |
|---|---|
| Dashboard (`astreo_monitor.web`) | Flask servito da waitress su `127.0.0.1`, dietro nginx per HTTPS; pagina unica con viste, API REST `/api/v1/…` |
| Job (`astreo_monitor.jobs.*`) | processi brevi lanciati dai timer systemd; un job lento non blocca la dashboard |
| Bot Telegram | servizio permanente che legge i comandi |
| Agenti (`astreo_monitor/agent`, `agent/windows`) | Linux in Python, Windows in PowerShell; inviano a `/api/v1/agents/ingest` |
| Strato dati (`db.py`, `models.py`) | SQLAlchemy Core, stesse query su SQL Server, PostgreSQL e SQLite; schema con migrazioni Alembic |
| Raccolta (`collectors/`) | sistema, sensori, servizi, unit, journal |
| Moduli (`integrations/`) | Docker e Pi-hole, rilevati automaticamente |
| Installatore (`installer.py`) | domande, file di sistema da `deploy/templates/`, database, HTTPS, diagnosi |

<a id="ambiente"></a>
## Ambiente di sviluppo e test

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
bash scripts/verifica.sh          # pyflakes, sintassi JavaScript, test
```
I test su PostgreSQL e SQL Server si attivano con `ASTREO_TEST_PG` / `ASTREO_TEST_MSSQL` (formato in
`tests/test_database.py`). Su GitHub, a ogni push, girano su tutti e tre i database, insieme a `pip-audit`.

<a id="regole"></a>
## Regole del progetto

| Regola | Perché |
|---|---|
| Ogni modifica allo schema ha una migrazione; `models.py` e migrazioni coincidono | aggiornamenti automatici e sicuri (c'è un test) |
| Query con SQLAlchemy Core; confronti booleani con `== true()` | `IS 1` non funziona su SQL Server (c'è un test) |
| File di sistema solo nei modelli, senza utenti, percorsi o indirizzi di un'installazione | installazione generica (c'è un test) |
| Nessun dato personale o segreto in codice, documentazione, esempi e test | repository pubblico (c'è un test) |
| Testi per l'utente sempre traducibili, con la traduzione inglese | interfaccia in due lingue (c'è un test) |
| **Documentazione in `docs/it` e `docs/en` aggiornata nello stesso commit della funzione** | la guida è anche l'aiuto in linea (c'è un test) |

<a id="traduzioni"></a>
## Traduzioni

La chiave di ogni traduzione è il **testo italiano**; il catalogo inglese è `astreo_monitor/i18n/en.json`.
Pagine: `{{ _("testo") }}`; script: `t("testo")` o `t("Disco {p0}", { p0: nome })`; Python: `_()` o
`i18n.t()`. I testi salvati dai job in italiano si traducono in lettura (`i18n.STORED_TEMPLATES`).
Comandi a terminale: lingua da `ASTREO_LANG`, `install.ini` o `LANG`.

<a id="documentazione"></a>
## Documentazione

Le pagine hanno lo stesso nome in `docs/it/` e `docs/en/`. I capitoli che la dashboard apre dall'aiuto hanno
un'ancora fissa, uguale nelle due lingue (`<a id="…"></a>` prima del titolo). Il test della documentazione
controlla che ogni pagina esista in entrambe le lingue con gli stessi capitoli, le stesse ancore e lo stesso
numero di tabelle e blocchi di codice, e che i collegamenti interni portino a pagine e ancore esistenti.
Anche ogni icona **?** della dashboard (`data-help="pagina#ancora"`) deve portare a una pagina e a un'ancora
esistenti in entrambe le lingue.

Per aggiungere una funzione: codice, test, traduzioni, pagine `docs/it` e `docs/en`, voce in `CHANGELOG.md`.
