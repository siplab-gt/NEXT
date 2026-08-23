# Acceptance and capacity results — leak fix + retry feature

*2026-08-22/23, branch `fix/redis-leak-and-retry`. Sections "Leak acceptance",
"Retry feature", "Combined" and "Integration re-run" ran on the original lab box (a
t2.2xlarge, 8 vCPU burstable, 31 GiB); the "Capacity ramp" ran on its replacement, a
c6i.2xlarge (8 real cores). All after the rollout (plain `redis:8` result backend, gunicorn
`-w 2 --max-requests 2000`, nginx 330 s proxy timeouts). Throwaway experiment
launched from the production config `ARankB-InfoTuple-cog_rank4_precompute.yaml`
(158 queries incl. 8 traps, precompute on). Driver: `local/acceptance_driver.sh`;
log `local/acceptance.log`; samples `local/leak_accept.csv` (30 s).*

Earlier sizing and the precompute design: `PRECOMPUTE_REPORT.md` (its 30-participant numbers predate these fixes).

## Leak acceptance (M1)

| Test | Result |
|---|---|
| 10 participants, think 5–10 s, 10 % wrong traps, through nginx | 2,407 requests, **all 200**; 9 completed, 1 expelled (expected); peak 20 live sockets; **0 CLOSE_WAIT**; 60 s after load: **0 sockets** |
| Export check (10) | PASS — contiguous, duplicate-free answers; traps in slot; expulsion shape correct |
| Idle soak 2 h | **0 sockets, 0 errors, backend RSS flat at 233 MiB** for the whole window |
| In-process regression `diag_result_backend.py 40 8` | FLAT (8 pooled sockets after warm-up, 8 at the end) |
| Reproduction protocol (`REPRO_REDIS_LEAK.md`) re-run on the fix | 155 requests under a 160-port range and three `CLIENT KILL` cycles: all 200, 0 × Errno 99 (was total failure) |

Whole run (439 samples over ~4 h): **max CLOSE_WAIT = 0, nginx 5xx = 0, Errno 99 = 0,
ConcurrentObjectUseError = 0**, max live sockets 42 (during the 25-way run).

## Retry / technical-exit feature (M3)

Browser scenarios (`local/test_query_page_retry.py`, headless Chrome): normal flow,
worker paused mid-submit → retry banner → recovery with **no duplicate answer**,
retries exhausted → "Technical problem" modal with `debrief_link_error` → resume at the
same query, genuine expulsion → attention-check fail exit (not the technical one),
refresh resumes. **5/5 PASS.** Found on the way: a genuine expulsion used to reach the
browser as a generic HTML 500 (unclassifiable); `processAnswer` now returns
`200 {meta.expelled: true}`.

## Combined: 25 simultaneous participants on this box (M4, acceptance bar)

| | |
|---|---|
| Requests | **7,519, all HTTP 200** — 0 × 5xx, 0 technical exits, 0 Errno 99 |
| Participants | 23 completed all 158 queries, 2 expelled at exactly the 3rd wrong trap (the 10 % wrong-trap cohort) |
| Duration | 74 min (think 8–15 s) |
| getQuery latency | p50 **9.1 s**, p95 22.5 s, p99 30.1 s, max 44.9 s |
| processAnswer latency | p50 5.3 s, p95 19.1 s, max 38.5 s |
| Machine | load average ~10–11 on 8 vCPU, worker ~780 % CPU, **steal 0 %** (not credit-throttled during this run — genuine compute saturation) |
| Sockets | peak 42 live, **0 CLOSE_WAIT**, none 60 s after the run |
| Export check (25) | PASS |

**Reading:** stability is solved — 25 concurrent participants complete with zero
participant-visible failures, because slow answers are now waited for (nginx 330 s)
instead of being cut off at 60 s and mislabelled as failures. Latency at 25 on this
box is poor (p50 9 s per query; the 10-participant run had p50 7.7 s), i.e. the box is
compute-bound well before 25: this is the capacity problem, not a reliability one.

## Integration re-run (2026-08-22 morning) and the burst-credit finding

A second full run (`local/integration_driver.sh`) repeated every test after the later
changes (dashboard shim, expelling-answer storage, health check, venv untracking):
leak regression FLAT; six browser scenarios PASS; export integrity PASS with the
expelling answer now stored; dashboard plots 200; 10 participants: 2,407 requests all
200, 0 CLOSE_WAIT; 2 h idle: 0 sockets; health check OK throughout (cron firing).

