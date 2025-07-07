from celery import Celery


app = Celery('celery',
             include=['next.broker.celery_app.tasks'])

# Configuration file for the worker. The default values can be tnitialized from salt module
app.config_from_object('next.constants')
app.conf.update(
    broker_pool_limit=10,
    broker_heartbeat=10,
    worker_concurrency=4,
    redis_max_connections=100,
    redis_socket_timeout=30,
    redis_retry_on_timeout=True,
    redis_socket_connect_timeout=10,
    
    # Timeout settings to prevent gateway timeouts
    task_soft_time_limit=300,  # 5 minutes soft limit
    task_time_limit=360,       # 6 minutes hard limit
    worker_max_memory_per_child=1000000,  # 1GB per worker
    worker_max_tasks_per_child=5,         # Restart worker after 5 tasks
)

if __name__ == '__main__':
    app.start()
