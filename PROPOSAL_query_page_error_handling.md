# Proposal: stop sending server-error victims to the FAIL exit

*Status: PROPOSAL ONLY — not implemented. Written 2026-08-21 after the rank-4
overload incident. No code has been changed.*

## The problem (what happened on 2026-08-20/21)

The query page funnels **every** AJAX failure into one callback
(`next/query_page/templates/query_page.html`, `widget_failure`), which shows the
**fail debrief with the fail completion code** (`debrief_link_fail`). The AJAX
layer (`next/query_page/static/js/next_widget.js`, `getQuery` and
`processAnswer` `.fail()` handlers) does no retry and no discrimination — a
one-off nginx 504 during load is treated identically to a genuine
attention-check expulsion.

Consequence during the overload: participants who were 125–154 queries deep
with **zero missed traps** were handed the fail code `C1G34UO8` and appear on
Prolific as "FAILED ATTENTION CHECKS". 16 of the 18 fail-code submissions that
night were server casualties, not real failures; one participant (154/159,
clean traps) effectively completed the study and still got the fail exit. This
poisoned the review queue and nearly caused mass wrongful rejections.

## Design goals

1. A transient server hiccup should be invisible (auto-retry), or at worst end
   in a **neutral** "technical problem" exit — never the fail exit.
2. A genuine trap-expulsion must still reach the fail exit exactly as today.
3. Never risk double-recording an answer.

## Key facts the fix must respect

- **Genuine failure is signalled through the same error path.** A trap-failed
  participant triggers `ValueError("Participant <uid> failed")` in
  `apps/ARankB/myApp.py` (`processAnswer`, ~line 151); the API wraps it as
  `ReportAnswerError` (`next/api/resources/process_answer.py`, `custom_errors`)
  with `backend_error` containing the message. So `widget_failure` cannot just
  be neutralized — it must *discriminate*.
- **The success payload already carries `participant_failed`**
  (`myApp.processAnswer` return, ~line 157). The client can track this flag on
  every answer and know *before* any error whether this participant is failed.
- **`getQuery` is retry-safe by design.** A served-but-unanswered query does
  not consume the slot and is re-served on the next `getQuery`
  (`myApp.processAnswer` comment, ~line 127). Repeating `getQuery` can never
  corrupt state.
- **`processAnswer` is NOT retry-safe.** During the incident the backend often
  finished processing *after* nginx had already returned 504 to the browser —
  the answer WAS recorded even though the client saw an error. Re-POSTing the
  same answer would double-increment `query_id` and corrupt the schedule.

## Proposed changes

All template/static-file only — live after `docker restart
local_nextbackenddocker_1` (~2 s), no relaunch, no effect on stored data.

### 1. Track failed-state on the client (`query_page.html`)

In `processAnswer_success`, read `participant_failed` from the response meta
and keep it in a JS variable (`participant_is_failed`). This is the ground
truth for which exit a participant deserves.

### 2. Retry `getQuery` on transient errors (`next_widget.js` or the page)

On `getQuery` failure: retry up to 3 times with growing delays (e.g. 5 s /
15 s / 30 s), showing a small "Connection is slow — retrying…" notice instead
of tearing down the page. Safe because getQuery is idempotent (fact above).
Only after all retries fail, fall through to the exit logic (step 4).

### 3. Recover from `processAnswer` errors WITHOUT re-posting the answer

On `processAnswer` failure, do **not** retry the POST (double-record hazard).
Instead, after a delay, call **`getQuery`**:

- If the failed POST actually succeeded server-side (the 504-after-success
  case), getQuery serves the *next* query — the participant continues
  seamlessly, nothing lost.
- If the POST truly failed, getQuery re-serves the *same* query — the
  participant answers it again — by design, no state corruption.

The server's own re-serve semantics resolve the ambiguity; the client never
needs to know which case occurred.

### 4. Discriminate the exits in `widget_failure`

Pass the jqXHR into the callback. Then:

- **Fail exit (`debrief_link_fail`) only when the failure is genuinely the
  participant's**: `participant_is_failed === true` (from step 1), or the
  response body carries the app-level failure signature
  (`ReportAnswerError` / `backend_error` containing "Participant … failed").
