#!/usr/bin/env bash
# integration_driver.sh — run every test on the branch together, unattended.
#
#   tmux new-session -d -s integration "./integration_driver.sh"
#   tail -f local/integration.log        # progress;  last line = verdict
#
# Steps: preflight (health check, compile) -> leak regression (diag) -> browser
# scenarios incl. success run, screenshots not saved -> export check incl. the new
# expelling-answer shape -> dashboard plots -> full acceptance (10 participants,
# 2 h idle, 25 participants, export checks) -> final health check + cron evidence.
# Writes INTEGRATION_VERDICT (PASS/FAIL) into integration.log and PR_NOTES.md.
set -u
cd /home/ubuntu/NEXT/local
PY=./local-venv/bin/python; LOG=integration.log; : > $LOG
fails=0
say(){ echo "[$(date -u +%FT%TZ)] $*" | tee -a $LOG; }
check(){ # check NAME  (uses $? of the previous command via $1=status)
  if [ "$1" = 0 ]; then say "PASS $2"; else say "FAIL $2"; fails=$((fails+1)); fi; }
launch(){ $PY launch.py "$1" 2>&1 | grep -oE "experiment_dashboard/[a-f0-9]+" | head -1 | cut -d/ -f2; }

RUN_START=$(date -u +%FT%TZ)
say "=== INTEGRATION RUN on $(git -C .. rev-parse --short HEAD) ($(git -C .. branch --show-current)) ==="

say "STEP 0 preflight"
./healthcheck.sh >> $LOG 2>&1; check $? "healthcheck.sh reports OK on the idle stack"
docker exec local_nextbackenddocker_1 python -m py_compile /next_backend/next/broker/broker.py /next_backend/next/api/resources/process_answer.py /next_backend/next/apps/AppDashboard.py /next_backend/apps/ARankB/myApp.py >> $LOG 2>&1; check $? "changed Python compiles in the container"
[ -z "$(git -C .. status --short)" ]; check $? "git working tree clean"

say "STEP 1 leak regression (diag_result_backend.py, 40 calls at concurrency 8)"
EXP_BASE=$(launch ARankB-InfoTuple-cog_rank4_sample_base.yaml); say "throwaway sample experiment: $EXP_BASE"
docker exec -i local_nextbackenddocker_1 python -u /next_backend/local/diag_result_backend.py $EXP_BASE 40 8 2>&1 | grep -v "dubious\|safe.dir\|exception for\|^$" | tail -4 >> $LOG; grep -q "RESULT: FLAT" $LOG; check $? "leak regression FLAT"

say "STEP 2 browser scenarios (A-E + success run) on a placeholder-code experiment"
cp ARankB-InfoTuple-cog_rank4_sample_base.yaml /tmp/integ_shots.yaml; sed -i 's|cc=YOUR_TECHNICAL_CODE|cc=EXAMPLE1|' /tmp/integ_shots.yaml
EXP_BROWSER=$(launch /tmp/integ_shots.yaml); say "browser experiment: $EXP_BROWSER"
docker rm -f selenium-load >/dev/null 2>&1; docker run -d --name selenium-load --shm-size=2g -p 4444:4444 -e SE_NODE_MAX_SESSIONS=4 -e SE_NODE_OVERRIDE_MAX_SESSIONS=true selenium/standalone-chrome >/dev/null; sleep 10
timeout 2400 $PY test_query_page_retry.py $EXP_BROWSER --only=A,B,C,D,E,S 2>&1 | grep -E "^(PASS|FAIL|SUMMARY)" >> $LOG; grep -q "SUMMARY: A=PASS, B=PASS, C=PASS, D=PASS, E=PASS, S=PASS" $LOG; check $? "all six browser scenarios"
docker unpause local_minionworker_1 >/dev/null 2>&1; docker rm -f selenium-load >/dev/null 2>&1

say "STEP 3 export integrity on the browser experiment (includes the stored expelling answer)"
$PY check_export.py $EXP_BROWSER >> $LOG 2>&1; check $? "check_export on browser experiment"
grep -q "expelled at trap 3)" $LOG; check $? "expelling trap answer is stored (new shape present)"

say "STEP 4 dashboard plots"
code=$(curl -s -m 60 -o /dev/null -w '%{http_code}' -X POST -H 'Content-Type: application/json' -d "{\"exp_uid\":\"$EXP_BROWSER\",\"args\":{\"stat_id\":\"test_error_multiline_plot\",\"params\":{},\"force_recompute\":0}}" http://127.0.0.1:8000/dashboard/get_stats); [ "$code" = 200 ]; check $? "dashboard test_error_multiline_plot -> HTTP $code"
code=$(curl -s -m 60 -o /dev/null -w '%{http_code}' -X POST -H 'Content-Type: application/json' -d "{\"exp_uid\":\"$EXP_BROWSER\",\"args\":{\"stat_id\":\"most_current_embedding\",\"params\":{\"alg_label\":\"InfoTuple\"},\"force_recompute\":0}}" http://127.0.0.1:8000/dashboard/get_stats); [ "$code" = 200 ]; check $? "dashboard most_current_embedding -> HTTP $code"

say "STEP 5 acceptance: 10 participants, 2 h idle, 25 participants (production precompute config)"
EXP_ACC=$(launch ARankB-InfoTuple-cog_rank4_precompute.yaml); say "acceptance experiment: $EXP_ACC"
: > acceptance.log     # acceptance_driver appends; the checks below assume one run
./acceptance_driver.sh $EXP_ACC >> $LOG 2>&1
grep -q "max_close_wait=0 nginx_5xx_total=0 errno99_total=0" acceptance.log; check $? "acceptance summary: 0 CLOSE_WAIT, 0 5xx, 0 Errno 99"
[ "$(grep -c 'export check: PASS' acceptance.log)" = 2 ]; check $? "both acceptance export checks PASS"
[ "$(grep -c 'technical exits: 0' acceptance.log)" = 2 ]; check $? "0 technical exits in both load runs"
grep -A7 "load_sim summary (c25)" acceptance.log | grep -E "getQuery|participants:|5xx" >> $LOG

say "STEP 6 final health + cron evidence"
./healthcheck.sh >> $LOG 2>&1; check $? "healthcheck.sh OK after the run"
[ "$(grep -c ' OK ' health.log)" -ge 10 ]; check $? "cron has been running healthcheck.sh (>=10 OK lines in health.log)"
! awk -v t="$RUN_START" '$1 >= t' health.log | grep -q "restarted local_nextbackenddocker_1" || say "NOTE: an auto-restart happened during the run (see health.log)"
awk -v t="$RUN_START" '$1 >= t && $2 != "OK"' health.log | head -3 | sed 's/^/  health during run: /' | tee -a $LOG

if [ $fails = 0 ]; then verdict="INTEGRATION_VERDICT: ALL PASS"; else verdict="INTEGRATION_VERDICT: FAILED ($fails checks failed - see integration.log)"; fi
say "$verdict"
sed -i "s|^_Integration run:.*_$|_Integration run ($(date -u +%F)): ${verdict#INTEGRATION_VERDICT: } — details in local/integration.log._|" ../PR_NOTES.md 2>/dev/null
say "DONE (throwaway experiments: $EXP_BASE $EXP_BROWSER $EXP_ACC)"
