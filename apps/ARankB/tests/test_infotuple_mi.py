"""Correctness tests for the InfoTuple question score (mutual information).

Pure numpy, no running stack needed. Run from the repo root with the worker
image (it has numpy/scipy; the repo is mounted read-only):

    docker run --rm -v /home/ubuntu/NEXT:/next_backend:ro -w /next_backend \
        --entrypoint python local_minionworker:latest \
        -m unittest apps.ARankB.tests.test_infotuple_mi -v
"""
import math
import os
import sys
import time
import unittest
from itertools import permutations

import numpy as np
from scipy.spatial.distance import pdist

# Load utilsInfoTuple directly: importing the apps.ARankB package pulls in the
# NEXT framework, which these tests don't need.
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                '..', 'algs', 'InfoTuple'))
import utilsInfoTuple as U  # noqa: E402

MU = 0.05
N_ITEMS = 25          # production rank-4 study: 33 targets - 8 attention checks
BODY = 4              # items ranked per screen
MAX_INFO = math.log(math.factorial(BODY))   # an answer can't carry more than this


def make_case(seed=0, n=N_ITEMS):
    rs = np.random.RandomState(seed)
    X = rs.rand(n, 3)
    dist_std = np.sqrt(np.var(pdist(X)))
    others = [i for i in range(n) if i != 0]
    bodies = [list(rs.choice(others, BODY, replace=False)) for _ in range(200)]
    return X, dist_std, bodies


def score(X, body, n_samples, dist_std, seed, head=0):
    return U.mutual_information(X, head, body, n_samples, dist_std, MU,
                                np.random.RandomState(seed))


def reference_mi(X, head, body, noise, mu=MU):
    """Slow, line-by-line formula from the paper's Algorithm 1, kept separate
    from the production code: noise[s, i] is sample s's error on the distance
    head -> body[i], shared by every ordering of the body."""
    per_sample = []
    for s in range(noise.shape[0]):
        d = [np.linalg.norm(X[head] - X[body[i]]) + noise[s, i] for i in range(len(body))]
        p = np.array([U.tuple_probability_model([d[j] for j in order], mu)
                      for order in permutations(range(len(body)))])
        per_sample.append(p / p.sum())
    per_sample = np.array(per_sample)

    def entropy(q):
        return -sum(x * math.log(x) for x in q if x > 0)
    pooled = per_sample.mean(axis=0)
    return entropy(pooled) - np.mean([entropy(q) for q in per_sample])


