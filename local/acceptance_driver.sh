#!/usr/bin/env bash
# acceptance_driver.sh — runs the leak-fix acceptance sequence unattended (inside tmux).
#   1. 10 simulated participants, full production config, through nginx   (M1 load soak)
#   2. export integrity check
#   3. 2 h idle soak                                                        (M1 idle soak)
#   4. 25 simultaneous participants                                         (M4 on this box)
#   5. export integrity check + summary
# Everything is logged to acceptance.log; leak_accept.csv holds the 30 s samples.
#   tmux new-session -d -s acceptance "./acceptance_driver.sh EXP_UID"
set -u
cd /home/ubuntu/NEXT/local
EXP=$1
PY=./local-venv/bin/python
LOG=acceptance.log
say(){ echo "[$(date -u +%FT%TZ)] $*" | tee -a $LOG; }
socks(){ docker exec local_nextbackenddocker_1 awk 'NR>1{split($3,a,":"); if(a[2]=="18EB") s[$4]++} END{o=""; for(k in s) o=o" "k"="s[k]; print (o==""?"none":o)}' /proc/net/tcp; }

./leak_monitor.sh 30 > leak_accept.csv 2>/dev/null &
MON=$!
say "acceptance run on experiment $EXP (monitor pid $MON)"
say "sockets at start: $(socks)"

say "STEP 1: 10 participants, think 5-10 s, 10% wrong traps, via nginx"
$PY load_sim.py --base http://127.0.0.1 --host-header 52.2.236.217 --exp $EXP --participants 10 --think 5,10 --wrong-trap-fraction 0.1 --stagger 2 --tag soak10 --quiet >> $LOG 2>&1
say "sockets after step 1: $(socks)"; sleep 60; say "sockets 60 s later: $(socks)"

say "STEP 2: export check (soak10)"
$PY check_export.py $EXP --prefix simsoak10 >> $LOG 2>&1 && say "export check: PASS" || say "export check: FAIL"

say "STEP 3: idle soak 2 h (monitor keeps sampling)"
for i in 1 2 3 4; do sleep 1800; say "idle soak: $((i*30)) min, sockets: $(socks), last sample: $(tail -1 leak_accept.csv)"; done

say "STEP 4: 25 simultaneous participants, think 8-15 s, 10% wrong traps, via nginx"
$PY load_sim.py --base http://127.0.0.1 --host-header 52.2.236.217 --exp $EXP --participants 25 --think 8,15 --wrong-trap-fraction 0.1 --stagger 1 --tag c25 --quiet >> $LOG 2>&1
say "sockets after step 4: $(socks)"; sleep 60; say "sockets 60 s later: $(socks)"

say "STEP 5: export check (c25)"
$PY check_export.py $EXP --prefix simc25 >> $LOG 2>&1 && say "export check: PASS" || say "export check: FAIL"

kill $MON 2>/dev/null
say "SUMMARY from leak_accept.csv:"
awk -F, 'NR>1{ if($2>me) me=$2; if($3>mc) mc=$3; n5+=$10; e99+=$11; cu+=$12; rows++ } END{ printf "  samples=%d max_est=%d max_close_wait=%d nginx_5xx_total=%d errno99_total=%d concurrent_use_total=%d\n", rows, me, mc, n5, e99, cu }' leak_accept.csv | tee -a $LOG
say "DONE"
