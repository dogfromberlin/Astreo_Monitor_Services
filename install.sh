#!/bin/bash
# Astreo Monitor - installazione guidata.
# Uso, dalla cartella del progetto scaricato (git clone o zip estratto):
#   sudo bash install.sh
# Prepara l'ambiente Python e poi fa le domande (database, HTTPS, terminale, moduli).
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")"
[ "$(id -u)" -eq 0 ] || exec sudo bash "$0" "$@"
OWNER=${SUDO_USER:-$(stat -c %U .)}

echo "== Astreo Monitor: controllo dei prerequisiti"
. /etc/os-release
case "${ID:-}${ID_LIKE:-}" in
  *ubuntu*|*debian*) ;;
  *) echo "Sistema non supportato: serve Ubuntu o Debian (trovato: ${PRETTY_NAME:-sconosciuto})"; exit 1 ;;
esac
command -v systemctl >/dev/null || { echo "Serve systemd"; exit 1; }
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' || { echo "Serve Python 3.10 o superiore"; exit 1; }

echo "== Pacchetti di sistema"
apt-get update -q
apt-get install -y -q python3-venv python3-pip zstd smartmontools iputils-ping openssl

echo "== Ambiente Python (.venv, utente $OWNER)"
if [ ! -x .venv/bin/python ]; then
  sudo -u "$OWNER" python3 -m venv .venv
fi
sudo -u "$OWNER" .venv/bin/python -m pip install -q --upgrade pip
sudo -u "$OWNER" .venv/bin/python -m pip install -q -r requirements.txt

echo "== Installazione"
exec env SUDO_USER="$OWNER" .venv/bin/python -m astreo_monitor.installer install "$@"
