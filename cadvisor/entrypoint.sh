#!/bin/sh

# Read secrets and export them as environment variables
BASIC_AUTH_USERNAME=$(cat /run/secrets/cadvisor_user)
BASIC_AUTH_PASSWORD=$(cat /run/secrets/cadvisor_password)

echo "auth username: $BASIC_AUTH_USERNAME"
htpasswd -nb "$BASIC_AUTH_USERNAME" "$BASIC_AUTH_PASSWORD" > /etc/cadvisor/auth.htpasswd

echo "Other options: $@"

/usr/bin/cadvisor -logtostderr --http_auth_file=/etc/cadvisor/auth.htpasswd "$@"
