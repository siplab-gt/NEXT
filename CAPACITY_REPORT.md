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

## c6i.4xlarge, worker counts unchanged (2026-11-02)

Instance resized to a c6i.4xlarge (16 vCPU, 30 GiB); stack restarted with `docker start`,
**nothing else changed** (still 4 async + 6 sync worker processes, commit `671bc81`). Same
driver and config as above: `./capacity_ramp.sh 20 40`, production rank-4 precompute
config, think 8–15 s, 10 % wrong traps, through nginx.

**Measure the wait the participant sees.** After a submit, the query page calls
`processAnswer`, waits for it, then calls `getQuery` and waits again
(`query_page.html`, `processAnswer_success`). The participant's wait per question is
therefore the **sum** of the two latencies, measured from the client through nginx. Only
their own internet round trip (~0.1–0.3 s) is missing, and the targets are text, so
rendering is negligible. Earlier tables quoted `getQuery` alone, which understates the
wait by roughly half. The table below recomputes every run as the sum, steady state only
(first 10 minutes excluded):

| Run | Wait per question p50 / p90 / max | Waits > 20 s | > 30 s | Study length |
|---|---|---|---|---|
| c6i.2xlarge, 25 (Aug) | 26.7 s / 42.1 s / 93 s | 72 % | 39 % | ~92 min |
| c6i.2xlarge, 40 (Aug) | 45.2 s / 65.9 s / 125 s | 97 % | 87 % | ~136 min |
| **c6i.4xlarge, 20** | **7.0 s / 12.9 s / 26 s** | 1 % | 0 % | **~48 min** |
| **c6i.4xlarge, 40** (stopped by hand at ~50/158 answers, 22 min) | **22.9 s / 33.0 s / 47 s** | 69 % | 17 % | ~1 h 40 min projected |

Reliability: 20 → 5,934 requests, all 200; 18 completed + 2 expelled as designed; export
check PASS. 40 → all requests 200 and export check PASS up to the stop; 0 technical
exits, 0 CLOSE_WAIT, 0 % steal throughout.

**Reading.** The new box roughly halves the wait at 40 and gives ~7 s at 20, but **it is
not using half its cores**: the worker sat at ~750–900 % CPU of 1,600 % at both levels
(peak ~1,070 %), while 10–16 jobs (20) and ~40–48 jobs (40) waited in RabbitMQ. The 10
worker processes each run one job at a time (about one core each), so they cap the
machine at ~10 cores. The fix is the worker-count step below, a config-only change (no
code), expected to shorten waits further at both levels; it has to be measured.

## c6i.4xlarge, worker counts raised to 8 async + 12 sync (2026-11-02)

Commit `9cc324e`; worker and backend recreated, rest unchanged. `./capacity_ramp.sh 20`:
5,934 requests all 200, 18 completed + 2 expelled as designed, export check PASS, 0
technical exits, 0 CLOSE_WAIT, 0 % steal. Steady-state wait per question (first 10 min
excluded): **p50 5.6 s, p90 12.7 s, max 28 s**, compared with 7.0 / 12.9 / 26 s with 10
processes. The worker now uses ~12.5 of 16 vCPUs (peak ~15.6), up from ~7.7, but
throughput rose only ~5–15 %. The 16 vCPUs are **8 physical cores with hyperthreading**:
10 processes already occupied the real cores, and the extra processes mostly add
hyperthread siblings and contention. Kept as the production setting (nothing got worse).

Estimates for this setting, not measured. They come from the closed-loop model: once
saturated, throughput is fixed at ~1.25–1.4 questions/s, so wait ≈ N / throughput −
think. The model reproduces the measured 20 and 40 points. Simulated think time is 8–15 s:

| Simultaneous | Median wait per question | Study length (158 questions) |
|---|---|---|
| 20 | **5.6 s (measured)** | ~45–50 min |
| 25 | ~7–9 s | ~50–55 min |
| 30 | ~9–12 s | ~55–60 min |
| 40 | ~16–19 s | ~75 min |

Further levers if needed: `OPENBLAS_NUM_THREADS=1` (less contention, modest gain), a
c6i.8xlarge (16 physical cores, ~2× throughput), or a lower `down_sample` (an algorithm
choice).

## New InfoTuple candidate scoring, over HTTP and HTTPS (2026-11-09 / 2026-11-10)

Same machine and worker counts (c6i.4xlarge, 8 async + 12 sync), same driver
(`./capacity_ramp.sh 20 30`: production rank-4 precompute config, 158 questions incl.
8 traps, think 8–15 s, 10 % wrong traps, full study, fresh experiment per level).
What changed is the code:

- **Nov 9, HTTP** — commit `ae17d38` (branch `fix/infotuple-mi-samples`, **not merged**):
  InfoTuple scores each distinct body set once (10,626 for rank-4 instead of a 5 %
  sample of orderings), with the vectorized information score and the sample-count fix
  (`REPRO_INFOTUPLE_MI.md`). Participants through nginx on `http://127.0.0.1`.
- **Nov 10, HTTPS** — commit `8bf6e54` (branch `feature/https-impl` = the above + the
  duplicate-answer fix + HTTPS). Participants through `https://siplab-next.xyz`, i.e. the
  public address, TLS and the admin-password nginx config, like real participants
  (`BASE=https://siplab-next.xyz HOSTHDR= ./capacity_ramp.sh 20 30`).

