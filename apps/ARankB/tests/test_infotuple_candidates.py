"""Correctness tests for InfoTuple candidate generation: each body is a SET
(a combination, not a permutation), each set is scored at most once, the
chosen body is shown in random order, and the experiment's saved random
state advances exactly as the code says.

Run from the repo root with the worker image (it has numpy/scipy and the NEXT
framework; the repo is mounted read-only):

    docker run --rm -v /home/ubuntu/NEXT:/next_backend:ro -w /next_backend \
        --entrypoint python local_minionworker:latest \
        -m unittest apps.ARankB.tests.test_infotuple_candidates -v
"""
import json
import math
import os
import sys
import time
import unittest
from itertools import combinations, permutations

import numpy as np
from scipy.stats import chisquare

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 'algs', 'InfoTuple'))
import utilsInfoTuple as U  # noqa: E402

MU = 0.05
# Fixed seeds make every test deterministic; the chi-square tests use a
# loose threshold so a correct sampler passes by a wide margin.
P_MIN = 1e-3


def colex_rank(row):
    """Reference ranking, written independently of unrank_combinations."""
    return sum(math.comb(int(c), j + 1) for j, c in enumerate(sorted(row)))


def state_equal(a, b):
    """Compare two RandomState.get_state() tuples field by field."""
    return (a[0] == b[0] and np.array_equal(a[1], b[1])
            and tuple(a[2:]) == tuple(b[2:]))


class TestUnrank(unittest.TestCase):

    def test_matches_itertools_exactly(self):
        """All ranks 0..C(m,k)-1 decode to every k-subset once, in colex
        order, for every small m and k (incl. k = 0 and k = m)."""
        for m in range(0, 13):
            for k in range(0, m + 1):
                got = [tuple(r) for r in
                       U.unrank_combinations(np.arange(math.comb(m, k)), m, k)]
                expected = sorted(combinations(range(m), k), key=lambda c: c[::-1])
                self.assertEqual(got, expected, (m, k))

    def test_round_trip_at_large_sizes(self):
        """Random ranks (plus both ends) decode to valid subsets whose rank
        is the number we started from, well past what can be enumerated."""
        rs = np.random.RandomState(0)
        for m, k in [(99, 4), (99, 5), (199, 6), (1000, 3)]:
            total = math.comb(m, k)
            ranks = np.concatenate([[0, 1, total - 2, total - 1],
                                    rs.randint(0, total, size=2000, dtype=np.int64)])
            rows = U.unrank_combinations(ranks, m, k)
            self.assertEqual(rows.shape, (len(ranks), k))
            self.assertTrue((np.diff(rows, axis=1) > 0).all())      # strictly increasing
            self.assertTrue(((rows >= 0) & (rows < m)).all())
            self.assertEqual([colex_rank(r) for r in rows], [int(x) for x in ranks])
            np.testing.assert_array_equal(rows[0], np.arange(k))            # rank 0
            np.testing.assert_array_equal(rows[3], np.arange(m - k, m))     # last rank

    def test_rejects_out_of_range_ranks(self):
        for bad in ([-1], [math.comb(10, 3)]):
            with self.assertRaises(ValueError):
                U.unrank_combinations(bad, 10, 3)

    def test_leaves_input_untouched(self):
        ranks = np.array([5, 17, 100])
        U.unrank_combinations(ranks, 20, 4)
        np.testing.assert_array_equal(ranks, [5, 17, 100])


class TestSampleDistinctIntegers(unittest.TestCase):

    def test_distinct_in_range_and_right_size(self):
        # covers both numpy code paths: Floyd's algorithm (small population,
        # or a small sample) and the partial shuffle (big population, big sample)
        for total, size in [(10, 3), (10, 9), (10626, 531), (3764376, 11293), (20000, 1000)]:
            x = U.sample_distinct_integers(total, size, np.random.RandomState(1))
            self.assertEqual(len(x), size)
            self.assertEqual(len(np.unique(x)), size)
            self.assertTrue(((x >= 0) & (x < total)).all())

    def test_full_size_is_everything_and_draws_nothing(self):
        rng = np.random.RandomState(4)
        before = rng.get_state()
        for size in (50, 51, 1000):
            np.testing.assert_array_equal(U.sample_distinct_integers(50, size, rng),
                                          np.arange(50))
        self.assertTrue(state_equal(before, rng.get_state()))

    def test_every_subset_equally_likely(self):
        """Exact check on a small case: all C(10, 3) = 120 subsets turn up
        equally often (chi-square), not just every single value."""
        rng = np.random.RandomState(2)
        index = {c: i for i, c in enumerate(combinations(range(10), 3))}
        counts = np.zeros(len(index))
        for _ in range(60000):
            counts[index[tuple(sorted(U.sample_distinct_integers(10, 3, rng)))]] += 1
        self.assertGreater(chisquare(counts).pvalue, P_MIN)

    def test_values_equally_likely_on_large_populations(self):
        """Each value is equally likely to be picked, on both code paths."""
        for total, size, trials in [(10000, 20, 5000), (20000, 1000, 400)]:
            rng = np.random.RandomState(3)
            counts = np.bincount(np.concatenate(
                [U.sample_distinct_integers(total, size, rng) for _ in range(trials)]),
                minlength=total)
            self.assertGreater(chisquare(counts).pvalue, P_MIN, (total, size))

    def test_deterministic_and_fixed_rng_advance(self):
        """Same state in -> same sample out, and rng moves by the same amount
        whatever the sample size (one seeding draw)."""
        a, b, c = (np.random.RandomState(9) for _ in range(3))
        np.testing.assert_array_equal(U.sample_distinct_integers(10 ** 6, 500, a),
                                      U.sample_distinct_integers(10 ** 6, 500, b))
        U.sample_distinct_integers(10 ** 6, 5, c)
        self.assertTrue(state_equal(a.get_state(), c.get_state()))


