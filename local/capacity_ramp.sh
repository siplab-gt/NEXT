#!/usr/bin/env bash
# capacity_ramp.sh — find how many simultaneous participants this machine handles.
#   tmux new-session -d -s ramp "./capacity_ramp.sh 25 40 60 100"
# Per level: fresh throwaway experiment (production rank-4 precompute config),
# N HTTP participants through nginx (think 8-15 s, 10% wrong traps, full study),
# CPU/queue/steal sampler, export check, one summary line in ramp.log.
# Stops early when a level has >10% technical exits.
set -u
cd /home/ubuntu/NEXT/local
PY=./local-venv/bin/python; LOG=ramp.log
say(){ echo "[$(date -u +%FT%TZ)] $*" | tee -a $LOG; }
sampler(){ # every 60 s: load, steal, worker/backend CPU, rabbit backlog
  while :; do
    st=$( { head -1 /proc/stat; sleep 1; head -1 /proc/stat; } | awk 'NR==1{s1=$9;t1=$2+$3+$4+$5+$6+$7+$8+$9} NR==2{s2=$9;t2=$2+$3+$4+$5+$6+$7+$8+$9; printf "%.0f",(t2>t1)?100*(s2-s1)/(t2-t1):0}')
    cpu=$(docker stats --no-stream --format '{{.Name}}={{.CPUPerc}}' local_minionworker_1 local_nextbackenddocker_1 | tr '\n' ' ')
    q=$(docker exec local_rabbitmq_1 rabbitmqctl list_queues name messages 2>/dev/null | awk '/^async@|^sync_queue/{s+=$2} END{print s+0}')
    echo "$(date -u +%FT%TZ) load=$(cut -d' ' -f1 /proc/loadavg) steal=${st}% $cpu queued=$q" >> "$1"; sleep 59
  done
}
say "=== CAPACITY RAMP on $(nproc) cores ($(curl -s -m 2 -X PUT http://169.254.169.254/latest/api/token -H 'X-aws-ec2-metadata-token-ttl-seconds: 30' | xargs -I{} curl -s -m 2 -H 'X-aws-ec2-metadata-token: {}' http://169.254.169.254/latest/meta-data/instance-type)), commit $(git -C .. rev-parse --short HEAD) ==="
./leak_monitor.sh 30 > leak_ramp.csv 2>/dev/null & MON=$!
for n in "$@"; do
  exp=$($PY launch.py ARankB-InfoTuple-cog_rank4_precompute.yaml 2>&1 | grep -oE "experiment_dashboard/[a-f0-9]+" | head -1 | cut -d/ -f2)
  say "LEVEL $n participants -> experiment $exp"
  sampler ramp_sys_$n.log & SMP=$!
  $PY load_sim.py --base http://127.0.0.1 --host-header 52.2.236.217 --exp $exp --participants $n --think 8,15 --wrong-trap-fraction 0.1 --stagger 1 --tag ramp$n --quiet > loadsim_ramp$n.log 2>&1
  kill $SMP 2>/dev/null
  grep -E "duration|getQuery |processAnswer |statuses|participants:|5xx total" loadsim_ramp$n.log >> $LOG
  $PY check_export.py $exp --prefix simramp$n > check_ramp$n.log 2>&1 && say "export check ($n): PASS" || say "export check ($n): FAIL (see check_ramp$n.log)"
  peak=$(awk '{for(i=1;i<=NF;i++) if($i ~ /^load=/){sub("load=","",$i); if($i+0>m) m=$i+0}} END{print m}' ramp_sys_$n.log)
  mxsteal=$(awk '{for(i=1;i<=NF;i++) if($i ~ /^steal=/){sub("steal=","",$i); sub("%","",$i); if($i+0>m) m=$i+0}} END{print m+0}' ramp_sys_$n.log)
  mxq=$(awk '{for(i=1;i<=NF;i++) if($i ~ /^queued=/){sub("queued=","",$i); if($i+0>m) m=$i+0}} END{print m+0}' ramp_sys_$n.log)
  tech=$(grep -oE "technical exits: [0-9]+" loadsim_ramp$n.log | grep -oE "[0-9]+$"); comp=$(grep -oE "completed: [0-9]+" loadsim_ramp$n.log | tail -1 | grep -oE "[0-9]+$")
  p50=$(grep -E "^getQuery " loadsim_ramp$n.log | grep -oE "p50= *[0-9]+ms" | tr -d ' '); p95=$(grep -E "^getQuery " loadsim_ramp$n.log | grep -oE "p95= *[0-9]+ms" | tr -d ' ')
  say "SUMMARY level=$n completed=$comp technical_exits=$tech getQuery_$p50 getQuery_$p95 peak_load=$peak max_steal=${mxsteal}% max_queued=$mxq"
  sleep 90
  if [ "${tech:-0}" -gt $((n/10)) ]; then say "STOP: level $n had >10% technical exits; higher levels would only confirm saturation"; break; fi
done
kill $MON 2>/dev/null
awk -F, 'NR>1{ if($3>mc) mc=$3; n5+=$10; e99+=$11 } END{ printf "  leak over the ramp: max_close_wait=%d nginx_5xx=%d errno99=%d\n", mc, n5, e99 }' leak_ramp.csv | tee -a $LOG
say "RAMP DONE"
