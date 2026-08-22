# PR: Fix the Redis connection leak, retry server errors on the query page, alerting, docs

*Branch `fix/redis-leak-and-retry` → `master`. Written 2026-08-22. Everything below is already running on the lab box; merging only publishes it.*

_Integration run (2026-08-22 06:40–10:37 UTC, `local/integration.log`): **code checks all PASS** — leak regression FLAT, all six browser scenarios, export integrity incl. the stored expelling answer, dashboard plots, 10-participant load (2,407 requests all 200, 0 CLOSE_WAIT), 2 h idle soak (0 sockets), health check + cron. **The 25-participant step failed on machine capacity, not code**: 35 minutes in, the t2.2xlarge's burst credits ran out (23% of all non-idle CPU time since boot is hypervisor steal), everything slowed ~2.5×, background jobs hit their 60 s limit, queries crossed the 120 s client timeout and 21 of 25 simulated participants took the technical exit — no 5xx, no leak, no restart. The same 25-participant run passed in full last night on a fresh credit balance (`CAPACITY_REPORT.md`). Re-run it after moving to a non-burstable instance._

## Why

The Aug 20–21 2026 Prolific collection lost ~$1,000 and a day of recruiting to two bugs:

1. **A backend Redis connection leak** took the whole platform down for 7 hours (every request `Error 99 connecting to rabbitmqredis:6379`). Reproduced on demand, root-caused, fixed, and re-proved: `REPRO_REDIS_LEAK.md`.
2. **Every server error sent participants to the attention-check FAIL exit**, so dozens of clean participants showed on Prolific as "FAILED ATTENTION CHECKS". The query page now retries and has a separate "Technical problem" exit: README §3.5.

Plus the things found on the way: expulsions arrived as unclassifiable HTML 500s, the dashboard graphs were broken by a library mismatch, the expelling trap answer was never stored, nothing alerted anyone, and git tracked a stale venv.

## What changed

**Backend reliability**
- `next/broker/broker.py`: release each request's celery result backend after the call (celery keeps it greenlet-local under gevent; the drainer pinned 2 sockets per request forever). `result.get` polls at 0.1 s with a 320 s timeout; results are forgotten and detached. The "obvious" alternative (`result_backend_thread_safe=True`) deadlocks under gevent — tested and rejected.
- `rabbitmqredis` is the stock `redis:8` image; the custom image whose cron `CLIENT KILL`ed idle connections (56k kills/day — the trigger) is deleted.
- Celery settings that were silently ignored now take effect (`result_expires=3600`, json serializers, keepalive) in `next/broker/celery_app/celery_broker.py`.
- gunicorn `-w 2 --max-requests 2000`; nginx proxy timeouts 330 s (slow answers are no longer cut off at 60 s and mislabelled as failures).
- Hygiene: cached worker-domain lookup, no per-request Redis SET, shared minionredis pool.

**Participant experience**
- `next/query_page/templates/query_page.html`, `next/query_page/static/js/next_widget.js`: failed calls show a "Connection problem — retrying in N s (attempt k of `retry_attempts`)" banner with a Retry-now button; delays 5/15/30 s; recovery is always a fresh `getQuery` (never a re-POST, so nothing double-counts); retries exhausted → separate "Technical problem" modal with `debrief_link_error`. Only a genuine expulsion reaches the fail exit.
- `next/api/resources/process_answer.py`: expulsion returns `200 {meta.expelled: true}` instead of a generic HTML 500.
- `apps/base.yaml`: new fields `retry_attempts`, `debrief_error`, `debrief_link_error` (with defaults — old configs and experiments keep working). All tracked configs updated; explicit success/fail wording.
- `apps/ARankB/myApp.py`: the wrong trap that expels a participant is now stored on its query document (it used to be lost).
- `next/apps/AppDashboard.py`: dashboard plots work again (mpld3 0.5.11 vs matplotlib 3.8 API mismatch; shim + tighter pin).

**Operations**
- `local/healthcheck.sh` (cron, every 5 min): full-path probe, dead-socket count, containers, 5xx, load → `health.log`, webhook alert on change, auto-restart of the stateless backend on the leak signature.
- `local/make_live.sh`: builds the gitignored `_live` configs (real Prolific codes) from the tracked templates + `prolific_codes.local.txt` — templates are versioned, codes never enter git.
- The stale tracked venv (5,343 files, 5,326 already missing) and the generated `local/docker-compose.yml` are untracked; `git status` is clean.

