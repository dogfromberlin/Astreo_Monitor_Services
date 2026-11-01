# Astreo Monitor - lingua dei messaggi degli script (da includere con: . scripts/lingua.sh)
# Ordine: ASTREO_LANG, poi install.ini (language), poi la lingua del sistema (LANG). Predefinita: italiano.
_L=${ASTREO_LANG:-$( (grep -m1 '^language' /etc/astreo-monitor/install.ini 2>/dev/null || true) | cut -d= -f2 | tr -d ' ')}
_LS=${LANG:-}
_L=${_L:-${_LS:0:2}}
[ "$_L" = en ] || _L=it
export ASTREO_LANG=$_L
# m "testo italiano" "english text"
m() { if [ "$_L" = en ]; then echo "$2"; else echo "$1"; fi; }
