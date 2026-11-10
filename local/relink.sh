#!/usr/bin/env bash
# Move a short study link (/s/<name>) to another experiment, on purpose.
#   ./relink.sh <name> <EXP_UID>     e.g. after relaunching a study, before publishing it
#   ./relink.sh list                 all short links
# Launching an experiment never moves a name that is already taken (it fails
# instead), so this is the only way a live link changes. See next/short_links.py.
set -eu
if [ "${1:-}" = list ]; then
  exec docker exec local_nextbackenddocker_1 python -m next.short_links list
fi
[ $# -eq 2 ] || { echo "usage: $0 <name> <EXP_UID> | $0 list"; exit 2; }
exec docker exec local_nextbackenddocker_1 python -m next.short_links move "$1" "$2"
