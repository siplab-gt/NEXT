# One-step-ahead InfoTuple precompute: design, verification, and load test

*ARankB + InfoTuple, August 2026. Feature flag: `precompute: true` in the experiment config (default off).*

## The problem

InfoTuple selects each query by scoring candidate tuples by expected information gain — for a 25-target, A=4 experiment that is ~255,000 candidate orderings, downsampled (`down_sample`) and scored with a Monte-Carlo mutual-information estimate. On a typical instance the selection takes ~8 s per query, and the participant's browser blocks on it after **every** answer. Over a 158-query session that is ~20 minutes of spinner; with a batch of concurrent participants the waits compound into queueing delays and Prolific timeouts.

## The idea

Compute query *i+1* while the participant is still answering query *i*. The anchor schedule (a deterministic round-robin of anchors per participant, `head`/`curr_iteration` on the participant document) makes the next selection's inputs known at serve time — so a background job can run the identical selection ahead of need, and the serve path can hand over the stored result instantly. The schedule, the algorithm, and the collected data are unchanged; only *when* the computation happens moves.

Rule of thumb: **a participant who takes longer to answer than one selection takes to compute never sees a spinner.** Faster participants fall back to the inline computation — the pre-feature behavior, not an error.

## Design (implementation in `apps/ARankB/myApp.py` and `apps/ARankB/algs/InfoTuple/myAlg.py`)

- **Trigger:** serving query *i* schedules a background job for the participant's predicted next state. Jobs run on the sync worker pool under a **per-participant namespace** — different participants parallelize, one participant's jobs stay FIFO.
- **Prediction steps over traps.** Trap slots consume an answer (the anchor head advances) without needing a tuple, so the target is the next *non-trap* query. Serving and prediction share one trap-slot function; they cannot disagree.
- **Consume-if-present:** the serve path uses the stored tuple only when its state token (`curr_iteration × n + head`) matches the participant's current state, else it computes inline. A stored result for a *future* state (page refresh) is kept, not destroyed; past-state leftovers are discarded; a job whose target has already passed abandons itself without computing.
- **Guards** skip scheduling when the target is past the end of the experiment (the final query *is* a trap whenever `num_tries` divides evenly by `num_trap_questions`), when the participant has failed (their head freezes under `expel: false`), during burn-in (random selection is instant anyway), and — by default — across the anchor-cycle **wrap**, where the participant embedding is refreshed (`PRECOMPUTE_ACROSS_WRAP = False`; flipping it trades one slightly-stale-embedding query per cycle for zero wrap misses).
- **Isolation:** background failures degrade to inline latency, never to wrong data. Precompute writes nothing to query documents; job exceptions are contained by the worker wrapper; experiments without the flag execute the pre-feature code path bit-for-bit.
- **Monitoring:** worker logs emit `PRECOMPUTE SCHEDULED / DONE / HIT / STALE / FUTURE / ABANDONED / SKIP-WRAP` per event.

A prerequisite fix shipped with the feature: the sync queues were historically bound to a **fanout** exchange, so every background job executed once per sync worker (6× duplicated compute on a default deployment). They now bind to a direct exchange with per-queue routing keys (`next/constants.py`); each job runs exactly once.

## Verification

A 16-case edge matrix was drilled on disposable experiments: traps in every position (including experiments *ending* on a trap), wrap crossings on both normal and trap steps, burn-in boundaries, page refreshes mid-query and mid-trap, participants answering faster than the job, failed-but-not-expelled participants (frozen head), expulsion mid-flow, `setTrap: false` configs, and worker-process recycling. Event accounting balanced exactly in every drill (e.g. 22 scheduled → 22 hits → 1 deliberate wrap skip for a single paced participant), and exports showed unbroken anchor walks with traps at their exact slots throughout.

At a single participant with ~12 s answer pacing: **every eligible query served in 0.1–1.5 s instead of ~8 s** (the residual ~1.3 s cases are celery's `worker_max_tasks_per_child` re-import cost, not the selection).

## Load test: 30 simultaneous participants

Two identical 40-query experiments (32 normal + 8 traps, selection active from query 1), 30 threaded headless-Chrome participants each with 10–20 s think time, two drivers deliberately failing traps. Baseline capped at 12 answers per driver; the precompute run went to completion.

| | Baseline (no precompute) | Precompute |
|---|---|---|
| Normal-query latency p50 | **54.5 s** | **31.3 s (−42%)** |
| Normal-query latency p95 | 78.1 s | 62.1 s |
| Answers recorded / errors | 360 / 0 | 1150 / 0 |
| Throughput (answers/s) | ~0.41 | ~0.59 (+44%) |
| Serve-level precompute hit rate | — | 61% (558/920) |

Integrity under load was perfect: every completing participant's query ids, trap slots, and anchor walk were exact; both wrong-trap drivers were expelled at precisely the third wrong trap; the only logged exceptions were those two expulsions. The abandon guard skipped 205 late jobs (~27 minutes of compute that would otherwise have been wasted).

### Interpreting the numbers — the honest part

At 30 participants on an 8-core instance the workload is **compute-bound**: total selection demand exceeds what the cores can produce in real time, so requests queue regardless of where the computation runs. Precompute's −42% at that scale comes from mobilizing the sync workers alongside the async ones (all cores instead of half), not from instant serves — 61% of selections were precomputed, but even those served ~30 s late because every HTTP request waited behind the remaining inline computations in the shared async queue.

The regime change happens when compute supply exceeds demand. Approximate sizing for the default deployment (4 async + 6 sync workers, ~8 s per selection, ~15–20 s human answers):

- **Up to ~8–12 simultaneous participants:** near-instant serves, high hit rates — the intended experience.
- **~30 participants:** ~30 s median waits (still half of baseline); consider the levers below.

Levers, in rough order of cost-effectiveness:

1. **A larger instance for collection days** — worker counts are environment variables; cores scale both pools directly.
2. **More async workers** — cheap requests (traps, hits, answer processing) stop queueing behind inline selections.
3. **Cheaper selections** — `down_sample` linearly controls the per-query cost (0.02 ≈ half of 0.05's time); also lowers the think-time threshold participants must exceed for instant serves.
4. **`PRECOMPUTE_ACROSS_WRAP = True`** — removes the one guaranteed miss per anchor cycle.

## Enabling it

Add one line to the experiment YAML and launch:

```yaml
precompute: true
```

Running experiments are unaffected (the flag is read from the experiment document created at launch). To watch it work, grep the worker container logs for `PRECOMPUTE`.
