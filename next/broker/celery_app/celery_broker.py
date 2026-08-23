from celery import Celery


app = Celery('celery',
             include=['next.broker.celery_app.tasks'])

# Configuration file for the worker. The default values can be tnitialized from salt module
app.config_from_object('next.constants')
# All celery settings live here as new-style (lowercase) keys. next.constants only
# provides BROKER_URL / CELERY_RESULT_BACKEND / CELERY_QUEUES. (Mixing old-style
# keys in constants.py with new-style keys here is fine for these; but keys that
# belong to neither scheme, like the former TASK_RESULT_EXPIRES, were silently
# ignored - results lived for the 1-day default.)
app.conf.update(
    broker_pool_limit=10,
    broker_heartbeat=10,
    worker_concurrency=4,
    redis_max_connections=100,
    redis_socket_timeout=30,
    redis_retry_on_timeout=True,
    redis_socket_connect_timeout=10,
    redis_socket_keepalive=True,          # detect dead peers instead of waiting forever
    # One result backend per greenlet/thread (the default). True would share one
    # backend across gunicorn's gevent greenlets, which deadlocks (tested 2026-08-22);
    # the backend is instead released per request in next/broker/broker.py.
    result_backend_thread_safe=False,
    result_expires=3600,                  # results are forget()-ed after use anyway
    task_serializer='json',
    result_serializer='json',
    accept_content=['json'],

    # Timeout settings to prevent gateway timeouts
    task_soft_time_limit=300,  # 5 minutes soft limit
    task_time_limit=360,       # 6 minutes hard limit
    worker_max_memory_per_child=1000000,  # 1GB per worker
    worker_max_tasks_per_child=5,         # Restart worker after 5 tasks
)

if __name__ == '__main__':
    app.start()
