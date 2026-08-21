#!/usr/bin/env bash
# leak_monitor.sh — sample the backend's Redis connection state every INTERVAL seconds.
#
# Usage:  ./leak_monitor.sh [INTERVAL=30] > leak_<tag>.csv
#
# Columns (CSV on stdout):
#   ts            UTC timestamp
#   est           backend sockets to rabbitmqredis:6379 in ESTABLISHED
#   close_wait    ... in CLOSE_WAIT   (the leak: peer closed, we never did)
#   time_wait     ... in TIME_WAIT
#   other         ... any other state
#   all_tcp       every TCP socket in the backend container (ports exhaust ~28k)
#   redis_clients connected_clients as seen by rabbitmqredis itself
#   load1         host 1-minute load average
#   backend_rss   backend container memory (docker stats)
#   nginx_5xx     5xx responses logged by nginx in the last INTERVAL seconds
#   errno99       "Errno 99" lines in the backend log in the last INTERVAL seconds
#   concurrent    "ConcurrentObjectUseError" lines in the backend log, same window
#
# Pass criterion after the fix: close_wait < 100 and flat; est returns to its idle
# baseline within ~60 s of load stopping; errno99 == 0; concurrent == 0.
INT=${1:-30}
B=local_nextbackenddocker_1; R=local_rabbitmqredis_1; N=reverse_proxy
echo "ts,est,close_wait,time_wait,other,all_tcp,redis_clients,load1,backend_rss,nginx_5xx,errno99,concurrent"
while :; do
  ts=$(date -u +%FT%TZ)
  # /proc/net/tcp: col3 = remote addr:port (hex), col4 = state. 18EB = 6379.
  read est cw tw oth all < <(docker exec $B awk '
    NR>1 { n++; split($3,a,":");
           if (a[2]=="18EB") { if ($4=="01") e++; else if ($4=="08") c++; else if ($4=="06") t++; else o++ } }
    END { print e+0, c+0, t+0, o+0, n+0 }' /proc/net/tcp 2>/dev/null || echo "0 0 0 0 0")
  rc=$(docker exec $R redis-cli info clients 2>/dev/null | awk -F: '/^connected_clients/{gsub("\r","",$2); print $2}')
  load=$(cut -d' ' -f1 /proc/loadavg)
  rss=$(docker stats --no-stream --format '{{.MemUsage}}' $B 2>/dev/null | cut -d/ -f1 | tr -d ' ')
  n5=$(docker logs --since ${INT}s $N 2>&1 | grep -cE '" 5[0-9]{2} ')
  e99=$(docker logs --since ${INT}s $B 2>&1 | grep -c 'Errno 99')
  cu=$(docker logs --since ${INT}s $B 2>&1 | grep -c 'ConcurrentObjectUseError')
  echo "$ts,$est,$cw,$tw,$oth,$all,${rc:-?},$load,${rss:-?},$n5,$e99,$cu"
  sleep "$INT"
done
