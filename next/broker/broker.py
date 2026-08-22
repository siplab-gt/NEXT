import next.utils as utils

from datetime import datetime, timedelta

import celery
from next.broker.celery_app import tasks as tasks

from next.broker.celery_app.celery_broker import app

import os

import next.constants
import redis
import json
import time
import next.utils as utils
from contextlib import contextmanager

# How long a request may wait for a worker result before giving up. Kept below the
# nginx proxy_read_timeout (330 s) so the browser receives a JSON 500 it can classify
# instead of an nginx HTML 504 -- and below celery's task_time_limit (360 s).
RESULT_GET_TIMEOUT = 320
# Poll fallback while waiting; the gevent drainer wakes waiters on the pubsub message
# anyway, so this only bounds the polling loop (the old 0.001 spun ~1000x/s per request).
RESULT_GET_INTERVAL = 0.1


def _release_result_backend():
    """Tear down the calling greenlet's celery result backend.

    Celery stores ``app.backend`` in ``threading.local`` unless
    ``result_backend_thread_safe`` is set (celery/app/base.py, ``_backend``).
    Under gunicorn --worker-class=gevent that is *greenlet*-local, i.e. one backend
    per HTTP request: each request builds its own RedisBackend, redis client pool,
    pubsub subscription and a drainer greenlet that never stops. The drainer keeps
    the whole object graph alive after the request ends, so every request pinned
    ~2 sockets to rabbitmqredis forever (28k CLOSE_WAIT sockets -> port exhaustion ->
    "Errno 99" outage, 2026-08-21). Sharing one backend across greenlets
    (result_backend_thread_safe=True) deadlocks under gevent (tested), so instead
    we release this greenlet's backend explicitly after every call.

    Pinned to celery 5.4 / redis-py 5 internals; local/diag_result_backend.py
    is the regression check (must report FLAT).
    """
    local = getattr(app, '_local', None)
    backend = getattr(local, 'backend', None) if local is not None else None
    if backend is None:
        return
    try:
        rc = backend.__dict__.get('result_consumer')
        if rc is not None:
            drainer = getattr(rc, 'drainer', None)
            g = getattr(drainer, '_g', None)
            if g is not None and not g.dead:
                # Wait for the drainer to actually die before touching its socket:
                # killing non-blocking and closing underneath it let the drainer's
                # retry logic reconnect the pubsub (leaking it) under concurrency.
                g.kill(block=True, timeout=2)
            rc.stop()  # closes the pubsub: disconnects + releases its connection
            # AsyncResult.__del__ -> remove_pending_result -> cancel_for ->
            # _pubsub.unsubscribe(): on a closed PubSub redis-py opens a NEW
            # connection just to send that UNSUBSCRIBE, and nothing ever closes
            # it. cancel_for() is guarded by `if self._pubsub:`, so clear it.
            rc._pubsub = None
        client = backend.__dict__.get('client')  # cached_property: do not create one
        if client is not None:
            client.connection_pool.disconnect()
    except Exception as e:  # cleanup must never break a request
        utils.debug_print('_release_result_backend: {}'.format(e))
    finally:
        try:
            del local.backend
        except AttributeError:
            pass


def _wait_result(result):
    """Block on an AsyncResult, delete its stored value, detach it from the backend."""
    try:
        return result.get(interval=RESULT_GET_INTERVAL, timeout=RESULT_GET_TIMEOUT)
    finally:
        try:
            result.forget()
        except Exception:
            pass
        # Detach so AsyncResult.__del__ (which runs later, from the cyclic GC)
        # cannot touch the backend we are about to tear down.
        try:
            result.backend = None
        except Exception:
            pass