Wait per question = `processAnswer` + the following `getQuery`, steady state (first
10 min excluded), computed with `local/wait_per_question.py` — the same script gives
5.58 s for the Nov 2 run above, matching its published 5.6 s.

| Run | Participants | Median wait | p90 | p99 | Max | Requests (all 200) | Completed / expelled | Export check | Worker CPU avg / peak (of 16) | Peak load |
|---|---|---|---|---|---|---|---|---|---|---|
| Nov 2, old InfoTuple, HTTP | 20 | 5.58 s | 12.7 s | 19.0 s | 28.1 s | 5,934 | 18 / 2 | PASS | 10.3 / 15.6 | 16.9 |
| Nov 9, new InfoTuple, HTTP | 20 | 0.37 s | 3.3 s | 5.3 s | 6.1 s | 5,934 | 18 / 2 | PASS | 2.0 / 7.4 | 18.0 |
| Nov 9, new InfoTuple, HTTP | 30 | 0.26 s | 3.4 s | 5.2 s | 5.8 s | 8,901 | 27 / 3 | PASS | 3.1 / 9.1 | 10.0 |
| **Nov 10, new InfoTuple, HTTPS** | **20** | **0.24 s** | 3.1 s | 5.1 s | 6.0 s | 5,934 | 18 / 2 | PASS | 1.5 / 7.8 | 5.1 |
| **Nov 10, new InfoTuple, HTTPS** | **30** | **0.29 s** | 3.6 s | 5.4 s | 6.2 s | 8,901 | 27 / 3 | PASS | 3.7 / 8.3 | 8.9 |

Every run: 0 technical exits, 0 server errors, 0 CLOSE_WAIT, 0 % steal; expulsions
exactly the designed ones (3rd wrong trap). Nov 10 also: 0 `DUPLICATE-ANSWER` events
(~7,400 answers), precompute served the ready question 5,540 times of 5,545 scheduled
(plus 280 deliberate wrap skips), host memory never below 25 GB free, health check OK
throughout.

**Findings**
- **HTTPS costs nothing measurable.** Nov 10 (HTTPS, through the public address) and
  Nov 9 (HTTP, local) agree within run-to-run noise at both levels.
- **The new InfoTuple scoring is what made the machine fast** — roughly 20× shorter
  median wait at 20 participants and a ~4× shorter worst case, with the worker using
  ~2–4 of 16 vCPUs on average instead of ~10. At 30 participants the system is far from
  saturated (at most 11 tasks queued, load ≤ 10), so the old closed-loop estimates
  (30 ≈ 9–12 s) no longer apply *to this code*.
- The remaining tail (p90 ~3 s) is mostly in `processAnswer` (p95 2.8–3.5 s); not
  investigated.

**Caveat — these numbers depend on unmerged code.** The InfoTuple changes
(`fix/infotuple-mi-samples`) are still awaiting a decision: in simulation the fixed
selector did not beat random questions (`REPRO_INFOTUPLE_MI.md`). If they are not
adopted, capacity is the Nov 2 table above (20 ≈ 5.6 s; 30 estimated 9–12 s). HTTPS was
not measured on the old InfoTuple code, but it adds no measurable cost here.
Raw data: `local/ramp_archive_c6i4xlarge_infotuple-bodysets_http_2026-11-09/`,
`local/ramp_archive_c6i4xlarge_https_2026-11-10/` (on the server only, not in git). Throwaway experiments:
`5515cd27…`, `ebe5c882…` (Nov 9), `125a41de…`, `c07722b3…` (Nov 10).

## `dev` branch: master's InfoTuple + duplicate-answer fix + HTTPS (2026-11-10 evening)

Branch `dev` = `origin/master` + config wording (`e9510f6`) + duplicate-answer fix +
HTTPS work, **without** the InfoTuple changes (commit `4262985`). Same driver, over HTTPS
(`BASE=https://siplab-next.xyz HOSTHDR= ./capacity_ramp.sh 20 30`).

| Participants | Median wait | p90 | p99 | Max | Requests (all 200) | Completed / expelled | Export check | Worker CPU avg / peak (of 16) | Peak load | Max queued |
|---|---|---|---|---|---|---|---|---|---|---|
| 20 | **5.3 s** | 12.0 s | 17.5 s | 26 s | 5,934 | 18 / 2 | PASS | 6.6 / 15.7 | 16.0 | 12 |
| 30 | **13.6 s** | 23.5 s | 34.4 s | 48 s | 8,901 | 27 / 3 | PASS | 9.7 / 15.9 | 21.1 | 26 |

Both levels: 0 technical exits, 0 server errors, 0 CLOSE_WAIT, 0 % steal, 0
`DUPLICATE-ANSWER` events, health check OK throughout. Run length 46 min (20) and 65 min
(30); at 30 the worker sat at ~15.5 of 16 vCPUs, and precompute fell behind (3,876 ready
of 5,547 scheduled; 469 stale, 431 abandoned).

- **20 matches the Nov 2 baseline** (5.6 s): HTTPS and the duplicate-answer fix cost
  nothing measurable on master's InfoTuple code either.
- **30 is saturated: 13.6 s median**, worse than the 9–12 s estimated above. Stable and
  correct, but a 158-question study takes a participant ~70 min. With master's InfoTuple
  code, plan for **≤ 20–25 simultaneous participants**. (With the unmerged InfoTuple
  candidate scoring, 30 waited 0.3 s — previous section.)

Raw data: `local/ramp_archive_c6i4xlarge_dev-https_2026-11-10/` (server only).

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
