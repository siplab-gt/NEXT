# LORE as InfoTuple's map-fitting method

November 2026. InfoTuple (A Rank B) refits each participant's map after every round of
25 answers. It used SOE for this. New experiments now use **LORE** (Anand et al., ICLR 2026,
[arXiv 2602.04192](https://arxiv.org/abs/2602.04192); `cblearn.embedding.LORE`, cblearn 0.4.0).
SOE can still be chosen per experiment.

**In short**

- **Quality:** on the 198 completed participants of the November 2026 rank-4 study, LORE
  maps predict held-out answers slightly *better* than SOE maps, in every round: 69.9% vs
  69.2% at the end (+0.7 points ± 0.2, 106 participants up / 66 down). In the offline
  simulation LORE matches SOE (differences within noise). It is ahead early, which is when
  the map steers question choice.
- **Speed:** a LORE refit takes **~0.2 s** (median; 95th percentile ~0.4 s; worst 0.65 s)
  against ~0.01 s for SOE. It runs inline on 1 answer in 25, so that one answer takes about
  0.2 s longer. That is small next to the ~5.6 s median wait at 20 simultaneous
  participants (`CAPACITY_REPORT.md`).
- **The 30 s pooled-map job:** uncapped, LORE on everyone's answers reached **~30 s at
  ~175 participants**, which is the job's hard limit. It now fits a fixed random subsample
  of 20,000 comparisons. That takes 1.4–4 s on real data at any study size (worst case ~10 s).
  Held-out accuracy is unchanged by the subsample.
- **1000 iterations, not 1500.** 1500 is ~25% slower and is not better: about the same on
  real data, and worse on noise-free simulated answers.
- **Map size: the configs now use `d: 6`** (previously 3; "rank 4" in the study name is the
  4 items ranked per question). LORE starts at 6 dimensions and keeps only those the answers
  support. It costs no question-selection time and ~0.1 s more per refit. It helps in
  simulation and is neutral on real data (§4).
- **Deploying needs a rebuild of the worker/backend image** (steps below). Until then the
  code is safe on the current image: running experiments keep SOE, and a new LORE launch
  fails at once with a clear message.

## 1. What changed

| | |
|---|---|
| `apps/ARankB/algs/InfoTuple/myAlg.py` | `_embedder()` builds the estimator for both call sites (`incremental_embedding_update`, inline in processAnswer at the end of each round; `full_embedding_update`, a `butler.job` with `time_limit=30`). |
| New settings (experiment YAML, optional) | `embedding_method: LORE` or `SOE` (default **LORE**) and `embedding_max_iter` (default **1000** for LORE, 20 for SOE). Declared in `myApp.yaml` and `Algs.yaml` and passed through `myApp.py`, like `mi_samples`. Like `mi_samples`, RandomSampling does not accept them, so don't set them when RandomSampling is in `alg_list`. |
| Experiments created before this change | They have no stored method and **keep SOE with the old settings**. After the upgrade SOE output is bit-identical (cblearn 0.3.0/sklearn 1.5.1 vs 0.4.0/1.9.1, 20 real participants × 6 refits: max difference 0.0). |
| Pooled map (`full_embedding_update`) | With LORE it fits at most 20,000 × 3/d comparisons (`full_update_cap`: 20k at d = 3, 10k at d = 6), a seeded random subsample. It uses its own random generator, so the question-selection random stream is untouched. This map is only read by `getModel` (the dashboard), never by question selection. |
| Participant document | New `embedding_rank`: the number of dimensions LORE kept after the latest refit. |
| Old image safety | `from cblearn.embedding import LORE` is guarded. On cblearn 0.3.0 the module still imports, SOE experiments run, and launching a LORE experiment raises `embedding_method LORE needs cblearn >= 0.4.0 ...` at initExp. |
| `next/base_docker_image/requirements.txt` | `cblearn==0.4.0`, `scikit-learn==1.9.1` (cblearn 0.4.0 needs ≥ 1.6; it also pulls in numba and sparse). |
| Tests | `apps/ARankB/tests/test_infotuple_embedding.py` (10 tests). All 41 InfoTuple tests pass on Python 3.11.9 + cblearn 0.4.0. On the current image (0.3.0) the 35 SOE-side tests pass and the 6 LORE tests skip. |
| `local/sim_infotuple.py` | Settings `random_soe/random_lore/prod_soe/prod_lore/prod_lore1500`; records map rank and scale; `--summarize --baseline`. Older settings still use SOE, so earlier results reproduce. |

**LORE parameters.** `n_components = d` (3 in all current studies). This is LORE's upper
bound; it may use fewer dimensions. `backend='scipy'`, because the default backend is torch,
which is not in the image. `lamb=0.01, p=0.5, margin=0.1` are the cblearn/paper defaults.
On real data `lamb` behaves as follows (198 participants, held-out accuracy after 150
answers):

| lamb | held-out | vs SOE | dimensions kept |
|---|---|---|---|
| 0.001 | 69.1% | −0.1 ± 0.2 | 3 for everyone (LORE ≈ unregularised) |
| **0.01** | **69.9%** | **+0.7 ± 0.2** | 3 for 181, 2 for 17 |
| 0.1 | 41.9% | −27 | 0–1: maps collapse. Never raise it this far. |

`margin` stays at 0.1. SOE's `margin=5` belongs to SOE's hinge loss and sets the scale of
SOE maps; it does not carry over. LORE has no `n_init`; with a starting map given, SOE ran
once anyway. `random_state=seed` and the warm start `init=X` are kept.

**Map scale.** LORE maps come out ~2× smaller than SOE maps: median distance between items
4.5 vs 10.0 on real data. Question scoring adapts its noise to the map's spread, and the
questions asked look the same. In simulation the average closeness-rank of the items asked
about was 10.6 with LORE vs 10.7 with SOE (noisy answers), and 8.3 vs 8.1 (exact answers).

## 2. Timings

c6i.4xlarge, one thread, real November 2026 answers (25 items, 3-D). Another session's load
test was running for part of this (load average 3–11), so read these as upper-end figures.

**Per-participant refit** (inline in processAnswer, once per round; 150 → 900 comparisons).
Median / 95th percentile / max in seconds over 198 participants:

| round (comparisons) | SOE | LORE 1000 | LORE 1500 |
|---|---|---|---|
| 1 (150) | 0.005 / 0.010 / 0.014 | 0.18 / 0.28 / 0.29 | 0.26 / 0.40 / 0.43 |
| 2 (300) | 0.006 / 0.011 / 0.017 | 0.23 / 0.35 / 0.40 | 0.32 / 0.50 / 0.56 |
| 3 (450) | 0.007 / 0.013 / 0.016 | 0.26 / 0.41 / 0.46 | 0.36 / 0.49 / 0.60 |
| 4 (600) | 0.008 / 0.015 / 0.022 | 0.25 / 0.42 / 0.59 | 0.24 / 0.46 / 0.68 |
| 5 (750) | 0.010 / 0.018 / 0.027 | 0.23 / 0.39 / 0.60 | 0.21 / 0.50 / 0.85 |
| 6 (900) | 0.011 / 0.020 / 0.026 | 0.19 / 0.45 / 0.64 | 0.16 / 0.49 / 0.75 |

LORE stops early once it has converged. Early rounds use all 1000 iterations; by round 6 the
median is ~220. Per participant that is ~1.3 s of extra CPU over the whole study. The
32-question demo config (`cog_rank4_sample_base.yaml`, 24 regular questions) never finishes
a 25-answer round, so it triggers **no** refits under either method.

**Pooled map** (`full_embedding_update`, 30 s hard limit):

| comparisons (≈ participants) | SOE | LORE uncapped | LORE, 20k cap (shipped) |
|---|---|---|---|
| 9,000 (10) | 0.13 s | 1.5 s | 1.4 s |
| 45,000 (50) | 0.67 s | 8.1 s | 4.1 s |
| 90,000 (100) | 1.3 s | 19 s | 2.9 s |
| 158,322 (175) | 3.0 s | **30.4 s** | 3.4 s |

On real data LORE converges in ~300 iterations, so 1000 vs 1500 makes no difference here.
The slowest case is perfectly consistent (noise-free) answers, where LORE runs to the
iteration cap. At the 20k cap that took 10.4 s (1000) or 14.7 s (1500) on a busy machine.

Held-out accuracy of the pooled map (30k comparisons held out): SOE 63.9%; LORE 62.6% on all
128k comparisons, and 62.5–62.8% on subsamples of 10k–50k. On pooled data LORE keeps 2
dimensions. This is the one place it scores below SOE (−1.3 points). The pooled map only
feeds the dashboard; each participant's own map drives question selection.

## 3. Quality

**Real data.** 198 participants who completed the November 2026 rank-4 study, 150 answers
each. 30 random answers per participant (180 comparisons) were held out. Each method then
refit round by round on the rest, starting from a random map and reusing the previous map,
as production does. Figures are held-out accuracy (share of held-out comparisons the map
gets right):

| after round | 1 | 2 | 3 | 4 | 5 | 6 |
|---|---|---|---|---|---|---|
| SOE | 56.5 | 60.1 | 63.6 | 66.1 | 68.1 | 69.2 |
| LORE 1000 | 58.2 | 61.8 | 65.2 | 67.2 | 69.0 | **69.9** |
| LORE 1500 | 58.0 | 61.5 | 65.1 | 67.1 | 69.0 | 70.0 |

Fit to the answers used for fitting: 82.8% (LORE) vs 82.9% (SOE). LORE generalises a little
better rather than fitting the same answers harder. Caveat: these questions were chosen by
the SOE-driven study, so this compares the fitting methods on fixed data, not the full loop.

**Simulation, the full loop** (`local/sim_infotuple.py`, production settings: burn-in 1,
`down_sample` 1.0, default `mi_samples`). There are 24 truth maps: the fitted maps of 24
random November participants. Score is agreement with the true map on held-out
comparisons, paired by participant:

| answers | setting | round 1 → 6 | final vs `prod_soe` |
|---|---|---|---|
| noisy (InfoTuple's own response model) | prod_soe | 0.532 → 0.646 | — |
| | prod_lore | 0.538 → 0.647 | +0.001 ± 0.010 |
| | prod_lore1500 | 0.537 → 0.652 | +0.006 ± 0.010 |
| exact (always the true order) | prod_soe | 0.670 → 0.948 | — |
| | prod_lore | **0.729** → 0.941 | −0.007 ± 0.009 |
| | prod_lore1500 | 0.730 → 0.930 | −0.018 ± 0.008 |

With random questions instead of InfoTuple's: noisy answers give 0.647 (SOE) vs 0.656
(LORE); exact answers give 0.953 vs 0.945. Both methods give the same picture of adaptive
vs random questions as `REPRO_INFOTUPLE_MI.md`: no clear overall gain.

**Dimensions kept.** On real data LORE keeps 3 dimensions for 181 participants and 2 for 17
(9%). That is decided at the first refit and never changes afterwards, because each refit
starts from the previous map and LORE's update cannot add back a dimension the map has
lost. I tested whether that hides a third dimension the data supports: before each refit I
added small random noise to the starting map so a lost dimension could grow back. For
those 17 participants, accuracy stayed the same (74.6–74.8%), and with small noise LORE
kept them at 2 dimensions. So 2 dimensions is LORE's estimate, not an artefact. These 17
are still better fit by LORE than by SOE (74.8% vs 73.8%). `embedding_rank` on the
participant document makes this visible during a study.

## 4. How many dimensions to start LORE with (`d` / n_components)

LORE is meant to start with more dimensions than the data needs and shrink the extra ones.
`n_components` is the experiment's `d`. Every current config uses `d: 3`. ("Rank 4" in
the study name is the 4 items ranked per question, A = B = 4, not the map's dimension.)
Measured at d = 3, 4, 6, 8, 10 with production settings.

**Question-selection time doesn't depend on `d`.** `d` only enters the head-to-body
distances; all the scoring runs on those scalar distances. `select_query` over all 10,626
body sets took 0.034–0.038 s at every d with the default 3 samples, and 0.16–0.19 s with 20
samples. Directions LORE has zeroed add nothing to any distance: a 10-D map with its extra
dimensions zeroed picks exactly the same question as the same map cut down to 4-D.
**Cutting the map down to LORE's `rank_` before selection would therefore save nothing and
change nothing**, so InfoTuple keeps scoring in the full d.

**What does grow with d is LORE's own fitting.**

| d | refit per round, median / 95th pct / max | pooled 20k, real / noise-free |
|---|---|---|
| 3 | 0.28 / 0.50 / 0.74 s | 4.1 / 10.4 s |
| 4 | 0.32 / 0.60 / 0.89 s | 6.3 / 17.2 s |
| 6 | 0.40 / 0.74 / 1.06 s | 9.9 / 22.6 s |
| 8 | 0.45 / 0.84 / 1.27 s | 11.5 / 28.3 s |
| 10 | 0.49 / 0.95 / 1.40 s | 14.3 / 34.2 s |

(Measured while the sweeps ran, so slower than §2.) The refit is still well under a second
on the one answer in 25 that triggers it. The pooled update would pass 30 s at d ≥ 8, so its
cap now shrinks with d (20k × 3/d). The noise-free worst case is now 8.0 s at d = 3, 6.9 s at
d = 6 and 5.9 s at d = 10. On real pooled data 10k comparisons score the same as 128k.

**Dimensions recovered and accuracy.**

*Real data* (198 participants, the same held-out split as §3; held-out accuracy after 150
answers, change vs starting at d = 3):

| start d | held-out | vs d = 3 | dimensions kept (2 / 3 / 4 / 5) |
|---|---|---|---|
| 3 | 69.9% | — | 17 / 181 / – / – |
| 4 | 70.1% | +0.2 ± 0.2 | 8 / 152 / 38 / – |
| 6 | 70.0% | +0.1 ± 0.2 | 7 / 146 / 45 / – |
| 8 | 70.0% | +0.1 ± 0.2 | 7 / 139 / 52 / – |
| 10 | 70.0% | +0.1 ± 0.2 | 6 / 139 / 53 / – |

Whatever the start, LORE settles on 3 dimensions for most participants and 4 for about a
quarter, and never goes above 4. So this data really is about 3-dimensional, and starting
bigger doesn't predict answers measurably better.

*Simulation* (24 participants per cell; final agreement with the true map, change vs
starting at d = 3, ± standard error):

| truth maps | answers | d=4 | d=6 | d=8 | d=10 |
|---|---|---|---|---|---|
| real 3-D maps | noisy | −0.000 ± 0.013 | +0.016 ± 0.012 | +0.016 ± 0.013 | −0.006 ± 0.010 |
| real 3-D maps | exact | +0.010 ± 0.009 | **+0.016 ± 0.007** | +0.009 ± 0.009 | +0.005 ± 0.009 |
| made-up 4-D maps | noisy | +0.007 ± 0.008 | +0.003 ± 0.010 | −0.003 ± 0.012 | −0.002 ± 0.009 |
| made-up 4-D maps | exact | **+0.031 ± 0.008** | **+0.033 ± 0.009** | **+0.030 ± 0.010** | **+0.023 ± 0.009** |

Starting above 3 helps when answers are clean. With 3-D truths and d = 3, LORE sometimes
drops to 2 dimensions on the first round and can't get back (§3); started bigger, it keeps
all 3. With 4-D truths, d = 3 can't represent them. Rank recovery is only partial in 150
answers, though: with exact answers to 4-D truths LORE kept 4 dimensions for 8–12 of 24
participants and 3 for the rest. With noisy answers (InfoTuple's own response model, much
noisier than real participants) nothing differs beyond noise. d = 10 is never better than
d = 6.

**Decision: `d: 6` in all six InfoTuple configs.** `n_components = d` (no separate
setting), and InfoTuple keeps scoring in the full d.
- d = 6 costs no selection time, ~0.1 s more per refit, and nothing on the pooled job (the
  cap adapts).
- It is never worse than d = 3 here, and it is the best or near-best setting in every
  simulation.
- It lets LORE find each participant's dimension instead of having it fixed at 3.
- Don't go above ~8: there is no further gain and fitting cost keeps rising.
- For a study that should match the old 3-D maps exactly, set `d: 3` (and
  `embedding_method: SOE` for the old method).
- The dashboard's scatter plot now shows the map's two main directions (PCA) instead of its
  first two columns.

Two things to know before raising `d`:
- Exported participant maps and the pooled `X` then have d columns in a rotated basis. The
  dimensions LORE kept are spread across all columns, not placed in the first few, so use
  an SVD/PCA of the map for analysis or plots.
- `d` also sets the map size for RandomSampling if it is in `alg_list`.

## 5. Deploying (worker/backend image rebuild)

Do this when no collection is live (check `http://52.2.236.217/dashboard/experiment_list`),
after the InfoTuple MI branch has landed, with this branch merged into the lab branch via a
GitHub PR and checked out in `/home/ubuntu/NEXT` as usual (`CLAUDE.md` git rules).

1. Back up:
   ```bash
   docker exec local_mongodb_1 mongodump --host 127.0.0.1 --port 27017 --out /next_backend/local/backup_$(date +%F)
   ```
2. Rebuild **only** the worker and backend images. Run it in tmux; it takes a while. The
   running containers are unaffected until step 4.
   ```bash
   cd /home/ubuntu/NEXT/local && docker-compose build minionworker nextbackenddocker
   ```
   **Do not run a bare `docker-compose build`.** The `mongodb` service builds from the same
   Dockerfile. A new `local_mongodb` image would make the next `docker-compose up` recreate
   `local_mongodb_1`, which holds all experiment data in an anonymous volume.
   Also: the unpinned `colormath`, `opencv-python` and `scikit-image` re-resolve on a
   rebuild. With these pins, the scratch venv resolved opencv-python 4.11.0.86 and
   scikit-image 0.26.0 against numpy 1.26.4.
3. Check the new image before swapping (throwaway container, repo read-only):
   ```bash
   docker run --rm -v /home/ubuntu/NEXT:/next_backend:ro -w /next_backend --entrypoint python local_minionworker:latest -c "import cblearn, sklearn; from cblearn.embedding import LORE; print(cblearn.__version__, sklearn.__version__)"
   ```
   ```bash
   docker run --rm -v /home/ubuntu/NEXT:/next_backend:ro -w /next_backend --entrypoint python local_minionworker:latest -B -m unittest apps.ARankB.tests.test_infotuple_embedding apps.ARankB.tests.test_infotuple_mi apps.ARankB.tests.test_infotuple_candidates
   ```
   Expect `0.4.0 1.9.1`, then 41 tests OK with none skipped.
4. Swap the stateless containers (the usual procedure from `CLAUDE.md`):
   ```bash
   docker rm -f local_nextbackenddocker_1 local_minionworker_1
   ```
   ```bash
   cd /home/ubuntu/NEXT/local && ./docker_up.sh 52.2.236.217
   ```
   Then `docker ps -a`: remove any hash-prefixed leftover container, and confirm
   `local_mongodb_1` was **not** recreated (same container ID and uptime as before).
5. Smoke test: launch a test experiment with the production config and answer at least 25
   regular questions. A round has to finish for a refit to happen, so the 32-question demo
   won't show it. Then check:
   ```bash
   docker logs local_minionworker_1 2>&1 | grep -c "Embedding update failed"
   ```
   It should print 0. The participant document should now have `embedding_rank`. Also
   check `tail -3 local/health.log`.

**Configs.** The tracked configs already have `d: 6`; new launches use LORE with 1000
iterations by default. Regenerate the gitignored `_live` configs with `./make_live.sh`, since
they still say `d: 3`. For
SOE, add `embedding_method: SOE` to the experiment YAML; for another cap, add
`embedding_max_iter: N`. Then re-run `./make_live.sh` for the `_live` copy. The conda
`environment.yml` files still say cblearn 0.3.0, but the Docker build doesn't use them (the
conda steps are commented out of the Dockerfile).

**Rollback.** Set `embedding_method: SOE` for new launches, or rebuild with the old pins.
Experiments started under LORE keep LORE, because the method is stored at launch.

## 6. Reproducing

Python 3.11.9 venv outside the repo with `next/base_docker_image/requirements.txt`, minus
`av`, which needs ffmpeg headers to build and isn't used here. Answers and fitted maps come
from `local/backup_2026-11-05` (`ARankB:participants` / `ARankB:algorithms` of experiment
`8674955c…`), read with `bson.decode_all`. Keep extracted participant data out of the repo.

```bash
python -B -m unittest apps.ARankB.tests.test_infotuple_embedding -v
```
```bash
python -B local/sim_infotuple.py --truth truth.json --out model.jsonl --procs 4 --settings random_soe,random_lore,prod_soe,prod_lore,prod_lore1500 --response model
```
```bash
python -B local/sim_infotuple.py --summarize model.jsonl --baseline prod_soe
```
(same with `--response exact`). The real-data held-out comparison and the timing scripts were
one-off scratch scripts. They follow the procedure in §2–3: production chaining, a random
starting map, 30 held-out answers per participant. Map-size runs: settings
`prod_lore,prod_lore_d4,prod_lore_d6,prod_lore_d8,prod_lore_d10,prod_soe`, with the real
truth maps and with 24 random 4-D point clouds scaled to the real maps' median distance.
