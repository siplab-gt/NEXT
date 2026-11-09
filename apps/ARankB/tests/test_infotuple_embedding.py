"""Tests for InfoTuple's map fitting (embedding_method LORE / SOE).

No running stack needed, but this imports the InfoTuple algorithm, so run it
from the repo root with an environment that has the worker requirements
(cblearn >= 0.4.0 for the LORE tests; they are skipped on older images):

    docker run --rm -v /home/ubuntu/NEXT:/next_backend:ro -w /next_backend \
        --entrypoint python local_minionworker:latest \
        -m unittest apps.ARankB.tests.test_infotuple_embedding -v
"""
import os
import sys
import time
import unittest
from unittest import mock

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '..'))
from apps.ARankB.algs.InfoTuple import myAlg as M  # noqa: E402

N_ITEMS, DIM = 25, 3          # production rank-4 study: 25 items, 3-D map
HAVE_LORE = M.LORE is not None


class _Store:
    def __init__(self):
        self.d = {}

    def get(self, uid=None, key=None):
        return self.d.get((uid, key))

    def set(self, uid=None, key=None, value=None):
        self.d[(uid, key)] = value

    def exists(self, uid=None, key=None):
        return (uid, key) in self.d

    def increment(self, uid=None, key=None, value=1):
        self.d[(uid, key)] = self.d.get((uid, key), 0) + value
        return self.d[(uid, key)]

    def append(self, uid=None, key=None, value=None):
        self.d.setdefault((uid, key), []).append(value)


class FakeButler:
    def __init__(self):
        self.algorithms = _Store()
        self.participants = _Store()
        self.jobs = []

    def job(self, name, args, time_limit=0):
        self.jobs.append(name)


def init(butler, **kw):
    M.MyAlg().initExp(butler, 4, 4, N_ITEMS, DIM, random_seed=13, failure_probability=0.01,
                      iteration=5, burn_in=1, down_sample=1.0, mu=0.05, debug=False,
                      setTrap=False, expel=False, tolerance=0.3, trapRatio=0.0,
                      num_trap_questions=0, **kw)


def answers(true_X, count, rng):
    """`count` answers to 4-item questions, exactly in the true order, as the
    6 (head, closer, farther) comparisons each one stores."""
    out = []
    for _ in range(count):
        head = rng.randint(N_ITEMS)
        body = rng.choice([i for i in range(N_ITEMS) if i != head], 4, replace=False)
        body = body[np.argsort(np.linalg.norm(true_X[body] - true_X[head], axis=1))]
        out += [[int(head), int(body[i]), int(body[j])] for i in range(4) for j in range(i + 1, 4)]
    return out


def agreement(X, trip):
    X, trip = np.asarray(X), np.asarray(trip)
    return float(np.mean(np.linalg.norm(X[trip[:, 0]] - X[trip[:, 1]], axis=1)
                         < np.linalg.norm(X[trip[:, 0]] - X[trip[:, 2]], axis=1)))


class TestSetting(unittest.TestCase):
    @unittest.skipUnless(HAVE_LORE, 'cblearn < 0.4.0')
    def test_new_experiments_default_to_lore(self):
        b = FakeButler()
        init(b)
        self.assertEqual(b.algorithms.get(key='embedding_method'), 'LORE')
        self.assertEqual(b.algorithms.get(key='embedding_max_iter'), 1000)
        e = M.MyAlg()._embedder(b, DIM)
        self.assertIsInstance(e, M.LORE)
        self.assertEqual((e.n_components, e.max_iter, e.backend, e.random_state), (DIM, 1000, 'scipy', 13))
        self.assertEqual((e.lamb, e.p, e.margin), (0.01, 0.5, 0.1))

    def test_soe_still_selectable(self):
        b = FakeButler()
        init(b, embedding_method='SOE')
        self.assertEqual(b.algorithms.get(key='embedding_max_iter'), 20)
        e = M.MyAlg()._embedder(b, DIM)
        self.assertIsInstance(e, M.SOE)
        self.assertEqual((e.max_iter, e.margin), (20, 5))

    @unittest.skipUnless(HAVE_LORE, 'cblearn < 0.4.0')
    def test_iteration_cap_is_configurable(self):
        b = FakeButler()
        init(b, embedding_max_iter=1500)
        self.assertEqual(M.MyAlg()._embedder(b, DIM).max_iter, 1500)

    def test_experiments_from_before_the_setting_keep_soe(self):
        b = FakeButler()
        init(b, embedding_method='SOE')
        del b.algorithms.d[(None, 'embedding_method')]
        del b.algorithms.d[(None, 'embedding_max_iter')]
        e = M.MyAlg()._embedder(b, DIM)
        self.assertIsInstance(e, M.SOE)
        self.assertEqual((e.max_iter, e.margin, e.n_init), (20, 5, 10))

    def test_unknown_method_rejected(self):
        with self.assertRaises(ValueError):
            init(FakeButler(), embedding_method='tSTE')

    def test_lore_on_old_cblearn_fails_the_launch(self):
        with mock.patch.object(M, 'LORE', None):
            with self.assertRaises(ValueError):
                init(FakeButler())
            init(FakeButler(), embedding_method='SOE')    # SOE still launches


