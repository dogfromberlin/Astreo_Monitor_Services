# Development

<a id="architettura"></a>
## Architecture

| Component | What it does |
|---|---|
| Dashboard (`astreo_monitor.web`) | Flask served by waitress on `127.0.0.1`, behind nginx for HTTPS; single page with views, REST API `/api/v1/…` |
| Jobs (`astreo_monitor.jobs.*`) | short processes started by systemd timers; a slow job does not block the dashboard |
| Telegram bot | permanent service reading the commands |
| Agents (`astreo_monitor/agent`, `agent/windows`) | Linux in Python, Windows in PowerShell; they send to `/api/v1/agents/ingest` |
| Data layer (`db.py`, `models.py`) | SQLAlchemy Core, same queries on SQL Server, PostgreSQL and SQLite; schema with Alembic migrations |
| Collection (`collectors/`) | system, sensors, services, units, journal |
| Modules (`integrations/`) | Docker and Pi-hole, detected automatically |
| Installer (`installer.py`) | questions, system files from `deploy/templates/`, database, HTTPS, health check |

<a id="ambiente"></a>
## Development environment and tests

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
bash scripts/verifica.sh          # pyflakes, JavaScript syntax, tests
```
Tests on PostgreSQL and SQL Server are enabled with `ASTREO_TEST_PG` / `ASTREO_TEST_MSSQL` (format in
`tests/test_database.py`). On GitHub, on every push, they run on all three databases, together with `pip-audit`.

<a id="regole"></a>
## Project rules

| Rule | Why |
|---|---|
| Every schema change has a migration; `models.py` and migrations match | automatic, safe updates (there is a test) |
| Queries with SQLAlchemy Core; boolean comparisons with `== true()` | `IS 1` does not work on SQL Server (there is a test) |
| System files only in templates, without users, paths or addresses of an installation | generic installation (there is a test) |
| No personal data or secrets in code, docs, examples and tests | public repository (there is a test) |
| User-facing texts always translatable, with the English translation | two-language interface (there is a test) |
| **Documentation in `docs/it` and `docs/en` updated in the same commit as the feature** | the guide is also the online help (there is a test) |

<a id="traduzioni"></a>
## Translations

The key of every translation is the **Italian text**; the English catalogue is `astreo_monitor/i18n/en.json`.
Pages: `{{ _("text") }}`; scripts: `t("text")` or `t("Disco {p0}", { p0: name })`; Python: `_()` or `i18n.t()`.
Texts stored in Italian by the jobs are translated when read (`i18n.STORED_TEMPLATES`).
Command-line tools: language from `ASTREO_LANG`, `install.ini` or `LANG`.

<a id="documentazione"></a>
## Documentation

Pages have the same name in `docs/it/` and `docs/en/`. Chapters opened by the dashboard help have a fixed anchor,
identical in both languages (`<a id="…"></a>` before the heading). The documentation test checks that every page
exists in both languages with the same chapters, anchors and number of tables and code blocks, and that internal
links lead to existing pages and anchors. Every **?** icon of the dashboard (`data-help="page#anchor"`) must also
lead to a page and an anchor existing in both languages.

To add a feature: code, tests, translations, `docs/it` and `docs/en` pages, entry in `CHANGELOG.md`.
