# Acceptance and capacity results — leak fix + retry feature

*2026-08-22, branch `fix/redis-leak-and-retry`, on the lab box (t2.2xlarge, 8 vCPU
burstable, 31 GiB) after the rollout (plain `redis:8` result backend, gunicorn
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

## Next: capacity ramp on a non-burstable instance

After resizing (e.g. `c5.4xlarge`, 16 vCPU; the Elastic IP survives; restart with
`docker start …`), run from this box or a laptop:

```bash
cd /home/ubuntu/NEXT/local
./leak_monitor.sh 30 > leak_ramp.csv &
for n in 25 40 60 100; do
  ./local-venv/bin/python load_sim.py --base http://127.0.0.1 --host-header 52.2.236.217 \
      --exp <EXP_UID> --participants $n --think 8,15 --wrong-trap-fraction 0.1 --tag ramp$n --quiet
  ./local-venv/bin/python check_export.py <EXP_UID> --prefix simramp$n
done
```

Record p50/p95 per level, `docker stats` CPU per container and RabbitMQ
`messages_ready` on `async@localhost`; the levers (as separate commits) are
`CELERY_ASYNC_WORKER_COUNT` 4→8/12 and `CELERY_SYNC_WORKER_COUNT` in
`local/docker-compose.yml.pre`, `worker_max_tasks_per_child` 5→200 and
`broker_pool_limit` 10→30 in `next/broker/celery_app/celery_broker.py`, gunicorn
`-w 2→4`, and `down_sample` in the experiment YAML if still compute-bound. Target:
the largest N with getQuery p95 under ~5 s (precompute keeping ahead of think time)
and zero failures.

## Open items

- ~~Dashboard `get_stats` 500s (matplotlib `XAxis.get_converter`)~~ — fixed: mpld3 0.5.11 needs an API from matplotlib 3.10 while the image has 3.8.4; `next/apps/AppDashboard.py` installs a compatibility shim and the mpld3 pin is tightened for the next image build.
- ~~The expelling trap answer is not stored on the query doc~~ — fixed:
  `myApp.processAnswer` records it before the expulsion propagates; `check_export.py`
  recognises both the new and the pre-fix shape.
- Throwaway experiments created for these tests (UIDs `46ab46c5…`, `4f6860d8…`,
  `2ee6764e…`, `49489c8c…`) can be cleaned up per README §5 whenever convenient.
