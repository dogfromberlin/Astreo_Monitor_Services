#!/bin/bash
# Astreo Monitor - verifiche del pacchetto PRIMA di installarlo o riavviare i servizi.
# Uso (finestra SSH su astreo, dalla cartella del progetto):
#   bash scripts/verifica.sh
# Esito 0 = si può procedere; diverso da 0 = NON installare e segnalare l'errore.
set -u
cd "$(dirname "$0")/.."
PY=${PY:-.venv/bin/python}
fail=0

echo "== 1. Strumenti di verifica"
if ! $PY -c "import pytest, pyflakes" 2>/dev/null; then
    echo "   installo pytest e pyflakes nel venv (solo la prima volta)"
    $PY -m pip install -q -r requirements-dev.txt || { echo "   installazione non riuscita"; exit 2; }
fi

echo "== 2. Codice Python (pyflakes)"
$PY -m pyflakes astreo_monitor tests && echo "   ok" || fail=1

echo "== 3. Sintassi JavaScript"
if command -v node >/dev/null; then
    for f in astreo_monitor/web/static/js/*.js; do node --check "$f" || fail=1; done
    echo "   controllata"
else
    echo "   node non installato: controllo saltato (lo esegue GitHub ad ogni push)"
fi

echo "== 4. Script della raccolta SMART"
bash -n deploy/bin/astreo-smart-collect && echo "   ok" || fail=1

echo "== 5. Test automatici"
$PY -m pytest -q tests || fail=1

if command -v nginx >/dev/null && [ "$(id -u)" = "0" ]; then
    echo "== 6. Configurazione nginx attualmente installata"
    nginx -t 2>&1 | tail -2 || fail=1
fi

echo
if [ $fail -eq 0 ]; then echo "VERIFICHE SUPERATE: si può procedere con l'installazione."; else echo "VERIFICHE FALLITE: NON installare, segnala l'errore."; fi
exit $fail
