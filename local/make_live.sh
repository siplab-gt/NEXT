#!/usr/bin/env bash
# make_live.sh — build the gitignored *_live.yaml launch configs from the tracked
# templates + the real Prolific completion codes in prolific_codes.local.txt.
#
#   cd local && ./make_live.sh                      # rebuild the default set
#   ./make_live.sh ARankB-InfoTuple-cog_rank5.yaml  # any tracked template(s)
#
# Re-run after editing a template so the change propagates to the live config.
# The codes never enter git: templates carry cc=YOUR_SUCCESS_CODE /
# YOUR_FAILURE_CODE / YOUR_TECHNICAL_CODE placeholders, this script substitutes
# exactly those three, and *_live.yaml + prolific_codes.local.txt are gitignored.
set -euo pipefail
cd "$(dirname "$0")"
CODES=prolific_codes.local.txt
[ -f "$CODES" ] || { echo "missing $CODES (SUCCESS_CODE=, FAILURE_CODE=, TECHNICAL_CODE=)"; exit 1; }
get(){ grep -E "^$1=" "$CODES" | tail -1 | cut -d= -f2- | tr -d '[:space:]'; }
SUCCESS=$(get SUCCESS_CODE); FAILURE=$(get FAILURE_CODE); TECHNICAL=$(get TECHNICAL_CODE)
for v in SUCCESS FAILURE TECHNICAL; do
  val=${!v}
  [ -n "$val" ] || { echo "no ${v}_CODE in $CODES"; exit 1; }
  case "$val" in YOUR_*) echo "WARNING: ${v}_CODE is still the placeholder '$val'";; esac
done
mask(){ sed -E 's/(cc=)[A-Za-z0-9]{4}[A-Za-z0-9]*/\1****/g'; }
TEMPLATES=("$@")
[ ${#TEMPLATES[@]} -gt 0 ] || TEMPLATES=(ARankB-InfoTuple-cog_rank4_precompute.yaml)
for t in "${TEMPLATES[@]}"; do
  [ -f "$t" ] || { echo "no such template: $t"; exit 1; }
  out="${t%.yaml}_live.yaml"
  sed -e "s|cc=YOUR_SUCCESS_CODE|cc=$SUCCESS|" -e "s|cc=YOUR_FAILURE_CODE|cc=$FAILURE|" -e "s|cc=YOUR_TECHNICAL_CODE|cc=$TECHNICAL|" "$t" > "$out"
  git check-ignore -q "$out" || { echo "REFUSING: $out is not gitignored"; rm -f "$out"; exit 1; }
  echo "wrote $out"
  grep -E "^\s*debrief_link(_fail|_error)?:" "$out" | mask | sed 's/^/   /'
done
