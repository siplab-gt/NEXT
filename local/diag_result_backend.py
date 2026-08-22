#!/usr/bin/env python3
"""
diag_result_backend.py — run INSIDE the backend container to measure how many Redis
sockets one process leaks per broker call, and why.

    docker exec -i local_nextbackenddocker_1 python /next_backend/local/diag_result_backend.py EXP_UID [N]

It gevent-monkeypatches (like gunicorn --worker-class=gevent), then calls
JobBroker.applyAsync('ARankB', EXP, 'getQuery', ...) N times (N disposable participant
ids) and after each call reports: sockets THIS process holds to port 6379 by state,
whether celery's ResultConsumer reconnected its pubsub, and which exception caused it.

Exit status 0 if the socket count is flat (<= baseline + 3) after the loop, 1 otherwise.
"""
import os, sys, json, time, traceback

from gevent import monkey; monkey.patch_all()   # same environment as gunicorn gevent worker

EXP = sys.argv[1] if len(sys.argv) > 1 else None
N = int(sys.argv[2]) if len(sys.argv) > 2 else 10
K = int(sys.argv[3]) if len(sys.argv) > 3 else 1     # concurrent greenlets (gunicorn serves requests concurrently)
if not EXP:
    sys.exit(__doc__)

def my_sockets():
    """sockets held by this process to remote port 6379, as {state: count}."""
    inodes = set()
    for fd in os.listdir('/proc/self/fd'):
        try:
            l = os.readlink('/proc/self/fd/' + fd)
        except OSError:
            continue
        if l.startswith('socket:['):
            inodes.add(l[8:-1])
    out = {}
    with open('/proc/net/tcp') as f:
        next(f)
        for line in f:
            p = line.split()
            if p[9] in inodes and p[2].split(':')[1] == '18EB':
                out[p[3]] = out.get(p[3], 0) + 1
    return out

from next.broker import broker as brokermod
from celery.backends import redis as rb

if os.environ.get('DIAG_THREAD_SAFE'):
    # candidate fix A: one backend shared by all greenlets instead of one per greenlet
    brokermod.app.conf.result_backend_thread_safe = True
    print("DIAG_THREAD_SAFE=1 -> result_backend_thread_safe=True", flush=True)

# --- instrument celery's reconnect path ---
counters = {'reconnect': 0, 'errors': []}
_orig_reconnect = rb.ResultConsumer._reconnect_pubsub
def _patched_reconnect(self):
    counters['reconnect'] += 1
    counters['errors'].append(traceback.format_exc(limit=3).strip().splitlines()[-1] if sys.exc_info()[0] else '(no active exception)')
    return _orig_reconnect(self)
rb.ResultConsumer._reconnect_pubsub = _patched_reconnect

jb = brokermod.JobBroker()
base = my_sockets()
print("baseline sockets to :6379:", base, flush=True)

import gevent
def one_call(i):
    pid = "diag%d_%d" % (os.getpid(), i)
    args = json.dumps({"exp_uid": EXP, "args": {"participant_uid": EXP + "_" + pid, "widget": False}})
    t0 = time.time()
    try:
        out = jb.applyAsync('ARankB', EXP, 'getQuery', args)
        ok = 'ok' if out and out[1] else 'app-fail'
    except Exception as e:
        ok = 'EXC ' + type(e).__name__ + ': ' + str(e)[:60]
    rc = getattr(brokermod.app.backend, 'result_consumer', None)
    ps = getattr(rc, '_pubsub', None)
    print("call %2d: %-8s %.1fs  sockets=%s  reconnects=%d  pubsub_id=%s conn_id=%s" % (
        i + 1, ok, time.time() - t0, my_sockets(), counters['reconnect'],
        hex(id(ps)) if ps else None, hex(id(ps.connection)) if ps and ps.connection else None), flush=True)

print("running %d calls with concurrency %d" % (N, K), flush=True)
warm = None
for start in range(0, N, K):
    gevent.joinall([gevent.spawn(one_call, i) for i in range(start, min(start + K, N))])
    if warm is None:
        time.sleep(1)
        warm = sum(my_sockets().values())   # after the first batch: pools are warm
        print("after first batch (warm pools): %d sockets" % warm, flush=True)

time.sleep(2)
final = my_sockets()
# Identify leftover sockets from Redis's side (what was their last command?)
try:
    import redis as _r, next.constants as _c
    inodes = set()
    for fd in os.listdir('/proc/self/fd'):
        try: l = os.readlink('/proc/self/fd/' + fd)
        except OSError: continue
        if l.startswith('socket:['): inodes.add(l[8:-1])
    my_ports = {}
    with open('/proc/net/tcp') as f:
        next(f)
        for line in f:
            q = line.split()
            if q[9] in inodes and q[2].split(':')[1] == '18EB':
                my_ports[int(q[1].split(':')[1], 16)] = q[3]
    cl = _r.Redis(host=_c.RABBITREDIS_HOSTNAME, port=_c.RABBITREDIS_PORT).client_list()
    seen = set()
    for c in cl:
        port = int(c['addr'].rsplit(':', 1)[1])
        if port in my_ports:
            seen.add(port)
            print("  leftover port %d state=%s  cmd=%s sub=%s age=%ss flags=%s" % (port, my_ports[port], c.get('cmd'), c.get('sub'), c.get('age'), c.get('flags')))
    for port, st in my_ports.items():
        if port not in seen:
            print("  leftover port %d state=%s  (not known to redis -> dead/CLOSE_WAIT)" % (port, st))
except Exception as e:
    print("  (client_list failed: %s)" % e)
print("final sockets to :6379:", final)
print("reconnect count:", counters['reconnect'])
for e in counters['errors'][:5]:
    print("  reconnect cause:", e)
total = sum(final.values()); btotal = sum(base.values())
# Pass = no growth after the first batch (bounded connection pools are expected:
# one JobBroker pool connection per concurrent caller, max 10).
grew = total - (warm if warm is not None else btotal)
print("RESULT:", "FLAT (leak fixed): %d sockets after warm-up, %d at the end over %d calls" % (warm, total, N)
      if grew <= 1 else "LEAKING (+%d sockets after warm-up over %d calls)" % (grew, N))
sys.exit(0 if grew <= 1 else 1)