The 25-participant step **failed on capacity**: fine for 35 minutes (p50 10 s), then
from 10:05 UTC the box slowed ~2.5× — two background jobs were killed at the 60 s
celery limit (normally ~8 s), the worker's throughput collapsed while load *fell*,
in-flight requests piled up, getQuery crossed the simulator's 120 s timeout and 21/25
participants took the technical exit. No 5xx, no CLOSE_WAIT, no restart, no OOM, empty
queues. `/proc/stat` shows **23 % of all non-idle CPU time since boot stolen by the
hypervisor**: the t2.2xlarge had spent its burst credits after ~7 h of heavy use
(last night's run + this one). Last night's identical run passed on a fresh balance.

Consequences: (1) capacity numbers from this box are only valid while its credit
balance is healthy — check *CPU credit balance* in the EC2 console's Monitoring tab
before trusting a run; (2) `leak_monitor.sh` and `healthcheck.sh` now report
`steal_pct` / warn at ≥ 20 %, so throttling is visible as it happens; (3) the capacity
ramp belongs on a non-burstable instance, as planned. Worth tuning there regardless:
`CELERY_ASYNC_WORKER_PREFETCH` 4 → 1 (long tasks + prefetch = head-of-line blocking
under load) and the sync-job time limit for precompute under contention.

## Capacity ramp on c6i.2xlarge (8 real cores, 2026-08-22/23)

Same production config (rank-4, precompute on, 158 queries), think 8–15 s, 10 % wrong
traps, through nginx, one fresh experiment per level, worker counts unchanged from the
t2 (4 async + 6 sync). Driver: `local/capacity_ramp.sh`; log `local/ramp.log`.

| Simultaneous participants | Requests | HTTP | getQuery p50 / p95 / max | Technical exits | Completed |
|---|---|---|---|---|---|
| 25 | 7,519 | all 200 | 13.6 s / 32 s / 68 s | 0 | 23 (+2 expelled as designed) |
| 40 | 11,868 | all 200 | 20.1 s / 48 s / 76 s | 0 | 36 (+4 expelled) |
| 60 | 14,368 | all 200 | 29.7 s / 68 s / 117 s | 0 | stopped by hand at ~120/158 answers (+6 expelled) |

Whole ramp: 0 CLOSE_WAIT, 0 nginx 5xx, 0 Errno 99, **0 % steal** (real cores), worker
pegged at ~790 % of 8 vCPUs from 25 upwards, RabbitMQ backlog 20 → 50 → 65 tasks.

**Reading.** Nothing breaks up to 60 simultaneous participants — the reliability work
holds — but the experience degrades linearly because the box is compute-bound from
~15 participants on: each InfoTuple selection costs ~13 s of CPU here (9 s on the t2's
older cores with credits; the c6i's 8 vCPUs are 4 physical cores with hyperthreading,
and each of the 10 worker processes lets OpenBLAS run 2 threads — see tuning). Rule of
thumb on 8 real cores with this config: **~10 simultaneous participants for near-instant
serves, ~25 for tolerable (≈15 s median) waits, 40+ only if participants will accept
half-minute waits.** Per query the cost is the selection, so the only ways to move the
curve are more cores (c6i.4xlarge ≈ 2× throughput), cheaper selections (`down_sample`),
or fewer wasted selections.

Tuning: see "Next: c6i.4xlarge pass" below.

## Next: c6i.4xlarge pass (when ~25 comfortable participants are needed)

Stop → change instance type → start → `docker start …` (README §2.1), then in this order,
each as its own commit and each re-measured at 25 participants with
`./capacity_ramp.sh 25` (one level is enough to compare):

1. Raise the worker counts to use the cores: `CELERY_ASYNC_WORKER_COUNT` 4 → 8,
   `CELERY_SYNC_WORKER_COUNT` 6 → 12 in `local/docker-compose.yml.pre`; recreate the
   worker (`docker rm -f local_minionworker_1 && ./docker_up.sh <IP>`).
2. `OPENBLAS_NUM_THREADS=1` on the worker (BLAS thread contention).
3. `CELERY_ASYNC_WORKER_PREFETCH` 4 → 1 (head-of-line blocking).
4. `worker_max_tasks_per_child` 5 → 200.
Then the full ramp (`./capacity_ramp.sh 25 40 60 100`) for the 16-core rule of thumb.

## Open items

- ~~Dashboard `get_stats` 500s (matplotlib `XAxis.get_converter`)~~ — fixed: mpld3 0.5.11 needs an API from matplotlib 3.10 while the image has 3.8.4; `next/apps/AppDashboard.py` installs a compatibility shim and the mpld3 pin is tightened for the next image build.
- ~~The expelling trap answer is not stored on the query doc~~ — fixed:
  `myApp.processAnswer` records it before the expulsion propagates; `check_export.py`
  recognises both the new and the pre-fix shape.
- Throwaway experiments created for these tests (UIDs `46ab46c5…`, `4f6860d8…`,
  `2ee6764e…`, `49489c8c…`) can be cleaned up per README §5 whenever convenient.
