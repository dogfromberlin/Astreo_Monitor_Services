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
# 4.2.1: durante l'aggiornamento i job non partono. Altrimenti girerebbero con il codice nuovo sullo schema
# del database vecchio (tra la copia del codice e la migrazione, che con SQL Server aspetta la password di sa).
# I timer vengono riattivati alla fine, anche se l'aggiornamento si interrompe; solo quelli ancora abilitati.
PAUSED=""
resume_timers() {
  local t
  for t in $PAUSED; do
    if systemctl is-enabled --quiet "$t" 2>/dev/null; then systemctl start "$t" || true; fi
  done
  if [ -n "$PAUSED" ] && type m >/dev/null 2>&1; then m "   job riattivati" "   jobs resumed"; fi
  PAUSED=""
}
cleanup() { resume_timers; rm -f "$ASTREO_UPDATE_COPY"; }
trap cleanup EXIT
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

if command -v systemctl >/dev/null 2>&1; then
  PAUSED=$(systemctl list-units --type=timer --state=active --no-legend --plain 'astreo-*' 2>/dev/null | awk '{print $1}' | tr '\n' ' ')
  if [ -n "${PAUSED// /}" ]; then
    systemctl stop $PAUSED || true
    m "== 0. Job sospesi durante l'aggiornamento: $PAUSED" "== 0. Jobs paused during the update: $PAUSED"
    # un job già partito finisce il suo giro (al massimo 2 minuti) prima di toccare codice e database
    for _i in $(seq 1 24); do
      running=$(systemctl list-units --type=service --state=activating,active --no-legend --plain 'astreo-*' 2>/dev/null \
                | awk '{print $1}' | grep -vE '^astreo-(monitor-web|telegram|terminal)\.service' || true)
      [ -z "$running" ] && break
      sleep 5
    done
  fi
fi

m "== 1. Codice" "== 1. Code"
if [ -n "$ZIP" ]; then
  sudo -u "$OWNER" python3 -m zipfile -e "$ZIP" .
  # File tolti dalla nuova versione: lo zip non li cancella, li rimuove questo passo
  # (solo file tracciati da git e solo con un pacchetto completo)
  if [ -d .git ]; then
    sudo -u "$OWNER" python3 - "$ZIP" <<'PY'
import os, subprocess, sys, zipfile
names = set(zipfile.ZipFile(sys.argv[1]).namelist())
if {"astreo_monitor/__init__.py", "update.sh", "requirements.txt"} <= names:
    tracked = subprocess.run(["git", "ls-files"], capture_output=True, text=True).stdout.split("\n")
    for f in tracked:
        if f and f not in names and os.path.isfile(f):
            os.remove(f)
            print("   -", f)
PY
  fi
elif [ "$CMD" = update ] && [ -d .git ]; then
  sudo -u "$OWNER" git pull --ff-only
else
  m "   nessun aggiornamento del codice richiesto" "   no code update requested"
fi
grep -h "__version__" astreo_monitor/__init__.py

if [ -f /etc/astreo-agent/agent.ini ] && [ ! -f /etc/astreo-monitor/config.ini ]; then
  m "== 2. Agente: librerie e unit" "== 2. Agent: libraries and units"
  sudo -u "$OWNER" .venv/bin/python -m pip install -q --upgrade pip
  sudo -u "$OWNER" .venv/bin/python -m pip install -q -r requirements-agent.txt
  .venv/bin/python -m astreo_monitor.agent.install --update
  exit $?
fi

m "== 2. Librerie" "== 2. Libraries"
sudo -u "$OWNER" .venv/bin/python -m pip install -q --upgrade pip
sudo -u "$OWNER" .venv/bin/python -m pip install -q -r requirements.txt

m "== 3. Verifiche" "== 3. Checks"
sudo -u "$OWNER" ASTREO_LANG="$ASTREO_LANG" bash scripts/verifica.sh

m "== 4. Installazione" "== 4. Installation"
env ASTREO_LANG="$ASTREO_LANG" .venv/bin/python -m astreo_monitor.installer "$CMD"
