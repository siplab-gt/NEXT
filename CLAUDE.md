# NEXT lab deployment — operational guide

This checkout on the lab EC2 instance IS the live deployment: the whole repo is
bind-mounted into the Docker containers. The instance has an **Elastic IP:
52.2.236.217** (stable across stop/start).

## Critical safety rules

- **Never switch git branches on this machine** (`git checkout master`, etc.) and
  never use `git add -A` / `git stash` / `git reset --hard` / `git clean`. Until
  `fix/redis-leak-and-retry` is merged, `master` still tracks the Python venv
  (`local/local-venv/`, untracked on this branch since Aug 2026) and the generated
  `local/docker-compose.yml`, so a checkout would write stale files into the live
  environment under the running containers. Work stays on the lab branch
  (`prolific-id`, or a feature branch created from it such as
  `fix/redis-leak-and-retry`) — never check out a branch with a different tree;
  merge to master only via GitHub PRs. Commit with targeted `git add <file>`.
- **Always `docker-compose` (v1, hyphen), never `docker compose` (v2).**
- **Never `docker-compose down`, `docker volume prune`, or `docker system prune
  --volumes`.** All experiment data lives in an anonymous Docker volume on the
  `local_mongodb_1` container; these commands orphan or delete it. Stop with
  `docker-compose stop`.
- **Never `docker rm local_mongodb_1`** — removing that container orphans the data
  volume. The backend/worker containers are stateless and safe to remove.
- A data collection may be live at any time — check
  `http://52.2.236.217/dashboard/experiment_list` before anything disruptive, and
  take a backup first (see below).

## Machine

The lab instance is a **burstable t2.2xlarge** (8 vCPU on paper, 3.2 guaranteed): after a
few hours of heavy load its CPU credits run out and everything slows 2–3× (the
2026-08-22 25-participant re-run failed this way; README §2.1). Capacity numbers are
only valid with a healthy credit balance — `healthcheck.sh`/`leak_monitor.sh` show
`steal %`. Plan: move to `c6i.2xlarge`/`c6i.4xlarge` (stop → change type → start; EBS
root and Elastic IP persist; then `docker start …` below).

## Starting the stack

**After an instance reboot** (only nginx auto-restarts; everything else stays down):
```bash
docker start local_mongodb_1 local_rabbitmq_1 local_rabbitmqredis_1 local_minionredis_1 local_minionworker_1 local_nextbackenddocker_1 local_cadvisor_1
```
This restarts the existing containers unchanged — no compose, no recreate bug.

**Fresh start / after new commits** — docker-compose v1 on Docker Engine 25+ throws
`KeyError: 'ContainerConfig'` when recreating containers whose config changed
(happens after every commit: the worker bakes in `GIT_HASH`; and after any host/IP
change: backend env). Remove the stateless containers first:
```bash
docker rm -f local_nextbackenddocker_1 local_minionworker_1
cd /home/ubuntu/NEXT/local && ./docker_up.sh 52.2.236.217   # run inside tmux (attached)
```
Also `docker rm -f` any hash-prefixed leftover (e.g. `5df8..._local_minionworker_1`)
shown by `docker ps -a` — that is the bug's debris.

## Launching an experiment

```bash
cd /home/ubuntu/NEXT/local && ./local-venv/bin/python launch.py ARankB-InfoTuple-cog_rank4_precompute_live.yaml
```
Configs in `local/`: **`ARankB-InfoTuple-cog_rank4_precompute.yaml` is the production
rank-4 study** (150 queries + 8 traps, one-step-ahead precompute on);
`cog_rank4_sample_base.yaml` is its 32-query demo used by every test; `cog_rank2 / 5 /
6.yaml` and `cog_tutorial.yaml` are other studies on the same Prolific standard. The
command prints the experiment UID; each launch creates a brand-new experiment (old
data is untouched).

