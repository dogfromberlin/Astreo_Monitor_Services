#!/bin/bash
# Astreo Monitor - aggiornamento in un comando / one-command update.
#   sudo bash update.sh                    # da git / from git
#   sudo bash update.sh /tmp/pacchetto.zip # da uno zip / from a zip
#   sudo bash update.sh --enable-https     # aggiunge nginx, certificato e terminale / adds nginx, certificate, terminal
# Passi / steps: codice -> librerie -> verifiche -> file di sistema -> schema -> riavvio -> diagnosi.
set -euo pipefail
PROJECT=${ASTREO_PROJECT:-$(dirname "$(readlink -f "$0")")}
[ "$(id -u)" -eq 0 ] || exec sudo bash "$0" "$@"
# Lo zip sovrascrive anche questo script: per sicurezza si prosegue da una copia temporanea
if [ -z "${ASTREO_UPDATE_COPY:-}" ]; then
  COPY=$(mktemp /tmp/astreo-update.XXXXXX.sh)
  cp "$0" "$COPY"
  exec env ASTREO_UPDATE_COPY="$COPY" ASTREO_PROJECT="$PROJECT" bash "$COPY" "$@"
fi
trap 'rm -f "$ASTREO_UPDATE_COPY"' EXIT
cd "$PROJECT"
. scripts/lingua.sh
OWNER=$(stat -c %U .)
CMD=update
ZIP=""
for a in "$@"; do
  case "$a" in
    --enable-https) CMD=enable-https ;;
    *.zip) ZIP="$a" ;;
    *) m "Argomento non riconosciuto: $a" "Unknown argument: $a"; exit 2 ;;
  esac
done

m "== 1. Codice" "== 1. Code"
if [ -n "$ZIP" ]; then
  sudo -u "$OWNER" python3 -m zipfile -e "$ZIP" .
elif [ "$CMD" = update ] && [ -d .git ]; then
  sudo -u "$OWNER" git pull --ff-only
else
  m "   nessun aggiornamento del codice richiesto" "   no code update requested"
fi
grep -h "__version__" astreo_monitor/__init__.py

m "== 2. Librerie" "== 2. Libraries"
sudo -u "$OWNER" .venv/bin/python -m pip install -q -r requirements.txt

m "== 3. Verifiche" "== 3. Checks"
sudo -u "$OWNER" ASTREO_LANG="$ASTREO_LANG" bash scripts/verifica.sh

m "== 4. Installazione" "== 4. Installation"
env ASTREO_LANG="$ASTREO_LANG" .venv/bin/python -m astreo_monitor.installer "$CMD"
