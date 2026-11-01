# Contributing

Thanks for your interest in Astreo Monitor! Issues and pull requests are welcome, in English or Italian.

## Before you start

- For anything bigger than a small fix, open an issue first to discuss the idea.
- Security problems: **do not** open a public issue, see [SECURITY.md](SECURITY.md).

## Development setup

```bash
git clone https://github.com/dogfromberlin/Astreo_Monitor_Services.git
cd Astreo_Monitor_Services
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
bash scripts/verifica.sh          # pyflakes, JavaScript syntax, tests (SQLite)
```

Tests against PostgreSQL and SQL Server run in GitHub Actions; locally you can enable them with
`ASTREO_TEST_PG` / `ASTREO_TEST_MSSQL` (format in `tests/test_database.py`).

## Guidelines

- **Database**: every schema change needs an Alembic migration in `astreo_monitor/migrations/versions/`;
  `models.py` and the migrations must match (a test checks it). Queries use SQLAlchemy Core so they work on
  SQL Server, PostgreSQL and SQLite.
- **Translations**: user-facing texts use `{{ _("…") }}` in templates, `t("…")` in JavaScript and `_()` /
  `i18n.t()` in Python, with the Italian text as key; add the English text to `astreo_monitor/i18n/en.json`
  (a test reports missing ones).
- **System files** (systemd, nginx, polkit) are templates in `deploy/templates/`: no user names, paths or
  addresses of a specific installation (a test checks it).
- **No personal data or secrets** in code, docs, examples or tests.
- Keep `bash scripts/verifica.sh` green; new behaviour should come with a test.