class TestMutualInformation(unittest.TestCase):

    def test_matches_slow_reference(self):
        """The vectorized batch score equals the line-by-line formula on the
        same noise, including candidates with different heads."""
        X, dist_std, bodies = make_case(seed=5)
        rs = np.random.RandomState(7)
        heads = rs.randint(0, N_ITEMS, size=60)
        cand_bodies = [list(rs.choice([i for i in range(N_ITEMS) if i != h], BODY, replace=False))
                       for h in heads]
        for n_samples in (1, 3, 10):
            got = U.mutual_information_batch(X, heads, cand_bodies, n_samples, dist_std, MU,
                                             np.random.RandomState(11))
            noise = np.random.RandomState(11).normal(0.0, dist_std, (len(heads), n_samples, BODY))
            want = [reference_mi(X, h, b, noise[t]) for t, (h, b) in enumerate(zip(heads, cand_bodies))]
            np.testing.assert_allclose(got, want, rtol=0, atol=1e-12)

    def test_chunking_does_not_change_scores(self):
        """Scores don't depend on how candidates are split into chunks."""
        X, dist_std, bodies = make_case(seed=6)
        heads = [0] * len(bodies)
        full = U.mutual_information_batch(X, heads, bodies, 5, dist_std, MU, np.random.RandomState(3))
        saved = U.MI_CHUNK_ELEMENTS
        try:
            U.MI_CHUNK_ELEMENTS = 5 * 24 * BODY * 7       # 7 candidates per chunk
            chunked = U.mutual_information_batch(X, heads, bodies, 5, dist_std, MU,
                                                 np.random.RandomState(3))
        finally:
            U.MI_CHUNK_ELEMENTS = saved
        np.testing.assert_array_equal(full, chunked)

    def test_single_equals_batch(self):
        """Scoring one candidate at a time gives the same numbers as a batch."""
        X, dist_std, bodies = make_case(seed=8)
        batch = U.mutual_information_batch(X, [0] * 50, bodies[:50], 4, dist_std, MU,
                                           np.random.RandomState(2))
        rng = np.random.RandomState(2)
        single = [U.mutual_information(X, 0, b, 4, dist_std, MU, rng) for b in bodies[:50]]
        np.testing.assert_allclose(batch, single, rtol=0, atol=1e-15)

    def test_selector_respects_n_samples(self):
        """mi_samples reaches the score: 1 sample gives zeros, more give real scores."""
        X, _, _ = make_case(seed=9)

        def gains(n_samples):
            cands = ([0] + list(c) for c in permutations(range(1, N_ITEMS), BODY))
            return U.primal_body_selector(X, cands, np.random.RandomState(0), MU, 0.005,
                                          n_samples=n_samples)[1]
        self.assertLess(np.abs(gains(1)).max(), 1e-12)
        self.assertGreater(np.ptp(gains(20)), 1e-3)

    def test_production_size_is_fast(self):
        """A full production selection (25 items, 5% of 255,024 candidates,
        20 samples) runs in well under the precompute job's 60 s limit."""
        X, _, _ = make_case(seed=10)
        cands = ([0] + list(c) for c in permutations(range(1, N_ITEMS), BODY))
        t0 = time.time()
        _, gains, _ = U.primal_body_selector(X, cands, np.random.RandomState(0), MU, 0.05,
                                             n_samples=20)
        elapsed = time.time() - t0
        self.assertEqual(len(gains), 12752)
        self.assertLess(elapsed, 5.0)

    def test_scores_are_not_zero(self):
        """With several samples, typical questions carry real information.
        (The min(n_samples, 1) bug makes every score ~1e-15.)"""
        X, dist_std, bodies = make_case()
        s = np.array([score(X, b, 3, dist_std, seed=i) for i, b in enumerate(bodies)])
        self.assertGreater(s.max(), 1e-3)
        self.assertGreater(np.mean(s > 1e-6), 0.9)

    def test_scores_within_bounds(self):
        """0 <= score <= log(24): information can't be negative or exceed
        what a single ranking can say."""
        X, dist_std, bodies = make_case(seed=1)
        for i, b in enumerate(bodies):
            for n_samples in (1, 3, 20):
                s = score(X, b, n_samples, dist_std, seed=i)
                self.assertGreaterEqual(s, -1e-12)
                self.assertLessEqual(s, MAX_INFO + 1e-12)

    def test_no_uncertainty_means_no_information(self):
        """If the map were known exactly (no noise), asking teaches nothing."""
        X, _, bodies = make_case(seed=2)
        for i, b in enumerate(bodies[:20]):
            self.assertLess(abs(score(X, b, 5, 0.0, seed=i)), 1e-12)

    def test_more_samples_give_steadier_scores(self):
        """The score is an estimate; more samples should make it steadier
        and settle on a positive value."""
        X, dist_std, bodies = make_case(seed=3)
        b = bodies[0]
        few = [score(X, b, 4, dist_std, seed=s) for s in range(30)]
        many = [score(X, b, 40, dist_std, seed=s) for s in range(30)]
        self.assertGreater(np.mean(many), 1e-3)
        self.assertLess(np.std(many), 0.6 * np.std(few))

    def test_selector_scores_differ(self):
        """The production path (primal_body_selector, sample count from the
        item count) must give candidates different scores, otherwise its
        argmax is a pick on rounding noise."""
        X, _, _ = make_case(seed=4)
        cands = ([0] + list(c) for c in permutations(range(1, N_ITEMS), BODY))
        _, infogains, _ = U.primal_body_selector(X, cands, np.random.RandomState(0),
                                                 MU, 0.005)
        self.assertGreater(np.ptp(infogains), 1e-3)


if __name__ == '__main__':
    unittest.main()
