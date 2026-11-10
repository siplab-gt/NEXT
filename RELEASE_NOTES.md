# Release notes

## v0.4.0 — HTTPS, admin password, short study links; duplicate answers fixed (2026-11-10)

*Branch `dev`, PR to `master` pending (`PR_NOTES.md`). Builds on v0.3.0. Question
selection (InfoTuple) is unchanged.*

### Fixed

- **Duplicate answers no longer skip questions or double-count traps.** A browser that
  re-sent an answer after a dropped connection made the server process it twice: the next
  question was skipped and a wrong trap could count twice (early expulsion). Now exactly
  one copy is processed; the others wait and return the same result
  (`REPRO_DUPLICATE_ANSWER.md`).

### Added

- **HTTPS** at `https://siplab-next.xyz` (Let's Encrypt, renewed automatically; the health
  check warns 20 days before expiry).
- **Admin password**: the dashboard, data downloads, logs and experiment creation need a
  login, over HTTPS only. Participants never see a password (README §3.6).
- **Per-experiment `protocol: http | https`** (default `http`): HTTPS studies redirect
  plain-HTTP visits, keeping `?participant=`. Launch fails if HTTPS isn't working.
- **Short study links**: `link_name: rank4` → `https://siplab-next.xyz/s/rank4`; names
  are unique, `local/relink.sh` moves one on purpose.
- `launch.py` and the dashboard print the participant link to paste into Prolific.
- Test tools: `check_https.sh`, `test_https_e2e.py`, `repro_duplicate_answer.py`,
  `wait_per_question.py`; unit tests `test_duplicate_answer.py`.

### Changed

- nginx config is the folder `local/nginx/` (was `local/nginx.conf`); the backend (8000)
  and cAdvisor (8888) answer on the server only.
- Configs: neutral attention-check fail message; media examples use relative `/media/...`
  paths.

### Measured (`CAPACITY_REPORT.md`)

- 20 simultaneous participants over HTTPS: median wait 5.3 s (unchanged from v0.3.0);
  30: 13.6 s — the machine is saturated, plan for ≤ 20–25 with this InfoTuple code.

### Upgrading an existing deployment

Everything outside git is listed in `PR_NOTES.md` ("Outside git") and README §3.6:
DNS, security group, certbot + certificate + deploy hook, `local/site.local.conf`,
`local/nginx/admin.htpasswd`, `HEALTH_AUTH`. Then recreate nginx
(`GENERATE_ONLY=1 ./docker_up.sh <IP>`, `docker rm -f reverse_proxy`,
`docker-compose up -d nginx`) and, at the next full deploy, the backend and cAdvisor.

## v0.3.0 — Reliability under load, honest participant exits, alerting (2026-08-23)

*Merged as PR #4 (`4f9a0f5`). Builds on v0.2.0 (Prolific flow, flexible traps, trap
exports, one-step-ahead precompute).*

### Why this release exists

The August 2026 rank-4 Prolific study hit two platform bugs at once: a backend
connection leak took the server down for seven hours, and the participant page showed
every server error as a failed attention check — so dozens of honest participants were
labelled "FAILED ATTENTION CHECKS" on Prolific. This release fixes both, adds the
monitoring that would have caught the outage in five minutes instead of seven hours,
and documents how to size the machine.

### Fixed

- **Backend Redis connection leak (the outage).** Under gunicorn's gevent worker,
  celery created a separate result backend for every HTTP request and never released
  it; each request pinned two sockets to the Redis result store until the machine ran
  out of ports (`Error 99 connecting to rabbitmqredis:6379`). The backend now releases
  each request's result backend after the call. The custom Redis image whose cron
  "cleaned up" idle connections (and turned them into zombies) is replaced by the stock
  `redis:8` image. Reproduced on demand and re-proved after the fix: `REPRO_REDIS_LEAK.md`.
- **Server errors no longer look like failed attention checks.** The query page
  retries a failed server call automatically (visible countdown, "Retry now" button,
  delays 5/15/30 s) and, if retries run out, shows a separate "Technical problem"
  screen with its own Prolific link. Only a genuine attention-check expulsion reaches
  the fail exit. An interrupted answer is never re-sent, so nothing is double-counted.
- **Expulsions are explicit.** `processAnswer` answers `200 {meta.expelled: true}`
  instead of an anonymous HTML 500, so the page can tell a real expulsion from an outage.
- **The expelling trap answer is now stored.** The wrong trap that expels a participant
  used to be missing from the export (the app raised before the write).
