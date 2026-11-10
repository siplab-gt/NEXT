"""Unit tests for duplicate-answer handling in App.processAnswer
(next/apps/App.py; background in REPRO_DUPLICATE_ANSWER.md).

The same answer (same query_uid) can reach the server twice, even at the same
time on different workers. Exactly one copy may run the app's processAnswer;
every other copy changes nothing, waits for that outcome and returns it.

The real App.processAnswer is driven with an in-memory stand-in for the
database, so no stack is needed. Run from the repo root with the worker image:

    docker run --rm -v /home/ubuntu/NEXT:/next_backend:ro -w /next_backend \
        --entrypoint python local_minionworker:latest \
        -m unittest apps.ARankB.tests.test_duplicate_answer -v
"""
import json
import threading
import time
import unittest
from unittest import mock

import next.utils as utils
from next.apps.App import App


class FakeQueries(object):
    """Thread-safe in-memory stand-in for butler.queries; increment is atomic
    like MongoDB's find_one_and_update($inc)."""

    def __init__(self):
        self.docs = {}
        self.lock = threading.Lock()

    def get(self, uid="", key=None):
        with self.lock:
            doc = self.docs.get(uid)
            if doc is None:
                return None
            return dict(doc) if key is None else doc.get(key)

    def increment(self, uid="", key=None, value=1):
        with self.lock:
            doc = self.docs.setdefault(uid, {})
            doc[key] = doc.get(key, 0) + value
            return doc[key]

    def set_many(self, uid="", key_value_dict=None):
        with self.lock:
            self.docs.setdefault(uid, {}).update(key_value_dict)


class FakeButler(object):
    def __init__(self):
        self.queries = FakeQueries()
        self.ell = mock.Mock()


def make_app(app_fn):
    """An App with only what processAnswer touches. app_fn(args_dict) plays
    the app's processAnswer (myApp + algorithm)."""
    app = App.__new__(App)
    app.app_id = 'ARankB'
    app.exp_uid = 'exp'
    app.butler = FakeButler()
    app.helper = mock.Mock()
    app.helper.convert_json.side_effect = json.loads
    app.reference_dict = {'processAnswer': {'args': {}}}
    app.calls = []

    def call_app_fn(alg_label, alg_id, func_name, args_dict):
        app.calls.append(args_dict['args']['query_uid'])
        app.log_entry_durations = {'task': func_name, 'duration': 0}
        return app_fn(args_dict)

    app.call_app_fn = call_app_fn
    return app


def serve(app, query_uid):
    app.butler.queries.set_many(uid=query_uid, key_value_dict={
        'alg_label': 'InfoTuple', 'alg_id': 'InfoTuple',
        'timestamp_query_generated': utils.datetimeNow('string')})


def answer_json(query_uid):
    return json.dumps({'exp_uid': 'exp', 'args': {
        'query_uid': query_uid, 'target_winner': [1, 2, 3],
        'participant_uid': 'exp_p1', 'trapped': False, 'response_time': 1.0,
        'timestamp_answer_received': utils.datetimeNow('string')}})


class DuplicateAnswerTest(unittest.TestCase):

    def setUp(self):
        patcher = mock.patch('next.lib.pijemont.verifier.verify', side_effect=lambda d, ref: d)
        patcher.start()
        self.addCleanup(patcher.stop)
        utils_patch = mock.patch.object(utils, 'debug_print')
        utils_patch.start()
        self.addCleanup(utils_patch.stop)

    def test_single_answer_processed_once(self):
        app = make_app(lambda a: {'target_winner': a['args']['target_winner']})
        serve(app, 'q1')
        response, ok, _ = app.processAnswer('exp', answer_json('q1'))
        self.assertTrue(ok)
        self.assertEqual(app.calls, ['q1'])
        doc = app.butler.queries.get(uid='q1')
        self.assertEqual(doc['answer_posts'], 1)
        self.assertEqual(doc['answer_outcome'], 'ok')
        self.assertEqual(doc['target_winner'], [1, 2, 3])
        self.assertNotIn('duplicate', json.loads(response)['meta'])

    def test_sequential_duplicate_is_ignored(self):
        app = make_app(lambda a: {'target_winner': a['args']['target_winner']})
        serve(app, 'q1')
        body = answer_json('q1')
        app.processAnswer('exp', body)
        response, ok, _ = app.processAnswer('exp', body)
        self.assertTrue(ok)
        self.assertTrue(json.loads(response)['meta']['duplicate'])
        self.assertEqual(app.calls, ['q1'])           # the app ran once
        self.assertEqual(app.butler.queries.get(uid='q1', key='answer_posts'), 2)

    def test_concurrent_duplicate_waits_for_original(self):
        finished = {}

        def slow_app(a):
            time.sleep(0.6)
            finished['original'] = time.time()
            return {'target_winner': a['args']['target_winner']}

        app = make_app(slow_app)
        serve(app, 'q1')
        body = answer_json('q1')
        results = {}

        def post(name):
            results[name] = app.processAnswer('exp', body)
            finished[name] = time.time()

        t1 = threading.Thread(target=post, args=('first',))
        t1.start()
        time.sleep(0.1)                               # copy arrives mid-processing
        t2 = threading.Thread(target=post, args=('copy',))
        t2.start()
        t1.join()
        t2.join()
        self.assertEqual(app.calls, ['q1'])
        self.assertTrue(results['copy'][1])
        # the copy must not answer before the original has recorded the answer
        self.assertGreaterEqual(finished['copy'], finished['original'])

    def test_many_simultaneous_copies_run_app_once(self):
        app = make_app(lambda a: (time.sleep(0.2), {})[1])
        serve(app, 'q1')
        body = answer_json('q1')
        threads = [threading.Thread(target=app.processAnswer, args=('exp', body)) for _ in range(8)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        self.assertEqual(app.calls, ['q1'])
        self.assertEqual(app.butler.queries.get(uid='q1', key='answer_posts'), 8)

    def test_copy_replays_expulsion(self):
        def expel(a):
            raise ValueError('Participant exp_p1 failed')

        app = make_app(expel)
        serve(app, 'q1')
        body = answer_json('q1')
        with self.assertRaisesRegex(Exception, 'Participant exp_p1 failed'):
            app.processAnswer('exp', body)
        with self.assertRaisesRegex(Exception, 'Participant exp_p1 failed'):
            app.processAnswer('exp', body)
        self.assertEqual(app.calls, ['q1'])
        self.assertEqual(app.butler.queries.get(uid='q1', key='answer_outcome'), 'error')

    def test_copy_gives_up_waiting(self):
        app = make_app(lambda a: {})
        app.DUPLICATE_ANSWER_WAIT_S = 0.5
        serve(app, 'q1')
        # an original that claimed the answer but never recorded an outcome
        app.butler.queries.increment(uid='q1', key='answer_posts')
        t0 = time.time()
        response, ok, _ = app.processAnswer('exp', answer_json('q1'))
        self.assertTrue(ok)
        self.assertGreaterEqual(time.time() - t0, 0.5)
        self.assertEqual(app.calls, [])

    def test_different_queries_are_independent(self):
        app = make_app(lambda a: {})
        for q in ('q1', 'q2', 'q3'):
            serve(app, q)
            app.processAnswer('exp', answer_json(q))
        self.assertEqual(app.calls, ['q1', 'q2', 'q3'])


if __name__ == '__main__':
    unittest.main()
