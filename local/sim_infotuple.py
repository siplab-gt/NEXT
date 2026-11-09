"""Offline simulation: does InfoTuple learn a participant's map better than
random questions, and which settings are worth their cost?

Runs the app's real InfoTuple code (apps/ARankB/algs/InfoTuple/myAlg.py:
burn-in, question selection, SOE map updates after every round) against an
in-memory stand-in for the database, so no stack is needed. Each fake
participant has a known "true" map and answers by sampling a ranking from the
same response model InfoTuple assumes (a best case for InfoTuple).

Settings (see SETTINGS): random questions are run as the app runs them, by
making every round burn-in.

Score: after each round, the fraction of held-out comparisons "is i or j more
similar to h?" on which the learned map agrees with the true map.

Truth maps: a JSON list of 25x3 lists (e.g. fitted maps of real participants,
extracted from a backup; keep that file out of the repo).

Run with the worker image, repo read-only, output dir writable:
    docker run --rm -v /home/ubuntu/NEXT:/next_backend:ro -v OUT:/out \
      -w /next_backend --entrypoint python local_minionworker:latest -B \
      local/sim_infotuple.py --truth /out/truth.json --out /out/results.jsonl --procs 14
    ... local/sim_infotuple.py --summarize /out/results.jsonl
"""
import argparse
import json
import os
import sys
import time
from itertools import permutations

os.environ.setdefault('OMP_NUM_THREADS', '1')
os.environ.setdefault('OPENBLAS_NUM_THREADS', '1')
os.environ.setdefault('MKL_NUM_THREADS', '1')

import numpy as np  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

# Production rank-4 study (local/ARankB-InfoTuple-cog_rank4_precompute.yaml)
A = B = 4
D = 3
ROUNDS = 6            # burn_in 1 + 5 adaptive rounds = 150 questions for 25 items
BURN_IN = 1
MU = 0.05

SETTINGS = {
    # name: (burn_in, mi_samples, down_sample)
    'random':       (ROUNDS, None, 0.05),
    'bug_1sample':  (BURN_IN, 1, 0.05),
    's3_ds0.05':    (BURN_IN, 3, 0.05),
    's20_ds0.05':   (BURN_IN, 20, 0.05),
    's50_ds0.05':   (BURN_IN, 50, 0.05),
    's20_ds0.25':   (BURN_IN, 20, 0.25),
    's20_ds1':      (BURN_IN, 20, 1.0),
}
COST_ORDER = ['s20_ds1', 's20_ds0.25', 's50_ds0.05', 's20_ds0.05', 's3_ds0.05',
              'bug_1sample', 'random']


class _Store:
    """Minimal stand-in for butler.algorithms / butler.participants."""

    def __init__(self):
        self.d = {}

    def _k(self, uid, key):
        return (uid, key)

    def get(self, uid=None, key=None):
        if isinstance(key, list):
            return {k: self.d.get(self._k(uid, k)) for k in key}
        return self.d.get(self._k(uid, key))

    def set(self, uid=None, key=None, value=None):
        self.d[self._k(uid, key)] = value

    def exists(self, uid=None, key=None):
        return self._k(uid, key) in self.d

    def increment(self, uid=None, key=None, value=1):
        self.d[self._k(uid, key)] = self.d.get(self._k(uid, key), 0) + value
        return self.d[self._k(uid, key)]

    def append(self, uid=None, key=None, value=None):
        self.d.setdefault(self._k(uid, key), []).append(value)

    def get_and_delete(self, uid=None, key=None):
        return self.d.pop(self._k(uid, key), None)


class FakeButler:
    def __init__(self):
        self.algorithms = _Store()
        self.participants = _Store()
        self.alg_id = self.alg_label = 'InfoTuple'
        self.exp_uid = 'sim'
        self.app_id = 'ARankB'

    def job(self, *args, **kwargs):     # full_embedding_update: not needed here
        pass


def sample_ranking(true_X, tup, rng, response='model'):
    """Participant's answer, closest first: drawn from InfoTuple's response
    model on the true distances ('model'), or the exact true order ('exact')."""
    from apps.ARankB.algs.InfoTuple import utilsInfoTuple as U
    head, body = tup[0], tup[1:]
    dist = [np.linalg.norm(true_X[head] - true_X[b]) for b in body]
    if response == 'exact':
        return [head] + [int(body[j]) for j in np.argsort(dist)]
    orders = list(permutations(range(len(body))))
    p = np.array([U.tuple_probability_model([dist[j] for j in o], MU) for o in orders])
    o = orders[rng.choice(len(orders), p=p / p.sum())]
    return [head] + [int(body[j]) for j in o]


def heldout_triplets(n, rng, count=20000):
    t = np.array([rng.choice(n, 3, replace=False) for _ in range(count)])
    return t


