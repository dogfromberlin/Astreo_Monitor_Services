#!/bin/bash
# Astreo Monitor - aggiornamento in un comando.
# Uso, dalla cartella del progetto:
#   sudo bash update.sh                    # aggiorna da git (git pull)
#   sudo bash update.sh /tmp/pacchetto.zip # aggiorna da uno zip scaricato
#   sudo bash update.sh --enable-https     # aggiunge nginx, certificato e terminale a un'installazione HTTP
# Passi: codice -> verifiche -> librerie -> file di sistema -> schema del database -> riavvio -> diagnosi.
# Se le verifiche falliscono si ferma PRIMA di toccare servizi e database.
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")"
[ "$(id -u)" -eq 0 ] || exec sudo bash "$0" "$@"
OWNER=$(stat -c %U .)
CMD=update
ZIP=""
for a in "$@"; do
  case "$a" in
    --enable-https) CMD=enable-https ;;
    *.zip) ZIP="$a" ;;
    *) echo "Argomento non riconosciuto: $a"; exit 2 ;;
  esac
done

echo "== 1. Codice"
if [ -n "$ZIP" ]; then
  sudo -u "$OWNER" python3 -m zipfile -e "$ZIP" .
elif [ "$CMD" = update ] && [ -d .git ]; then
  sudo -u "$OWNER" git pull --ff-only
else
  echo "   nessun aggiornamento del codice richiesto"
fi
grep -h "__version__" astreo_monitor/__init__.py

echo "== 2. Librerie"
sudo -u "$OWNER" .venv/bin/python -m pip install -q -r requirements.txt

echo "== 3. Verifiche"
sudo -u "$OWNER" bash scripts/verifica.sh

echo "== 4. Installazione"
exec .venv/bin/python -m astreo_monitor.installer "$CMD"