class TestCandidateQueries(unittest.TestCase):

    CASES = [  # n, head, A, rate
        (25, 0, 4, 1.0), (25, 7, 4, 1.0), (25, 24, 4, 1.0), (25, 12, 4, 0.05),
        (25, 3, 2, 1.0), (25, 3, 5, 0.3), (25, 3, 6, 0.01), (10, 4, 3, 1.0),
        (100, 0, 4, 0.003), (100, 57, 4, 0.003), (100, 99, 5, 0.0002),
    ]

    def test_no_two_candidates_share_head_and_body_set(self):
        for n, head, A, rate in self.CASES:
            q = U.candidate_queries(n, head, A, rate, np.random.RandomState(0))
            keys = {(int(r[0]), frozenset(int(x) for x in r[1:])) for r in q}
            self.assertEqual(len(keys), len(q), (n, head, A, rate))

    def test_shape_and_valid_items(self):
        for n, head, A, rate in self.CASES:
            q = U.candidate_queries(n, head, A, rate, np.random.RandomState(0))
            total = math.comb(n - 1, A)
            self.assertEqual(q.shape, (min(total, math.ceil(total * rate)), A + 1))
            self.assertTrue((q[:, 0] == head).all())
            body = q[:, 1:]
            self.assertFalse((body == head).any())
            self.assertTrue(((body >= 0) & (body < n)).all())
            self.assertTrue((np.diff(body, axis=1) > 0).all())     # sorted, no repeats

    def test_full_rate_is_every_body_set_once(self):
        """rate 1.0 at production size: exactly the 10,626 sets of 4 of the
        24 non-head items."""
        for head in (0, 11, 24):
            q = U.candidate_queries(25, head, 4, 1.0, np.random.RandomState(0))
            others = [i for i in range(25) if i != head]
            got = {tuple(int(x) for x in r[1:]) for r in q}
            self.assertEqual(len(q), 10626)
            self.assertEqual(len(got), len(q))                     # no set twice
            # set comparison: a mismatch fails fast with the differing sets
            # (a list assertEqual would spend minutes diffing 10,626 rows)
            self.assertSetEqual(got, set(combinations(others, 4)))

    def test_at_least_one_candidate(self):
        q = U.candidate_queries(25, 0, 4, 1e-9, np.random.RandomState(0))
        self.assertEqual(len(q), 1)

    def test_items_equally_likely_when_downsampled(self):
        """Down-sampling picks body sets uniformly: every non-head item is in
        the scored bodies about equally often (the head-skipping shift
        doesn't favour anyone)."""
        n, head, A = 100, 57, 4
        rng = np.random.RandomState(5)
        counts = np.zeros(n)
        for _ in range(40):
            q = U.candidate_queries(n, head, A, 0.003, rng)
            counts += np.bincount(q[:, 1:].ravel(), minlength=n)
        self.assertEqual(counts[head], 0)
        self.assertGreater(chisquare(np.delete(counts, head)).pvalue, P_MIN)

    def test_n100_is_fast_and_small(self):
        """N = 100: C(99, 4) = 3,764,376 possible bodies. Sampling 0.3% of
        them must not enumerate them all."""
        t0 = time.time()
        q = U.candidate_queries(100, 3, 4, 0.003, np.random.RandomState(0))
        self.assertLess(time.time() - t0, 0.5)
        self.assertEqual(len(q), 11294)
        self.assertLess(q.nbytes, 1e6)


