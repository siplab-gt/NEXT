# PR: HTTPS on siplab-next.xyz with an admin password, per-experiment protocol and short links; duplicate answers fixed

*Branch `dev` → `master`. Written 2026-11-10. Everything below already runs on the lab box
(the live checkout is on `dev`); merging only publishes it. No InfoTuple changes: question
selection is exactly `master`'s.*

## Why

1. **The dashboard and all participant data were public.** Anyone who found
   `http://52.2.236.217/dashboard/...` could list experiments, download participant data
   (Prolific IDs included), retire experiments or create new ones; the backend's own port
   8000 bypassed nginx entirely. There was also no HTTPS, which upcoming image studies
   and participant trust need.
2. **Duplicate answers corrupted data.** When a browser re-sent an answer after a dropped
   connection, the server processed it twice: the participant skipped a question, and a
   duplicated wrong trap counted twice — enough to expel someone after 2 wrong traps
   instead of 3. Reproduced first (`REPRO_DUPLICATE_ANSWER.md`); in the Nov 2026 study it
   skipped questions for 4 of 236 participants and failed nobody unfairly.

## What changed

**Duplicate answers** (`next/apps/App.py`, all apps)
- One answer per query: an atomic counter (`answer_posts`) on the query document lets
  exactly one request process an answer; any copy changes nothing, waits (≤ 120 s) for the
  original's outcome (`answer_outcome`) and returns the same result — OK, or the same
  error, so an expulsion still reaches the participant when only the copy's reply arrives.
  Copies are logged as `DUPLICATE-ANSWER` in the worker log.