- **⚠ Prolific completion codes live only in `*_live.yaml` configs**, which are
  gitignored (`local/*_live.yaml`) because the GitHub repo is public — the tracked
  configs carry `YOUR_SUCCESS_CODE` / `YOUR_FAILURE_CODE` / `YOUR_TECHNICAL_CODE`
  placeholders. **Launch real studies from the `_live` config**
  (`ARankB-InfoTuple-cog_rank4_precompute_live.yaml`), regenerated with
  `cd local && ./make_live.sh` from the template + `local/prolific_codes.local.txt`
  (`SUCCESS_CODE=`, `FAILURE_CODE=`, `TECHNICAL_CODE=`) — re-run it after editing the
  template; pass another template as an argument for the other studies. Never put
  real codes in a tracked file.
- **One-step-ahead precompute** (`precompute: true` in the YAML, off by default) is
  on in the production config. Monitor with
  `docker logs local_minionworker_1 2>&1 | grep PRECOMPUTE`; design and levers in
  `PRECOMPUTE_REPORT.md`, measured sizing in `CAPACITY_REPORT.md` (see "Machine").

## URLs (substitute the experiment UID)

- Experiment list: `http://52.2.236.217/dashboard/experiment_list`
- Dashboard (data downloads live here): `http://52.2.236.217/dashboard/experiment_dashboard/<EXP_UID>/ARankB`
- Participant query page: `http://52.2.236.217/query/query_page/query_page/<EXP_UID>`
  — append `?participant=<PROLIFIC_ID>` to pre-fill the ID modal (Qualtrics
  end-of-survey redirect: `?participant=${e://Field/PROLIFIC_PID}`); without it,
  participants type their ID manually. Exported `participant_uid` is prefixed
  `<EXP_UID>_`.

## Data

- Backup: `docker exec local_mongodb_1 mongodump --host 127.0.0.1 --port 27017 --out /next_backend/local/backup_$(date +%F)`
- Export per experiment: dashboard links, or `/api/experiment/<EXP_UID>/participants?zip=1` (JSON) / `?csv=1&zip=1` (CSV).
- Cleanup / orphaned-volume recovery: README §5. A ~441 MB orphaned volume with
  Oct 2025–Mar 2026 data still awaits recovery — never prune dangling volumes.

## Stability fixes (Aug 2026, branch `fix/redis-leak-and-retry`)

- The Redis connection leak behind the 2026-08-21 outage is fixed
  (`next/broker/broker.py`); `rabbitmqredis` is the stock `redis:8` image;
  gunicorn runs `-w 2 --max-requests 2000`; nginx waits 330 s (`local/nginx.conf`,
  apply with `docker exec reverse_proxy nginx -t && docker exec reverse_proxy nginx -s reload`).
  How it works and how to check it: DEV_DOCUMENTATION "System architecture" and
  §6.4; the outage itself: `REPRO_REDIS_LEAK.md`.
- The query page retries server errors and has a separate "Technical problem"
  exit, so studies need **three** Prolific completion codes — README §3.5.
- `local/healthcheck.sh` (cron every 5 min, README §3.3) probes the stack, logs
  to `local/health.log`, alerts via `WEBHOOK_URL` in `local/alert.local.conf`,
  and auto-restarts the backend on the leak signature. Check `tail -3
  local/health.log` before assuming the stack is fine.

## Code changes on the live stack

- Templates/widgets (`.html`) and `next/query_page/static/js`: live after `docker restart local_nextbackenddocker_1` (~2 s). Backend Python under `next/` is also hot-reloaded by gunicorn `--reload`.
- `apps/*/myApp.py` / algorithms: celery children re-import within ~5 tasks — run
  `python -m py_compile` inside the container before saving is considered done;
  a syntax error breaks running experiments.
- Never edit `local/docker-compose.yml` directly — it is regenerated from
  `docker-compose.yml.pre` by `docker_up.sh` (and is gitignored for that reason).

## Docs

README.md = user guide (funnel setup, completion codes §3.5, data management §5,
troubleshooting §3.2). DEV_DOCUMENTATION.md = architecture (System architecture,
Framework Contracts incl. server-error handling, trap questions, database quick
reference, test tools §6). Reports: `PRECOMPUTE_REPORT.md` (precompute design +
first load test), `REPRO_REDIS_LEAK.md` (the Aug 2026 outage, reproduced and
fixed), `CAPACITY_REPORT.md` (acceptance numbers + capacity ramp plan).
