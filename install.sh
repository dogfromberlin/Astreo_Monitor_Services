#!/bin/bash
# Astreo Monitor - installazione guidata / guided installation.
#   sudo bash install.sh
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")"
[ "$(id -u)" -eq 0 ] || exec sudo bash "$0" "$@"
. scripts/lingua.sh
OWNER=${SUDO_USER:-$(stat -c %U .)}

m "== Astreo Monitor: controllo dei prerequisiti" "== Astreo Monitor: checking prerequisites"
. /etc/os-release
case "${ID:-}${ID_LIKE:-}" in
  *ubuntu*|*debian*) ;;
  *) m "Sistema non supportato: serve Ubuntu o Debian (trovato: ${PRETTY_NAME:-?})" \
       "Unsupported system: Ubuntu or Debian required (found: ${PRETTY_NAME:-?})"; exit 1 ;;
esac
command -v systemctl >/dev/null || { m "Serve systemd" "systemd is required"; exit 1; }
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' \
  || { m "Serve Python 3.10 o superiore" "Python 3.10 or newer is required"; exit 1; }

m "== Pacchetti di sistema" "== System packages"
apt-get update -q
apt-get install -y -q python3-venv python3-pip zstd smartmontools iputils-ping openssl

m "== Ambiente Python (.venv, utente $OWNER)" "== Python environment (.venv, user $OWNER)"
if [ ! -x .venv/bin/python ]; then
  sudo -u "$OWNER" python3 -m venv .venv
fi
sudo -u "$OWNER" .venv/bin/python -m pip install -q --upgrade pip
sudo -u "$OWNER" .venv/bin/python -m pip install -q -r requirements.txt

m "== Installazione" "== Installation"
exec env SUDO_USER="$OWNER" ASTREO_LANG="$ASTREO_LANG" .venv/bin/python -m astreo_monitor.installer install "$@"