**HTTPS** (domain `siplab-next.xyz` + `www`, Let's Encrypt)
- nginx config is now the folder `local/nginx/` mounted as the container's `conf.d/`
  (`next.conf` + `snippets/*.inc`). The old single-file mount kept serving a stale file
  after an editor replaced it, and the image's `default.conf` answered every hostname
  except the IP.
- Port 443: HTTP/2, TLS 1.2/1.3, **no HSTS** (it would break `protocol: http` studies).
  Renewal: `certbot.timer` + `local/certbot-deploy-hook.sh` (reloads nginx).
- Query-page templates load jQuery over `https://` (was blocked as mixed content).

**Admin password**
- Allow-list: only `snippets/participant.inc` is open — query page, `getQuery`,
  `processAnswer`, `/s/`, `/media/`, favicon. Everything else (dashboard, data downloads,
  logs, experiment creation, cAdvisor) needs HTTP basic auth over HTTPS; on port 80 those
  paths redirect to HTTPS so a password never travels unencrypted. Logins in the
  gitignored `local/nginx/admin.htpasswd` (README §3.6).
- Backend 8000 and cAdvisor 8888 bound to `127.0.0.1` in `docker-compose.yml.pre`; the
  security group closes MongoDB/Redis/RabbitMQ.
- Bare `https://siplab-next.xyz/` → experiment list.

**Per-experiment protocol and short links** (`next/site_links.py`, `next/short_links.py`)
- YAML `protocol: http | https` (default `http`; old experiments unchanged). `https`
  experiments redirect plain-HTTP visits to `https://NEXT_HTTPS_HOST`, keeping
  `?participant=`; `http` experiments are served on both schemes, never downgraded.
- YAML `link_name: rank4` → `https://siplab-next.xyz/s/rank4` (302, query string kept,
  protocol honoured). Names are unique (`app_data.short_links`); `local/relink.sh` moves
  one on purpose.
- Launch refuses `protocol: https` without working HTTPS, and a taken or malformed
  `link_name`. `launch.py` and the dashboard show the participant link and short link.
- `NEXT_HTTPS_HOST` comes from the environment or the gitignored `local/site.local.conf`.

**Operations**
- `healthcheck.sh`: probes the dashboard over HTTPS with its own login (`HEALTH_AUTH`),
  warns 20 days before the certificate expires (Let's Encrypt no longer emails).
- `docker_up.sh`: reads `site.local.conf`; `GENERATE_ONLY=1` writes `docker-compose.yml`
  without starting anything.
- Configs: neutral attention-check fail message (used in the Nov 2026 study); media
  examples use relative `/media/...` paths; `protocol` / `link_name` shown (commented) in
  the production config. `next/assistant/s3.py` builds `https://` URLs.

**Tests and tools** (`local/`, `apps/ARankB/tests/`)
- `test_duplicate_answer.py` (7 unit tests; 6 fail on the old code),
  `repro_duplicate_answer.py` (scenarios A–D), `check_https.sh` (48 checks),
  `test_https_e2e.py` (real Chrome), `wait_per_question.py` (participant wait metric),
  `capacity_ramp.sh` (`BASE=` entry point, memory sampling).

**Docs**: README §3.6 (new) + §2.3/3.2/3.3/3.4, CLAUDE.md runbook, DEV_DOCUMENTATION
(nginx/HTTPS, protocol, short links), `HTTPS_PLAN.md` (design + results),
`REPRO_DUPLICATE_ANSWER.md`, `CAPACITY_REPORT.md`, `RELEASE_NOTES.md` (v0.4.0).

## How it was verified (on `dev`, live, 2026-11-10)

| Check | Result |
|---|---|
| Duplicate answers: unit tests | 7/7 pass (6/7 fail on the old code) |
| Duplicate answers: scenarios A–D over HTTPS, with and without precompute | all correct — no skipped question, no double-counted trap, both copies report an expulsion |
| `check_https.sh dev-https dev-http` | 48/48 pass (certificate, HTTP/2, no HSTS, open participant paths, 10 admin paths 401 / 200 with password, HTTP→HTTPS redirects, protocol matrix, short links incl. relink, ports closed from outside, health check) |
| Launch refusals | taken `link_name`, malformed `link_name`, `protocol: htps` all refused |
| Real Chrome (`test_https_e2e.py`) | `http://52.2.236.217/s/dev-img?participant=…` → HTTPS page with ID kept, 32 questions to the success debrief, all images loaded over HTTP/2, no browser errors, export ids 1..32 once; `http` experiment over HTTPS not downgraded |
| Load, 20 participants over HTTPS (full 158-question production study) | 5,934 requests all 200, 18 completed + 2 expelled as designed, export PASS, **median wait 5.3 s** (Nov 2 baseline 5.6 s) |
| Load, 30 participants over HTTPS | 8,901 requests all 200, 27 + 3, export PASS, **median wait 13.6 s** — saturated (worker ~15.5/16 vCPUs); plan ≤ 20–25 with this InfoTuple code |
| Both load levels | 0 technical exits, 0 server errors, 0 CLOSE_WAIT, 0 duplicate answers, health check OK |

## Outside git (already done on the lab box; needed on any other server)

DNS A records (`@`, `www`) → server IP; security group 80/443 open, 22 from your IP only;
`sudo apt install certbot`, `/var/www/certbot`, the certificate, the deploy hook in
`/etc/letsencrypt/renewal-hooks/deploy/`; `local/site.local.conf`
(`NEXT_HTTPS_HOST=…`); `local/nginx/admin.htpasswd` (logins incl. `healthcheck`);
`HEALTH_AUTH=` in `local/alert.local.conf`. Full steps: README §3.6.

**Not yet applied on the lab box:** the `127.0.0.1` binding of ports 8000/8888 takes
effect at the next full deploy (`docker rm -f local_nextbackenddocker_1
local_minionworker_1 local_cadvisor_1`, then `./docker_up.sh 52.2.236.217`). Until then
the security group blocks both.

## Reviewing this PR

45 files, +1,856 / −133. Commits (oldest first):

```
038464c Configs: neutral attention-check fail message ("Click on this link to return to Prolific.")
3b84fda capacity_ramp.sh: sample container and host memory, report min host memory per level
2657099 Reproduce duplicate-answer bug: skipped query and double-counted wrong trap
1fa20dd processAnswer: one answer per query - duplicates wait for and replay the original's outcome
840b59a..794e34c  HTTPS plan (4 commits)
cf4d04f Query page: load jQuery over https
f028f7b nginx: config folder mount, domain names, ACME webroot, 443 published; backend/cAdvisor ports host-only
2227c33 certbot deploy hook: reload nginx after a certificate renewal
7e1248d HTTPS on siplab-next.xyz with an admin password; participant paths stay open
1732419 Per-experiment protocol (http|https) and short study links /s/<link_name>
d479eb7 Media: relative /media/ paths in config examples; S3 URLs over https
20e1095 test_https_e2e.py: real Chrome over the live domain
1396882 Docs: HTTPS, admin password, per-experiment protocol, short links
f7b24f1 nginx: bare https://<domain>/ -> /dashboard/experiment_list
1fba14f capacity_ramp.sh: BASE/HOSTHDR entry point
1f53b34 wait_per_question.py
76bb08f Capacity: 20/30 participants with the new InfoTuple scoring (Nov 9/10)
4262985 check_https.sh: 48 acceptance checks
```

`CAPACITY_REPORT.md` also records the Nov 9/10 runs of the **unmerged** InfoTuple
candidate scoring (30 participants at 0.3 s median) — results only, that code is not in
this PR.

## Next (separate PRs, on top of `dev`)

1. **InfoTuple** — branch `fix/infotuple-mi-samples` (on origin; local tip `9c36142`
   also has the memory-sampling commit already in `dev`). Sample-count bug fix (selection
   was effectively random since Mar 2025), vectorized score, candidates as distinct body
   sets (the big speed-up), tests, `sim_infotuple.py`, `REPRO_INFOTUPLE_MI.md`. Merges
   cleanly onto `dev` (trial merge 2026-11-10). Open scientific question before using it
   in a study: in simulation the fixed selector did not beat random questions.
2. **LORE** — branch `claude/lore-embedding-b0214b` (worktree
   `.claude/worktrees/lore-embedding-b0214b`), built **on top of** the InfoTuple branch:
   LORE map fitting (default for new experiments; SOE selectable), configs `d: 6`,
   `LORE_EMBEDDING.md`. Merges cleanly onto dev + InfoTuple. **Needs the worker/backend
   image rebuilt** (`cblearn==0.4.0`, `scikit-learn==1.9.1`, pulls numba) — then re-run the
   unit tests, `check_https.sh`, and `capacity_ramp.sh 20 30` with LORE on.
