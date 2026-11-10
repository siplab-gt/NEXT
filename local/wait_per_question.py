#!/usr/bin/env python3
"""
wait_per_question.py — what a participant waits per question in a load_sim run:
processAnswer latency + the following getQuery latency (CAPACITY_REPORT.md metric).

    ./local-venv/bin/python wait_per_question.py loadsim_ramp20.csv [more.csv ...] [--warmup-min=10]

Steady state excludes the first --warmup-min minutes of each run (participants start
staggered, so early questions are faster than the sustained rate).
"""
import csv, sys
from collections import defaultdict
from datetime import datetime

args = [a for a in sys.argv[1:] if not a.startswith('--')]
opts = dict(a[2:].split('=', 1) for a in sys.argv[1:] if a.startswith('--') and '=' in a)
WARMUP_S = float(opts.get('warmup-min', 10)) * 60
if not args:
    sys.exit(__doc__)


def ts(s):
    return datetime.strptime(s, '%Y-%m-%dT%H:%M:%SZ')


def pct(xs, p):
    xs = sorted(xs)
    k = max(0, min(len(xs) - 1, int(round(p / 100.0 * len(xs) + 0.5)) - 1))
    return xs[k]


for path in args:
    rows = list(csv.DictReader(open(path)))
    if not rows:
        print(path, 'empty'); continue
    t0 = min(ts(r['ts']) for r in rows)
    by_pid = defaultdict(list)
    for r in rows:
        by_pid[r['pid']].append(r)
    waits, steady = [], []
    for pid, rs in by_pid.items():
        for a, b in zip(rs, rs[1:]):
            if a['kind'] == 'processAnswer' and b['kind'] == 'getQuery' \
                    and a['outcome'] == 'ok' and b['outcome'] == 'ok':
                w = (int(a['latency_ms']) + int(b['latency_ms'])) / 1000.0
                waits.append(w)
                if (ts(a['ts']) - t0).total_seconds() >= WARMUP_S:
                    steady.append(w)
    errors = sum(1 for r in rows if r['outcome'] not in ('ok', 'expelled'))
    span = (max(ts(r['ts']) for r in rows) - t0).total_seconds() / 60
    print('{}  ({} requests, {} not ok, {:.0f} min)'.format(path, len(rows), errors, span))
    for name, xs in (('all', waits), ('steady', steady)):
        if xs:
            print('  {:6s} n={:5d}  p50={:5.2f}s  p90={:5.2f}s  p99={:5.2f}s  max={:5.1f}s'.format(
                name, len(xs), pct(xs, 50), pct(xs, 90), pct(xs, 99), max(xs)))
