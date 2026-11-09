# InfoTuple question selection: the sample-count bug, the fix, and what the fix showed

*Branch `fix/infotuple-mi-samples` (from `fix/redis-leak-and-retry`). Work done 2026-11-09.
Reported by an outside reviewer; reproduced on unchanged code before any change.*

## In short

- **The bug.** InfoTuple picks each question by scoring candidates on how much the answer
  would teach it. The score was computed from **one** sample instead of several
  (`min(n_samples, 1)` instead of `max`). With one sample the score is always 0 (about 1e-15,
  rounding error), so the "best" question was effectively a random one. This has been the
  case since March 2025 (commit `a51375e`), including the November 2026 rank-4 collection.
- **The fix.** Restored the intended sample count and rewrote the score with numpy so it is
  ~100x faster. Correctness is covered by 10 tests, including agreement with an
  independent line-by-line implementation of the paper's formula.
- **What the fix showed.** In a simulation that runs the app's own selection and map-fitting
  code, the *fixed* InfoTuple learns a participant's overall map **slightly worse than random
  questions**, not better. The cause is the score itself, not the code: it strongly prefers
  questions about the head item's nearest neighbours and keeps asking them.
- **What it means.**
  - Past data: questions after the first round were effectively random. In this simulation
    that is as good as the method gets for the overall map, so the bug likely cost nothing.
  - Next studies: plain random questions are at least as good for the overall map and need no
    selection computing (much more capacity). Before deciding, it is worth checking whether the
    paper meant the score's noise to shrink as answers arrive (see "Open question").

## 1. The bug

`apps/ARankB/algs/InfoTuple/utilsInfoTuple.py`, `mutual_information`:

```python
n_samples = min(int(n_samples), 1)   # always 1
```

The score for a candidate question is

    information = uncertainty of the answer pooled over samples
                - average uncertainty of the answer within one sample

where a *sample* is one plausible version of the participant's map (the head-to-item
distances with random noise added). The score measures how much the samples disagree about
the answer. With one sample the two terms are the same number and cancel, so every candidate
scores ~1e-15 and `primal_body_selector`'s `argmax` picks on rounding noise.

History: the October 2024 code had `n_samples = int(n_samples)`; the `min(..., 1)` arrived in
the March 28, 2025 "version0" commit and was never changed after. The live workers run this
checkout, so every InfoTuple experiment since then used it.

## 2. Reproduction (unchanged code)

`apps/ARankB/tests/test_infotuple_mi.py`, run with the worker image (no stack needed):

```bash
docker run --rm -v /home/ubuntu/NEXT:/next_backend:ro -w /next_backend \
  --entrypoint python local_minionworker:latest -B -m unittest apps.ARankB.tests.test_infotuple_mi -v
```

On unchanged code 3 of the first 5 tests failed: the largest score among 200 candidates was
**1.8e-15**; the spread of scores across the selector's candidates was **2.7e-15**. The two
sanity tests (scores within bounds, zero score when there is no uncertainty) passed.

## 3. The fix (commits on this branch)

| Commit | What |
|---|---|
| `f9684d9` | Tests that fail on the old code |
| `a8ffe02` | `min` -> `max` (the one-line fix); all 5 tests pass |
| `f015507` | Vectorized score, one noise draw per sample shared by all orderings, `mi_samples` setting, 10 tests |
| `83b6ea6`, `a4aad18` | Simulator `local/sim_infotuple.py` and its diagnostics |

Details of `f015507`:

- **Speed.** The score is computed for all candidates at once with numpy. A full selection
  (25 items, 5% of the 255,024 candidates = 12,752 scored) takes **0.36 s at 20 samples**,
  versus **5.4 s for the old loop at 1 sample**. The old loop was most of the 5.6 s median
  wait measured in `CAPACITY_REPORT.md`.
- **Noise per sample.** One sample now uses one noisy set of distances for all 24 orderings
  of the 4 items, as in the paper's Algorithm 1. The old loop (copied from the authors'
  released code, `siplab-gt/infotuple`, `body_metrics.py`) drew fresh noise for each ordering.
- **New optional YAML setting `mi_samples`** (samples per candidate). If omitted the old
  `ceil(n/10)` is used (3 for 25 items), so existing configs and running experiments are
  unaffected. RandomSampling never receives it.
- Removed the unused and broken `fast_mutual_information`.

Selection time per query on one core (full path, including building the candidate list):

| `down_sample` | 3 samples | 20 samples | 50 samples |
|---|---|---|---|
| 0.05 (production) | 0.21 s | 0.36 s | 0.64 s |
| 0.25 | 0.41 s | 1.23 s | 2.71 s |
| 1.0 (all candidates) | 1.23 s | 4.68 s | 10.56 s |

## 4. Does the fixed InfoTuple ask better questions? (simulation)

`local/sim_infotuple.py` runs the app's real InfoTuple code (first round random, then
selection, map refit with SOE after every round of 25 questions; 150 questions in all, as in
the production rank-4 study) against an in-memory database. Each fake participant has a known
"true" map:

- **Real maps:** the fitted maps of 24 randomly chosen participants who completed the
  November 2026 rank-4 collection (199 completed). These are kept outside the repo.
- **Made-up maps:** 12 random point clouds (25 points in 3D), scaled to the real maps' size.

Fake participants answer either **exactly** (always the true order) or by sampling from the
response model InfoTuple itself assumes ("noisy"; only ~12% of its 4-item rankings are fully
right). Real participants sit in between: their own fitted maps agree with **82%** of their
pairwise judgements (10th–90th percentile 72–89%).

**Score used:** the share of held-out comparisons ("is item i or j more like item h?") on
which the learned map agrees with the true map, after all 150 questions. A second score uses
only comparisons among each head's 6 nearest neighbours ("local").

### Results: change vs random questions (same participants, paired)

12 real maps per row, ± is the standard error:

| Setting | Exact answers, whole map | Exact answers, local | Noisy answers, whole map |
|---|---|---|---|
| Random questions (baseline) | 0.957 | 0.880 | 0.666 |
| Old bug (1 sample) | −0.003 ± 0.008 | −0.004 | −0.020 ± 0.011 |
| Fixed, 20 samples | **−0.036 ± 0.014** (4/12 better) | +0.023 ± 0.016 | **−0.038 ± 0.012** (2/12 better) |
| Fixed, noise × 0.3 | −0.035 ± 0.009 | +0.006 | −0.024 ± 0.011 |
| Fixed, noise × 0.1 | −0.026 ± 0.007 | −0.003 | −0.015 ± 0.010 |
| Scored on the **true** map | **−0.054 ± 0.012** (1/12 better) | **+0.052 ± 0.012** | −0.039 ± 0.009 |

Also: fixed InfoTuple at 20 samples on all 24 real maps with noisy answers: −0.021 ± 0.012
(10/24 better). On made-up maps with exact answers: −0.048 ± 0.014 (3/12 better), and
−0.025 when scored on the true map.

### Why: the score prefers the head's nearest neighbours

- Scoring 4,000 candidates on a real map with 200 samples: the score is strongly tied to
  how close the items are to the head (rank correlation **−0.87**). Among the top 1% of
  questions, **72%** of the items are among the head's 6 nearest neighbours, against 25%
  overall. With the noise shrunk to 0.1× the tie weakens but stays (−0.76, 61%).
- In the simulation, items in questions asked after round 1 have an average closeness rank
  of **5.9** with 20 samples and **4.1** when scored on the true map, against **11.6** for
  random questions (0 = the head's nearest of the 24 other items, 23 = farthest). Some items end up in only ~9 questions and others in
  ~40 (random: 16–33).

The noise a sample adds to each distance has a fixed width (the spread of all distances in
the map). Relative to a short distance that is a lot of noise, so the score always rates the
order of nearby items as the most uncertain. Because the width never shrinks as answers come
in, it keeps asking about neighbours it has already learned. Even with the true map in hand
it trades the overall map for local detail: better on nearest-neighbour comparisons, worse
on everything else.

### What would make this wrong

- It is a simulation: 25 items, 150 questions, 12–24 participants per setting, answers drawn
  from InfoTuple's own response model or exact. Real people may differ.
- The paper reports gains over random in its own experiments (different items, sizes and
  numbers of questions); we did not reproduce those setups.

## 5. Open question

The paper's Algorithm 1 draws distances from N(D̂, σ²<sub>n−1</sub>); the subscript suggests
the noise width is meant to be updated (and shrink) as answers arrive. This code, like the
authors' released code, uses the variance of all distances in the current map, which does not
shrink. The appendix that defines it (A.3) was not read word for word. If the width is meant
to shrink, that is the next thing to simulate before choosing between InfoTuple and random
questions.

## 6. Not done yet

- End-to-end test on the stack and the 20- and 30-participant load tests.
- Changes to README / DEV_DOCUMENTATION / CAPACITY_REPORT, and the production configs
  (`mi_samples`, `down_sample`) — waiting on the decision above.

## Appendix: re-running

Tests: see section 2. Simulation (truth maps are a JSON list of 25x3 lists; keep real
participants' maps out of the repo):

```bash
OUT=/path/to/sim   # writable, holds truth.json
docker run --rm -v /home/ubuntu/NEXT:/next_backend:ro -v $OUT:/out -w /next_backend \
  --entrypoint python local_minionworker:latest -B local/sim_infotuple.py \
  --truth /out/truth.json --out /out/results.jsonl --procs 12 --participants 12 \
  --settings random,bug_1sample,s20_ds0.05,s20_oracle --response exact
docker run --rm -v /home/ubuntu/NEXT:/next_backend:ro -v $OUT:/out -w /next_backend \
  --entrypoint python local_minionworker:latest -B local/sim_infotuple.py --summarize /out/results.jsonl
```

All settings are listed in `SETTINGS` at the top of the script. A 12-participant run of one
20-sample setting takes about a minute per participant per process; the machine was otherwise
idle (stack stopped).
