#!/usr/bin/env bash
# healthcheck.sh — five-minute health check for the NEXT stack (run from cron).
#
#   */5 * * * * /home/ubuntu/NEXT/local/healthcheck.sh >/dev/null 2>&1
#
# Checks, in order: all containers running; the backend's sockets to the Redis
# result store (dead CLOSE_WAIT sockets = the Aug 2026 leak signature); a real
# request through nginx -> backend -> celery -> Redis (the dashboard's cached
# embedding stat); nginx 5xx in the last 5 min; load average.
# Writes one line per run to health.log, posts to WEBHOOK_URL (Slack/Discord-style
# {"text": ...}) when the state changes or a CRIT persists, and - on the leak
# signature only - restarts the stateless backend container (AUTO_RESTART=1).
#
# Optional settings in alert.local.conf (gitignored), KEY=value:
#   WEBHOOK_URL=https://hooks.slack.com/...     PROBE_EXP_UID=<exp uid for the probe>
#   HOST_HEADER=52.2.236.217  AUTO_RESTART=1  CLOSE_WAIT_CRIT=5000  CLOSE_WAIT_WARN=1000  STEAL_WARN=20
# Exit status: 0 healthy, 1 warning, 2 critical.
set -u
cd "$(dirname "$0")"
[ -f alert.local.conf ] && . ./alert.local.conf
WEBHOOK_URL=${WEBHOOK_URL:-}; HOST_HEADER=${HOST_HEADER:-52.2.236.217}
AUTO_RESTART=${AUTO_RESTART:-1}; CLOSE_WAIT_CRIT=${CLOSE_WAIT_CRIT:-5000}; CLOSE_WAIT_WARN=${CLOSE_WAIT_WARN:-1000}
PROBE_TIMEOUT=${PROBE_TIMEOUT:-60}
LOG=health.log; STATE=health.state
B=local_nextbackenddocker_1
ts=$(date -u +%FT%TZ); level=0; msgs=(); actions=()
worst(){ [ "$1" -gt "$level" ] && level=$1; }

# 1. containers
missing=""
for c in local_mongodb_1 local_rabbitmq_1 local_rabbitmqredis_1 local_minionredis_1 local_minionworker_1 $B reverse_proxy; do
  [ "$(docker inspect -f '{{.State.Running}}' $c 2>/dev/null)" = "true" ] || missing="$missing $c"
done
[ -n "$missing" ] && { worst 2; msgs+=("containers down:$missing"); }

# 2. sockets to the Redis result store (18EB = 6379)
read est cw all < <(docker exec $B awk 'NR>1{n++; split($3,a,":"); if(a[2]=="18EB"){ if($4=="01")e++; else if($4=="08")c++ }} END{print e+0,c+0,n+0}' /proc/net/tcp 2>/dev/null || echo "0 0 0")
errno99=$(docker logs --since 5m $B 2>&1 | grep -c 'Errno 99')
[ -n "${HC_TEST_CLOSE_WAIT:-}" ] && cw=$HC_TEST_CLOSE_WAIT   # test hook: pretend the leak is back
leak=0
if [ "$cw" -ge "$CLOSE_WAIT_CRIT" ] || [ "$errno99" -gt 0 ] || [ "$all" -ge 20000 ]; then
  worst 2; leak=1; msgs+=("LEAK SIGNATURE: close_wait=$cw all_tcp=$all errno99(5m)=$errno99")
elif [ "$cw" -ge "$CLOSE_WAIT_WARN" ]; then
  worst 1; msgs+=("close_wait rising: $cw")
fi

# 3. full-path probe (nginx -> backend -> celery -> redis): cached dashboard stat
exp=${PROBE_EXP_UID:-$(docker exec local_mongodb_1 mongosh --quiet --host 127.0.0.1 --port 27017 app_data --eval 'var e=db.getCollection("ARankB:experiments").find({},{exp_uid:1}).sort({start_date:-1}).limit(1).toArray(); print(e.length?e[0].exp_uid:"")' 2>/dev/null | tail -1)}
probe="skipped"
if [ -n "$exp" ]; then
  code=$(curl -s -m "$PROBE_TIMEOUT" -o /dev/null -w '%{http_code}' -H "Host: $HOST_HEADER" -H 'Content-Type: application/json' \
    -d "{\"exp_uid\":\"$exp\",\"args\":{\"stat_id\":\"most_current_embedding\",\"params\":{\"alg_label\":\"InfoTuple\"},\"force_recompute\":0}}" \
    http://127.0.0.1/dashboard/get_stats)
  probe="HTTP $code"
  [ "$code" = "200" ] || { worst 2; msgs+=("probe failed ($probe, exp ${exp:0:8})"); }
fi

# 4. nginx 5xx last 5 min, 5. load
n5=$(docker logs --since 5m reverse_proxy 2>&1 | grep -cE '" 5[0-9]{2} ')
[ "$n5" -gt 5 ] && { worst 1; msgs+=("nginx 5xx in 5 min: $n5"); }
load=$(cut -d' ' -f1 /proc/loadavg); cores=$(nproc)
awk -v l="$load" -v c="$cores" 'BEGIN{exit !(l > 2*c)}' && { worst 1; msgs+=("load $load on $cores cores"); }
# 6. CPU steal (burstable instances: credits exhausted -> everything slows down)
steal=$( { head -1 /proc/stat; sleep 1; head -1 /proc/stat; } | awk 'NR==1{s1=$9; t1=$2+$3+$4+$5+$6+$7+$8+$9} NR==2{s2=$9; t2=$2+$3+$4+$5+$6+$7+$8+$9; if(t2>t1) printf "%.0f", 100*(s2-s1)/(t2-t1); else print 0}')
[ "${steal:-0}" -ge "${STEAL_WARN:-20}" ] && { worst 1; msgs+=("CPU throttled: steal ${steal}% (burstable credits exhausted?)"); }

# auto-remediation: the leak signature only (backend is stateless)
if [ "$leak" = 1 ] && [ "$AUTO_RESTART" = 1 ]; then
  docker restart $B >/dev/null 2>&1 && actions+=("restarted $B") || actions+=("restart of $B FAILED")
fi

case $level in 0) status=OK;; 1) status=WARN;; 2) status=CRIT;; esac
line="$ts $status est=$est close_wait=$cw all_tcp=$all errno99=$errno99 probe=$probe nginx5xx=$n5 load=$load steal=${steal:-0}%${msgs:+ | ${msgs[*]}}${actions:+ | ${actions[*]}}"
echo "$line" >> $LOG

# alert on state change, and every 6th consecutive non-OK run (~30 min)
prev=$(cut -d' ' -f1 $STATE 2>/dev/null || echo OK); cnt=$(cut -d' ' -f2 $STATE 2>/dev/null || echo 0)
[ "$status" = "$prev" ] && cnt=$((cnt+1)) || cnt=1
echo "$status $cnt" > $STATE
if { [ "$status" != "$prev" ] || { [ "$status" != OK ] && [ $((cnt % 6)) = 0 ]; }; } && [ "$status$prev" != "OKOK" ]; then
  text="NEXT health: $status ($(hostname)) - ${msgs[*]:-recovered}${actions:+ | ${actions[*]}}"
  if [ -n "$WEBHOOK_URL" ]; then
    curl -s -m 15 -X POST -H 'Content-Type: application/json' -d "{\"text\": \"$text\"}" "$WEBHOOK_URL" >/dev/null 2>&1 || echo "$ts webhook post failed" >> $LOG
  else
    echo "$ts ALERT (no WEBHOOK_URL configured): $text" >> $LOG
  fi
fi
echo "$line"
exit $level