class TestSelectQuery(unittest.TestCase):

    def test_picks_the_best_scored_set(self):
        X = np.random.RandomState(0).rand(25, 3)
        for seed in range(5):
            sel, queries, gains = U.select_query(X, 6, 4, np.random.RandomState(seed), MU, 0.2, 5)
            self.assertEqual(sel[0], 6)
            self.assertEqual(sorted(sel[1:]), [int(x) for x in queries[np.argmax(gains)][1:]])
            self.assertTrue(all(type(x) is int for x in sel))      # JSON/Mongo-safe

    def test_display_order_is_uniformly_random(self):
        """The shown order of the chosen body is a uniform random ordering
        of it: each of the 4! = 24 orderings about equally often."""
        X = np.random.RandomState(1).rand(8, 2)
        orders = {p: i for i, p in enumerate(permutations(range(4)))}
        counts = np.zeros(len(orders))
        rng = np.random.RandomState(0)
        for _ in range(4800):
            sel = U.select_query(X, 0, 4, rng, MU, 1.0, 2)[0]
            body = sel[1:]
            counts[orders[tuple(int(i) for i in np.argsort(np.argsort(body)))]] += 1
        self.assertGreater(chisquare(counts).pvalue, P_MIN)

    def test_rng_use_matches_documented_order(self):
        """select_query draws candidates, then score noise, then the display
        shuffle - nothing else. Replaying those steps by hand from the same
        state gives the same query and leaves rng in the same state."""
        X = np.random.RandomState(2).rand(25, 3)
        for rate in (1.0, 0.1):
            a, b = np.random.RandomState(7), np.random.RandomState(7)
            sel, _, _ = U.select_query(X, 4, 4, a, MU, rate, 3)
            q = U.candidate_queries(25, 4, 4, rate, b)
            g = U.score_queries(X, q, b, MU, 3)
            best = q[np.argmax(g)].copy()
            b.shuffle(best[1:])
            self.assertEqual(sel, [int(x) for x in best])
            self.assertTrue(state_equal(a.get_state(), b.get_state()))


def _load_myalg():
    sys.path.insert(0, os.path.abspath(os.path.join(HERE, '..', '..', '..')))
    from apps.ARankB.algs.InfoTuple.myAlg import MyAlg
    return MyAlg


try:
    MyAlg = _load_myalg()
except Exception as e:  # framework deps missing outside the worker image
    MyAlg, _IMPORT_ERROR = None, e


class _Store:
    def __init__(self):
        self.d = {}

    def get(self, uid=None, key=None):
        return self.d.get((uid, key))

    def set(self, uid=None, key=None, value=None):
        self.d[(uid, key)] = value


class _Butler:
    def __init__(self):
        self.algorithms = _Store()
        self.participants = _Store()


@unittest.skipIf(MyAlg is None, 'needs the worker image (NEXT framework)')
class TestMyAlgRngState(unittest.TestCase):
    """_select_infotuple restores the experiment's saved RandomState, uses it,
    and saves it back - one restore and one save per question, with nothing
    lost in the JSON round trip through the database."""

    def make(self, rate, seed=11, n=25, A=4):
        butler = _Butler()
        for k, v in dict(A=A, mu=MU, down_sample=rate, mi_samples=3).items():
            butler.algorithms.set(key=k, value=v)
        rs = np.random.RandomState(seed)
        rs.normal(size=3)            # odd count: leaves a cached gaussian in the state
        alg = MyAlg()
        alg._save_rng(butler, rs)
        X = np.random.RandomState(seed + 1).rand(n, 3)
        butler.participants.set(uid='p', key='embedding', value=X.tolist())
        return alg, butler, rs.get_state(), X

    def test_saved_state_equals_replay(self):
        """After two questions, the stored state is exactly that of a
        RandomState started from the same state and run through the same two
        select_query calls; the questions match too."""
        for rate in (1.0, 0.1):
            alg, butler, start, X = self.make(rate)
            got = [alg._select_infotuple(butler, 'p', h) for h in (0, 1)]
            replay = np.random.RandomState()
            replay.set_state(start)
            want = [U.select_query(X, h, 4, replay, MU, rate, 3)[0] for h in (0, 1)]
            self.assertEqual(got, want)
            self.assertTrue(state_equal(alg._restore_rng(butler).get_state(),
                                        replay.get_state()))

    def test_state_round_trip_is_lossless(self):
        """save -> JSON -> restore keeps every field (key array, position,
        cached gaussian), so later draws are identical."""
        alg, butler, start, _ = self.make(1.0)
        stored = json.loads(json.dumps(butler.algorithms.get(key='rng_state')))
        butler.algorithms.set(key='rng_state', value=stored)
        restored = alg._restore_rng(butler)
        self.assertTrue(state_equal(restored.get_state(), start))
        self.assertEqual(start[3], 1)                       # has_gauss really set
        ref = np.random.RandomState()
        ref.set_state(start)
        np.testing.assert_array_equal(restored.normal(size=5), ref.normal(size=5))

    def test_state_advances_and_is_stored_as_json(self):
        alg, butler, start, _ = self.make(0.1)
        alg._select_infotuple(butler, 'p', 3)
        saved = butler.algorithms.get(key='rng_state')
        json.dumps(saved)                                   # Mongo-storable
        self.assertFalse(state_equal(alg._restore_rng(butler).get_state(), start))


if __name__ == '__main__':
    unittest.main()