- **Dashboard graphs work again** (mpld3 / matplotlib version mismatch).
- **Celery settings that were silently ignored** (result expiry, serializers) now apply;
  results expire after 1 h instead of 1 day.
- nginx waits 330 s for slow answers (was 60 s) so a slow-but-successful query is no
  longer reported as a failure while it is still being recorded; gunicorn runs two
  workers with periodic recycling.

### Added

- **Three completion codes per study.** New experiment fields `retry_attempts`
  (default 3), `debrief_error` and `debrief_link_error` (README §3.5). Existing configs
  and running experiments keep working — the fields have defaults.
- **Health check with alerts** (`local/healthcheck.sh`, cron every 5 min): probes the
  whole request path, counts dead sockets, checks containers, nginx 5xx, load and CPU
  steal; logs to `local/health.log`, posts to a webhook on state change, and restarts
  the stateless backend automatically on the leak signature (README §3.3).
- **`local/make_live.sh`**: builds the gitignored `_live` launch configs (real Prolific
  codes) from the tracked templates + `prolific_codes.local.txt`, so templates are
  versioned and codes never enter git.
- **Test tools** in `local/`: `load_sim.py` (simulated participants over HTTP),
  `check_export.py` (export integrity / double-record detector), `leak_monitor.sh`,
  `diag_result_backend.py` (leak regression), `test_query_page_retry.py` (browser
  scenarios with `--screenshots`), `acceptance_driver.sh`, `integration_driver.sh`,
  `capacity_ramp.sh`.
- **Reports**: `REPRO_REDIS_LEAK.md` (the outage, reproduced and fixed),
  `CAPACITY_REPORT.md` (acceptance runs and the capacity ramp).
- **Docs**: README (§3.2 troubleshooting, §3.3 monitoring, §3.5 exits with screenshots,
  §2.1 instance sizing), DEV_DOCUMENTATION (lifecycle and architecture diagrams now
  include Redis and the error path; a "Server-error handling" contract; test tools §6),
  CLAUDE.md runbook.

### Changed

- Launch configs: `ARankB-InfoTuple-cog_rank4_precompute.yaml` is the production rank-4
  config and `cog_rank4_sample_base.yaml` the test config; the one-flag twins
  (`cog_rank4.yaml`, `cog_rank4_sample_pre.yaml`) are gone; rank2/5/6/tutorial use the
  same Prolific placeholder links and wording.
- `local/local-venv/` and the generated `local/docker-compose.yml` are no longer
  tracked (create the venv from `local/requirements.txt`, README §2.3).
- Debrief texts: the fail message now says attention checks were not passed instead of
  repeating the success text.

### Measured (see `CAPACITY_REPORT.md`)

- Leak fix: 105 requests left 212 hoarded sockets before, 2 after; with the port range
  squeezed and the old cron's kills replayed, the fixed backend served every request
  (the old one failed completely).
- On 8 real cores (`c6i.2xlarge`): reliable up to 60 simultaneous participants with
  zero errors; comfortable at 10–15, ~15 s median waits at 25, ~30 s at 60. Burstable
  `t2`/`t3` instances are not suitable for collection days (README §2.1).

### Upgrading an existing deployment

1. `docker pull redis:8`; `docker rm -f local_nextbackenddocker_1 local_minionworker_1 local_rabbitmqredis_1` (never the mongodb container); `cd local && ./docker_up.sh <PUBLIC_IP>`; `docker exec reverse_proxy nginx -s reload`.
2. Create a venv from `local/requirements.txt` if you relied on the tracked one.
3. Create a third Prolific completion code ("technical issue"), put all three codes in `local/prolific_codes.local.txt`, run `./make_live.sh`.
4. Install the health check: `*/5 * * * * /path/to/NEXT/local/healthcheck.sh` in `crontab -e`; optional `WEBHOOK_URL=` in `local/alert.local.conf`.
5. Prefer a non-burstable instance (`c6i.2xlarge` or larger) for data collection.

## Earlier releases

- **v0.2.0** (2026-08-12) — Prolific flow, flexible traps, trap exports, one-step-ahead InfoTuple precompute (PR #3).
- **v0.1.3** (2026-08-04) — Prolific ID linking, refresh-proof sessions, deceptive trap questions (PR #2).
- **v0.1.2** (2025-08-27) — PAQ development merge (PR #1).
- **v0.1.1** (2025-04-04) — documentation update.
