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


class TestMutualInformation(unittest.TestCase):

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
