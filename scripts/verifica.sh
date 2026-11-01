#!/bin/bash
# Astreo Monitor - verifiche del pacchetto PRIMA di installarlo o riavviare i servizi.
# Uso (finestra SSH su astreo, dalla cartella del progetto):
#   bash scripts/verifica.sh
# Esito 0 = si può procedere; diverso da 0 = NON installare e segnalare l'errore.
set -u
cd "$(dirname "$0")/.."
. scripts/lingua.sh
PY=${PY:-.venv/bin/python}
fail=0

m "== 1. Strumenti di verifica" "== 1. Check tools"
if ! $PY -c "import pytest, pyflakes" 2>/dev/null; then
    m "   installo pytest e pyflakes nel venv (solo la prima volta)" "   installing pytest and pyflakes in the venv (first time only)"
    $PY -m pip install -q -r requirements-dev.txt || { m "   installazione non riuscita" "   installation failed"; exit 2; }
fi

m "== 2. Codice Python (pyflakes)" "== 2. Python code (pyflakes)"
$PY -m pyflakes astreo_monitor tests && echo "   ok" || fail=1

m "== 3. Sintassi JavaScript" "== 3. JavaScript syntax"
if command -v node >/dev/null; then
    for f in astreo_monitor/web/static/js/*.js; do node --check "$f" || fail=1; done
    m "   controllata" "   checked"
else
    m "   node non installato: controllo saltato (lo esegue GitHub ad ogni push)" "   node not installed: check skipped (GitHub runs it on every push)"
fi

m "== 4. Script della raccolta SMART" "== 4. SMART collection script"
bash -n deploy/bin/astreo-smart-collect && echo "   ok" || fail=1

m "== 5. Test automatici" "== 5. Automated tests"
$PY -m pytest -q tests || fail=1

if command -v nginx >/dev/null && [ "$(id -u)" = "0" ]; then
    m "== 6. Configurazione nginx attualmente installata" "== 6. Currently installed nginx configuration"
    nginx -t 2>&1 | tail -2 || fail=1
fi

echo
if [ $fail -eq 0 ]; then m "VERIFICHE SUPERATE: si può procedere con l'installazione." "CHECKS PASSED: you can proceed with the installation."
else m "VERIFICHE FALLITE: NON installare, segnala l'errore." "CHECKS FAILED: do NOT install, report the error."; fi
exit $fail
