#!/bin/bash

# Start the Cron daemon
echo "Starting cron daemon"
cron

# Start the Redis server
echo "Starting redis-server"
redis-server --appendonly yes &

# Wait forever (or until one of the services stops)
echo "Waiting for processes to exit..."
tail -f /var/log/cron.log /var/log/cleanup_idle_redis_connections.log