@unittest.skipUnless(HAVE_LORE, 'cblearn < 0.4.0')
class TestLoreUpdates(unittest.TestCase):
    def setUp(self):
        self.rng = np.random.RandomState(0)
        self.true_X = self.rng.rand(N_ITEMS, DIM)
        self.b = FakeButler()
        init(self.b)
        self.alg = M.MyAlg()

    def test_incremental_update_learns_the_map(self):
        """One participant, production-sized: 150 answers = 900 comparisons."""
        resp = answers(self.true_X, 150, self.rng)
        held_out = answers(self.true_X, 100, self.rng)
        uid = 'p'
        self.b.participants.set(uid, 'embedding', self.rng.rand(N_ITEMS, DIM).tolist())
        self.b.participants.set(uid, 'responses', resp)
        before = agreement(self.b.participants.get(uid, 'embedding'), held_out)
        t = time.time()
        self.alg.incremental_embedding_update(self.b, uid)
        elapsed = time.time() - t
        X = np.array(self.b.participants.get(uid, 'embedding'))
        self.assertEqual(X.shape, (N_ITEMS, DIM))
        self.assertTrue(np.all(np.isfinite(X)))
        self.assertGreater(agreement(X, held_out), 0.85)
        self.assertGreater(agreement(X, held_out), before + 0.2)
        self.assertIn(self.b.participants.get(uid, 'embedding_rank'), (1, 2, 3))
        self.assertLess(elapsed, 3.0, 'runs inline in processAnswer: participants wait on it')

    def test_rounds_through_process_answer(self):
        """processAnswer refits after every 25th answer (a round) and moves on."""
        uid = 'p'
        q = M.MyAlg()
        for _ in range(2 * N_ITEMS):
            tup = q.getQuery(self.b, uid)
            head, body = tup[0], np.array(tup[1:])
            order = body[np.argsort(np.linalg.norm(self.true_X[body] - self.true_X[head], axis=1))]
            q.processAnswer(self.b, [head] + [int(i) for i in order], uid, False)
        self.assertEqual(self.b.participants.get(uid, 'curr_iteration'), 2)
        self.assertEqual(self.b.participants.get(uid, 'head'), 0)
        self.assertEqual(len(self.b.participants.get(uid, 'responses')), 2 * N_ITEMS * 6)
        self.assertIsNotNone(self.b.participants.get(uid, 'embedding_rank'))

    def test_full_update_fits_a_bounded_subsample(self):
        resp = answers(self.true_X, 600, self.rng)               # 3600 comparisons
        self.b.algorithms.set(key='responses', value=resp)
        rng_state = self.b.algorithms.get(key='rng_state')
        seen = []
        orig = M.LORE.fit_transform

        def spy(est, X, *a, **kw):
            seen.append(len(X))
            return orig(est, X, *a, **kw)
        with mock.patch.object(M, 'FULL_UPDATE_MAX_RESPONSES', 1000), \
                mock.patch.object(M.LORE, 'fit_transform', spy):
            self.alg.full_embedding_update(self.b, None)
            X1 = self.b.algorithms.get(key='X')
            self.b.algorithms.set(key='X', value=np.random.RandomState(13).rand(N_ITEMS, DIM))
            self.alg.full_embedding_update(self.b, None)
        self.assertEqual(seen, [1000, 1000])
        np.testing.assert_allclose(X1, self.b.algorithms.get(key='X'))   # same subsample both times
        self.assertEqual(self.b.algorithms.get(key='rng_state'), rng_state,
                         'must not consume the question-selection random stream')
        self.assertGreater(agreement(X1, answers(self.true_X, 100, self.rng)), 0.85)

    def test_full_update_cap_shrinks_with_dimension(self):
        self.assertEqual([M.full_update_cap(d) for d in (2, 3, 4, 6, 10)],
                         [20000, 20000, 15000, 10000, 6000])

    def test_full_update_fits_the_job_time_limit(self):
        """~175 participants' comparisons pooled: ~30 s uncapped on real data
        (the job's hard limit is 30 s). Noise-free answers are LORE's slowest
        case (it never meets its stopping rule, so runs all 1000 iterations):
        ~10 s on the subsample, measured on a busy c6i.4xlarge."""
        resp = answers(self.true_X, 175 * 150, self.rng)
        self.b.algorithms.set(key='responses', value=resp)
        t = time.time()
        self.alg.full_embedding_update(self.b, None)
        self.assertLess(time.time() - t, 20.0)


if __name__ == '__main__':
    unittest.main()
