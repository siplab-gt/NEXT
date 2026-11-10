# Duplicate answers: skipped questions and early expulsion

Branch `fix/duplicate-answer`, 2026-11-10.

## What was wrong (plain words)

When the same answer reached the server twice, the server treated it as two answers.
That happens when a participant's browser re-sends a request after a dropped
connection: in the Nov 2026 collection, 3 of 199 participants each skipped a question
number this way (e.g. 6ae9123d: query ids 20 and 116 missing, after an nginx 499 — the
browser closed the first connection and sent the request again).

Each extra copy:
- advanced the participant's question counter one more step → the next question
  number is **skipped**;
- counted one more answer towards the experiment's total;
- fed the answer to the algorithm a second time;
- on a trap question answered wrongly, counted **two wrong traps** → a participant
  could be **expelled after 2 wrong traps instead of 3** (and be handed the fail code).

The query page's own retry never re-sends an answer (it asks for a fresh question),
and the submit button disables itself, so the copies come from the browser/network,
not from the page. The fix therefore belongs on the server.

## Reproduction (unchanged code)

`local/repro_duplicate_answer.py --exp <EXP_UID>` on the 32-query demo
(`ARankB-InfoTuple-cog_rank4_sample_base.yaml`, trap every 4th query, expelled at the
3rd wrong trap), through nginx, fresh participant per scenario:

| Scenario | Expected | Before fix |
|---|---|---|
| A — same answer POSTed twice, one after the other | next question 2 | **3** (skipped) |
| B — same answer POSTed twice at the same time | next question 2 | **3** (skipped) |
| C — 2 wrong traps, the first one POSTed twice | not expelled | **expelled at question 8** |
| C0 — 2 wrong traps, no duplicate (control) | not expelled | not expelled |

Experiment `1d3e07aaf7f76f4f99acf4249ab25b` (demo, tag `before1`).

## Nov 2026 collection, checked again

`check_export.py 8674955cb542b870b79cdac8ce7091` (read-only): 4 of 236 participants have
a skipped question number — 6aca7df3, 6adfc36e, 6ae9123d (known) and 67420b34 (stopped at
146 answers). No participant has a wrong-trap count higher than their wrong trap
answers, so **nobody in that study was failed because of a duplicate**.

## The fix

One answer per question, enforced by the server (`next/apps/App.py`, `processAnswer`,
so it covers every app):

- Each answer request first bumps a counter `answer_posts` on its query document. The
  bump is a single atomic MongoDB operation, so even two copies arriving at the same
  moment on different workers get 1 and 2 — exactly one of them sees 1.
- The request that got **1** processes the answer as before, then records the result
  on the query document: `answer_outcome: ok`, or `error` plus `answer_error` (for
  example an expulsion).
- A request that got **2 or more** is a copy. It changes nothing. It waits for the
  original's `answer_outcome` (checking every 0.2 s, at most 120 s) and returns the
  **same result**: OK, or the same error. So:
  - the page only asks for the next question once the answer is fully recorded (if
    the copy answered "OK" immediately, the page could fetch the next question before
    the original had advanced the counter — and skip anyway);
  - an expulsion is never lost: if the browser only sees the copy's response, it
    still gets the fail exit.
- Copies are logged in the worker as `DUPLICATE-ANSWER exp=… query=… copy=N`
  (`docker logs local_minionworker_1 2>&1 | grep DUPLICATE-ANSWER`), and the
  query document keeps `answer_posts`, so the export shows how often it happened.

Not changed: the query page (its retry never re-sends an answer), getQuery, the
algorithms. Queries answered before the fix have no `answer_posts` field; that is fine.

## After the fix

Same script, same demo experiment (tags `after2`, `after3`), plus a new scenario D:

| Scenario | Expected | After fix |
|---|---|---|
| A — sequential duplicate | next question 2 | 2, both copies 200 |
| B — concurrent duplicate | next question 2 | 2, both copies 200 |
| C — 2 wrong traps, first sent twice | not expelled | not expelled |
| C0 — control | not expelled | not expelled |
| D — 3rd (expelling) wrong trap sent twice at the same time | both copies say expelled | both say expelled |

Also with **precompute on** (demo config + `precompute: true`, experiment
`c4cc3914ab4c115a33bade599c799d`, tag `pre1`): all five correct, precomputed queries
still served (`PRECOMPUTE HIT`).

Normal runs to completion (`load_sim.py`, 6 simulated participants per experiment,
2 of them answering traps wrongly), then `check_export.py`:

- demo `1d3e07aa…`: 4 completed (32/32), 2 expelled at their 3rd wrong trap, 0 server
  errors; every participant since the fix passes the export check. The one failure
  is `dupCbefore1` from the run on the old code — question 5 missing and failed after
  2 wrong traps, the same pattern as Nov 2026.
- precompute `c4cc3914…`: 4 completed (32/32), 2 expelled at their 3rd wrong trap,
  0 server errors, export check 0 problems.
- The only worker exceptions logged during all of this are the expected
  "Participant … failed" expulsions.

Unit tests: `apps/ARankB/tests/test_duplicate_answer.py` (7 tests: single answer,
sequential copy, concurrent copy waits for the original, 8 simultaneous copies run the
app once, copy replays an expulsion, copy gives up after the wait limit, separate
queries independent) — all pass; against the old `App.py`, 6 of 7 fail. Run command
in the file's docstring.

A first version of the fix returned an error (500) to the copy: the duplicate
response referenced a timing field that only exists after the algorithm runs. Fixed
before these results (the copy's response now carries no timing entry, since no
algorithm ran).