def agreement(X_est, X_true, trip):
    def side(X):
        X = np.asarray(X)
        return np.sign(np.linalg.norm(X[trip[:, 0]] - X[trip[:, 1]], axis=1)
                       - np.linalg.norm(X[trip[:, 0]] - X[trip[:, 2]], axis=1))
    return float(np.mean(side(X_est) == side(X_true)))


def run_one(job):
    pidx, setting, true_X, response = job
    from apps.ARankB.algs.InfoTuple.myAlg import MyAlg
    true_X = np.asarray(true_X)
    n = true_X.shape[0]
    burn_in, mi_samples, down_sample = SETTINGS[setting]
    butler = FakeButler()
    alg = MyAlg()
    alg.initExp(butler, A, B, n, D, random_seed=1000 + pidx, failure_probability=0.01,
                iteration=ROUNDS - 1, burn_in=burn_in, down_sample=down_sample, mu=MU,
                debug=False, setTrap=False, expel=False, tolerance=0.3, trapRatio=0.0,
                num_trap_questions=0, mi_samples=mi_samples)
    answer_rng = np.random.RandomState(5000 + pidx)    # same answer stream per participant
    trip = heldout_triplets(n, np.random.RandomState(9000 + pidx))
    uid = 'p%d' % pidx
    curve, select_s = [], 0.0
    counts = np.zeros(n)
    exact_answers = 0
    for r in range(ROUNDS):
        for _ in range(n):
            t0 = time.time()
            tup = alg.getQuery(butler, uid)
            select_s += time.time() - t0
            ans = sample_ranking(true_X, tup, answer_rng, response)
            exact_answers += ans == sample_ranking(true_X, tup, None, 'exact')
            counts[tup[1:]] += 1
            alg.processAnswer(butler, ans, uid, False)
        curve.append(agreement(butler.participants.get(uid, 'embedding'), true_X, trip))
    return {'participant': pidx, 'setting': setting, 'response': response,
            'agreement_by_round': curve, 'getQuery_seconds_total': round(select_s, 2),
            'answers_fully_correct': exact_answers / float(ROUNDS * n),
            'body_appearances_min_max': [int(counts.min()), int(counts.max())]}


def summarize(path):
    rows = [json.loads(l) for l in open(path)]
    by = {}
    for r in rows:
        by.setdefault(r['setting'], {})[r['participant']] = r
    base = by.get('random', {})
    print('%-12s %3s  %-38s %-22s %s' % ('setting', 'n', 'agreement after round 1..6 (mean)',
                                           'final vs random (paired)', 's per question'))
    for s in SETTINGS:
        if s not in by:
            continue
        rs = by[s]
        curve = np.mean([r['agreement_by_round'] for r in rs.values()], axis=0)
        common = [p for p in rs if p in base]
        diff = np.array([rs[p]['agreement_by_round'][-1] - base[p]['agreement_by_round'][-1]
                         for p in common])
        se = diff.std(ddof=1) / np.sqrt(len(diff)) if len(diff) > 1 else float('nan')
        wins = int(np.sum(diff > 0))
        perq = np.mean([r['getQuery_seconds_total'] for r in rs.values()]) / (ROUNDS * 25)
        cov = np.mean([r.get('body_appearances_min_max', [np.nan, np.nan]) for r in rs.values()], axis=0)
        exact = np.mean([r.get('answers_fully_correct', np.nan) for r in rs.values()])
        print('%-12s %3d  %-38s %+.4f ± %.4f (%2d/%2d up) %.3f   item appears %4.1f..%4.1f times; %.0f%% answers exactly right' % (
            s, len(rs), ' '.join('%.3f' % c for c in curve), diff.mean() if len(diff) else 0,
            se, wins, len(diff), perq, cov[0], cov[1], 100 * exact))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--truth')
    ap.add_argument('--out')
    ap.add_argument('--procs', type=int, default=1)
    ap.add_argument('--settings', default=','.join(COST_ORDER))
    ap.add_argument('--response', choices=['model', 'exact'], default='model')
    ap.add_argument('--participants', type=int, default=None, help='use only the first N truth maps')
    ap.add_argument('--summarize')
    a = ap.parse_args()
    if a.summarize:
        return summarize(a.summarize)
    truths = json.load(open(a.truth))[:a.participants]
    settings = a.settings.split(',')
    done = set()
    if os.path.exists(a.out):
        done = {(r['participant'], r['setting']) for r in map(json.loads, open(a.out))}
    jobs = [(p, s, truths[p], a.response) for s in settings for p in range(len(truths)) if (p, s) not in done]
    print('%d jobs (%d already done)' % (len(jobs), len(done)), flush=True)
    import multiprocessing as mp
    with mp.Pool(a.procs) as pool, open(a.out, 'a') as f:
        for i, r in enumerate(pool.imap_unordered(run_one, jobs), 1):
            f.write(json.dumps(r) + '\n')
            f.flush()
            print('%d/%d %s p%d final=%.3f' % (i, len(jobs), r['setting'], r['participant'],
                                              r['agreement_by_round'][-1]), flush=True)


if __name__ == '__main__':
    main()