class JobBroker:

    # Initialization method for the broker
    def __init__(self):

        self.hostname = None

        # location of hashes
        self.pool = redis.ConnectionPool(
            host=next.constants.RABBITREDIS_HOSTNAME,
            port=next.constants.RABBITREDIS_PORT,
            max_connections=10,
            db=0
        )

    @contextmanager
    def get_redis_connection(self):
        client = redis.Redis(connection_pool=self.pool)
        client.set('MINIONWORKER_HOSTNAME', 'localhost')
        try:
            yield client
        finally:
            client.close()

    def applyAsync(self, app_id, exp_uid, task_name, args, ignore_result=False):
        """
        Run a task (task_name) on a set of args with a given app_id, and exp_uid.
        Waits for computation to finish and returns the answer unless ignore_result=True in which case its a non-blocking call.
        No guarantees about order of execution.

        Inputs: ::\n
            (string) app_id, (string) exp_id, (string) task_name, (json) args
        Outputs: ::\n
            task_name(app_id, exp_id, args)

        """
        submit_timestamp = utils.datetimeNow('string')
        domain = self.__get_domain_for_job(app_id+"_"+exp_uid)
        if next.constants.CELERY_ON:

            try:
                result = tasks.apply.apply_async(args=[app_id,
                                                       exp_uid,
                                                       task_name,
                                                       args,
                                                       submit_timestamp],
                                                 exchange='async@'+domain,
                                                 routing_key='async@'+domain,
                                                 ignore_result=ignore_result)
                if ignore_result:
                    return True
                else:
                    return _wait_result(result)
            finally:
                _release_result_backend()
        else:
            result = tasks.apply(app_id, exp_uid, task_name,
                                 args, submit_timestamp)
            if ignore_result:
                return True
            else:
                return result

    def dashboardAsync(self, app_id, exp_uid, args, ignore_result=False):
        """
        Run a task (task_name) on a set of args with a given app_id, and exp_uid.
        Waits for computation to finish and returns the answer unless ignore_result=True in which case its a non-blocking call.
        No guarantees about order of execution.

        Inputs: ::\n
            (string) app_id, (string) exp_id, (string) task_name, (json) args
        Outputs: ::\n
            task_name(app_id, exp_id, args)

        """
        submit_timestamp = utils.datetimeNow('string')
        domain = self.__get_domain_for_job(app_id+"_"+exp_uid)
        if next.constants.CELERY_ON:

            try:
                result = tasks.apply_dashboard.apply_async(args=[app_id,
                                                                 exp_uid,
                                                                 args,
                                                                 submit_timestamp],
                                                           exchange='dashboard@'+domain,
                                                           routing_key='dashboard@'+domain,
                                                           ignore_result=ignore_result)
                if ignore_result:
                    return True
                else:
                    return _wait_result(result)
            finally:
                _release_result_backend()
        else:
            result = tasks.apply_dashboard(
                app_id, exp_uid, args, submit_timestamp)
            if ignore_result:
                return True
            else:
                return result

    def applySyncByNamespace(self, app_id, exp_uid, alg_id, alg_label, task_name, args, namespace=None, ignore_result=False, time_limit=0):
        """
        Run a task (task_name) on a set of args with a given app_id, and exp_uid asynchronously.
        Waits for computation to finish and returns the answer unless ignore_result=True in which case its a non-blocking call.
        If this method is called a sequence of times with the same namespace (defaults to exp_uid if not set) it is guaranteed that they will execute in order, each job finishing before the next begins

        Inputs: ::\n
            (string) app_id, (string) exp_id, (string) task_name, (json) args

        """
        submit_timestamp = utils.datetimeNow('string')
        if namespace == None:
            namespace = exp_uid
        domain = self.__get_domain_for_job(app_id+"_"+exp_uid)
        num_queues = next.constants.CELERY_SYNC_WORKER_COUNT

        # assign namespaces to queues (with worker of concurrency 1) in round-robbin
        with self.get_redis_connection() as client:
            try:
                namespace_cnt = int(client.get(namespace+"_cnt"))
            except:
                pipe = client.pipeline(True)
                while 1:
                    try:
                        pipe.watch(namespace+"_cnt", "namespace_counter")
                        if not pipe.exists(namespace+"_cnt"):
                            if not pipe.exists('namespace_counter'):
                                namespace_counter = 0
                            else:
                                namespace_counter = pipe.get(
                                    'namespace_counter')
                            pipe.multi()
                            pipe.set(namespace+"_cnt",
                                     int(namespace_counter)+1)
                            pipe.set('namespace_counter',
                                     int(namespace_counter)+1)
                            pipe.execute()
                        else:
                            pipe.unwatch()
                        break
                    except redis.exceptions.WatchError:
                        continue
                    finally:
                        pipe.reset()
                namespace_cnt = int(client.get(namespace+"_cnt"))
        queue_number = (namespace_cnt % num_queues) + 1

        queue_name = 'sync_queue_'+str(queue_number)+'@'+domain
        job_uid = utils.getNewUID()
        if time_limit == 0:
            soft_time_limit = None
            hard_time_limit = None
        else:
            soft_time_limit = time_limit
            hard_time_limit = time_limit + .01
        if next.constants.CELERY_ON:

            try:
                result = tasks.apply_sync_by_namespace.apply_async(args=[app_id, exp_uid,
                                                                         alg_id, alg_label,
                                                                         task_name, args,
                                                                         namespace, job_uid,
                                                                         submit_timestamp, time_limit],
                                                                   queue=queue_name,
                                                                   soft_time_limit=soft_time_limit,
                                                                   time_limit=hard_time_limit,
                                                                   ignore_result=ignore_result)
                if ignore_result:
                    return True
                else:
                    return _wait_result(result)
            finally:
                _release_result_backend()
        else:
            result = tasks.apply_sync_by_namespace(
                app_id, exp_uid, alg_id, alg_label, task_name, args, namespace, job_uid, submit_timestamp, time_limit)
            if ignore_result:
                return True
            else:
                return result

    def __get_domain_for_job(self, job_id):
        """
        Computes which domain to run a given job_id on.
        Git Commit: c1e4f8aacaa42fae80e111979e3f450965643520 has support
        for multiple worker nodes. See the code in broker.py, cluster_monitor.py, and the docker-compose
        file in that commit to see how to get that up and running. It uses
        a simple circular hashing scheme to load balance getQuery/processAnswer calls.
        This implementation assumes just a single master node and no workers
        so only a single hostname (e.g. localhost) has celery workers.
        """
        with self.get_redis_connection() as client:
            if client.exists('MINIONWORKER_HOSTNAME'):
                self.hostname = client.get(
                    'MINIONWORKER_HOSTNAME').decode('utf-8')
                utils.debug_print(
                    'Found hostname: {} (Redis)'.format(self.hostname))
            else:
                with open('/etc/hosts', 'r') as fid:
                    for line in fid:
                        if 'MINIONWORKER' in line:
                            self.hostname = line.split('\t')[1].split(' ')[1]
                            # expire after 10 minutes
                            client.set('MINIONWORKER_HOSTNAME',
                                       self.hostname, ex=360)
                            utils.debug_print(
                                'Found hostname: {} (/etc/hosts)'.format(self.hostname))
                            break
            if self.hostname is None:
                import socket
                self.hostname = socket.gethostname()
                client.set('MINIONWORKER_HOSTNAME', self.hostname,
                           ex=360)  # expire after 10 minutes
                utils.debug_print(
                    'Found hostname: {} (socket.gethostname())'.format(self.hostname))

            return self.hostname
