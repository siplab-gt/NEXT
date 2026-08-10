# NEXT lab deployment — operational guide

This checkout on the lab EC2 instance IS the live deployment: the whole repo is
bind-mounted into the Docker containers. The instance has an **Elastic IP:
52.2.236.217** (stable across stop/start).

## Critical safety rules

- **Never switch git branches on this machine** (`git checkout master`, etc.) and
  never use `git add -A` / `git stash` / `git reset --hard` / `git clean`. The repo
  tracks the Python venv (`local/local-venv/`), so those commands rewrite the live
  environment under the running containers. Work stays on the `prolific-id` branch;
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
cd /home/ubuntu/NEXT/local && ./local-venv/bin/python launch.py ARankB-InfoTuple-cog_rank4.yaml
```
Lab configs: `ARankB-InfoTuple-cog_rank{2,4,5,6}.yaml` and `cog_tutorial.yaml` in
`local/`. The command prints the experiment UID; each launch creates a brand-new
experiment (old data is untouched).

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

## Code changes on the live stack

- Templates/widgets (`.html`): live after `docker restart local_nextbackenddocker_1` (~2 s).
- `apps/*/myApp.py` / algorithms: celery children re-import within ~5 tasks — run
  `python -m py_compile` inside the container before saving is considered done;
  a syntax error breaks running experiments.
- Never edit `local/docker-compose.yml` directly — it is regenerated from
  `docker-compose.yml.pre` by `docker_up.sh`.

## Docs

README.md = user guide (funnel setup, data management §5, troubleshooting §3.2).
DEV_DOCUMENTATION.md = architecture (Framework Contracts, trap questions, database
quick reference, diagrams).