**Test tooling** (`local/`): `load_sim.py` (HTTP participants), `check_export.py` (export integrity / double-record detector), `leak_monitor.sh`, `diag_result_backend.py` (leak regression), `test_query_page_retry.py` (browser scenarios, screenshots), `acceptance_driver.sh`, `integration_driver.sh`.

**Docs**: README (§3.2–3.5 with screenshots, §7), DEV_DOCUMENTATION (lifecycle + architecture diagrams with Redis, server-error contract, Step 6 test tools), CLAUDE.md runbook, `REPRO_REDIS_LEAK.md`, `CAPACITY_REPORT.md`.

## How it was verified

- Leak: reproduced the exact outage on old code (port range squeezed → `Errno 99`, every request 500); on the fix the same protocol gives all-200 and 0 `Errno 99`. In-process regression FLAT at 8-way concurrency.
- Acceptance on the rebuilt stack: 10 participants (2,407 requests, all 200, 0 CLOSE_WAIT), 2 h idle (0 sockets, RSS flat), **25 simultaneous participants through nginx: 7,519 requests, all 200, 0 technical exits, 0 CLOSE_WAIT**, export integrity PASS. Latency at 25 on the t2.2xlarge is poor (p50 9 s) — a capacity question for a bigger instance, not a reliability one (`CAPACITY_REPORT.md`).
- Browser: normal flow, worker paused mid-submit → banner → recovery with no duplicate answer, retries exhausted → technical exit → resume, genuine expulsion → fail exit, refresh → resume, full run → success exit: all PASS.
- Dashboard plots, expelling-answer storage, and every health-check path (healthy / probe failure / leak signature with auto-restart / recovery) each reproduced-then-verified.

## Deploying elsewhere (the lab box already runs this)

`docker pull redis:8`; `docker rm -f local_nextbackenddocker_1 local_minionworker_1 local_rabbitmqredis_1` (never mongodb); `cd local && ./docker_up.sh <PUBLIC_IP>`; `docker exec reverse_proxy nginx -s reload`. Create a venv from `local/requirements.txt`; `./make_live.sh` for live configs; install the cron line from README §3.3.

## Commits (25)

```
efbed2e Add leak_monitor.sh and load_sim.py for reproducing the Redis leak
a545ee6 load_sim: add --host-header so nginx can be exercised from localhost
d19676b Reproduce the Redis connection leak outage on demand (before-fix results)
6faff20 Fix backend Redis connection leak: release each request's celery result backend
4c1ffe4 Remove the rabbitmqredis CLIENT KILL cron; use the plain redis image
49d3138 Celery settings: make result expiry/serializers effective, enable keepalive
e753380 Safety nets: gunicorn -w 2 + --max-requests, nginx 330 s proxy timeouts
5c6f3cc Broker/Butler hygiene: cache the worker domain, drop per-request SET, share minionredis
afd4b33 REPRO_REDIS_LEAK: record the real mechanism and the after-fix results
d73a085 Add retry_attempts, debrief_error, debrief_link_error experiment fields
5fe091f Query page: retry server errors, separate technical-problem exit
15b55aa processAnswer: return a structured 200 {meta.expelled: true} on expulsion
7bc8c5f Add browser test for query-page error handling (selenium grid)
7f1c287 Configs: add retry/technical-exit fields, explicit success and fail wording
a769cea Add check_export.py: per-participant export integrity check
3989134 Docs: three completion codes / technical exit (README), load_sim, check_export, leak_mo
d09cfc9 Runbook: stability fixes, three completion codes, test tools; proposal marked implement
97afcb3 Acceptance results: leak soaks and 25-participant run all clean; capacity ramp plan
d9e60a4 Add make_live.sh: generate the gitignored _live launch configs from tracked templates
a431d76 Docs: retry/technical exit with screenshots, architecture with Redis, test tools
544250f Docs: prune duplication — drop the implemented proposal note, trim runbook and legacy
7c5d312 Dashboard: fix every stats plot failing with 'XAxis has no attribute get_converter'
f5530d5 ARankB: record the expelling trap answer before the expulsion propagates
eff1aa9 Add healthcheck.sh: cron health probe with alerts and auto-restart on the leak signatur
647eecd Stop tracking the local venv and the generated docker-compose.yml
```
