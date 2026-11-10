#!/usr/bin/env bash
# check_https.sh — acceptance checks for HTTPS, the admin password, per-experiment
# protocol and short links, against the live domain (HTTPS_PLAN.md "Test plan").
#
#   ./check_https.sh <https-link-name> <http-link-name>
#
# Needs two experiments launched with `protocol: https` / `protocol: http` and those
# link_names, and HEALTH_AUTH (an admin login) in alert.local.conf. Read-only except
# for one short-link move that it moves back. Exit 0 = all PASS.
set -u
cd "$(dirname "$0")"
[ -f alert.local.conf ] && . ./alert.local.conf
[ -f site.local.conf ] && . ./site.local.conf
H=${NEXT_HTTPS_HOST:?NEXT_HTTPS_HOST not set (site.local.conf)}
IP=${IP:-52.2.236.217}
LS=${1:?usage: $0 <https-link-name> <http-link-name>}; LH=${2:?usage: $0 <https-link-name> <http-link-name>}
AUTH=${HEALTH_AUTH:?HEALTH_AUTH not set (alert.local.conf)}
Q=/query/query_page/query_page
fails=0
check(){ # name, expected, actual
  if [ "$2" = "$3" ]; then echo "PASS $1"; else echo "FAIL $1 (expected $2, got $3)"; fails=$((fails+1)); fi; }
code(){ curl -s -o /dev/null -w '%{http_code}' "$@"; }
loc(){ curl -s -o /dev/null -w '%{redirect_url}' "$@"; }
exp_of(){ loc "https://$H/s/$1" | sed -E 's#.*/query_page/query_page/([0-9a-f]+).*#\1#'; }
S=$(exp_of "$LS"); P=$(exp_of "$LH")
[ -n "$S" ] && [ -n "$P" ] || { echo "FAIL could not resolve /s/$LS or /s/$LH"; exit 1; }
echo "https experiment $S (/s/$LS), http experiment $P (/s/$LH)"

echo "--- certificate and transport"
check "certificate valid for $H"      0 "$(curl -s -o /dev/null -w '%{ssl_verify_result}' https://$H/favicon.ico)"
check "certificate valid for www.$H"  0 "$(curl -s -o /dev/null -w '%{ssl_verify_result}' https://www.$H/favicon.ico)"
check "HTTP/2 on 443"                 2 "$(curl -s -o /dev/null -w '%{http_version}' https://$H/favicon.ico)"
check "no HSTS header"                0 "$(curl -sI https://$H$Q/$S | grep -ci strict-transport)"

echo "--- participant paths: open, no password"
for u in "https://$H$Q/$S" "http://$H$Q/$P" "http://$IP$Q/$P" "https://$H$Q/$P" "https://$H/query/static/js/next_widget.js" "https://$H/media/cats/cat01.png"; do
  check "200 $u" 200 "$(code "$u")"; done
check "204 favicon" 204 "$(code https://$H/favicon.ico)"
check "POST getQuery over https" 200 "$(code -X POST -H 'Content-Type: application/json' -d "{\"exp_uid\":\"$S\",\"args\":{\"participant_uid\":\"checkhttps\",\"widget\":false}}" https://$H/api/experiment/getQuery)"
check "query page loads jQuery over https" 1 "$(curl -s https://$H$Q/$S | grep -c 'src="https://code.jquery.com')"

echo "--- admin paths: password on HTTPS, redirect on HTTP"
for u in /dashboard/experiment_list "/dashboard/experiment_dashboard/$S/ARankB" "/api/experiment/$S/participants?zip=1" "/api/experiment/$S/logs" "/api/experiment/$S" /assistant/init /home/ /cadvisor/; do
  check "401 without password $u" 401 "$(code "https://$H$u")"; done
check "401 POST /assistant/init/experiment" 401 "$(code -X POST -d x https://$H/assistant/init/experiment)"
check "401 wrong password" 401 "$(code -u "healthcheck:wrong" https://$H/dashboard/experiment_list)"
check "200 with password" 200 "$(code -u "$AUTH" https://$H/dashboard/experiment_list)"
check "dashboard shows participant + short link" 2 "$(curl -s -u "$AUTH" "https://$H/dashboard/experiment_dashboard/$S/ARankB" | grep -c -E 'Participant link|Short link')"
check "bare https://$H/ -> experiment list" "https://$H/dashboard/experiment_list" "$(loc https://$H/)"
check "admin over http (IP) -> https" "https://$H/dashboard/experiment_list" "$(loc http://$IP/dashboard/experiment_list)"
check "data download over http -> https" "https://$H/api/experiment/$S/participants?zip=1" "$(loc "http://$H/api/experiment/$S/participants?zip=1")"

echo "--- per-experiment protocol"
check "https exp over http (domain) -> https, ID kept" "https://$H$Q/$S?participant=PID1" "$(loc "http://$H$Q/$S?participant=PID1")"
check "https exp over http (IP) -> https, ID kept"     "https://$H$Q/$S?participant=PID1" "$(loc "http://$IP$Q/$S?participant=PID1")"
check "http exp over https: served, no downgrade" 200 "$(code "https://$H$Q/$P?participant=PID1")"

echo "--- short links"
check "/s/$LS over http -> https page, ID kept"  "https://$H$Q/$S?participant=PID1" "$(loc "http://$IP/s/$LS?participant=PID1")"
check "/s/$LH over http -> http page, ID kept"   "http://$H$Q/$P?participant=PID1"  "$(loc "http://$H/s/$LH?participant=PID1")"
check "/s/$LH over https stays on https"          "https://$H$Q/$P"                  "$(loc "https://$H/s/$LH")"
check "uppercase name works" "https://$H$Q/$S" "$(loc "https://$H/s/$(echo $LS | tr a-z A-Z)")"
check "unknown name -> 404 page" 404 "$(code https://$H/s/no-such-study-xyz)"
check "followed to the end, ID pre-filled" 1 "$(curl -s -L "http://$IP/s/$LS?participant=PIDEND" | grep -c PIDEND)"
check "relink.sh moves a name" "$LH: $P -> $S" "$(./relink.sh "$LH" "$S" 2>/dev/null | tail -1)"
./relink.sh "$LH" "$P" >/dev/null 2>&1
check "relink.sh moved it back" "$P" "$(exp_of "$LH")"
check "relink.sh refuses an unknown experiment" "error: no experiment nonexistent" "$(./relink.sh "$LH" nonexistent 2>/dev/null | tail -1)"

echo "--- ports from the public address (security group + host-only bindings)"
for p in 8000 8888 27017 28017 5672 15672 6379; do
  r=$(timeout 5 bash -c "exec 3<>/dev/tcp/$IP/$p" 2>/dev/null && echo open || echo closed)
  check "port $p closed from outside" closed "$r"; done

echo "--- health check"
check "healthcheck.sh OK" 0 "$(./healthcheck.sh >/dev/null; echo $?)"

echo; [ $fails -eq 0 ] && echo "RESULT: all passed" || echo "RESULT: $fails FAILED"
exit $((fails > 0))
