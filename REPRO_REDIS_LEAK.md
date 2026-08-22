# Reproducing the backend Redis connection leak (the 2026-08-21 outage)

*Branch `fix/redis-leak-and-retry`. Reproduced 2026-08-22 00:00 UTC on unchanged code
(commit `a545ee6`, i.e. the code that ran the Aug 20–21 collection).*

## The outage we are reproducing

On 2026-08-21 from ~10:00 to 17:45 UTC every participant request failed instantly with

```
redis.exceptions.ConnectionError: Error 99 connecting to rabbitmqredis:6379. Cannot assign requested address.
OSError: [Errno 99] Cannot assign requested address
```

The backend container held **28,271 TCP sockets to rabbitmqredis:6379, 28,230 of them in
CLOSE_WAIT** (peer closed, backend never did). With the ephemeral port range exhausted no
new connection to Redis could be opened, so `getQuery`/`processAnswer` 500'd for 7 hours.
A `docker restart` of the backend cleared it (sockets → ~30) and the count started
climbing again immediately (~3k/hour).

## Mechanism (verified read-only before reproducing)

1. Under gunicorn+gevent, celery's `app.backend` is greenlet-local, so **every HTTP request
   builds its own result backend + a drainer greenlet that is never stopped** — ~2 sockets
   to Redis per request that stay open after the response is sent.
2. The `rabbitmqredis` container runs a cron (`next/database/redis/Dockerfile:15`,
   `cleanup_idle_redis_connections.sh`) that `CLIENT KILL`s any client idle ≥ 300 s. Its own
   log: **56,678 kills of backend (172.18.0.7) connections in 24 h** (~200 per 5-min cycle).
3. Redis closes its side; the backend never notices → **CLOSE_WAIT forever**. When a request
   does touch a killed pubsub connection, celery's `_reconnect_pubsub()` drops it without
   closing and calls `connection_pool.reset()`, which in redis-py 5 orphans the pool's
   sockets and zeroes its counter — so nothing bounds the growth.

## Reproduction protocol (≈10 min, disposable experiment, no real data touched)

Tools (committed): `local/leak_monitor.sh`, `local/load_sim.py`.

```bash
cd /home/ubuntu/NEXT/local
./local-venv/bin/python launch.py ARankB-InfoTuple-cog_rank4_sample_base.yaml   # -> EXP
docker restart local_nextbackenddocker_1                                          # clean baseline
./leak_monitor.sh 10 > leak_repro.csv &                                           # instrument

# Part 1 — per-request hoarding
./local-venv/bin/python load_sim.py --base http://127.0.0.1 --host-header 52.2.236.217 \
    --exp EXP --participants 5 --think 1,2 --max-queries 10 --tag repro --quiet

# Part 2 — the cron's effect, on demand
docker exec local_rabbitmqredis_1 redis-cli CLIENT KILL TYPE normal SKIPME yes

# Part 3 — force the port exhaustion in minutes instead of a day
PID=$(docker inspect -f '{{.State.Pid}}' local_nextbackenddocker_1)
sudo nsenter -t $PID -n sysctl -w net.ipv4.ip_local_port_range="40000 40160"
./local-venv/bin/python load_sim.py ... --participants 5 --max-queries 8 --no-retry --tag repro2
docker exec local_rabbitmqredis_1 redis-cli CLIENT KILL TYPE normal SKIPME yes
./local-venv/bin/python load_sim.py ... --participants 5 --max-queries 6 --no-retry --tag repro3
docker exec local_rabbitmqredis_1 redis-cli CLIENT KILL TYPE normal SKIPME yes
curl -s -X POST -H 'Content-Type: application/json' -H 'Host: 52.2.236.217' \
     -d '{"exp_uid":"EXP","args":{"participant_uid":"probe1","widget":false}}' \
     http://127.0.0.1/api/experiment/getQuery -o /dev/null -w '%{http_code}\n'

# Recover
sudo nsenter -t $PID -n sysctl -w net.ipv4.ip_local_port_range="32768 60999"
docker restart local_nextbackenddocker_1
```

Socket counts: `docker exec local_nextbackenddocker_1 awk 'NR>1{split($3,a,":"); if(a[2]=="18EB") s[$4]++} END{for(k in s) print k, s[k]}' /proc/net/tcp`
(state `01` = ESTABLISHED, `08` = CLOSE_WAIT; `18EB` = port 6379).

## Results on unchanged code (BEFORE the fix)

