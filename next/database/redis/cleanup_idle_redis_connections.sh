#!/bin/bash

# Monitor and close idle connections (example script)
IDLE_LIMIT=300  # Idle time limit in seconds
REDIS_CLI_PATH=/usr/local/bin/redis-cli

# Get the list of client IDs that are idle for more than IDLE_LIMIT seconds
clients_to_kill=$($REDIS_CLI_PATH client list | awk -v idle_limit=$IDLE_LIMIT '
BEGIN { FS = " " }
{
    id = ""; idle = 0
    for (i=1; i<=NF; i++) {
        if ($i ~ /^id=/) id = substr($i, 4)
        if ($i ~ /^addr=/) addr = substr($i, 6)
        if ($i ~ /^idle=/) idle = substr($i, 6)
    }
    if (idle+0 >= idle_limit+0) print addr
}')

 # Check if there are any clients to kill
if [ -n "$clients_to_kill" ]; then
    echo "Found idle clients exceeding $IDLE_LIMIT seconds:"
    # echo "$clients_to_kill"

    # Iterate over each client ID and kill the connection
    for client_id in $clients_to_kill; do
        echo "Closing idle client: $client_id"
        $REDIS_CLI_PATH client kill $client_id
    done
else
    echo "No idle clients found exceeding $IDLE_LIMIT seconds."
fi