- **Everything else** (timeout, HTTP 0/502/504, nginx HTML error body) after
  retries are exhausted → **neutral technical exit**: a message like "A
  technical problem interrupted the study — your progress is saved. Please
  return the study on Prolific or message the researcher; you will not be
  penalized." with **no completion code** (or a dedicated third Prolific code
  configured as a follow-up action, if desired). On Prolific such people then
  show as NO CODE / returned instead of "failed attention checks", which is
  truthful and reviewable.
- Verify the exact HTTP status/body of a real expulsion on a **disposable
  experiment** during implementation (drill: fail 3 traps, capture jqXHR) —
  don't trust this doc's reading of flask-restful's status-code behavior.

### 5. Optional YAML follow-up

`debrief_fail` text currently reads "Click the link to finish" — identical to
the success text. Consider making the fail text explicit ("You did not pass the
attention checks") in the next launched config so participants aren't confused
about which outcome they got. (Config change → applies to *future* launches
only; the running-experiment doc is immutable.)

## What this does NOT change

- Server/app code paths, algorithms, data recording — untouched.
- Genuine expulsion flow — identical outcome, now deliberate instead of
  incidental.
- The overload itself — capacity is handled separately (≤10 concurrent via
  Prolific place-batching; see PRECOMPUTE_REPORT.md sizing).

## Test plan (before any live use)

1. Disposable experiment, one browser participant; verify normal completion
   unchanged (success exit, correct code).
2. Trap-failure drill (answer 3 traps wrong): must still land on the fail exit.
3. Transient-error drill: `docker stop local_minionworker_1` mid-session →
   observe retry notice → `docker start` → session continues, no duplicate
   answers in the export (check `query_id` sequence and per-query timestamps).
4. Hard-outage drill: keep worker stopped through all retries → neutral exit,
   no completion code shown.
5. Export integrity: participant list shows correct `num_trapped`,
   `participant_failed`, unbroken anchor walk.

## Companion fix 1 (elevated): backend Redis connection leak

Not a footnote — this is the bug that caused the 7-hour outage of 2026-08-21
(10:00–17:45 UTC). The backend never closes Redis connections that
`rabbitmqredis` drops; they accumulate in CLOSE_WAIT until the ephemeral port
range (~28k) is exhausted, after which **every** API call fails instantly with
`redis.exceptions.ConnectionError: Errno 99 Cannot assign requested address`.

Measured accumulation: ~28,231 sockets after the Aug-20 overload night;
~3k/hour re-accumulation under light load (5,070 after 100 idle-ish minutes;
6,160 after 3 h). This is steady-state behavior, not an overload artifact.

- **Stopgap (operational):** `docker restart local_nextbackenddocker_1` before
  each collection batch and after heavy days. The session watchdog alerts at
  15k sockets.
- **Real fix:** audit the backend's Redis client usage (`next/api/`,
  `next/broker/broker.py`, dashboard code) for per-request `StrictRedis`
  instantiation; switch to a module-level connection pool
  (`redis.ConnectionPool` + shared client) and/or set `socket_keepalive` /
  client `health_check_interval`. Verify by watching
  `/proc/net/tcp` count stay flat under a simulated participant loop.

## Companion fix 2: dashboard get_stats matplotlib incompatibility

Every `POST /dashboard/get_stats` returns HTTP 500 with
`AttributeError: 'XAxis' object has no attribute 'get_converter'` (raised in
the dashboard celery task, surfaced through `next/broker/broker.py:104` →
`next/dashboard/dashboard.py:87`). The dashboard's server-side plot code calls
a matplotlib API removed in the installed version — so the experiment
dashboard's stats panels are chronically broken (this produced the 992 errors
logged during the Aug-20 overload, and the browser's auto-retry polling of the
failing endpoint adds needless backend load whenever a dashboard tab is open).

- **Impact boundary:** plots only. Experiment list, participant exports
  (`/api/experiment/<uid>/participants`), and all participant-facing paths are
  unaffected.
- **Fix options:** update the plot code in `next/dashboard/` (and the app
  dashboard `apps/ARankB/dashboard/`) to the current matplotlib API, or pin
  `matplotlib` in the backend/worker image to the last compatible version.
  Test by loading an experiment dashboard and confirming stats panels render
  with zero 500s in `docker logs reverse_proxy`.

## Files touched when implemented

- `next/query_page/templates/query_page.html` (callbacks, exit logic, retry UI)
- `next/query_page/templates/query_page_popup.html` (same callbacks if this
  template is still used by any funnel)
- `next/query_page/static/js/next_widget.js` (pass jqXHR to `widget_failure`;
  optional getQuery retry helper)
