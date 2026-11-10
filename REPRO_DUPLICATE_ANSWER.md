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

## The fix

_(next commit)_