| Step | Requests | Sockets to :6379 (backend) | Redis `connected_clients` | Notes |
|---|---|---|---|---|
| fresh restart | 0 | 0 | 1 | baseline |
| Part 1: 5 participants × 10 queries | 105 | **212 ESTABLISHED**, still open 20 s after load ended | 216 | ≈ 2 sockets per request, never released |
| Part 2: `CLIENT KILL` | 0 | **212 CLOSE_WAIT**, 0 ESTABLISHED | 1 | the cron's effect: zombies the backend never closes |
| Part 3a: port range 40000–40160, 5 × 8 queries | 81 | 194 CLOSE_WAIT + **161 ESTABLISHED** (range full) | — | **2 × HTTP 500**, backend log: `Error 99 connecting to rabbitmqredis:6379. Cannot assign requested address` |
| Part 3b: kill, 5 × 6 queries | 14 | 330 CLOSE_WAIT + 7 | — | 5 × HTTP 500 (Errno 99) |
| Part 3c: kill, 5 fresh getQuery probes | 5 | **354 CLOSE_WAIT**, 1 ESTABLISHED | 1 | **5/5 probes → HTTP 500**; 46 `Errno 99` lines in the backend log |
| restart backend | — | 0 | 1 | probe → HTTP 200 |

Monitor trace (`leak_repro.csv`, 10 s samples): `est` rises 0 → 46 → 98 → 134 → 186 → 212
during Part 1 and stays at 212 after the load stops. Load-sim latency during Part 1 (no
precompute, 5 concurrent InfoTuple selections on this t2.2xlarge): getQuery p50 8.2 s,
p95 19.6 s; processAnswer p50 2.3 s.

This is the Aug-21 failure end to end: request-level hoarding → cron kills → CLOSE_WAIT
zombies → port exhaustion → `Errno 99` → every request 500. The narrow port range only
compresses the timeline (160 ports instead of ~28k); the mechanism and the error are
identical.

## What the fix turned out to be (deeper than the mechanism sketch above)

Instrumenting the broker path inside the container (`local/diag_result_backend.py`)
showed the per-request sockets are **celery's, created for every HTTP request**:

1. celery stores `app.backend` in `threading.local` unless `result_backend_thread_safe`
   is set (`celery/app/base.py`, `_backend` property). Under gunicorn's gevent worker
   that is *greenlet-local* → one `RedisBackend` per request, each with its own redis
   client pool, pubsub subscription and a drainer greenlet that never stops. The
   drainer keeps the object graph alive, so the 2 sockets (pubsub + `GET`) outlive the
   request. (A standalone sequential process reuses one greenlet and shows no leak,
   which is why this was easy to miss.)
2. The "obvious" fix, `result_backend_thread_safe=True` (one shared backend), **hangs
   under gevent**: 8 concurrent waiters never received results the worker had already
   produced. Rejected.
3. Releasing the greenlet's backend after each call (kill drainer, close pubsub,
   disconnect pool, drop the local reference) fixed the `GET` socket but pubsub
   connections still leaked under concurrency — because `AsyncResult.__del__` →
   `remove_pending_result` → `cancel_for` → `pubsub.unsubscribe()` makes redis-py open
   a **brand-new connection just to send UNSUBSCRIBE** on the closed PubSub. Clearing
   `_pubsub` after closing it, and detaching the result from the backend, closed that.

Fix commits: `6faff20` (broker teardown), `4c1ffe4` (remove the CLIENT KILL cron; plain
`redis:8` image), `49d3138` (celery settings actually in effect), `e753380` (gunicorn
`-w 2 --max-requests`, nginx 330 s timeouts), `5c6f3cc` (hygiene).

## Results AFTER the fix (same protocol, same throwaway experiment)

In-process regression (`diag_result_backend.py`, 40 calls at concurrency 8):
**8 sockets after warm-up, 8 at the end — FLAT** (all eight are the bounded JobBroker
pool connections, same age throughout).

Through nginx against the live gunicorn backend (code fix only; the cron-less Redis
image and gunicorn flags still need the container recreate):

| Step | Requests | Sockets to :6379 (backend) | HTTP | Notes |
|---|---|---|---|---|
| Part 1: 5 × 10 queries | 105 | **2 ESTABLISHED** + 28 TIME_WAIT (properly closed, drained in 60 s) | 105 × 200 | was 212 hoarded forever |
| Part 2: `CLIENT KILL` | — | 2 CLOSE_WAIT (the pool; self-heals on next use) | — | was 212 zombies |
| Part 3a: port range 40000–40160, 5 × 8 | 85 | 2 ESTABLISHED + TIME_WAIT | **85 × 200, 0 × 500** | was 2 × 500 / Errno 99 |
| Part 3b: kill, 5 × 6 | 65 | 2 ESTABLISHED | **65 × 200** | was 5 × 500 |
| Part 3c: kill, 5 probes | 5 | 1 ESTABLISHED, 1 CLOSE_WAIT | **5/5 × 200** | was 5/5 × 500 |
| `Errno 99` in backend log | | | **0** | was 46 |

The narrow port range that previously produced total failure cannot be exhausted any
more: connections are closed when the request ends instead of hoarded.

Rebuilt-stack acceptance (cron-less `redis:8`, gunicorn `-w 2`): 10-participant load
(2,407 requests, all 200, 0 CLOSE_WAIT, 0 sockets 60 s after), 2 h idle soak (0 sockets,
0 errors, RSS flat), 25 simultaneous participants (7,519 requests, all 200, 0 CLOSE_WAIT).
Details in `CAPACITY_REPORT.md`.
